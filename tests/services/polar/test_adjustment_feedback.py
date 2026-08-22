import datetime
import math
from dataclasses import replace
from unittest.mock import MagicMock, patch

import erfa

from astrolabe.camera.types import Image
from astrolabe.services.feedback import FeedbackDirection, FeedbackSession
from astrolabe.services.polar.adjustment import (
    AZ_ADJUSTMENT_AXIS,
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
from astrolabe.services.polar.workflow import (
    _AxisStageResult,
    _PolarAdjustmentWorkflow,
)
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


def _measurement(axis_vector):
    pole_ra, pole_dec = _horizon_to_icrs(axis_vector, _T0)
    return _PolarMeasurement(
        result=PolarResult(
            alt_correction_arcsec=0.0,
            az_correction_arcsec=0.0,
            residual_arcsec=0.5,
            confidence=0.95,
        ),
        poses=tuple(
            _PoseObservation(
                ra_rad=math.radians(index * 20.0),
                dec_rad=math.radians(60.0),
                rms_arcsec=1.0,
                timestamp_utc=_T0,
            )
            for index in range(4)
        ),
        fit=_CircleFitResult(
            pole_ra_rad=pole_ra,
            pole_dec_rad=pole_dec,
            radius_rad=math.radians(20.0),
            residual_rad=math.radians(0.5 / 3600.0),
        ),
    )


def test_realistic_solve_noise_does_not_false_complete_or_reverse_sign():
    _service, workflow, _mount, camera, solver = _service_and_workflow()
    reference = _horizon_vector(120.0, 45.0)
    target_deg = 0.5
    applied_deg = [
        0.0,
        0.45 + 10.0 / 3600.0,
        0.45 - 10.0 / 3600.0,
        0.45 + 5.0 / 3600.0,
        0.5,
        0.5,
        0.5,
    ]
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
    base = PolarAdjustConfig()
    config = replace(
        base,
        feedback=replace(base.feedback, smoothing_alpha=1.0),
    )
    updates = []

    stage = workflow._run_axis_stage(
        state=PolarWorkflowState.ADJUST_AZ,
        axis=PolarAxis.AZ,
        rotation_axis=AZ_ADJUSTMENT_AXIS,
        target_correction_rad=math.radians(target_deg),
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
    assert all(direction is FeedbackDirection.POSITIVE for direction in directions[:-3])
    assert directions[-3:] == [FeedbackDirection.CENTERED] * 3
    assert stage.success is True
    assert stage.samples == len(applied_deg)


def test_feedback_session_is_reset_between_az_and_alt():
    service, _workflow, _mount, _camera, _solver = _service_and_workflow()
    measurement = _measurement(_horizon_vector(-0.5, 44.6))

    class SpyFeedbackSession(FeedbackSession):
        last_instance = None

        def __init__(self, *args, **kwargs):
            self.reset_count = 0
            super().__init__(*args, **kwargs)
            SpyFeedbackSession.last_instance = self

        def reset(self):
            self.reset_count += 1
            super().reset()

    stage_results = [
        _AxisStageResult(
            success=True,
            remaining_rad=0.0,
            applied_rad=math.radians(0.5),
            samples=3,
            last_hint=None,
        ),
        _AxisStageResult(
            success=True,
            remaining_rad=0.0,
            applied_rad=math.radians(0.4),
            samples=3,
            last_hint=None,
        ),
    ]

    with (
        patch.object(service, "_measure", return_value=measurement),
        patch(
            "astrolabe.services.polar.workflow.FeedbackSession",
            SpyFeedbackSession,
        ),
        patch.object(
            _PolarAdjustmentWorkflow,
            "_run_axis_stage",
            side_effect=stage_results,
        ),
    ):
        result = service.adjust(
            ra_rotation_rad=math.radians(15.0),
            site_latitude_rad=_SITE_LAT_RAD,
            site_longitude_rad=_SITE_LON_RAD,
        )

    assert result.success is True
    assert SpyFeedbackSession.last_instance is not None
    assert SpyFeedbackSession.last_instance.reset_count == 2
