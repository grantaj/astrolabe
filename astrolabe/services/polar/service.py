from __future__ import annotations

import math
import time
from collections.abc import Callable

from astrolabe.errors import ServiceError
from astrolabe.solver.types import SolveRequest
from astrolabe.util.math import rad_to_arcsec

from .math import MIN_POSES, correction_confidence, fit_polar_axis
from .types import (
    PolarAdjustConfig,
    PolarAdjustmentUpdate,
    PolarAdjustResult,
    PolarResult,
    _PolarMeasurement,
    _PoseObservation,
)
from .workflow import _PolarAdjustmentWorkflow


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
        """Execute the compatibility N-pose polar-axis measurement."""
        return self._measure(
            ra_rotation_rad=ra_rotation_rad,
            site_latitude_rad=site_latitude_rad,
            exposure_s=exposure_s,
            settle_time_s=settle_time_s,
            num_poses=num_poses,
        ).result

    def adjust(
        self,
        ra_rotation_rad: float,
        site_latitude_rad: float,
        site_longitude_rad: float,
        *,
        site_elevation_m: float = 0.0,
        exposure_s: float = 2.0,
        settle_time_s: float = 2.0,
        num_poses: int = MIN_POSES,
        config: PolarAdjustConfig | None = None,
        on_update: Callable[[PolarAdjustmentUpdate], None] | None = None,
    ) -> PolarAdjustResult:
        """Measure once, then guide AZ and ALT manual adjustment in sequence."""
        _validate_adjustment_site(
            site_latitude_rad=site_latitude_rad,
            site_longitude_rad=site_longitude_rad,
            site_elevation_m=site_elevation_m,
        )
        workflow = _PolarAdjustmentWorkflow(
            self._mount,
            self._camera,
            self._solver,
            self._measure,
        )
        return workflow.run(
            ra_rotation_rad=ra_rotation_rad,
            site_latitude_rad=site_latitude_rad,
            site_longitude_rad=site_longitude_rad,
            site_elevation_m=site_elevation_m,
            exposure_s=exposure_s,
            settle_time_s=settle_time_s,
            num_poses=num_poses,
            config=config or PolarAdjustConfig(),
            on_update=on_update,
        )

    def _measure(
        self,
        *,
        ra_rotation_rad: float,
        site_latitude_rad: float,
        exposure_s: float,
        settle_time_s: float,
        num_poses: int,
    ) -> _PolarMeasurement:
        """Run the N-pose measurement while retaining fit geometry internally."""
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
                return _PolarMeasurement(
                    result=_fail(f"Plate solve failed at pose {i + 1}"),
                    poses=tuple(poses),
                    fit=None,
                )
            poses.append(pose)

        try:
            alt_err, az_err, fit = fit_polar_axis(poses, site_latitude_rad)
        except ValueError as exc:
            return _PolarMeasurement(
                result=_fail(f"Circle fit failed: {exc}"),
                poses=tuple(poses),
                fit=None,
            )

        confidence = correction_confidence(fit, poses)
        return _PolarMeasurement(
            result=PolarResult(
                alt_correction_arcsec=rad_to_arcsec(alt_err),
                az_correction_arcsec=rad_to_arcsec(az_err),
                residual_arcsec=rad_to_arcsec(fit.residual_rad),
                confidence=confidence,
            ),
            poses=tuple(poses),
            fit=fit,
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


def _validate_adjustment_site(
    *,
    site_latitude_rad: float,
    site_longitude_rad: float,
    site_elevation_m: float,
) -> None:
    values = (site_latitude_rad, site_longitude_rad, site_elevation_m)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("polar adjustment site values must be finite")
    if not -math.pi / 2.0 <= site_latitude_rad <= math.pi / 2.0:
        raise ValueError("site_latitude_rad must be in [-π/2, π/2]")
    if not -math.pi <= site_longitude_rad <= math.pi:
        raise ValueError("site_longitude_rad must be in [-π, π]")


def _fail(message: str) -> PolarResult:
    return PolarResult(
        alt_correction_arcsec=None,
        az_correction_arcsec=None,
        residual_arcsec=None,
        confidence=None,
        message=message,
    )
