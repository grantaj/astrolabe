"""Tests for the `astrolabe polar` CLI command.

These tests exercise `run_polar` directly with a fake args namespace and
mocked backends/config loading, to verify exit codes and JSON envelope
semantics on success and failure.
"""

import io
import json
import math
import types
from unittest.mock import MagicMock, patch

import pytest

from astrolabe.cli import commands
from astrolabe.services.polar.types import PolarResult


def _args(**overrides):
    defaults = dict(
        ra_rotation_deg=15.0,
        latitude_deg=45.0,
        exposure=2.0,
        settle_time=2.0,
        num_poses=4,
        json=False,
        dry_run=False,
        log_level=None,
        config=None,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


@pytest.fixture
def patched_backends():
    with (
        patch.object(commands, "load_config", return_value={}),
        patch.object(commands, "get_mount_backend", return_value=MagicMock()),
        patch.object(commands, "get_camera_backend", return_value=MagicMock()),
        patch.object(commands, "get_solver_backend", return_value=MagicMock()),
        patch.object(commands, "PolarAlignService") as svc_cls,
    ):
        yield svc_cls


def test_success_returns_zero_and_ok_true(patched_backends, capsys):
    patched_backends.return_value.run.return_value = PolarResult(
        alt_correction_arcsec=12.3,
        az_correction_arcsec=-4.5,
        residual_arcsec=1.1,
        confidence=0.85,
    )

    rc = commands.run_polar(_args(json=True))
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["alt_correction_arcsec"] == 12.3


def test_failure_returns_nonzero_and_ok_false(patched_backends, capsys):
    patched_backends.return_value.run.return_value = PolarResult(
        alt_correction_arcsec=None,
        az_correction_arcsec=None,
        residual_arcsec=None,
        confidence=None,
        message="Plate solve failed at pose 2",
    )

    rc = commands.run_polar(_args(json=True))
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "polar_failed"
    assert "pose 2" in payload["error"]["message"]


def test_failure_non_json_prints_to_stderr(patched_backends, capsys):
    patched_backends.return_value.run.return_value = PolarResult(
        alt_correction_arcsec=None,
        az_correction_arcsec=None,
        residual_arcsec=None,
        confidence=None,
        message="Circle fit failed: singular",
    )

    rc = commands.run_polar(_args(json=False))
    captured = capsys.readouterr()

    assert rc == 1
    assert "Polar alignment failed" in captured.err
    assert "singular" in captured.err


def test_num_poses_forwarded_to_service(patched_backends):
    patched_backends.return_value.run.return_value = PolarResult(
        alt_correction_arcsec=1.0,
        az_correction_arcsec=1.0,
        residual_arcsec=0.1,
        confidence=0.9,
    )

    commands.run_polar(_args(num_poses=6))

    call = patched_backends.return_value.run.call_args
    assert call.kwargs["num_poses"] == 6
    assert math.isclose(call.kwargs["ra_rotation_rad"], math.radians(15.0))
