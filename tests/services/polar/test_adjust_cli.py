import json
import math
import types
from unittest.mock import MagicMock, patch

from astrolabe.cli import polar as polar_cli
from astrolabe.config import Config
from astrolabe.errors import BackendError
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
        no_audio=True,
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


def _site_config():
    return Config(
        {
            "site": {
                "latitude_deg": -34.9,
                "longitude_deg": 138.6,
                "elevation_m": 120.0,
            }
        }
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

    with (
        patch.object(polar_cli, "prepare", return_value=_site_config()),
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


def test_adjust_wires_feedback_to_real_sink_boundary(capsys):
    service = MagicMock()
    sink = MagicMock()
    feedback = FeedbackState(
        direction=FeedbackDirection.POSITIVE,
        proximity=0.5,
        valid=True,
        guidance=math.radians(2.0 / 60.0),
    )

    def adjust(**kwargs):
        kwargs["on_update"](
            PolarAdjustmentUpdate(
                state=PolarWorkflowState.ADJUST_AZ,
                axis=PolarAxis.AZ,
                feedback=feedback,
            )
        )
        return _success_result()

    service.adjust.side_effect = adjust
    with (
        patch.object(polar_cli, "prepare", return_value=_site_config()),
        patch.object(
            polar_cli,
            "mount_camera_solver",
            return_value=(MagicMock(), MagicMock(), MagicMock()),
        ),
        patch.object(polar_cli, "PolarAlignService", return_value=service),
        patch.object(polar_cli, "AudioSink", return_value=sink) as audio_sink,
    ):
        rc = polar_cli.run_polar(_args(no_audio=False))

    assert rc == 0
    audio_sink.assert_called_once_with()
    sink.check.assert_called()
    sink.play.assert_called_once()
    cue = sink.play.call_args.args[0]
    assert cue is not None
    assert cue.frequencies_hz == (880.0,)
    sink.close.assert_called_once_with()
    assert "AZ: east" in capsys.readouterr().out


def test_no_audio_does_not_acquire_audio_resources():
    service = MagicMock()
    service.adjust.return_value = _success_result()

    with (
        patch.object(polar_cli, "prepare", return_value=_site_config()),
        patch.object(
            polar_cli,
            "mount_camera_solver",
            return_value=(MagicMock(), MagicMock(), MagicMock()),
        ),
        patch.object(polar_cli, "PolarAlignService", return_value=service),
        patch.object(polar_cli, "AudioSink") as audio_sink,
    ):
        rc = polar_cli.run_polar(_args(no_audio=True))

    assert rc == 0
    audio_sink.assert_not_called()


def test_audio_startup_failure_is_explicit_and_prevents_adjustment(capsys):
    service = MagicMock()

    with (
        patch.object(polar_cli, "prepare", return_value=_site_config()),
        patch.object(polar_cli, "PolarAlignService", return_value=service),
        patch.object(
            polar_cli,
            "AudioSink",
            side_effect=BackendError("no audio output device"),
        ),
    ):
        rc = polar_cli.run_polar(_args(no_audio=False))

    assert rc == 2
    service.adjust.assert_not_called()
    assert "no audio output device" in capsys.readouterr().err


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
