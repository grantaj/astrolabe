from dataclasses import dataclass
import math
import time

from astrolabe.errors import ServiceError
from astrolabe.solver.types import SolveRequest, SolveResult
from astrolabe.util.math import angular_separation_rad, normalize_angle_rad

from .model import PointingModel


_MAX_LEARNING_RESIDUAL_RAD = math.radians(10.0)
_SLEW_SETTLE_TIMEOUT_S = 30.0
_SLEW_SETTLE_POLL_S = 0.2
_SLEW_SETTLE_STABLE_READS = 2


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
    message: str | None = None


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
        a successful, complete solve whose residual is within the v1 model's
        learning envelope. Filesystem persistence remains the caller's
        responsibility.
        """
        predicted_alpha, predicted_delta = self._model.predict()
        command_ra, command_dec = self.apply_model(ra_rad, dec_rad)
        self._mount.slew_to(command_ra, command_dec)
        self._wait_for_slew_settle()
        solve = self.solve_current(exposure_s=exposure_s, use_mount_hints=False)

        rejection_reason = _solve_rejection_reason(solve)
        final_error_arcsec = None
        model_updated = False
        if rejection_reason is None:
            solved_ra = solve.ra_rad
            solved_dec = solve.dec_rad
            assert solved_ra is not None and solved_dec is not None
            residual_alpha, residual_delta = _tangent_plane_error(
                ra_target=ra_rad,
                dec_target=dec_rad,
                ra_solved=solved_ra,
                dec_solved=solved_dec,
            )
            final_error_arcsec = (
                math.degrees(math.hypot(residual_alpha, residual_delta)) * 3600.0
            )

            separation = angular_separation_rad(
                ra_rad,
                dec_rad,
                solved_ra,
                solved_dec,
            )
            if separation > _MAX_LEARNING_RESIDUAL_RAD:
                rejection_reason = (
                    f"Solved field is {math.degrees(separation):.2f} deg from the "
                    "requested target; refusing pointing-model update beyond the "
                    f"{math.degrees(_MAX_LEARNING_RESIDUAL_RAD):.1f} deg learning envelope"
                )
            else:
                # The solve measures what remains after applying the current model.
                # Reconstruct the underlying mount-bias observation before feeding it
                # to the model's EMA; using the residual itself would make a stable
                # bias converge to only half its true value.
                observed_alpha = predicted_alpha + residual_alpha
                observed_delta = predicted_delta + residual_delta
                self._model.update(observed_alpha, observed_delta, weight=0.1)
                model_updated = True

        return PointingResult(
            success=rejection_reason is None,
            target_ra_rad=ra_rad,
            target_dec_rad=dec_rad,
            command_ra_rad=command_ra,
            command_dec_rad=command_dec,
            solve=solve,
            final_error_arcsec=final_error_arcsec,
            model_updated=model_updated,
            message=rejection_reason,
        )

    def apply_model(self, ra_rad: float, dec_rad: float) -> tuple[float, float]:
        _validate_target(ra_rad, dec_rad)
        b_alpha, b_delta = self._model.predict()
        if not math.isfinite(b_alpha) or not math.isfinite(b_delta):
            raise ServiceError("Pointing model contains a non-finite bias")

        raw_corrected_ra = ra_rad - b_alpha / math.cos(dec_rad)
        corrected_dec = dec_rad - b_delta
        _validate_command(raw_corrected_ra, corrected_dec)
        return normalize_angle_rad(raw_corrected_ra), corrected_dec

    def _wait_for_slew_settle(self) -> None:
        """Wait until the mount reports a stable non-slewing state."""
        deadline = time.monotonic() + _SLEW_SETTLE_TIMEOUT_S
        stable_reads = 0
        while time.monotonic() < deadline:
            if self._mount.get_state().slewing:
                stable_reads = 0
            else:
                stable_reads += 1
                if stable_reads >= _SLEW_SETTLE_STABLE_READS:
                    return
            time.sleep(_SLEW_SETTLE_POLL_S)
        raise ServiceError(
            "Mount did not report a settled slew within "
            f"{_SLEW_SETTLE_TIMEOUT_S:.0f} seconds"
        )


def _validate_target(ra_rad: float, dec_rad: float) -> None:
    if not math.isfinite(ra_rad) or not math.isfinite(dec_rad):
        raise ServiceError("Pointing target coordinates must be finite")
    if not -math.pi / 2.0 <= dec_rad <= math.pi / 2.0:
        raise ServiceError("Pointing target declination is outside the physical sky")


def _validate_command(ra_rad: float, dec_rad: float) -> None:
    if not math.isfinite(ra_rad) or not math.isfinite(dec_rad):
        raise ServiceError("Pointing model produced non-finite mount coordinates")
    if not -math.pi / 2.0 <= dec_rad <= math.pi / 2.0:
        raise ServiceError("Pointing model produced an invalid mount declination")


def _solve_rejection_reason(result: SolveResult) -> str | None:
    """Return why a solve cannot become a pointing-model observation."""
    if not result.success:
        return result.message or "Plate solve failed"
    if result.ra_rad is None or result.dec_rad is None:
        return "Plate solve returned incomplete coordinates"
    if not math.isfinite(result.ra_rad) or not math.isfinite(result.dec_rad):
        return "Plate solve returned non-finite coordinates"
    if not -math.pi / 2.0 <= result.dec_rad <= math.pi / 2.0:
        return "Plate solve returned an invalid declination"
    return None


def _tangent_plane_error(
    *, ra_target: float, dec_target: float, ra_solved: float, dec_solved: float
) -> tuple[float, float]:
    d_ra = (ra_solved - ra_target + math.pi) % (2.0 * math.pi) - math.pi
    d_alpha = d_ra * math.cos(dec_target)
    d_delta = dec_solved - dec_target
    return d_alpha, d_delta
