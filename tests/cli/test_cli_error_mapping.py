"""Pins for the shared exception-to-exit-code mapping (`docs/cli.md` §2).

Before the CLI plumbing consolidation, only `mount`, `goto`, `pointing`/`align`,
`polar`, `guide` and `plan` wrapped exceptions, and only `NotImplementedFeature`
(all of them) plus `ServiceError` (`polar` alone) were mapped. Every other
Astrolabe exception escaped the handler, so the process died with a traceback
and the interpreter's exit status 1.

Now every handler routes AstrolabeError through
``astrolabe.cli.runtime.handle_error``, with one documented exemption: `update`
keeps its pre-existing broad ``except Exception`` -> code "update_failed",
exit 1 (see test_cli_golden.test_update_failure_json).

The mapping is:

    NotImplementedFeature -> exit 2, code "not_implemented"
    BackendError          -> exit 2, code "backend_error"
    ServiceError          -> exit 1, code "service_error"
    AstrolabeError        -> exit 2, code "internal_error"
"""

from __future__ import annotations

import pytest

from astrolabe.errors import (
    AstrolabeError,
    BackendError,
    NotImplementedFeature,
    ServiceError,
)
from golden import FakeCamera, FakeMount, FakeSolver, envelope, patch_backends, run_cli

_MAPPING = [
    (NotImplementedFeature("boom"), 2, "not_implemented"),
    (BackendError("boom"), 2, "backend_error"),
    (ServiceError("boom"), 1, "service_error"),
    (AstrolabeError("boom"), 2, "internal_error"),
]


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))


def _raise(exc):
    raise exc


def _patch(monkeypatch, exc):
    patch_backends(
        monkeypatch,
        mount=FakeMount(error=exc),
        camera=FakeCamera(error=exc),
        solver=FakeSolver(),
    )


def _unreachable_indi(monkeypatch):
    """Keep `doctor`'s socket probe deterministic and instant."""
    monkeypatch.setattr(
        "astrolabe.cli.commands.socket.create_connection",
        lambda *a, **k: _raise(ConnectionRefusedError()),
    )


@pytest.mark.parametrize("exc,exit_code,code", _MAPPING, ids=lambda v: str(v))
def test_doctor_wiring_error_mapping(monkeypatch, capsys, exc, exit_code, code):
    """`doctor` previously had no exception mapping at all (traceback, status 1)."""
    _patch(monkeypatch, exc)
    _unreachable_indi(monkeypatch)
    monkeypatch.setattr(
        "astrolabe.cli.commands.get_solver_backend", lambda config: _raise(exc)
    )
    result, out, err = run_cli(monkeypatch, capsys, "--json", "doctor")
    payload = envelope(out)
    assert result == exit_code
    assert payload["command"] == "doctor"
    assert payload["error"] == {"code": code, "message": "boom", "details": None}


@pytest.mark.parametrize("exc,exit_code,code", _MAPPING, ids=lambda v: str(v))
def test_doctor_solver_probe_error_mapping(monkeypatch, capsys, exc, exit_code, code):
    """The solver probe is the one `doctor` check without its own `except`."""

    class _ExplodingSolver(FakeSolver):
        def is_available(self):
            raise exc

    patch_backends(
        monkeypatch,
        mount=FakeMount(),
        camera=FakeCamera(),
        solver=_ExplodingSolver(),
    )
    _unreachable_indi(monkeypatch)
    result, out, err = run_cli(monkeypatch, capsys, "--json", "doctor")
    payload = envelope(out)
    assert result == exit_code
    assert payload["command"] == "doctor"
    assert payload["error"] == {"code": code, "message": "boom", "details": None}


def test_doctor_probe_failures_still_degrade_to_report_rows(monkeypatch, capsys):
    """Camera/mount/config probes keep their own `except Exception` degradation."""
    _patch(monkeypatch, BackendError("mount offline"))
    _unreachable_indi(monkeypatch)
    result, out, err = run_cli(monkeypatch, capsys, "--json", "doctor")
    payload = envelope(out)
    assert result == 1
    assert payload["error"]["code"] == "doctor_failed"
    assert payload["data"]["checks"]["mount (indi)"] == {
        "ok": False,
        "detail": "connect failed: mount offline",
    }


@pytest.mark.parametrize("exc,exit_code,code", _MAPPING, ids=lambda v: str(v))
def test_mount_status_error_mapping(monkeypatch, capsys, exc, exit_code, code):
    _patch(monkeypatch, exc)
    result, out, err = run_cli(monkeypatch, capsys, "--json", "mount", "status")
    payload = envelope(out)
    assert result == exit_code
    assert payload["command"] == "mount.status"
    assert payload["error"] == {"code": code, "message": "boom", "details": None}


@pytest.mark.parametrize("exc,exit_code,code", _MAPPING, ids=lambda v: str(v))
def test_resolve_error_mapping(monkeypatch, capsys, exc, exit_code, code):
    """`resolve` previously had no exception mapping at all (traceback, status 1)."""
    monkeypatch.setattr(
        "astrolabe.services.target.resolver.TargetResolver.from_repo_data",
        classmethod(lambda cls, **kwargs: _raise(exc)),
    )
    result, out, err = run_cli(monkeypatch, capsys, "--json", "resolve", "M31")
    payload = envelope(out)
    assert result == exit_code
    assert payload["command"] == "resolve"
    assert payload["error"] == {"code": code, "message": "boom", "details": None}


@pytest.mark.parametrize("exc,exit_code,code", _MAPPING, ids=lambda v: str(v))
def test_focus_measure_error_mapping(monkeypatch, capsys, exc, exit_code, code):
    """`focus` previously had no mapping around its prologue (traceback, status 1)."""
    monkeypatch.setattr("astrolabe.cli.runtime.load_config", lambda path: _raise(exc))
    result, out, err = run_cli(
        monkeypatch, capsys, "--json", "focus", "measure", "--in", "/nope/x.fits"
    )
    payload = envelope(out)
    assert result == exit_code
    assert payload["command"] == "focus.measure"
    assert payload["error"] == {"code": code, "message": "boom", "details": None}


@pytest.mark.parametrize("exc,exit_code,code", _MAPPING, ids=lambda v: str(v))
def test_view_error_mapping(monkeypatch, capsys, tmp_path, exc, exit_code, code):
    """`view` catches AstrolabeError ahead of its broad `except Exception`."""
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    monkeypatch.setattr("astropy.io.fits.open", lambda path: _raise(exc))
    result, out, err = run_cli(monkeypatch, capsys, "--json", "view", "--in", str(fits))
    payload = envelope(out)
    assert result == exit_code
    assert payload["command"] == "view"
    assert payload["error"] == {"code": code, "message": "boom", "details": None}


def test_view_non_astrolabe_error_still_maps_to_view_failed(
    monkeypatch, capsys, tmp_path
):
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    monkeypatch.setattr(
        "astropy.io.fits.open", lambda path: _raise(OSError("bad header"))
    )
    result, out, err = run_cli(monkeypatch, capsys, "--json", "view", "--in", str(fits))
    payload = envelope(out)
    assert result == 1
    assert payload["error"]["code"] == "view_failed"
    assert payload["error"]["message"] == "Error viewing FITS file: bad header"


@pytest.mark.parametrize("exc,exit_code,code", _MAPPING, ids=lambda v: str(v))
def test_capture_error_mapping(monkeypatch, capsys, exc, exit_code, code):
    """`capture` previously had no exception mapping at all (traceback, status 1)."""
    _patch(monkeypatch, exc)
    result, out, err = run_cli(
        monkeypatch, capsys, "--json", "capture", "--exposure", "1"
    )
    payload = envelope(out)
    assert result == exit_code
    assert payload["command"] == "capture"
    assert payload["error"]["code"] == code


@pytest.mark.parametrize("exc,exit_code,code", _MAPPING, ids=lambda v: str(v))
def test_solve_error_mapping(monkeypatch, capsys, tmp_path, exc, exit_code, code):
    """`solve` previously had no exception mapping at all (traceback, status 1)."""
    solver = FakeSolver()
    solver.result = exc
    patch_backends(monkeypatch, mount=FakeMount(), camera=FakeCamera(), solver=solver)
    fits = tmp_path / "frame.fits"
    fits.write_text("x")
    result, out, err = run_cli(monkeypatch, capsys, "--json", "solve", str(fits))
    payload = envelope(out)
    assert result == exit_code
    assert payload["command"] == "solve"
    assert payload["error"]["code"] == code


def test_human_error_text_matches_previous_wording(monkeypatch, capsys):
    _patch(monkeypatch, NotImplementedFeature("Mount park not implemented"))
    result, out, err = run_cli(monkeypatch, capsys, "mount", "park")
    assert result == 2
    assert err == "Mount park not implemented\n"

    _patch(monkeypatch, ServiceError("mount unhappy"))
    result, out, err = run_cli(monkeypatch, capsys, "mount", "park")
    assert result == 1
    assert err == "Error: mount unhappy\n"
