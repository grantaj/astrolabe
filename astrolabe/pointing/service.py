from dataclasses import dataclass
import math
import time

from astrolabe.errors import AstrolabeError, ServiceError
from astrolabe.solver.types import SolveRequest, SolveResult
from astrolabe.util.math import angular_separation_rad, normalize_angle_rad

from .model import PointingModel


_MAX_LEARNING_RESIDUAL_RAD = math.radians(10.0)
_CENTERING_TOLERANCE_RAD = math.radians(5.0 / 60.0)
_MAX_SINGLE_CORRECTION_RAD = math.radians(5.0)
_MAX_CORRECTION_ITERATIONS = 3
_MAX_CENTERING_TIME_S = 120.0
_MAX_CONSECUTIVE_SOLVE_FAILURES = 2
_MAX_STAGNANT_CORRECTIONS = 2
_STAGNATION_EPS_RAD = math.radians(1.0 / 3600.0)

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


class _CenteringDeadlineExceeded(Exception):
    pass


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
        return self._solve_current(
            exposure_s=exposure_s,
            use_mount_hints=use_mount_hints,
            deadline=None,
        )

    def _solve_current(
        self,
        exposure_s: float | None,
        *,
        use_mount_hints: bool,
        deadline: float | None,
    ) -> SolveResult:
        needs_disconnect = False
        if not self._camera.is_connected():
            _ensure_before_deadline(deadline)
            self._camera.connect()
            _ensure_before_deadline(deadline)
            needs_disconnect = True
        try:
            capture_exposure_s = exposure_s or 1.0
            remaining_s = _remaining_time_s(deadline)
            if remaining_s is not None and capture_exposure_s >= remaining_s:
                raise _CenteringDeadlineExceeded
            image = self._camera.capture(exposure_s=capture_exposure_s)
            _ensure_before_deadline(deadline)
        finally:
            if needs_disconnect:
                self._camera.disconnect()

        state = self._mount.get_state() if use_mount_hints else None
        _ensure_before_deadline(deadline)
        request = SolveRequest(
            image=image,
            ra_hint_rad=state.ra_rad if state else None,
            dec_hint_rad=state.dec_rad if state else None,
            timeout_s=_remaining_time_s(deadline),
        )
        result = self._solver.solve(request)
        _ensure_before_deadline(deadline)
        return result

    def point_to(
        self,
        ra_rad: float,
        dec_rad: float,
        exposure_s: float | None = None,
    ) -> PointingResult:
        """Point, learn from the first trustworthy solve, and center boundedly."""
        predicted_alpha, predicted_delta = self._model.predict()
        command_ra, command_dec = self.apply_model(ra_rad, dec_rad)
        self._mount.slew_to(command_ra, command_dec)
        self._wait_for_slew_settle()

        centering_deadline = time.monotonic() + _MAX_CENTERING_TIME_S
        current_command_ra = command_ra
        current_command_dec = command_dec
        model_updated = False
        correction_count = 0
        consecutive_solve_failures = 0
        stagnant_corrections = 0
        previous_error_rad: float | None = None
        last_trustworthy_solve: SolveResult | None = None
        last_error_arcsec: float | None = None

        while True:
            try:
                solve = self._solve_current(
                    exposure_s=exposure_s,
                    use_mount_hints=False,
                    deadline=centering_deadline,
                )
            except _CenteringDeadlineExceeded:
                return _centering_timeout_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    last_trustworthy_solve,
                    last_error_arcsec,
                    model_updated,
                )
            except AstrolabeError as exc:
                if last_trustworthy_solve is None:
                    raise
                return _pointing_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    last_trustworthy_solve,
                    last_error_arcsec,
                    model_updated,
                    f"Plate solve failed during centering: {exc}",
                )

            rejection_reason = _solve_rejection_reason(solve)
            if rejection_reason is not None:
                consecutive_solve_failures += 1
                if consecutive_solve_failures < _MAX_CONSECUTIVE_SOLVE_FAILURES:
                    continue
                return _pointing_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    last_trustworthy_solve or solve,
                    last_error_arcsec,
                    model_updated,
                    rejection_reason,
                )

            consecutive_solve_failures = 0
            solved_ra = solve.ra_rad
            solved_dec = solve.dec_rad
            assert solved_ra is not None and solved_dec is not None

            separation = angular_separation_rad(
                ra_rad,
                dec_rad,
                solved_ra,
                solved_dec,
            )
            final_error_arcsec = math.degrees(separation) * 3600.0

            if separation > _MAX_LEARNING_RESIDUAL_RAD:
                return _pointing_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    last_trustworthy_solve or solve,
                    last_error_arcsec,
                    model_updated,
                    f"Solved field is {math.degrees(separation):.2f} deg from the "
                    "requested target; treating the solve as geometrically "
                    "untrustworthy beyond the "
                    f"{math.degrees(_MAX_LEARNING_RESIDUAL_RAD):.1f} deg "
                    "learning envelope",
                )

            last_trustworthy_solve = solve
            last_error_arcsec = final_error_arcsec

            if correction_count == 0 and not model_updated:
                residual_alpha, residual_delta = _tangent_plane_error(
                    ra_target=ra_rad,
                    dec_target=dec_rad,
                    ra_solved=solved_ra,
                    dec_solved=solved_dec,
                )
                # Reconstruct the mount-bias observation from the first ordinary
                # model-applied pointing. Corrective solves are not new samples.
                self._model.update(
                    predicted_alpha + residual_alpha,
                    predicted_delta + residual_delta,
                    weight=0.1,
                )
                model_updated = True

            if separation <= _CENTERING_TOLERANCE_RAD:
                return PointingResult(
                    success=True,
                    target_ra_rad=ra_rad,
                    target_dec_rad=dec_rad,
                    command_ra_rad=current_command_ra,
                    command_dec_rad=current_command_dec,
                    solve=solve,
                    final_error_arcsec=final_error_arcsec,
                    model_updated=model_updated,
                )

            if correction_count >= _MAX_CORRECTION_ITERATIONS:
                return _pointing_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    solve,
                    final_error_arcsec,
                    model_updated,
                    "Target remained outside the 300 arcsec centering tolerance "
                    f"after {_MAX_CORRECTION_ITERATIONS} corrections",
                )

            if previous_error_rad is not None:
                if separation >= previous_error_rad - _STAGNATION_EPS_RAD:
                    stagnant_corrections += 1
                else:
                    stagnant_corrections = 0
                if stagnant_corrections >= _MAX_STAGNANT_CORRECTIONS:
                    return _pointing_failure(
                        ra_rad,
                        dec_rad,
                        current_command_ra,
                        current_command_dec,
                        solve,
                        final_error_arcsec,
                        model_updated,
                        "Centering correction failed to make meaningful progress",
                    )

            try:
                next_command_ra, next_command_dec = _corrective_command(
                    command_ra=current_command_ra,
                    command_dec=current_command_dec,
                    target_ra=ra_rad,
                    target_dec=dec_rad,
                    solved_ra=solved_ra,
                    solved_dec=solved_dec,
                )
            except AstrolabeError as exc:
                return _pointing_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    solve,
                    final_error_arcsec,
                    model_updated,
                    f"Cannot form a safe corrective slew: {exc}",
                )

            correction_magnitude_rad = angular_separation_rad(
                current_command_ra,
                current_command_dec,
                next_command_ra,
                next_command_dec,
            )
            if correction_magnitude_rad > _MAX_SINGLE_CORRECTION_RAD:
                return _pointing_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    solve,
                    final_error_arcsec,
                    model_updated,
                    "Required centering correction is "
                    f"{math.degrees(correction_magnitude_rad):.2f} deg, exceeding the "
                    f"{math.degrees(_MAX_SINGLE_CORRECTION_RAD):.1f} deg "
                    "single-correction bound",
                )

            previous_error_rad = separation
            correction_count += 1

            current_command_ra = next_command_ra
            current_command_dec = next_command_dec
            try:
                _ensure_before_deadline(centering_deadline)
                self._mount.slew_to(current_command_ra, current_command_dec)
                _ensure_before_deadline(centering_deadline)
                self._wait_for_slew_settle(deadline=centering_deadline)
            except _CenteringDeadlineExceeded:
                return _centering_timeout_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    last_trustworthy_solve,
                    last_error_arcsec,
                    model_updated,
                )
            except AstrolabeError as exc:
                return _pointing_failure(
                    ra_rad,
                    dec_rad,
                    current_command_ra,
                    current_command_dec,
                    solve,
                    final_error_arcsec,
                    model_updated,
                    f"Corrective slew failed: {exc}",
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

    def _wait_for_slew_settle(self, *, deadline: float | None = None) -> None:
        """Wait until the mount reports a stable non-slewing state."""
        settle_deadline = time.monotonic() + _SLEW_SETTLE_TIMEOUT_S
        if deadline is not None:
            settle_deadline = min(settle_deadline, deadline)
        stable_reads = 0
        while True:
            now = time.monotonic()
            if now >= settle_deadline:
                if deadline is not None and now >= deadline:
                    raise _CenteringDeadlineExceeded
                break
            if self._mount.get_state().slewing:
                stable_reads = 0
            else:
                stable_reads += 1
                if stable_reads >= _SLEW_SETTLE_STABLE_READS:
                    return
            sleep_s = min(_SLEW_SETTLE_POLL_S, settle_deadline - time.monotonic())
            if sleep_s > 0.0:
                time.sleep(sleep_s)
        raise ServiceError(
            "Mount did not report a settled slew within "
            f"{_SLEW_SETTLE_TIMEOUT_S:.0f} seconds"
        )


def _pointing_failure(
    target_ra_rad: float,
    target_dec_rad: float,
    command_ra_rad: float,
    command_dec_rad: float,
    solve: SolveResult,
    final_error_arcsec: float | None,
    model_updated: bool,
    message: str,
) -> PointingResult:
    return PointingResult(
        success=False,
        target_ra_rad=target_ra_rad,
        target_dec_rad=target_dec_rad,
        command_ra_rad=command_ra_rad,
        command_dec_rad=command_dec_rad,
        solve=solve,
        final_error_arcsec=final_error_arcsec,
        model_updated=model_updated,
        message=message,
    )


def _centering_timeout_failure(
    target_ra_rad: float,
    target_dec_rad: float,
    command_ra_rad: float,
    command_dec_rad: float,
    solve: SolveResult | None,
    final_error_arcsec: float | None,
    model_updated: bool,
) -> PointingResult:
    message = (
        "Target remained outside the 300 arcsec centering tolerance "
        f"after {_MAX_CENTERING_TIME_S:.0f} seconds"
    )
    return _pointing_failure(
        target_ra_rad,
        target_dec_rad,
        command_ra_rad,
        command_dec_rad,
        solve or _failed_solve_result(message),
        final_error_arcsec,
        model_updated,
        message,
    )


def _failed_solve_result(message: str) -> SolveResult:
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


def _remaining_time_s(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def _ensure_before_deadline(deadline: float | None) -> None:
    remaining_s = _remaining_time_s(deadline)
    if remaining_s is not None and remaining_s <= 0.0:
        raise _CenteringDeadlineExceeded


def _corrective_command(
    *,
    command_ra: float,
    command_dec: float,
    target_ra: float,
    target_dec: float,
    solved_ra: float,
    solved_dec: float,
) -> tuple[float, float]:
    d_ra = (solved_ra - target_ra + math.pi) % (2.0 * math.pi) - math.pi
    corrected_ra = normalize_angle_rad(command_ra - d_ra)
    corrected_dec = command_dec - (solved_dec - target_dec)
    _validate_command(corrected_ra, corrected_dec)
    return corrected_ra, corrected_dec


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
    """Return why a solve cannot become a pointing observation."""
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
