from dataclasses import dataclass
import math

from astrolabe.solver.types import SolveRequest, SolveResult
from astrolabe.util.math import normalize_angle_rad

from .model import PointingModel


@dataclass
class PointingResult:
    success: bool
    target_ra_rad: float
    target_dec_rad: float
    command_ra_rad: float
    command_dec_rad: float
    solve: SolveResult
    final_error_arcsec: float | None
    model_updated: bool


class PointingService:
    def __init__(
        self,
        mount_backend,
        camera_backend,
        solver_backend,
        model: PointingModel,
    ):
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend
        self._model = model

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

    def point_to(
        self,
        ra_rad: float,
        dec_rad: float,
        exposure_s: float | None = None,
    ) -> PointingResult:
        """Point at a target and learn from the solved residual when trustworthy.

        The supplied model is applied before the slew and updated in memory after
        a successful, complete solve. Filesystem persistence remains the caller's
        responsibility.
        """
        command_ra, command_dec = self.apply_model(ra_rad, dec_rad)
        self._mount.slew_to(command_ra, command_dec)
        solve = self.solve_current(exposure_s=exposure_s, use_mount_hints=False)

        trustworthy = _is_trustworthy_solve(solve)
        final_error_arcsec = None
        if trustworthy:
            solved_ra = solve.ra_rad
            solved_dec = solve.dec_rad
            assert solved_ra is not None and solved_dec is not None
            d_alpha, d_delta = _tangent_plane_error(
                ra_target=ra_rad,
                dec_target=dec_rad,
                ra_solved=solved_ra,
                dec_solved=solved_dec,
            )
            final_error_arcsec = math.degrees(math.hypot(d_alpha, d_delta)) * 3600.0
            self._model.update(d_alpha, d_delta, weight=0.1)

        return PointingResult(
            success=trustworthy,
            target_ra_rad=ra_rad,
            target_dec_rad=dec_rad,
            command_ra_rad=command_ra,
            command_dec_rad=command_dec,
            solve=solve,
            final_error_arcsec=final_error_arcsec,
            model_updated=trustworthy,
        )

    def apply_model(self, ra_rad: float, dec_rad: float) -> tuple[float, float]:
        b_alpha, b_delta = self._model.predict()
        corrected_ra = normalize_angle_rad(ra_rad - b_alpha / math.cos(dec_rad))
        corrected_dec = dec_rad - b_delta
        return corrected_ra, corrected_dec


def _is_trustworthy_solve(result: SolveResult) -> bool:
    """Return whether a solve can safely become a pointing-model observation.

    Solver backends own ambiguity/failure detection and report it through
    ``success``. Pointing additionally fails closed on incomplete/non-finite or
    physically impossible solved coordinates before learning from the result.
    """
    if not result.success or result.ra_rad is None or result.dec_rad is None:
        return False
    if not math.isfinite(result.ra_rad) or not math.isfinite(result.dec_rad):
        return False
    return -math.pi / 2.0 <= result.dec_rad <= math.pi / 2.0


def _tangent_plane_error(
    *, ra_target: float, dec_target: float, ra_solved: float, dec_solved: float
) -> tuple[float, float]:
    d_ra = (ra_solved - ra_target + math.pi) % (2.0 * math.pi) - math.pi
    d_alpha = d_ra * math.cos(dec_target)
    d_delta = dec_solved - dec_target
    return d_alpha, d_delta
