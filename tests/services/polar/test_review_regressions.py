import datetime
from dataclasses import replace
from unittest.mock import MagicMock, patch

from astrolabe.services.feedback import FeedbackSession
from astrolabe.services.polar.adjustment import AZ_ADJUSTMENT_AXIS
from astrolabe.services.polar.math import MIN_POSES
from astrolabe.services.polar.service import PolarAlignService
from astrolabe.services.polar.types import (
    PolarAdjustConfig,
    PolarAxis,
    PolarResult,
    PolarWorkflowState,
    _CircleFitResult,
    _PolarMeasurement,
    _PoseObservation,
    _SolveHint,
)
from astrolabe.services.polar.workflow import (
    _AxisStageResult,
    _LiveSolve,
    _PolarAdjustmentWorkflow,
)

_T0 = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)


def _measurement(*, hint: _SolveHint | None = None) -> _PolarMeasurement:
    poses = tuple(
        _PoseObservation(
            ra_rad=0.1 + 0.1 * index,
            dec_rad=0.5,
            rms_arcsec=1.0,
            timestamp_utc=_T0 + datetime.timedelta(seconds=index),
        )
        for index in range(MIN_POSES)
    )
    return _PolarMeasurement(
        result=PolarResult(
            alt_correction_arcsec=0.0,
            az_correction_arcsec=0.0,
            residual_arcsec=1.0,
            confidence=0.9,
        ),
        poses=poses,
        fit=_CircleFitResult(
            pole_ra_rad=0.2,
            pole_dec_rad=0.7,
            radius_rad=0.3,
            residual_rad=1e-6,
        ),
        hint=hint,
    )


def test_measurement_retains_final_solve_position_and_scale_for_live_hint():
    mount = MagicMock()
    mount.get_state.return_value = MagicMock(tracking=True, ra_rad=1.0, dec_rad=0.4)
    service = PolarAlignService(mount, MagicMock(), MagicMock())
    poses = [
        _PoseObservation(
            ra_rad=0.2 + 0.1 * index,
            dec_rad=0.5,
            rms_arcsec=1.0,
            timestamp_utc=_T0 + datetime.timedelta(seconds=index),
            scale_arcsec=1.25 + 0.1 * index,
        )
        for index in range(MIN_POSES)
    ]
    fit = _CircleFitResult(
        pole_ra_rad=0.2,
        pole_dec_rad=0.7,
        radius_rad=0.3,
        residual_rad=1e-6,
    )

    with (
        patch.object(service, "_capture_and_solve", side_effect=poses),
        patch(
            "astrolabe.services.polar.service.fit_polar_axis",
            return_value=(0.0, 0.0, fit),
        ),
        patch(
            "astrolabe.services.polar.service.correction_confidence",
            return_value=0.9,
        ),
        patch("astrolabe.services.polar.service.time.sleep"),
    ):
        measurement = service._measure(
            ra_rotation_rad=0.1,
            site_latitude_rad=0.5,
            exposure_s=1.0,
            settle_time_s=0.0,
            num_poses=MIN_POSES,
        )

    last = poses[-1]
    assert measurement.hint == _SolveHint(
        ra_rad=last.ra_rad,
        dec_rad=last.dec_rad,
        scale_arcsec=last.scale_arcsec,
    )


def test_live_az_stage_is_seeded_from_initial_measurement_hint():
    hint = _SolveHint(ra_rad=1.0, dec_rad=0.5, scale_arcsec=1.4)
    measurement = _measurement(hint=hint)
    mount = MagicMock()
    mount.get_state.return_value = MagicMock(tracking=True)
    workflow = _PolarAdjustmentWorkflow(
        mount,
        MagicMock(),
        MagicMock(),
        lambda **_kwargs: measurement,
    )
    stage_results = [
        _AxisStageResult(True, 0.0, 0.1, 3, hint),
        _AxisStageResult(True, 0.0, 0.1, 3, hint),
    ]

    with (
        patch(
            "astrolabe.services.polar.workflow.radec_to_horizon_vector",
            return_value=(0.0, 1.0, 0.0),
        ),
        patch(
            "astrolabe.services.polar.workflow.ideal_pole_horizon_vector",
            return_value=(0.0, 1.0, 0.0),
        ),
        patch(
            "astrolabe.services.polar.workflow.infer_rotation_about_axis",
            side_effect=[(0.1, 0.0), (0.1, 0.0)],
        ),
        patch(
            "astrolabe.services.polar.workflow.rotate_about_axis",
            return_value=(0.0, 1.0, 0.0),
        ),
        patch(
            "astrolabe.services.polar.workflow.altitude_adjustment_axis",
            return_value=(1.0, 0.0, 0.0),
        ),
        patch.object(workflow, "_run_axis_stage", side_effect=stage_results) as run_stage,
    ):
        result = workflow.run(
            ra_rotation_rad=0.1,
            site_latitude_rad=0.5,
            site_longitude_rad=0.2,
            site_elevation_m=0.0,
            exposure_s=1.0,
            settle_time_s=0.0,
            num_poses=MIN_POSES,
            config=PolarAdjustConfig(),
            on_update=None,
        )

    assert result.success is True
    assert run_stage.call_args_list[0].kwargs["initial_hint"] == hint


def test_invalid_sample_breaks_centered_stability_streak():
    mount = MagicMock()
    workflow = _PolarAdjustmentWorkflow(mount, MagicMock(), MagicMock(), MagicMock())

    def live(index: int) -> _LiveSolve:
        return _LiveSolve(
            observation=_PoseObservation(
                ra_rad=0.1,
                dec_rad=0.2,
                rms_arcsec=1.0,
                timestamp_utc=_T0 + datetime.timedelta(seconds=index),
            ),
            scale_arcsec=1.5,
        )

    captures = [
        (live(1), None),
        (None, "synthetic solve miss"),
        (live(2), None),
        (live(3), None),
        (live(4), None),
    ]
    base = PolarAdjustConfig()
    config = replace(
        base,
        feedback=replace(base.feedback, smoothing_alpha=1.0),
        max_samples_per_axis=len(captures),
    )

    with (
        patch.object(workflow, "_capture_live_solve", side_effect=captures),
        patch(
            "astrolabe.services.polar.workflow.radec_to_horizon_vector",
            return_value=(0.0, 1.0, 0.0),
        ),
        patch(
            "astrolabe.services.polar.workflow.infer_rotation_about_axis",
            return_value=(0.0, 0.0),
        ),
    ):
        stage = workflow._run_axis_stage(
            state=PolarWorkflowState.ADJUST_AZ,
            axis=PolarAxis.AZ,
            rotation_axis=AZ_ADJUSTMENT_AXIS,
            target_correction_rad=0.0,
            exposure_s=1.0,
            site_latitude_rad=0.5,
            site_longitude_rad=0.2,
            site_elevation_m=0.0,
            config=config,
            feedback=FeedbackSession(config.feedback),
            on_update=None,
            initial_hint=None,
        )

    assert stage.success is True
    assert stage.samples == 4
