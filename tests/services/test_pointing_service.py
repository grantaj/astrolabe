import datetime

from astrolabe.services.pointing import PointingService
from astrolabe.solver.types import Image, SolveRequest, SolveResult
from astrolabe.mount.base import MountState


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
        self.sync_calls: list[tuple[float, float]] = []
        self.state = MountState(
            connected=True,
            ra_rad=1.0,
            dec_rad=2.0,
            tracking=True,
            slewing=False,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        )

    def get_state(self):
        return self.state

    def sync(self, ra_rad, dec_rad):
        self.sync_calls.append((ra_rad, dec_rad))


def test_solve_current_uses_mount_hint_and_solver():
    camera = FakeCamera()
    solver = FakeSolver(
        SolveResult(
            success=True,
            ra_rad=1.1,
            dec_rad=2.2,
            pixel_scale_arcsec=1.0,
            rotation_rad=0.0,
            rms_arcsec=2.0,
            num_stars=10,
            message=None,
        )
    )
    mount = FakeMount()
    service = PointingService(mount, camera, solver)

    result = service.solve_current(exposure_s=3.0)

    assert result.success is True
    assert camera.captures == 1
    assert solver.requests
    assert solver.requests[0].ra_hint_rad == mount.state.ra_rad
    assert solver.requests[0].dec_hint_rad == mount.state.dec_rad


def test_sync_current_syncs_on_success():
    camera = FakeCamera()
    solver = FakeSolver(
        SolveResult(
            success=True,
            ra_rad=3.0,
            dec_rad=4.0,
            pixel_scale_arcsec=1.0,
            rotation_rad=0.0,
            rms_arcsec=1.5,
            num_stars=8,
            message="ok",
        )
    )
    mount = FakeMount()
    service = PointingService(mount, camera, solver)

    result = service.sync_current(exposure_s=1.0)

    assert result.success is True
    assert mount.sync_calls == [(3.0, 4.0)]


def test_initial_alignment_counts_successes():
    camera = FakeCamera()
    solver = FakeSolver(
        SolveResult(
            success=True,
            ra_rad=3.0,
            dec_rad=4.0,
            pixel_scale_arcsec=1.0,
            rotation_rad=0.0,
            rms_arcsec=1.5,
            num_stars=8,
            message=None,
        )
    )
    mount = FakeMount()
    service = PointingService(mount, camera, solver)

    result = service.initial_alignment(target_count=2, exposure_s=1.0)

    assert result.success is True
    assert result.solves_attempted == 2
    assert result.solves_succeeded == 2
    assert len(mount.sync_calls) == 2
