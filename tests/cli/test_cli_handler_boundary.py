"""Regression coverage for the final CLI Astrolabe-error boundary."""

from __future__ import annotations

import pytest

from astrolabe.errors import BackendError, ServiceError
from astrolabe.pointing import PointingResult
from golden import (
    FakeCamera,
    FakeMount,
    FakeSolver,
    envelope,
    patch_backends,
    run_cli,
    solve_result,
)


def _raise(exc):
    raise exc


def test_prepare_astrolabe_error_is_mapped(monkeypatch, capsys):
    monkeypatch.setattr(
        "astrolabe.cli.runtime.load_config",
        lambda path: _raise(BackendError("config boom")),
    )

    result, out, err = run_cli(monkeypatch, capsys, "--json", "solve", "frame.fits")
    payload = envelope(out)

    assert result == 2
    assert payload["command"] == "solve"
    assert payload["error"] == {
        "code": "backend_error",
        "message": "config boom",
        "details": None,
    }


def test_backend_factory_astrolabe_error_is_mapped(monkeypatch, capsys):
    monkeypatch.setattr(
        "astrolabe.cli.commands.get_mount_backend",
        lambda config: _raise(BackendError("mount factory boom")),
    )

    result, out, err = run_cli(monkeypatch, capsys, "--json", "mount", "status")
    payload = envelope(out)

    assert result == 2
    assert payload["command"] == "mount.status"
    assert payload["error"] == {
        "code": "backend_error",
        "message": "mount factory boom",
        "details": None,
    }


def test_pointing_service_constructor_astrolabe_error_is_mapped(monkeypatch, capsys):
    patch_backends(
        monkeypatch,
        mount=FakeMount(),
        camera=FakeCamera(),
        solver=FakeSolver(),
    )
    monkeypatch.setattr(
        "astrolabe.cli.commands.PointingService",
        lambda *args, **kwargs: _raise(ServiceError("pointing construction boom")),
    )

    result, out, err = run_cli(
        monkeypatch,
        capsys,
        "--json",
        "goto",
        "--ra-deg",
        "10",
        "--dec-deg",
        "20",
    )
    payload = envelope(out)

    assert result == 1
    assert payload["command"] == "goto"
    assert payload["error"] == {
        "code": "service_error",
        "message": "pointing construction boom",
        "details": None,
    }


def test_align_solve_preserves_legacy_failure_code(monkeypatch, capsys):
    patch_backends(
        monkeypatch,
        mount=FakeMount(),
        camera=FakeCamera(),
        solver=FakeSolver(),
    )

    class _PointingService:
        def __init__(self, *args, **kwargs):
            pass

        def solve_current(self, exposure_s=None):
            return solve_result(success=False)

    monkeypatch.setattr("astrolabe.cli.commands.PointingService", _PointingService)

    result, out, err = run_cli(monkeypatch, capsys, "--json", "align", "solve")
    payload = envelope(out)

    assert result == 1
    assert payload["command"] == "align.solve"
    assert payload["error"] == {
        "code": "align_failed",
        "message": "no stars",
        "details": None,
    }


def test_pointing_rejection_reason_reaches_cli(monkeypatch, capsys):
    patch_backends(
        monkeypatch,
        mount=FakeMount(),
        camera=FakeCamera(),
        solver=FakeSolver(),
    )

    class _PointingService:
        def __init__(self, *args, **kwargs):
            pass

        def point_to(self, ra_rad, dec_rad, exposure_s=None):
            return PointingResult(
                success=False,
                target_ra_rad=ra_rad,
                target_dec_rad=dec_rad,
                command_ra_rad=ra_rad,
                command_dec_rad=dec_rad,
                solve=solve_result(success=True),
                final_error_arcsec=100000.0,
                model_updated=False,
                message="Solved field is outside the pointing-model learning envelope",
            )

    monkeypatch.setattr("astrolabe.cli.commands.PointingService", _PointingService)

    result, out, err = run_cli(
        monkeypatch,
        capsys,
        "--json",
        "pointing",
        "goto",
        "--ra-deg",
        "10",
        "--dec-deg",
        "20",
    )
    payload = envelope(out)

    assert result == 1
    assert payload["error"] == {
        "code": "pointing_goto_failed",
        "message": "Solved field is outside the pointing-model learning envelope",
        "details": None,
    }


def test_non_astrolabe_setup_error_still_propagates(monkeypatch, capsys):
    """The final boundary must not become a broad catch-all."""
    monkeypatch.setattr(
        "astrolabe.cli.runtime.load_config",
        lambda path: _raise(ValueError("bad config")),
    )

    with pytest.raises(ValueError, match="bad config"):
        run_cli(monkeypatch, capsys, "--json", "plan")
