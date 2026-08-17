from dataclasses import dataclass
import math

from astrolabe.solver.types import SolveRequest, SolveResult
from astrolabe.pointing.model import PointingModel, DEFAULT_MODEL_PATH
from astrolabe.util.math import normalize_angle_rad


@dataclass
class PointingResult:
    success: bool
    solves_attempted: int
    solves_succeeded: int
    rms_arcsec: float | None
    message: str | None = None


class PointingService:
    def __init__(
        self,
        mount_backend,
        camera_backend,
        solver_backend,
        model: PointingModel | None = None,
    ):
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend
        self._model = model or PointingModel.load()

    def solve_current(
        self, exposure_s: float | None = None, *, use_mount_hints: bool = True
    ) -> SolveResult:
        needs_disconnect = False
        if not self._camera.is_connected():
            self._camera.connect()
            needs_disconnect = True
        try:
            image = self._camera.capture(exposure_s=exposure_s or 1.0)
        finally:
            if needs_disconnect:
                self._camera.disconnect()

        state = self._mount.get_state() if use_mount_hints else None
        request = SolveRequest(
            image=image,
            ra_hint_rad=state.ra_rad if state else None,
            dec_hint_rad=state.dec_rad if state else None,
        )
        return self._solver.solve(request)

    def sync_current(self, exposure_s: float | None = None) -> PointingResult:
        result = self.solve_current(exposure_s=exposure_s)
        if result.success and result.ra_rad is not None and result.dec_rad is not None:
            # A mount sync changes the mount's coordinate mapping to agree with the
            # solved sky position. Do not also learn the pre-sync discrepancy into
            # the persistent pointing model or later gotos would compensate twice.
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
            if (
                result.success
                and result.ra_rad is not None
                and result.dec_rad is not None
            ):
                # As in sync_current(), the sync itself corrects the mount model;
                # keeping the pre-sync delta in our persistent model would apply
                # the same correction again on a subsequent pointing-aware goto.
                self._mount.sync(result.ra_rad, result.dec_rad)
                successes += 1

        return PointingResult(
            success=successes >= target_count,
            solves_attempted=attempts,
            solves_succeeded=successes,
            rms_arcsec=last_rms,
            message=None
            if successes >= target_count
            else "Pointing calibrate incomplete",
        )

    def apply_model(self, ra_rad: float, dec_rad: float) -> tuple[float, float]:
        b_alpha, b_delta = self._model.predict()
        corrected_ra = normalize_angle_rad(ra_rad - b_alpha / math.cos(dec_rad))
        corrected_dec = dec_rad - b_delta
        return corrected_ra, corrected_dec

    def update_model_from_target(
        self,
        *,
        ra_target: float,
        dec_target: float,
        result: SolveResult,
        weight: float = 0.1,
    ) -> None:
        if result.ra_rad is None or result.dec_rad is None:
            return
        d_alpha, d_delta = _tangent_plane_error(
            ra_target=ra_target,
            dec_target=dec_target,
            ra_solved=result.ra_rad,
            dec_solved=result.dec_rad,
        )
        self._model.update(d_alpha, d_delta, weight=weight)
        self._model.save(DEFAULT_MODEL_PATH)


def _tangent_plane_error(
    *, ra_target: float, dec_target: float, ra_solved: float, dec_solved: float
) -> tuple[float, float]:
    d_ra = (ra_solved - ra_target + math.pi) % (2.0 * math.pi) - math.pi
    d_alpha = d_ra * math.cos(dec_target)
    d_delta = dec_solved - dec_target
    return d_alpha, d_delta
