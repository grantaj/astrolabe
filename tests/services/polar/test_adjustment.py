import datetime
import math
from unittest.mock import MagicMock, patch

import erfa
import pytest

from astrolabe.camera.types import Image
from astrolabe.services.feedback import FeedbackSession
from astrolabe.services.polar.adjustment import (
    AZ_ADJUSTMENT_AXIS,
    altitude_adjustment_axis,
    ideal_pole_horizon_vector,
    infer_rotation_about_axis,
    radec_to_horizon_vector,
    rotate_about_axis,
)
from astrolabe.services.polar.service import PolarAlignService, _SolveHint
from astrolabe.services.polar.types import (
    PolarAdjustConfig,
    PolarResult,
    PolarWorkflowState,
    _CircleFitResult,
    _PolarMeasurement,
    _PoseObservation,
)
from astrolabe.solver.types import SolveResult

_SITE_LAT_RAD = math.radians(45.0)
_SITE_LON_RAD = math.radians(10.0)
_T0 = datetime.datetime(2026, 3, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


def _utc_jd(timestamp_utc):
    seconds = timestamp_utc.second + timestamp_utc.microsecond / 1_000_000.0
    return erfa.dtf2d(
        "UTC",
        timestamp_utc.year,
        timestamp_utc.month,
        timestamp_utc.day,
        timestamp_utc.hour,
        timestamp_utc.minute,
        seconds,
    )


def _horizon_vector(az_deg, alt_deg):
    az = math.radians(az_deg)
    alt = math.radians(alt_deg)
    cos_alt = math.cos(alt)
    return (
        cos_alt * math.sin(az),
        cos_alt * math.cos(az),
        math.sin(alt),
    )


def _horizon_to_icrs(vector, timestamp_utc):
    east, north, up = vector
    az = math.atan2(east, north) % math.tau
    zenith = math.pi / 2.0 - math.asin(max(-1.0, min(1.0, up)))
    utc1, utc2 = _utc_jd(timestamp_utc)
    ra, dec = erfa.atoc13(
        "A",
        az,
        zenith,
        utc1,
        utc2,
        0.0,
        _SITE_LON_RAD,
        _SITE_LAT_RAD,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.55,
    )
    return float(erfa.anp(ra)), float(dec)


def _image(timestamp_utc):
    return Image(
        data=b"fits",
        width_px=800,
        height_px=600,
        timestamp_utc=timestamp_utc,
        exposure_s=1.0,
        metadata={},
    )


def _solve_for_horizon(vector, timestamp_utc, *, scale=1.5):
    ra, dec = _horizon_to_icrs(vector, timestamp_utc)
    return SolveResult(
        success=True,
        ra_rad=ra,
        dec_rad=dec,
        pixel_scale_arcsec=scale,
        rotation_rad=0.0,
        rms_arcsec=1.0,
        num_stars=40,
    )


def _measurement_for_axis(axis_vector):
    pole_ra, pole_dec = _horizon_to_icrs(axis_vector, _T0)
    poses = tuple(
        _PoseObservation(
            ra_rad=math.radians(i * 20.0),
            dec_rad=math.radians(60.0),
            rms_arcsec=1.0,
            timestamp_utc=_T0,
        )
        for i in range(4)
    )
    result = PolarResult(
        alt_correction_arcsec=0.0,
        az_correction_arcsec=0.0,
        residual_arcsec=0.5,
        confidence=0.95,
    )
    return _PolarMeasurement(
        result=result,
        poses=poses,
        fit=_CircleFitResult(
            pole_ra_rad=pole_ra,
            pole_dec_rad=pole_dec,
            radius_rad=math.radians(20.0),
            residual_rad=math.radians(0.5 / 3600.0),
        ),
        alt_correction_rad=0.0,
        az_correction_rad=0.0,
    )


def _mock_service():
    mount = MagicMock()
    camera = MagicMock()
    solver = MagicMock()
    mount.get_state.return_value = MagicMock(
        connected=True,
        ra_rad=0.0,
        dec_rad=0.0,
        tracking=True,
        slewing=False,
        timestamp_utc=_T0,
    )
    return PolarAlignService(mount, camera, solver), mount, camera, solver


class TestHorizonTransform:
    def test_tracking_off_fixed_field_is_time_invariant(self):
        fixed = _horizon_vector(132.0, 48.0)
        t1 = _T0 + datetime.timedelta(minutes=4)
        ra0, dec0 = _horizon_to_icrs(fixed, _T0)
        ra1, dec1 = _horizon_to_icrs(fixed, t1)

        recovered0 = radec_to_horizon_vector(
            ra0,
            dec0,
            _T0,
            latitude_rad=_SITE_LAT_RAD,
            longitude_rad=_SITE_LON_RAD,
        )
        recovered1 = radec_to_horizon_vector(
            ra1,
            dec1,
            t1,
            latitude_rad=_SITE_LAT_RAD,
            longitude_rad=_SITE_LON_RAD,
        )

        for expected, actual0, actual1 in zip(fixed, recovered0, recovered1):
            assert actual0 == pytest.approx(expected, abs=2e-10)
            assert actual1 == pytest.approx(expected, abs=2e-10)

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            radec_to_horizon_vector(
                0.1,
                0.2,
                datetime.datetime(2026, 3, 1),
                latitude_rad=_SITE_LAT_RAD,
                longitude_rad=_SITE_LON_RAD,
            )


class TestAdjustmentGeometry:
    @pytest.mark.parametrize("delta_deg", [0.4, -0.4])
    def test_pure_az_motion_has_correct_sign_and_negligible_cross_track(
        self, delta_deg
    ):
        reference = _horizon_vector(120.0, 45.0)
        current = rotate_about_axis(
            reference,
            AZ_ADJUSTMENT_AXIS,
            math.radians(delta_deg),
        )

        applied, cross_track = infer_rotation_about_axis(
            reference,
            current,
            AZ_ADJUSTMENT_AXIS,
        )

        assert math.degrees(applied) == pytest.approx(delta_deg, abs=1e-9)
        assert cross_track < 1e-7

    @pytest.mark.parametrize("delta_deg", [0.3, -0.3])
    def test_pure_alt_motion_has_correct_sign_and_negligible_cross_track(
        self, delta_deg
    ):
        polar_axis = _horizon_vector(0.0, 44.5)
        adjustment_axis = altitude_adjustment_axis(polar_axis)
        reference = _horizon_vector(120.0, 45.0)
        current = rotate_about_axis(
            reference,
            adjustment_axis,
            math.radians(delta_deg),
        )

        applied, cross_track = infer_rotation_about_axis(
            reference,
            current,
            adjustment_axis,
        )

        assert math.degrees(applied) == pytest.approx(delta_deg, abs=1e-9)
        assert cross_track < 1e-7

    def test_wrong_axis_motion_is_visible_as_cross_track(self):
        reference = _horizon_vector(120.0, 45.0)
        wrong_axis = (1.0, 0.0, 0.0)
        current = rotate_about_axis(reference, wrong_axis, math.radians(0.5))

        _applied, cross_track = infer_rotation_about_axis(
            reference,
            current,
            AZ_ADJUSTMENT_AXIS,
        )

        assert cross_track > math.radians(1.0 / 60.0)

    def test_ideal_pole_covers_both_hemispheres(self):
        north = ideal_pole_horizon_vector(math.radians(35.0))
        south = ideal_pole_horizon_vector(math.radians(-35.0))

        assert north[1] > 0.0 and north[2] > 0.0
        assert south[1] < 0.0 and south[2] > 0.0


class TestAdjustmentWorkflow:
    def test_happy_path_is_az_then_alt_and_restores_tracking(self):
        service, mount, camera, solver = _mock_service()
        initial_axis = _horizon_vector(-0.5, 44.6)
        measurement = _measurement_for_axis(initial_axis)

        az_reference = _horizon_vector(120.0, 45.0)
        az_applied = [0.0, 0.3, 0.5, 0.5, 0.5]
        az_vectors = [
            rotate_about_axis(
                az_reference,
                AZ_ADJUSTMENT_AXIS,
                math.radians(value),
            )
            for value in az_applied
        ]

        axis_after_az = rotate_about_axis(
            initial_axis,
            AZ_ADJUSTMENT_AXIS,
            math.radians(0.5),
        )
        alt_axis = altitude_adjustment_axis(axis_after_az)
        alt_reference = az_vectors[-1]
        alt_applied = [0.0, 0.2, 0.4, 0.4, 0.4]
        alt_vectors = [
            rotate_about_axis(alt_reference, alt_axis, math.radians(value))
            for value in alt_applied
        ]

        vectors = az_vectors + alt_vectors
        timestamps = [_T0 + datetime.timedelta(seconds=i + 1) for i in range(len(vectors))]
        camera.capture.side_effect = [_image(timestamp) for timestamp in timestamps]
        solver.solve.side_effect = [
            _solve_for_horizon(vector, timestamp)
            for vector, timestamp in zip(vectors, timestamps)
        ]
        updates = []

        with patch.object(service, "_measure", return_value=measurement) as measure:
            result = service.adjust(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
                site_longitude_rad=_SITE_LON_RAD,
                exposure_s=1.0,
                on_update=updates.append,
            )

        assert result.success is True
        assert result.state is PolarWorkflowState.COMPLETE
        assert result.az_samples == 5
        assert result.alt_samples == 5
        measure.assert_called_once()
        assert [call.args[0] for call in mount.set_tracking.call_args_list] == [
            False,
            True,
        ]
        states = [update.state for update in updates]
        assert states.index(PolarWorkflowState.ADJUST_AZ) < states.index(
            PolarWorkflowState.AZ_ON_TARGET
        )
        assert states.index(PolarWorkflowState.AZ_ON_TARGET) < states.index(
            PolarWorkflowState.REBASE_FOR_ALT
        )
        assert states.index(PolarWorkflowState.REBASE_FOR_ALT) < states.index(
            PolarWorkflowState.ADJUST_ALT
        )
        assert states[-1] is PolarWorkflowState.COMPLETE

        requests = [call.args[0] for call in solver.solve.call_args_list]
        assert requests[0].ra_hint_rad is None
        assert requests[1].ra_hint_rad == solver.solve.side_effect[0].ra_rad
        assert requests[1].scale_hint_arcsec == 1.5
        assert requests[1].search_radius_rad is not None
        # ALT starts from a fresh capture but may reuse the final AZ solve as a hint.
        assert requests[5].ra_hint_rad == solver.solve.side_effect[4].ra_rad

    def test_hinted_failure_gets_one_bounded_blind_fallback(self):
        service, _mount, camera, solver = _mock_service()
        timestamp = _T0 + datetime.timedelta(seconds=1)
        camera.capture.return_value = _image(timestamp)
        failed = SolveResult(
            success=False,
            ra_rad=None,
            dec_rad=None,
            pixel_scale_arcsec=None,
            rotation_rad=None,
            rms_arcsec=None,
            num_stars=0,
            message="hint miss",
        )
        recovered = _solve_for_horizon(_horizon_vector(120.0, 45.0), timestamp)
        solver.solve.side_effect = [failed, recovered]

        live, message = service._capture_live_solve(
            exposure_s=1.0,
            hint=_SolveHint(ra_rad=1.0, dec_rad=0.5, scale_arcsec=1.5),
            search_radius_rad=math.radians(2.0),
        )

        assert live is not None
        assert message is None
        assert solver.solve.call_count == 2
        hinted = solver.solve.call_args_list[0].args[0]
        fallback = solver.solve.call_args_list[1].args[0]
        assert hinted.ra_hint_rad == 1.0
        assert hinted.search_radius_rad == pytest.approx(math.radians(2.0))
        assert fallback.ra_hint_rad is None
        assert fallback.dec_hint_rad is None
        assert fallback.scale_hint_arcsec == 1.5

    def test_large_outlier_is_rejected(self):
        service, _mount, camera, solver = _mock_service()
        reference = _horizon_vector(120.0, 45.0)
        jumped = rotate_about_axis(reference, AZ_ADJUSTMENT_AXIS, math.radians(2.0))
        timestamps = [
            _T0 + datetime.timedelta(seconds=1),
            _T0 + datetime.timedelta(seconds=2),
        ]
        camera.capture.side_effect = [_image(timestamp) for timestamp in timestamps]
        solver.solve.side_effect = [
            _solve_for_horizon(reference, timestamps[0]),
            _solve_for_horizon(jumped, timestamps[1]),
        ]
        config = PolarAdjustConfig(
            max_step_rad=math.radians(0.5),
            max_consecutive_failures=1,
        )

        stage = service._run_axis_stage(
            state=PolarWorkflowState.ADJUST_AZ,
            axis=service_axis := __import__(
                "astrolabe.services.polar.types", fromlist=["PolarAxis"]
            ).PolarAxis.AZ,
            rotation_axis=AZ_ADJUSTMENT_AXIS,
            target_correction_rad=math.radians(0.5),
            exposure_s=1.0,
            site_latitude_rad=_SITE_LAT_RAD,
            site_longitude_rad=_SITE_LON_RAD,
            site_elevation_m=0.0,
            config=config,
            feedback=FeedbackSession(config.feedback),
            on_update=None,
            initial_hint=None,
        )

        assert service_axis.value == "az"
        assert stage.success is False
        assert "rebase/retry" in (stage.message or "")

    def test_ctrl_c_restores_tracking(self):
        service, mount, _camera, _solver = _mock_service()
        measurement = _measurement_for_axis(_horizon_vector(-0.5, 44.6))

        with (
            patch.object(service, "_measure", return_value=measurement),
            patch.object(service, "_run_axis_stage", side_effect=KeyboardInterrupt),
        ):
            result = service.adjust(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
                site_longitude_rad=_SITE_LON_RAD,
            )

        assert result.state is PolarWorkflowState.CANCELLED
        assert [call.args[0] for call in mount.set_tracking.call_args_list] == [
            False,
            True,
        ]

    def test_axis_already_inside_tolerance_requires_stable_evidence(self):
        service, _mount, camera, solver = _mock_service()
        reference = _horizon_vector(120.0, 45.0)
        timestamps = [_T0 + datetime.timedelta(seconds=i + 1) for i in range(3)]
        camera.capture.side_effect = [_image(timestamp) for timestamp in timestamps]
        solver.solve.side_effect = [
            _solve_for_horizon(reference, timestamp) for timestamp in timestamps
        ]
        config = PolarAdjustConfig(stable_samples=3)

        from astrolabe.services.polar.types import PolarAxis

        stage = service._run_axis_stage(
            state=PolarWorkflowState.ADJUST_AZ,
            axis=PolarAxis.AZ,
            rotation_axis=AZ_ADJUSTMENT_AXIS,
            target_correction_rad=0.0,
            exposure_s=1.0,
            site_latitude_rad=_SITE_LAT_RAD,
            site_longitude_rad=_SITE_LON_RAD,
            site_elevation_m=0.0,
            config=config,
            feedback=FeedbackSession(config.feedback),
            on_update=None,
            initial_hint=None,
        )

        assert stage.success is True
        assert stage.samples == 3
