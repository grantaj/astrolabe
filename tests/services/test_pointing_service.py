import datetime
import inspect
import math

import pytest

from astrolabe.mount.base import MountState
from astrolabe.pointing import PointingModel, PointingService
from astrolabe.solver.types import Image, SolveRequest, SolveResult


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
        self.requests: list[SolveRequest] = []

    def solve(self, request: SolveRequest) -> SolveResult:
        self.requests.append(request)
        return self.result


class FakeMount:
    def __init__(self):
        self.slew_calls: list[tuple[float, float]] = []
        self.state = MountState(
            connected=True,
            ra_rad=1.0,
            dec_rad=0.5,
            tracking=True,
            slewing=False,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        )

    def get_state(self):
        return self.state

    def slew_to(self, ra_rad, dec_rad):
        self.slew_calls.append((ra_rad, dec_rad))


def _solve_result(
    *,
    success: bool = True,
    ra_rad: float | None = 1.0,
    dec_rad: float | None = 0.5,
) -> SolveResult:
    return SolveResult(
        success=success,
        ra_rad=ra_rad,
        dec_rad=dec_rad,
        pixel_scale_arcsec=1.0 if success else None,
        rotation_rad=0.0 if success else None,
        rms_arcsec=1.5 if success else None,
        num_stars=8 if success else None,
        message="ok" if success else "failed",
    )


def test_service_requires_explicit_model():
    model_parameter = inspect.signature(PointingService).parameters["model"]
    assert model_parameter.default is inspect.Parameter.empty


def test_solve_current_uses_mount_hint_and_solver():
    camera = FakeCamera()
    solver = FakeSolver(_solve_result(ra_rad=1.1, dec_rad=0.4))
    mount = FakeMount()
    service = PointingService(mount, camera, solver, model=PointingModel())

    result = service.solve_current(exposure_s=3.0)

    assert result.success is True
    assert camera.captures == 1
    assert solver.requests
    assert solver.requests[0].ra_hint_rad == mount.state.ra_rad
    assert solver.requests[0].dec_hint_rad == mount.state.dec_rad


def test_apply_model_correction():
    camera = FakeCamera()
    solver = FakeSolver(_solve_result())
    mount = FakeMount()
    model = PointingModel(b_alpha_rad=0.01, b_delta_rad=-0.02)
    service = PointingService(mount, camera, solver, model=model)

    ra_cmd, dec_cmd = service.apply_model(1.0, 0.5)

    assert ra_cmd == pytest.approx(1.0 - 0.01 / math.cos(0.5))
    assert dec_cmd == pytest.approx(0.5 + 0.02)


def test_point_to_applies_model_slews_solves_and_updates_model():
    target_ra = 0.9
    target_dec = 0.4
    model = PointingModel(b_alpha_rad=0.01, b_delta_rad=-0.02)
    mount = FakeMount()
    solver = FakeSolver(_solve_result(ra_rad=0.92, dec_rad=0.41))
    service = PointingService(mount, FakeCamera(), solver, model=model)

    result = service.point_to(target_ra, target_dec, exposure_s=2.0)

    expected_ra = target_ra - 0.01 / math.cos(target_dec)
    expected_dec = target_dec + 0.02
    assert mount.slew_calls == [(pytest.approx(expected_ra), pytest.approx(expected_dec))]
    assert solver.requests[0].ra_hint_rad is None
    assert solver.requests[0].dec_hint_rad is None
    assert result.success is True
    assert result.model_updated is True
    assert result.command_ra_rad == pytest.approx(expected_ra)
    assert result.command_dec_rad == pytest.approx(expected_dec)
    assert result.final_error_arcsec is not None
    assert model.num_samples == 1


def test_point_to_does_not_learn_from_failed_solve():
    model = PointingModel()
    mount = FakeMount()
    solver = FakeSolver(_solve_result(success=False, ra_rad=None, dec_rad=None))
    service = PointingService(mount, FakeCamera(), solver, model=model)

    result = service.point_to(0.9, 0.4)

    assert result.success is False
    assert result.model_updated is False
    assert result.final_error_arcsec is None
    assert model.num_samples == 0


def test_point_to_does_not_learn_from_incomplete_solve():
    model = PointingModel()
    solver = FakeSolver(_solve_result(success=True, ra_rad=None, dec_rad=0.4))
    service = PointingService(FakeMount(), FakeCamera(), solver, model=model)

    result = service.point_to(0.9, 0.4)

    assert result.model_updated is False
    assert result.final_error_arcsec is None
    assert model.num_samples == 0


def test_point_to_wraps_ra_error_on_short_arc():
    model = PointingModel()
    target_ra = 2.0 * math.pi - 0.01
    solved_ra = 0.01
    solver = FakeSolver(_solve_result(ra_rad=solved_ra, dec_rad=0.0))
    service = PointingService(FakeMount(), FakeCamera(), solver, model=model)

    result = service.point_to(target_ra, 0.0)

    assert result.model_updated is True
    assert model.b_alpha_rad == pytest.approx(0.002)


def test_legacy_service_import_is_compatibility_alias():
    from astrolabe.services.pointing import PointingService as LegacyPointingService

    assert LegacyPointingService is PointingService
