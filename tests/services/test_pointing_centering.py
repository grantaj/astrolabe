import datetime
import math

import pytest

import astrolabe.pointing.service as pointing_service_module
from astrolabe.errors import BackendError
from astrolabe.mount.base import MountState
from astrolabe.pointing import PointingModel, PointingService
from astrolabe.solver.types import Image, SolveRequest, SolveResult
from astrolabe.util.math import normalize_angle_rad


_TARGET_RA = 1.0
_TARGET_DEC = 0.4


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


class SequencedSolver:
    def __init__(self, results):
        self._results = iter(results)
        self.requests: list[SolveRequest] = []

    def solve(self, request: SolveRequest) -> SolveResult:
        self.requests.append(request)
        return next(self._results)


class FakeMount:
    def __init__(self, *, fail_on_slew_call: int | None = None):
        self.slew_calls: list[tuple[float, float]] = []
        self.fail_on_slew_call = fail_on_slew_call

    def slew_to(self, ra_rad, dec_rad):
        self.slew_calls.append((ra_rad, dec_rad))
        if self.fail_on_slew_call == len(self.slew_calls):
            raise BackendError("injected mount failure")

    def get_state(self):
        return MountState(
            connected=True,
            ra_rad=_TARGET_RA,
            dec_rad=_TARGET_DEC,
            tracking=True,
            slewing=False,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        )


def _solve_offset(*, ra_arcsec: float = 0.0, dec_arcsec: float = 0.0) -> SolveResult:
    return SolveResult(
        success=True,
        ra_rad=_TARGET_RA + math.radians(ra_arcsec / 3600.0) / math.cos(_TARGET_DEC),
        dec_rad=_TARGET_DEC + math.radians(dec_arcsec / 3600.0),
        pixel_scale_arcsec=1.0,
        rotation_rad=0.0,
        rms_arcsec=1.0,
        num_stars=10,
        message="solved",
    )


def _failed_solve(message: str = "failed") -> SolveResult:
    return SolveResult(
        success=False,
        ra_rad=None,
        dec_rad=None,
        pixel_scale_arcsec=None,
        rotation_rad=None,
        rms_arcsec=None,
        num_stars=None,
        message=message,
    )


def _expected_ra_after_correction(current_ra: float, residual_arcsec: float) -> float:
    residual_ra_rad = math.radians(residual_arcsec / 3600.0) / math.cos(_TARGET_DEC)
    return normalize_angle_rad(current_ra - residual_ra_rad)


def test_already_centered_succeeds_after_one_solve():
    mount = FakeMount()
    solver = SequencedSolver([_solve_offset(ra_arcsec=120.0)])
    service = PointingService(mount, FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is True
    assert result.final_error_arcsec == pytest.approx(120.0, rel=0.01)
    assert len(mount.slew_calls) == 1
    assert len(solver.requests) == 1


def test_one_corrective_slew_centers_target():
    mount = FakeMount()
    solver = SequencedSolver(
        [_solve_offset(ra_arcsec=900.0), _solve_offset(ra_arcsec=60.0)]
    )
    service = PointingService(mount, FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is True
    assert result.final_error_arcsec == pytest.approx(60.0, rel=0.01)
    assert len(mount.slew_calls) == 2
    assert len(solver.requests) == 2
    assert mount.slew_calls[1][0] == pytest.approx(
        _expected_ra_after_correction(_TARGET_RA, 900.0)
    )
    assert mount.slew_calls[1][1] == pytest.approx(_TARGET_DEC)


def test_multiple_improving_corrections_converge():
    mount = FakeMount()
    solver = SequencedSolver(
        [
            _solve_offset(ra_arcsec=1800.0),
            _solve_offset(ra_arcsec=900.0),
            _solve_offset(ra_arcsec=120.0),
        ]
    )
    service = PointingService(mount, FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is True
    assert len(mount.slew_calls) == 3
    assert len(solver.requests) == 3
    first_correction_ra = _expected_ra_after_correction(_TARGET_RA, 1800.0)
    second_correction_ra = _expected_ra_after_correction(first_correction_ra, 900.0)
    assert mount.slew_calls[1] == pytest.approx((first_correction_ra, _TARGET_DEC))
    assert mount.slew_calls[2] == pytest.approx((second_correction_ra, _TARGET_DEC))


def test_one_overshoot_can_recover_and_converge():
    mount = FakeMount()
    solver = SequencedSolver(
        [
            _solve_offset(ra_arcsec=900.0),
            _solve_offset(ra_arcsec=-1100.0),
            _solve_offset(ra_arcsec=100.0),
        ]
    )
    service = PointingService(mount, FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is True
    assert len(mount.slew_calls) == 3
    first_correction_ra = _expected_ra_after_correction(_TARGET_RA, 900.0)
    recovery_ra = _expected_ra_after_correction(first_correction_ra, -1100.0)
    assert mount.slew_calls[1] == pytest.approx((first_correction_ra, _TARGET_DEC))
    assert mount.slew_calls[2] == pytest.approx((recovery_ra, _TARGET_DEC))


def test_repeated_solve_failure_is_bounded():
    mount = FakeMount()
    solver = SequencedSolver([_failed_solve("lost"), _failed_solve("lost")])
    model = PointingModel()
    service = PointingService(mount, FakeCamera(), solver, model=model)

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert result.message == "lost"
    assert len(mount.slew_calls) == 1
    assert len(solver.requests) == 2
    assert model.num_samples == 0


def test_two_stagnant_corrections_fail_without_using_last_iteration():
    mount = FakeMount()
    solver = SequencedSolver(
        [
            _solve_offset(ra_arcsec=1000.0),
            _solve_offset(ra_arcsec=1000.0),
            _solve_offset(ra_arcsec=1000.0),
        ]
    )
    service = PointingService(mount, FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert "meaningful progress" in (result.message or "")
    assert len(mount.slew_calls) == 3
    assert len(solver.requests) == 3


def test_max_correction_iterations_is_bounded():
    mount = FakeMount()
    solver = SequencedSolver(
        [
            _solve_offset(ra_arcsec=1000.0),
            _solve_offset(ra_arcsec=800.0),
            _solve_offset(ra_arcsec=600.0),
            _solve_offset(ra_arcsec=400.0),
        ]
    )
    service = PointingService(mount, FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert "after 3 corrections" in (result.message or "")
    assert len(mount.slew_calls) == 4
    assert len(solver.requests) == 4


def test_centering_time_is_bounded(monkeypatch):
    monkeypatch.setattr(pointing_service_module, "_MAX_CENTERING_TIME_S", 0.0)
    mount = FakeMount()
    camera = FakeCamera()
    solver = SequencedSolver([_solve_offset(ra_arcsec=1000.0)])
    service = PointingService(mount, camera, solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert "after 0 seconds" in (result.message or "")
    assert len(mount.slew_calls) == 1
    assert camera.captures == 0
    assert len(solver.requests) == 0


def test_solver_timeout_uses_remaining_centering_budget():
    solver = SequencedSolver([_solve_offset(ra_arcsec=120.0)])
    service = PointingService(FakeMount(), FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is True
    timeout_s = solver.requests[0].timeout_s
    assert timeout_s is not None
    assert 0.0 < timeout_s <= pointing_service_module._MAX_CENTERING_TIME_S


def test_expired_budget_during_corrective_settle_does_not_start_another_solve(
    monkeypatch,
):
    class FakeTime:
        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    fake_time = FakeTime()
    monkeypatch.setattr(pointing_service_module, "time", fake_time)

    class BudgetConsumingMount(FakeMount):
        def __init__(self):
            super().__init__()
            self.consumed_budget = False

        def get_state(self):
            state = super().get_state()
            if len(self.slew_calls) >= 2 and not self.consumed_budget:
                fake_time.now += pointing_service_module._MAX_CENTERING_TIME_S
                self.consumed_budget = True
            return state

    mount = BudgetConsumingMount()
    camera = FakeCamera()
    solver = SequencedSolver(
        [_solve_offset(ra_arcsec=900.0), _solve_offset(ra_arcsec=60.0)]
    )
    service = PointingService(mount, camera, solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert "after 120 seconds" in (result.message or "")
    assert len(mount.slew_calls) == 2
    assert camera.captures == 1
    assert len(solver.requests) == 1


def test_single_correction_magnitude_is_bounded_but_first_solve_can_still_learn():
    mount = FakeMount()
    model = PointingModel()
    solver = SequencedSolver([_solve_offset(ra_arcsec=6.0 * 3600.0)])
    service = PointingService(mount, FakeCamera(), solver, model=model)

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert "single-correction bound" in (result.message or "")
    assert len(mount.slew_calls) == 1
    assert model.num_samples == 1


def test_single_correction_bound_uses_actual_command_motion_geometry():
    target_ra = 0.0
    target_dec = math.radians(89.0)
    solve = SolveResult(
        success=True,
        ra_rad=math.pi,
        dec_rad=target_dec,
        pixel_scale_arcsec=1.0,
        rotation_rad=0.0,
        rms_arcsec=1.0,
        num_stars=10,
        message="solved",
    )
    mount = FakeMount()
    model = PointingModel(b_delta_rad=math.radians(9.0), num_samples=1)
    service = PointingService(
        mount, FakeCamera(), SequencedSolver([solve]), model=model
    )

    result = service.point_to(target_ra, target_dec)

    assert result.success is False
    assert "single-correction bound" in (result.message or "")
    assert len(mount.slew_calls) == 1
    assert mount.slew_calls[0][1] == pytest.approx(math.radians(80.0))


def test_mount_failure_during_correction_returns_last_truthful_residual():
    mount = FakeMount(fail_on_slew_call=2)
    first = _solve_offset(ra_arcsec=900.0)
    solver = SequencedSolver([first])
    service = PointingService(mount, FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert "Corrective slew failed" in (result.message or "")
    assert result.solve is first
    assert result.final_error_arcsec == pytest.approx(900.0, rel=0.01)


def test_geometrically_untrustworthy_solve_neither_corrects_nor_learns():
    mount = FakeMount()
    model = PointingModel()
    solver = SequencedSolver([_solve_offset(ra_arcsec=20.0 * 3600.0)])
    service = PointingService(mount, FakeCamera(), solver, model=model)

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert result.final_error_arcsec is None
    assert "geometrically untrustworthy" in (result.message or "")
    assert len(mount.slew_calls) == 1
    assert model.num_samples == 0


def test_corrective_solves_do_not_double_count_model_learning():
    model = PointingModel()
    solver = SequencedSolver(
        [
            _solve_offset(ra_arcsec=1200.0),
            _solve_offset(ra_arcsec=600.0),
            _solve_offset(ra_arcsec=60.0),
        ]
    )
    service = PointingService(FakeMount(), FakeCamera(), solver, model=model)

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is True
    assert model.num_samples == 1


def test_failure_after_later_solve_failures_reports_final_trustworthy_solve():
    first = _solve_offset(ra_arcsec=900.0)
    final_trustworthy = _solve_offset(ra_arcsec=400.0)
    solver = SequencedSolver(
        [first, final_trustworthy, _failed_solve("lost"), _failed_solve("lost")]
    )
    service = PointingService(FakeMount(), FakeCamera(), solver, model=PointingModel())

    result = service.point_to(_TARGET_RA, _TARGET_DEC)

    assert result.success is False
    assert result.solve is final_trustworthy
    assert result.final_error_arcsec == pytest.approx(400.0, rel=0.01)
