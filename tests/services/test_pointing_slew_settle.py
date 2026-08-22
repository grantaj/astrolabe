import datetime

import pytest

import astrolabe.pointing.service as pointing_service_module
from astrolabe.errors import ServiceError
from astrolabe.mount.base import MountState
from astrolabe.pointing import PointingModel, PointingService
from astrolabe.solver.types import Image, SolveResult


class FakeCamera:
    def __init__(self):
        self.connected = False
        self.captures = 0

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def is_connected(self):
        return self.connected

    def capture(self, exposure_s, gain=None, binning=None, roi=None):
        self.captures += 1
        return Image(
            data="fake",
            width_px=100,
            height_px=100,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
            exposure_s=exposure_s,
            metadata={},
        )


class FakeSolver:
    def __init__(self, result: SolveResult):
        self.result = result
        self.calls = 0

    def solve(self, request):
        self.calls += 1
        return self.result


class SequencedMount:
    def __init__(self, slewing_states):
        self._slewing_states = iter(slewing_states)
        self.state_calls = 0
        self.slew_calls = 0

    def slew_to(self, ra_rad, dec_rad):
        self.slew_calls += 1

    def get_state(self):
        self.state_calls += 1
        try:
            slewing = next(self._slewing_states)
        except StopIteration:
            slewing = False
        return MountState(
            connected=True,
            ra_rad=1.0,
            dec_rad=0.5,
            tracking=True,
            slewing=slewing,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        )


def _solve_result() -> SolveResult:
    return SolveResult(
        success=True,
        ra_rad=1.0,
        dec_rad=0.5,
        pixel_scale_arcsec=1.0,
        rotation_rad=0.0,
        rms_arcsec=1.0,
        num_stars=10,
        message="solved",
    )


def test_point_to_waits_for_stable_non_slewing_state(monkeypatch):
    mount = SequencedMount([True, False, False])
    camera = FakeCamera()
    solver = FakeSolver(_solve_result())
    service = PointingService(mount, camera, solver, model=PointingModel())
    monkeypatch.setattr(pointing_service_module.time, "sleep", lambda _seconds: None)

    result = service.point_to(1.0, 0.5)

    assert result.success is True
    assert mount.slew_calls == 1
    assert mount.state_calls == 3
    assert camera.captures == 1
    assert solver.calls == 1


def test_point_to_fails_before_capture_when_slew_does_not_settle(monkeypatch):
    mount = SequencedMount([True])
    camera = FakeCamera()
    solver = FakeSolver(_solve_result())
    service = PointingService(mount, camera, solver, model=PointingModel())
    monotonic_values = iter([0.0, 0.0, 31.0])
    monkeypatch.setattr(
        pointing_service_module.time, "monotonic", lambda: next(monotonic_values)
    )
    monkeypatch.setattr(pointing_service_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(ServiceError, match="did not report a settled slew"):
        service.point_to(1.0, 0.5)

    assert camera.captures == 0
    assert solver.calls == 0
