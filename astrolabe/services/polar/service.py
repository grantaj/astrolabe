import math
import time

from astrolabe.errors import ServiceError
from astrolabe.solver.types import SolveRequest

from .math import MIN_POSES, correction_confidence, fit_polar_axis
from .types import PolarResult, _PoseObservation

_RAD_TO_ARCSEC = 180.0 / math.pi * 3600.0


class PolarAlignService:
    def __init__(self, mount_backend, camera_backend, solver_backend):
        self._mount = mount_backend
        self._camera = camera_backend
        self._solver = solver_backend

    def run(
        self,
        ra_rotation_rad: float,
        site_latitude_rad: float,
        exposure_s: float = 2.0,
        settle_time_s: float = 2.0,
        num_poses: int = MIN_POSES,
    ) -> PolarResult:
        """Execute the N-pose polar alignment routine.

        Rotates in RA ``num_poses - 1`` times, capturing and plate-solving
        at each position.  The field centres are fitted to a small circle
        whose pole is the mount's actual rotation axis.  A minimum of four
        poses is required so that the fit residual is a meaningful signal
        of pose-to-pose consistency.
        """
        if num_poses < MIN_POSES:
            raise ServiceError(f"num_poses must be ≥{MIN_POSES}, got {num_poses}")

        state = self._mount.get_state()
        if not state.tracking:
            raise ServiceError("Mount must be sidereally tracking for polar alignment")
        if state.ra_rad is None or state.dec_rad is None:
            raise ServiceError(
                "Mount coordinates unavailable; cannot perform polar alignment"
            )

        poses: list[_PoseObservation] = []
        for i in range(num_poses):
            if i > 0:
                self._rotate_ra(ra_rotation_rad, settle_time_s)
            pose = self._capture_and_solve(exposure_s)
            if pose is None:
                return _fail(f"Plate solve failed at pose {i + 1}")
            poses.append(pose)

        try:
            alt_err, az_err, fit = fit_polar_axis(poses, site_latitude_rad)
        except ValueError as e:
            return _fail(f"Circle fit failed: {e}")

        confidence = correction_confidence(fit, poses)

        return PolarResult(
            alt_correction_arcsec=alt_err * _RAD_TO_ARCSEC,
            az_correction_arcsec=az_err * _RAD_TO_ARCSEC,
            residual_arcsec=fit.residual_rad * _RAD_TO_ARCSEC,
            confidence=confidence,
        )

    def _capture_and_solve(self, exposure_s: float) -> _PoseObservation | None:
        """Capture a frame, plate-solve it, return the field centre."""
        state = self._mount.get_state()
        image = self._camera.capture(exposure_s)

        request = SolveRequest(
            image=image,
            ra_hint_rad=state.ra_rad,
            dec_hint_rad=state.dec_rad,
        )
        result = self._solver.solve(request)

        if not result.success:
            return None
        if result.ra_rad is None or result.dec_rad is None:
            return None

        return _PoseObservation(
            ra_rad=result.ra_rad,
            dec_rad=result.dec_rad,
            rms_arcsec=result.rms_arcsec,
            timestamp_utc=image.timestamp_utc,
        )

    def _rotate_ra(self, delta_rad: float, settle_time_s: float) -> None:
        """Slew the mount by delta_rad in RA, then wait for vibrations."""
        state = self._mount.get_state()
        if state.ra_rad is None or state.dec_rad is None:
            raise ServiceError(
                "Mount coordinates became unavailable mid-sequence; aborting"
            )
        target_ra = state.ra_rad + delta_rad
        self._mount.slew_to(target_ra, state.dec_rad)
        time.sleep(settle_time_s)


def _fail(message: str) -> PolarResult:
    return PolarResult(
        alt_correction_arcsec=None,
        az_correction_arcsec=None,
        residual_arcsec=None,
        confidence=None,
        message=message,
    )
