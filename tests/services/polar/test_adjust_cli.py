import json
import math
import types
from unittest.mock import MagicMock, patch

from astrolabe.cli import polar as polar_cli
from astrolabe.config import Config
from astrolabe.services.feedback import FeedbackDirection, FeedbackState
from astrolabe.services.polar import (
    PolarAdjustResult,
    PolarAdjustmentUpdate,
    PolarAxis,
    PolarResult,
    PolarWorkflowState,
)


def _args(**overrides):
    defaults = dict(
        polar_action="adjust",
        ra_rotation_deg=15.0,
        latitude_deg=None,
        longitude_deg=None,
        elevation_m=None,
        exposure=2.0,
        settle_time=2.0,
        num_poses=4,
        tolerance_arcsec=30.0,
        stable_samples=3,
        json=False,
        dry_run=False,
        log_level=None,
        config=None,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def _success_result():
    return PolarAdjustResult(
        success=True,
        state=PolarWorkflowState.COMPLETE,
        initial=PolarResult(
            alt_correction_arcsec=120.0,
            az_correction_arcsec=-60.0,
            residual_arcsec=1.0,
            confidence=0.9,
        ),
        az_remaining_arcsec=2.0,
        alt_remaining_arcsec=-3.0,
        az_samples=5,
        alt_samples=6,
    )


def test_adjust_rejects_global_json_with_one_object(capsys):
    rc = polar_cli.run_polar(_args(json=True))

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["command"] == "polar.adjust"
    assert payload["error"]["code"] == "interactive_json_unsupported"


def test_adjust_uses_configured_site_and_calls_live_service(capsys):
    service = MagicMock()
    service.adjust.return_value = _success_result()
    config = Config(
        {
            "site": {
                "latitude_deg": -34.9,
                "longitude_deg": 138.6,
                "elevation_m": 120.0,
            }
        }
    )

    with (
        patch.object(polar_cli, "prepare", return_value=config),
        patch.object(
            polar_cli,
            "mount_camera_solver",
            return_value=(MagicMock(), MagicMock(), MagicMock()),
        ),
        patch.object(polar_cli, "PolarAlignService", return_value=service),
    ):
        rc = polar_cli.run_polar(_args())

    assert rc == 0
    call = service.adjust.call_args
    assert call.kwargs["site_latitude_rad"] == math.radians(-34.9)
    assert call.kwargs["site_longitude_rad"] == math.radians(138.6)
    assert call.kwargs["site_elevation_m"] == 120.0
    assert call.kwargs["config"].stable_samples == 3
    assert "tracking restored" in capsys.readouterr().out


def test_measure_default_preserves_legacy_handler():
    args = _args(polar_action=None, latitude_deg=45.0)
    with patch.object(polar_cli, "run_polar_measure", return_value=0) as run_measure:
        rc = polar_cli.run_polar(args)

    assert rc == 0
    run_measure.assert_called_once_with(args)


def test_measure_can_use_configured_latitude():
    args = _args(polar_action="measure", latitude_deg=None)
    with (
        patch.object(
            polar_cli,
            "load_config",
            return_value=Config({"site": {"latitude_deg": 42.0}}),
        ),
        patch.object(polar_cli, "run_polar_measure", return_value=0) as run_measure,
    ):
        rc = polar_cli.run_polar(args)

    assert rc == 0
    assert args.latitude_deg == 42.0
    run_measure.assert_called_once_with(args)


def test_physical_direction_words_are_axis_specific(capsys):
    polar_cli._render_adjustment_update(
        PolarAdjustmentUpdate(
            state=PolarWorkflowState.ADJUST_AZ,
            axis=PolarAxis.AZ,
            feedback=FeedbackState(
                direction=FeedbackDirection.POSITIVE,
                proximity=0.5,
                valid=True,
                guidance=math.radians(2.0 / 60.0),
            ),
        )
    )
    polar_cli._render_adjustment_update(
        PolarAdjustmentUpdate(
            state=PolarWorkflowState.ADJUST_AZ,
            axis=PolarAxis.AZ,
            feedback=FeedbackState(
                direction=FeedbackDirection.NEGATIVE,
                proximity=0.5,
                valid=True,
                guidance=-math.radians(1.0 / 60.0),
            ),
        )
    )
    polar_cli._render_adjustment_update(
        PolarAdjustmentUpdate(
            state=PolarWorkflowState.ADJUST_ALT,
            axis=PolarAxis.ALT,
            feedback=FeedbackState(
                direction=FeedbackDirection.POSITIVE,
                proximity=0.5,
                valid=True,
                guidance=math.radians(30.0 / 3600.0),
            ),
        )
    )
    polar_cli._render_adjustment_update(
        PolarAdjustmentUpdate(
            state=PolarWorkflowState.ADJUST_ALT,
            axis=PolarAxis.ALT,
            feedback=FeedbackState(
                direction=FeedbackDirection.NEGATIVE,
                proximity=0.5,
                valid=True,
                guidance=-math.radians(20.0 / 3600.0),
            ),
        )
    )

    output = capsys.readouterr().out
    assert "AZ: east" in output
    assert "AZ: west" in output
    assert "ALT: raise" in output
    assert "ALT: lower" in output
