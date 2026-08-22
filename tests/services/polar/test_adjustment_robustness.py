import datetime
import math
from dataclasses import replace
from unittest.mock import MagicMock, patch

import erfa
import pytest

from astrolabe.camera.types import Image
from astrolabe.services.feedback import FeedbackDirection, FeedbackSession
from astrolabe.services.polar.adjustment import (
    AZ_ADJUSTMENT_AXIS,
    altitude_adjustment_axis,
    infer_rotation_about_axis,
    rotate_about_axis,
)
from astrolabe.services.polar.service import PolarAlignService
from astrolabe.services.polar.types import (
    PolarAdjustConfig,
    PolarAxis,
    PolarResult,
    PolarWorkflowState,
    _CircleFitResult,
    _PolarMeasurement,
    _PoseObservation,
)
from astrolabe.services.polar.workflow import _PolarAdjustmentWorkflow
from astrolabe.solver.types import SolveResult

_SITE_LAT_RAD = math.radians(45.0)
_SITE_LON_RAD = math.radians(10.0)
_T0 = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)


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


def _horizon_to_icrs(vector, timestamp_utc, *, latitude_rad=_SITE_LAT_RAD):
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
        latitude_rad,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.55,
    )
    return float(erfa.anp(ra)), float(dec)


def _image(index):
    return Image(
        data=b"fits",
        width_px=800,
        height_px=600,
        timestamp_utc=_T0 + datetime.timedelta(seconds=index + 1),
        exposure_s=1.0,
        metadata={},
    )


def _solve_for_horizon(vector, image):
    ra, dec = _horizon_to_icrs(vector, image.timestamp_utc)
    return SolveResult(
        success=True,
        ra_rad=ra,
        dec_rad=dec,
        pixel_scale_arcsec=1.5,
        rotation_rad=0.0,
        rms_arcsec=1.0,
        num_stars=40,
    )


def _failed_solve(message="no solution"):
    return SolveResult(
        success=False,
        ra_rad=None,
        dec_rad=None,
        pixel_scale_arcsec=None,
        rotation_rad=None,
        rms_arcsec=None,
        num_stars=0,
        message=message,
    )


def _measurement(axis_vector):
    pole_ra, pole_dec = _horizon_to_icrs(axis_vector, _T0)
    poses = tuple(
        _PoseObservation(
            ra_rad=math.radians(index * 20.0),
            dec_rad=math.radians(60.0),
            rms_arcsec=1.0,
            timestamp_utc=_T0,
        )
        for index in range(4)
    )
    return _PolarMeasurement(
        result=PolarResult(
            alt_correction_arcsec=0.0,
            az_correction_arcsec=0.0,
            residual_arcsec=0.5,
            confidence=0.95,
        ),
        poses=poses,
        fit=_CircleFitResult(
            pole_ra_rad=pole_ra,
            pole_dec_rad=pole_dec,
            radius_rad=math.radians(20.0),
            residual_rad=math.radians(0.5 / 3600.0),
        ),
    )


def _service_and_workflow():
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
    service = PolarAlignService(mount, camera, solver)
    workflow = _PolarAdjustmentWorkflow(mount, camera, solver, service._measure)
    return service, workflow, mount, camera, solver


def _deterministic_config(**changes):
    base = PolarAdjustConfig()
    base = replace(
        base,
        feedback=replace(base.feedback, smoothing_alpha=1.0),
    )
    return replace(base, **changes)


class TestGeometryEnvelope:
    @pytest.mark.parametrize("field", [(25.0, 30.0), (120.0, 45.0), (250.0, 20.0)])
    @pytest.mark.parametrize("delta_deg", [-5.0, 5.0])
    def test_exact_az_rotation_at_max_single_step(self, field, delta_deg):
        reference = _horizon_vector(*field)
        current = rotate_about_axis(
            reference,
            AZ_ADJUSTMENT_AXIS,
            math.radians(delta_deg),
        )

        recovered, cross_track = infer_rotation_about_axis(
            reference,
            current,
            AZ_ADJUSTMENT_AXIS,
        )

        assert math.degrees(recovered) == pytest.approx(delta_deg, abs=1e-9)
        assert cross_track < 1e-7

    @pytest.mark.parametrize("latitude_deg", [-45.0, 45.0])
    def test_altitude_rotation_geometry_is_hemisphere_independent(self, latitude_deg):
        pole_az = 180.0 if latitude_deg < 0.0 else 0.0
        polar_axis = _horizon_vector(pole_az, abs(latitude_deg) - 1.0)
        adjustment_axis = altitude_adjustment_axis(polar_axis)
        reference = _horizon_vector(70.0, 35.0)
        current = rotate_about_axis(reference, adjustment_axis, math.radians(2.0))

        recovered, cross_track = infer_rotation_about_axis(
            reference,
            current,
            adjustment_axis,
        )

        assert math.degrees(recovered) == pytest.approx(2.0, abs=1e-9)
        assert cross_track < 1e-7


class TestWorkflowRobustness:
    def test_crossing_target_reverses_direction_before_stable_completion(self):
        _service, workflow, _mount, camera, solver = _service_and_workflow()
        reference = _horizon_vector(120.0, 45.0)
        target = math.radians(0.5)
        applied_deg = [0.0, 0.3, 0.6, 0.48, 0.5, 0.5, 0.5]
        images = [_image(index) for index in range(len(applied_deg))]
        camera.capture.side_effect = images
        solver.solve.side_effect = [
            _solve_for_horizon(
                rotate_about_axis(
                    reference,
                    AZ_ADJUSTMENT_AXIS,
                    math.radians(applied),
                ),
                image,
            )
            for applied, image in zip(applied_deg, images)
        ]
        updates = []
        config = _deterministic_config()

        stage = workflow._run_axis_stage(
            state=PolarWorkflowState.ADJUST_AZ,
            axis=PolarAxis.AZ,
            rotation_axis=AZ_ADJUSTMENT_AXIS,
            target_correction_rad=target,
            exposure_s=1.0,
            site_latitude_rad=_SITE_LAT_RAD,
            site_longitude_rad=_SITE_LON_RAD,
            site_elevation_m=0.0,
            config=config,
            feedback=FeedbackSession(config.feedback),
            on_update=updates.append,
            initial_hint=None,
        )

        directions = [
            update.feedback.direction
            for update in updates
            if update.feedback is not None and update.feedback.valid
        ]
        assert FeedbackDirection.POSITIVE in directions
        assert FeedbackDirection.NEGATIVE in directions
        assert directions[-3:] == [FeedbackDirection.CENTERED] * 3
        assert stage.success is True
        assert stage.samples == len(applied_deg)

    def test_intermittent_hinted_solve_failure_recovers_on_same_frame(self):
        _service, workflow, _mount, camera, solver = _service_and_workflow()
        reference = _horizon_vector(120.0, 45.0)
        target = math.radians(0.5)
        applied_deg = [0.0, 0.5, 0.5, 0.5]
        images = [_image(index) for index in range(len(applied_deg))]
        camera.capture.side_effect = images
        solved = [
            _solve_for_horizon(
                rotate_about_axis(
                    reference,
                    AZ_ADJUSTMENT_AXIS,
                    math.radians(applied),
                ),
                image,
            )
            for applied, image in zip(applied_deg, images)
        ]
        solver.solve.side_effect = [
            solved[0],
            _failed_solve("hint miss"),
            solved[1],
            solved[2],
            solved[3],
        ]
        config = _deterministic_config()

        stage = workflow._run_axis_stage(
            state=PolarWorkflowState.ADJUST_AZ,
            axis=PolarAxis.AZ,
            rotation_axis=AZ_ADJUSTMENT_AXIS,
            target_correction_rad=target,
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
        assert stage.samples == 4
        assert solver.solve.call_count == 5
        retry_request = solver.solve.call_args_list[2].args[0]
        assert retry_request.image is images[1]
        assert retry_request.ra_hint_rad is None
        assert retry_request.scale_hint_arcsec == 1.5

    def test_wrong_axis_motion_suppresses_guidance_and_requires_retry(self):
        _service, workflow, _mount, camera, solver = _service_and_workflow()
        reference = _horizon_vector(120.0, 45.0)
        wrong = rotate_about_axis(reference, (1.0, 0.0, 0.0), math.radians(0.5))
        images = [_image(0), _image(1)]
        camera.capture.side_effect = images
        solver.solve.side_effect = [
            _solve_for_horizon(reference, images[0]),
            _solve_for_horizon(wrong, images[1]),
        ]
        updates = []
        config = _deterministic_config(max_consecutive_failures=1)

        stage = workflow._run_axis_stage(
            state=PolarWorkflowState.ADJUST_AZ,
            axis=PolarAxis.AZ,
            rotation_axis=AZ_ADJUSTMENT_AXIS,
            target_correction_rad=math.radians(0.5),
            exposure_s=1.0,
            site_latitude_rad=_SITE_LAT_RAD,
            site_longitude_rad=_SITE_LON_RAD,
            site_elevation_m=0.0,
            config=config,
            feedback=FeedbackSession(config.feedback),
            on_update=updates.append,
            initial_hint=None,
        )

        assert stage.success is False
        assert "rebase/retry" in (stage.message or "")
        assert updates[-1].feedback is not None
        assert updates[-1].feedback.valid is False
        assert "wrong-axis" in (updates[-1].message or "")

    def test_repeated_solve_failures_stop_and_restore_tracking(self):
        service, _workflow, mount, camera, solver = _service_and_workflow()
        measurement = _measurement(_horizon_vector(-0.5, 44.6))
        camera.capture.side_effect = [_image(0), _image(1)]
        solver.solve.side_effect = [_failed_solve(), _failed_solve()]
        config = _deterministic_config(max_consecutive_failures=2)

        with patch.object(service, "_measure", return_value=measurement):
            result = service.adjust(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
                site_longitude_rad=_SITE_LON_RAD,
                exposure_s=1.0,
                config=config,
            )

        assert result.success is False
        assert result.state is PolarWorkflowState.FAILED
        assert "plate-solve failures" in (result.message or "")
        assert [call.args[0] for call in mount.set_tracking.call_args_list] == [
            False,
            True,
        ]

    def test_unexpected_exception_restores_tracking_and_propagates(self):
        service, _workflow, mount, _camera, _solver = _service_and_workflow()
        measurement = _measurement(_horizon_vector(-0.5, 44.6))

        with (
            patch.object(service, "_measure", return_value=measurement),
            patch.object(
                _PolarAdjustmentWorkflow,
                "_run_axis_stage",
                side_effect=RuntimeError("synthetic failure"),
            ),
            pytest.raises(RuntimeError, match="synthetic failure"),
        ):
            service.adjust(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
                site_longitude_rad=_SITE_LON_RAD,
            )

        assert [call.args[0] for call in mount.set_tracking.call_args_list] == [
            False,
            True,
        ]

    def test_tracking_disable_error_still_attempts_restoration(self):
        service, _workflow, mount, _camera, _solver = _service_and_workflow()
        measurement = _measurement(_horizon_vector(-0.5, 44.6))
        mount.set_tracking.side_effect = [RuntimeError("disable failed"), None]

        with (
            patch.object(service, "_measure", return_value=measurement),
            pytest.raises(RuntimeError, match="disable failed"),
        ):
            service.adjust(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
                site_longitude_rad=_SITE_LON_RAD,
            )

        assert [call.args[0] for call in mount.set_tracking.call_args_list] == [
            False,
            True,
        ]

    def test_invalid_site_is_rejected_before_initial_measurement(self):
        service, _workflow, _mount, _camera, _solver = _service_and_workflow()

        with (
            patch.object(service, "_measure") as measure,
            pytest.raises(ValueError, match="site_longitude_rad"),
        ):
            service.adjust(
                ra_rotation_rad=math.radians(15.0),
                site_latitude_rad=_SITE_LAT_RAD,
                site_longitude_rad=math.radians(200.0),
            )

        measure.assert_not_called()
