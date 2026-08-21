"""Shared helpers for the CLI golden/characterisation tests.

These tests pin the observable CLI contract: stdout in ``--json`` mode,
stdout + stderr in human mode, and the process exit code.
"""

from __future__ import annotations

import datetime
import importlib
import json

from astrolabe.cli.main import main
from astrolabe.mount.base import MountState
from astrolabe.solver.types import Image, SolveResult

ENVELOPE_KEYS = {"ok", "command", "timestamp_utc", "data", "error"}

# Which backend factories each CLI module imports. Stated explicitly so that a
# rename raises AttributeError here instead of silently leaving a real backend
# in place.
_BACKEND_IMPORTS = {
    "astrolabe.cli.commands": (
        "get_mount_backend",
        "get_camera_backend",
        "get_solver_backend",
    ),
    "astrolabe.cli.runtime": (
        "get_mount_backend",
        "get_camera_backend",
        "get_solver_backend",
    ),
    "astrolabe.cli.focus": ("get_camera_backend",),
}


def run_cli(monkeypatch, capsys, *argv: str) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.argv", ["astrolabe", *argv])
    exit_code = main()
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def envelope(stdout: str) -> dict:
    payload = json.loads(stdout)
    assert set(payload) == ENVELOPE_KEYS
    datetime.datetime.fromisoformat(payload["timestamp_utc"])
    return payload


def patch_backends(monkeypatch, *, mount=None, camera=None, solver=None) -> None:
    """Patch the backend factories in every module the CLI imports them into.

    No tolerance for missing modules or names: if a factory moves, these tests
    must fail loudly rather than quietly reach real hardware backends.
    """
    wanted = {
        "get_mount_backend": mount,
        "get_camera_backend": camera,
        "get_solver_backend": solver,
    }
    for module_name, names in _BACKEND_IMPORTS.items():
        module = importlib.import_module(module_name)
        for name in names:
            backend = wanted[name]
            if backend is None:
                continue
            monkeypatch.setattr(module, name, lambda config, _b=backend: _b)


TIMESTAMP = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)


class FakeMount:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple] = []

    def _record(self, *call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    def connect(self) -> None:
        self._record("connect")

    def disconnect(self) -> None:
        self._record("disconnect")

    def is_connected(self) -> bool:
        return True

    def get_state(self) -> MountState:
        self._record("get_state")
        return MountState(
            connected=True,
            ra_rad=1.0,
            dec_rad=0.5,
            tracking=True,
            slewing=False,
            timestamp_utc=TIMESTAMP,
        )

    def slew_to(self, ra_rad: float, dec_rad: float) -> None:
        self._record("slew_to", ra_rad, dec_rad)

    def sync(self, ra_rad: float, dec_rad: float) -> None:
        self._record("sync", ra_rad, dec_rad)

    def park(self) -> None:
        self._record("park")

    def stop(self) -> None:
        self._record("stop")

    def set_tracking(self, enabled: bool) -> None:
        self._record("set_tracking", enabled)


class FakeCamera:
    def __init__(self, path: str = "/tmp/frame.fits", error: Exception | None = None):
        self.path = path
        self.error = error

    def connect(self) -> None:
        if self.error is not None:
            raise self.error

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def capture(self, exposure_s=None, gain=None, binning=None, roi=None) -> Image:
        if self.error is not None:
            raise self.error
        return Image(
            data=self.path,
            width_px=100,
            height_px=200,
            timestamp_utc=TIMESTAMP,
            exposure_s=exposure_s or 0.0,
            metadata={},
        )


def solve_result(success: bool = True) -> SolveResult:
    return SolveResult(
        success=success,
        ra_rad=1.0 if success else None,
        dec_rad=0.5 if success else None,
        pixel_scale_arcsec=1.25 if success else None,
        rotation_rad=0.25 if success else None,
        rms_arcsec=0.4 if success else None,
        num_stars=42 if success else None,
        message="solved" if success else "no stars",
        raw_output="RAW SOLVER TEXT",
    )


class FakeSolver:
    def __init__(self, result: SolveResult | None = None, available: bool = True):
        self.result = result or solve_result()
        self.available = available
        self.requests: list = []

    def is_available(self) -> dict:
        return {"ok": self.available, "detail": "found"}

    def solve(self, request):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result
