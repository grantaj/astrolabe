"""Regression coverage for the final CLI Astrolabe-error boundary."""

from __future__ import annotations

import pytest

from astrolabe.errors import BackendError, ServiceError
from golden import FakeCamera, FakeMount, FakeSolver, envelope, patch_backends, run_cli


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


def test_service_constructor_astrolabe_error_is_mapped(monkeypatch, capsys):
    patch_backends(
        monkeypatch,
        mount=FakeMount(),
        camera=FakeCamera(),
        solver=FakeSolver(),
    )
    monkeypatch.setattr(
        "astrolabe.cli.commands.GotoService",
        lambda *args, **kwargs: _raise(ServiceError("goto construction boom")),
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
        "message": "goto construction boom",
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
