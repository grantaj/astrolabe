from dataclasses import dataclass
from astrolabe.solver.types import SolveRequest, SolveResult


@dataclass
class PointingResult:
    success: bool
    solves_attempted: int
    solves_succeeded: int
    rms_arcsec: float | None
    message: str | None = None


class PointingService:
    def __init__(self, mount_backend, camera_backend, solver_backend):
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend

    def solve_current(self, exposure_s: float | None = None) -> SolveResult:
        needs_disconnect = False
        if not self._camera.is_connected():
            self._camera.connect()
            needs_disconnect = True
        try:
            image = self._camera.capture(exposure_s=exposure_s or 1.0)
        finally:
            if needs_disconnect:
                self._camera.disconnect()

        state = self._mount.get_state()
        request = SolveRequest(
            image=image,
            ra_hint_rad=state.ra_rad,
            dec_hint_rad=state.dec_rad,
        )
        return self._solver.solve(request)

    def sync_current(self, exposure_s: float | None = None) -> PointingResult:
        result = self.solve_current(exposure_s=exposure_s)
        if result.success and result.ra_rad is not None and result.dec_rad is not None:
            self._mount.sync(result.ra_rad, result.dec_rad)
            return PointingResult(
                success=True,
                solves_attempted=1,
                solves_succeeded=1,
                rms_arcsec=result.rms_arcsec,
                message=result.message,
            )
        return PointingResult(
            success=False,
            solves_attempted=1,
            solves_succeeded=0,
            rms_arcsec=result.rms_arcsec,
            message=result.message or "Pointing sync failed",
        )

    def initial_alignment(
        self,
        target_count: int,
        exposure_s: float | None = None,
        max_attempts: int | None = None,
    ) -> PointingResult:
        if target_count <= 0:
            raise ValueError("target_count must be positive")
        attempts = 0
        successes = 0
        last_rms = None
        while successes < target_count:
            if max_attempts is not None and attempts >= max_attempts:
                break
            attempts += 1
            result = self.solve_current(exposure_s=exposure_s)
            last_rms = result.rms_arcsec
            if result.success and result.ra_rad is not None and result.dec_rad is not None:
                self._mount.sync(result.ra_rad, result.dec_rad)
                successes += 1

        return PointingResult(
            success=successes >= target_count,
            solves_attempted=attempts,
            solves_succeeded=successes,
            rms_arcsec=last_rms,
            message=None if successes >= target_count else "Pointing calibrate incomplete",
        )
