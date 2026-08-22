from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from astrolabe.errors import ServiceError
from astrolabe.services.feedback import FeedbackDirection, FeedbackSession
from astrolabe.solver.types import SolveRequest, SolveResult
from astrolabe.util.math import rad_to_arcsec

from .adjustment import (
    AZ_ADJUSTMENT_AXIS,
    altitude_adjustment_axis,
    ideal_pole_horizon_vector,
    infer_rotation_about_axis,
    radec_to_horizon_vector,
    rotate_about_axis,
)
from .math import MIN_POSES, correction_confidence, fit_polar_axis
from .types import (
    PolarAdjustConfig,
    PolarAdjustmentUpdate,
    PolarAdjustResult,
    PolarAxis,
    PolarResult,
    PolarWorkflowState,
    _PolarMeasurement,
    _PoseObservation,
)


@dataclass(frozen=True)
class _SolveHint:
    ra_rad: float
    dec_rad: float
    scale_arcsec: float | None


@dataclass(frozen=True)
class _LiveSolve:
    observation: _PoseObservation
    scale_arcsec: float | None

    @property
    def hint(self) -> _SolveHint:
        return _SolveHint(
            ra_rad=self.observation.ra_rad,
            dec_rad=self.observation.dec_rad,
            scale_arcsec=self.scale_arcsec,
        )


@dataclass(frozen=True)
class _AxisStageResult:
    success: bool
    remaining_rad: float | None
    applied_rad: float
    samples: int
    last_hint: _SolveHint | None
    message: str | None = None


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
        """Measure once, then guide AZ and ALT manual adjustments in sequence.

        The mount tracks during the initial N-pose measurement.  Tracking is
        then disabled while the user physically adjusts the mount base, so a
        solved field is fixed in the local horizon frame apart from mechanical
        motion.  Every solve is transformed using its own UTC timestamp before
        one-axis motion is inferred.
        """
        config = config or PolarAdjustConfig()
        self._notify(
            on_update,
            PolarAdjustmentUpdate(state=PolarWorkflowState.MEASURE_INITIAL_AXIS),
        )
        measurement = self._measure(
            ra_rotation_rad=ra_rotation_rad,
            site_latitude_rad=site_latitude_rad,
            exposure_s=exposure_s,
            settle_time_s=settle_time_s,
            num_poses=num_poses,
        )
        initial = measurement.result
        if measurement.fit is None or not measurement.poses:
            return PolarAdjustResult(
                success=False,
                state=PolarWorkflowState.FAILED,
                initial=initial,
                message=initial.message or "initial polar-axis measurement failed",
            )

        reference_time = measurement.poses[-1].timestamp_utc
        try:
            polar_axis = radec_to_horizon_vector(
                measurement.fit.pole_ra_rad,
                measurement.fit.pole_dec_rad,
                reference_time,
                latitude_rad=site_latitude_rad,
                longitude_rad=site_longitude_rad,
                elevation_m=site_elevation_m,
            )
            target_pole = ideal_pole_horizon_vector(site_latitude_rad)
            az_target_rad, _ = infer_rotation_about_axis(
                polar_axis,
                target_pole,
                AZ_ADJUSTMENT_AXIS,
            )
        except ValueError as exc:
            return PolarAdjustResult(
                success=False,
                state=PolarWorkflowState.FAILED,
                initial=initial,
                message=f"initial adjustment geometry failed: {exc}",
            )

        state = self._mount.get_state()
        original_tracking = state.tracking
        if not original_tracking:
            raise ServiceError("Mount must be tracking before polar adjustment")

        self._notify(
            on_update,
            PolarAdjustmentUpdate(
                state=PolarWorkflowState.PREPARE_ADJUSTMENT,
                message="disabling tracking for manual base adjustment",
            ),
        )

        tracking_changed = False
        az_stage: _AxisStageResult | None = None
        alt_stage: _AxisStageResult | None = None
        try:
            self._mount.set_tracking(False)
            tracking_changed = True

            feedback = FeedbackSession(config.feedback)
            az_stage = self._run_axis_stage(
                state=PolarWorkflowState.ADJUST_AZ,
                axis=PolarAxis.AZ,
                rotation_axis=AZ_ADJUSTMENT_AXIS,
                target_correction_rad=az_target_rad,
                exposure_s=exposure_s,
                site_latitude_rad=site_latitude_rad,
                site_longitude_rad=site_longitude_rad,
                site_elevation_m=site_elevation_m,
                config=config,
                feedback=feedback,
                on_update=on_update,
                initial_hint=None,
            )
            if not az_stage.success:
                return self._failed_adjust_result(
                    initial,
                    az_stage=az_stage,
                    alt_stage=None,
                    message=az_stage.message or "azimuth adjustment failed",
                )

            self._notify(
                on_update,
                PolarAdjustmentUpdate(
                    state=PolarWorkflowState.AZ_ON_TARGET,
                    axis=PolarAxis.AZ,
                    remaining_correction_rad=az_stage.remaining_rad,
                ),
            )

            polar_axis = rotate_about_axis(
                polar_axis,
                AZ_ADJUSTMENT_AXIS,
                az_stage.applied_rad,
            )
            self._notify(
                on_update,
                PolarAdjustmentUpdate(
                    state=PolarWorkflowState.REBASE_FOR_ALT,
                    message="azimuth accepted; establishing a fresh altitude reference",
                ),
            )
            feedback.reset()

            try:
                alt_rotation_axis = altitude_adjustment_axis(polar_axis)
                alt_target_rad, target_cross_track = infer_rotation_about_axis(
                    polar_axis,
                    target_pole,
                    alt_rotation_axis,
                )
            except ValueError as exc:
                return self._failed_adjust_result(
                    initial,
                    az_stage=az_stage,
                    alt_stage=None,
                    message=f"altitude rebase geometry failed: {exc}",
                )

            if target_cross_track > config.cross_track_limit_rad:
                return self._failed_adjust_result(
                    initial,
                    az_stage=az_stage,
                    alt_stage=None,
                    message=(
                        "azimuth adjustment left too much cross-track error for "
                        "a trustworthy altitude rebase"
                    ),
                )

            alt_stage = self._run_axis_stage(
                state=PolarWorkflowState.ADJUST_ALT,
                axis=PolarAxis.ALT,
                rotation_axis=alt_rotation_axis,
                target_correction_rad=alt_target_rad,
                exposure_s=exposure_s,
                site_latitude_rad=site_latitude_rad,
                site_longitude_rad=site_longitude_rad,
                site_elevation_m=site_elevation_m,
                config=config,
                feedback=feedback,
                on_update=on_update,
                initial_hint=az_stage.last_hint,
            )
            if not alt_stage.success:
                return self._failed_adjust_result(
                    initial,
                    az_stage=az_stage,
                    alt_stage=alt_stage,
                    message=alt_stage.message or "altitude adjustment failed",
                )

            self._notify(
                on_update,
                PolarAdjustmentUpdate(
                    state=PolarWorkflowState.ALT_ON_TARGET,
                    axis=PolarAxis.ALT,
                    remaining_correction_rad=alt_stage.remaining_rad,
                ),
            )
            self._notify(
                on_update,
                PolarAdjustmentUpdate(state=PolarWorkflowState.COMPLETE),
            )
            return PolarAdjustResult(
                success=True,
                state=PolarWorkflowState.COMPLETE,
                initial=initial,
                az_remaining_arcsec=_arcsec_or_none(az_stage.remaining_rad),
                alt_remaining_arcsec=_arcsec_or_none(alt_stage.remaining_rad),
                az_samples=az_stage.samples,
                alt_samples=alt_stage.samples,
            )
        except KeyboardInterrupt:
            return PolarAdjustResult(
                success=False,
                state=PolarWorkflowState.CANCELLED,
                initial=initial,
                az_remaining_arcsec=_arcsec_or_none(
                    az_stage.remaining_rad if az_stage is not None else None
                ),
                alt_remaining_arcsec=_arcsec_or_none(
                    alt_stage.remaining_rad if alt_stage is not None else None
                ),
                az_samples=az_stage.samples if az_stage is not None else 0,
                alt_samples=alt_stage.samples if alt_stage is not None else 0,
                message="polar adjustment cancelled",
            )
        finally:
            if tracking_changed:
                self._mount.set_tracking(original_tracking)

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
                result = _fail(f"Plate solve failed at pose {i + 1}")
                return _PolarMeasurement(
                    result=result,
                    poses=tuple(poses),
                    fit=None,
                    alt_correction_rad=None,
                    az_correction_rad=None,
                )
            poses.append(pose)

        try:
            alt_err, az_err, fit = fit_polar_axis(poses, site_latitude_rad)
        except ValueError as exc:
            result = _fail(f"Circle fit failed: {exc}")
            return _PolarMeasurement(
                result=result,
                poses=tuple(poses),
                fit=None,
                alt_correction_rad=None,
                az_correction_rad=None,
            )

        confidence = correction_confidence(fit, poses)
        result = PolarResult(
            alt_correction_arcsec=rad_to_arcsec(alt_err),
            az_correction_arcsec=rad_to_arcsec(az_err),
            residual_arcsec=rad_to_arcsec(fit.residual_rad),
            confidence=confidence,
        )
        return _PolarMeasurement(
            result=result,
            poses=tuple(poses),
            fit=fit,
            alt_correction_rad=alt_err,
            az_correction_rad=az_err,
        )

    def _run_axis_stage(
        self,
        *,
        state: PolarWorkflowState,
        axis: PolarAxis,
        rotation_axis: tuple[float, float, float],
        target_correction_rad: float,
        exposure_s: float,
        site_latitude_rad: float,
        site_longitude_rad: float,
        site_elevation_m: float,
        config: PolarAdjustConfig,
        feedback: FeedbackSession,
        on_update: Callable[[PolarAdjustmentUpdate], None] | None,
        initial_hint: _SolveHint | None,
    ) -> _AxisStageResult:
        reference: tuple[float, float, float] | None = None
        hint = initial_hint
        previous_timestamp = None
        previous_applied_rad = 0.0
        last_applied_rad = 0.0
        last_remaining_rad: float | None = None
        stable_count = 0
        consecutive_failures = 0
        valid_samples = 0

        for _attempt in range(config.max_samples_per_axis):
            live, failure_message = self._capture_live_solve(
                exposure_s=exposure_s,
                hint=hint,
                search_radius_rad=config.search_radius_rad,
            )
            if live is None:
                consecutive_failures += 1
                invalid = feedback.update(None, valid=False)
                self._notify(
                    on_update,
                    PolarAdjustmentUpdate(
                        state=state,
                        axis=axis,
                        feedback=invalid,
                        message=failure_message or "plate solve failed",
                    ),
                )
                if consecutive_failures >= config.max_consecutive_failures:
                    return _AxisStageResult(
                        success=False,
                        remaining_rad=last_remaining_rad,
                        applied_rad=last_applied_rad,
                        samples=valid_samples,
                        last_hint=hint,
                        message=(
                            f"{axis.value} adjustment stopped after repeated plate-solve "
                            "failures"
                        ),
                    )
                continue

            observation = live.observation
            hint = live.hint
            if previous_timestamp is not None and observation.timestamp_utc <= previous_timestamp:
                consecutive_failures += 1
                invalid = feedback.update(None, valid=False)
                self._notify(
                    on_update,
                    PolarAdjustmentUpdate(
                        state=state,
                        axis=axis,
                        feedback=invalid,
                        message="stale or non-monotonic solved frame timestamp",
                    ),
                )
                if consecutive_failures >= config.max_consecutive_failures:
                    return _AxisStageResult(
                        success=False,
                        remaining_rad=last_remaining_rad,
                        applied_rad=last_applied_rad,
                        samples=valid_samples,
                        last_hint=hint,
                        message=f"{axis.value} adjustment received repeated stale solves",
                    )
                continue
            previous_timestamp = observation.timestamp_utc

            try:
                current = radec_to_horizon_vector(
                    observation.ra_rad,
                    observation.dec_rad,
                    observation.timestamp_utc,
                    latitude_rad=site_latitude_rad,
                    longitude_rad=site_longitude_rad,
                    elevation_m=site_elevation_m,
                )
            except ValueError as exc:
                consecutive_failures += 1
                invalid = feedback.update(None, valid=False)
                self._notify(
                    on_update,
                    PolarAdjustmentUpdate(
                        state=state,
                        axis=axis,
                        feedback=invalid,
                        message=f"invalid solve geometry: {exc}",
                    ),
                )
                if consecutive_failures >= config.max_consecutive_failures:
                    return _AxisStageResult(
                        success=False,
                        remaining_rad=last_remaining_rad,
                        applied_rad=last_applied_rad,
                        samples=valid_samples,
                        last_hint=hint,
                        message=f"{axis.value} adjustment geometry remained invalid",
                    )
                continue

            if reference is None:
                reference = current
                applied_rad = 0.0
                cross_track_rad = 0.0
            else:
                try:
                    applied_rad, cross_track_rad = infer_rotation_about_axis(
                        reference,
                        current,
                        rotation_axis,
                    )
                except ValueError as exc:
                    consecutive_failures += 1
                    invalid = feedback.update(None, valid=False)
                    self._notify(
                        on_update,
                        PolarAdjustmentUpdate(
                            state=state,
                            axis=axis,
                            feedback=invalid,
                            message=f"one-axis geometry is ill-conditioned: {exc}",
                        ),
                    )
                    if consecutive_failures >= config.max_consecutive_failures:
                        return _AxisStageResult(
                            success=False,
                            remaining_rad=last_remaining_rad,
                            applied_rad=last_applied_rad,
                            samples=valid_samples,
                            last_hint=hint,
                            message=f"{axis.value} adjustment geometry is ill-conditioned",
                        )
                    continue

                step_rad = _signed_angle_difference(applied_rad, previous_applied_rad)
                if (
                    cross_track_rad > config.cross_track_limit_rad
                    or abs(step_rad) > config.max_step_rad
                ):
                    consecutive_failures += 1
                    invalid = feedback.update(None, valid=False)
                    reason = (
                        "wrong-axis/coupled motion exceeds the trust limit"
                        if cross_track_rad > config.cross_track_limit_rad
                        else "implausibly large adjustment jump"
                    )
                    self._notify(
                        on_update,
                        PolarAdjustmentUpdate(
                            state=state,
                            axis=axis,
                            feedback=invalid,
                            applied_correction_rad=applied_rad,
                            cross_track_rad=cross_track_rad,
                            message=reason,
                        ),
                    )
                    if consecutive_failures >= config.max_consecutive_failures:
                        return _AxisStageResult(
                            success=False,
                            remaining_rad=last_remaining_rad,
                            applied_rad=last_applied_rad,
                            samples=valid_samples,
                            last_hint=hint,
                            message=(
                                f"{axis.value} adjustment requires rebase/retry after "
                                "repeated inconsistent motion"
                            ),
                        )
                    continue

            consecutive_failures = 0
            previous_applied_rad = applied_rad
            last_applied_rad = applied_rad
            remaining_rad = _signed_angle_difference(target_correction_rad, applied_rad)
            last_remaining_rad = remaining_rad
            valid_samples += 1
            feedback_state = feedback.update(remaining_rad)
            if feedback_state.direction is FeedbackDirection.CENTERED:
                stable_count += 1
            else:
                stable_count = 0

            self._notify(
                on_update,
                PolarAdjustmentUpdate(
                    state=state,
                    axis=axis,
                    feedback=feedback_state,
                    remaining_correction_rad=remaining_rad,
                    applied_correction_rad=applied_rad,
                    cross_track_rad=cross_track_rad,
                ),
            )
            if stable_count >= config.stable_samples:
                return _AxisStageResult(
                    success=True,
                    remaining_rad=remaining_rad,
                    applied_rad=applied_rad,
                    samples=valid_samples,
                    last_hint=hint,
                )

        return _AxisStageResult(
            success=False,
            remaining_rad=last_remaining_rad,
            applied_rad=last_applied_rad,
            samples=valid_samples,
            last_hint=hint,
            message=f"{axis.value} adjustment exceeded the bounded sample budget",
        )

    def _capture_live_solve(
        self,
        *,
        exposure_s: float,
        hint: _SolveHint | None,
        search_radius_rad: float,
    ) -> tuple[_LiveSolve | None, str | None]:
        image = self._camera.capture(exposure_s)
        request = SolveRequest(
            image=image,
            ra_hint_rad=hint.ra_rad if hint is not None else None,
            dec_hint_rad=hint.dec_rad if hint is not None else None,
            scale_hint_arcsec=hint.scale_arcsec if hint is not None else None,
            search_radius_rad=search_radius_rad if hint is not None else None,
        )
        result = self._solver.solve(request)
        if not _trustworthy_live_solve(result) and hint is not None:
            # Bounded fallback: retry the same frame once without a positional
            # hint.  Retaining a valid scale hint narrows the blind fallback
            # without allowing a stale position to trap the workflow.
            fallback = SolveRequest(
                image=image,
                scale_hint_arcsec=hint.scale_arcsec,
            )
            result = self._solver.solve(fallback)

        if not _trustworthy_live_solve(result):
            return None, result.message or "plate solve failed"

        assert result.ra_rad is not None
        assert result.dec_rad is not None
        scale = result.pixel_scale_arcsec
        if scale is not None and (not math.isfinite(scale) or scale <= 0.0):
            scale = None
        return (
            _LiveSolve(
                observation=_PoseObservation(
                    ra_rad=result.ra_rad,
                    dec_rad=result.dec_rad,
                    rms_arcsec=result.rms_arcsec,
                    timestamp_utc=image.timestamp_utc,
                ),
                scale_arcsec=scale,
            ),
            None,
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

    @staticmethod
    def _notify(
        callback: Callable[[PolarAdjustmentUpdate], None] | None,
        update: PolarAdjustmentUpdate,
    ) -> None:
        if callback is not None:
            callback(update)

    @staticmethod
    def _failed_adjust_result(
        initial: PolarResult,
        *,
        az_stage: _AxisStageResult | None,
        alt_stage: _AxisStageResult | None,
        message: str,
    ) -> PolarAdjustResult:
        return PolarAdjustResult(
            success=False,
            state=PolarWorkflowState.FAILED,
            initial=initial,
            az_remaining_arcsec=_arcsec_or_none(
                az_stage.remaining_rad if az_stage is not None else None
            ),
            alt_remaining_arcsec=_arcsec_or_none(
                alt_stage.remaining_rad if alt_stage is not None else None
            ),
            az_samples=az_stage.samples if az_stage is not None else 0,
            alt_samples=alt_stage.samples if alt_stage is not None else 0,
            message=message,
        )


def _trustworthy_live_solve(result: SolveResult) -> bool:
    if not result.success or result.ra_rad is None or result.dec_rad is None:
        return False
    if not math.isfinite(result.ra_rad) or not math.isfinite(result.dec_rad):
        return False
    if not 0.0 <= result.ra_rad < math.tau:
        return False
    if not -math.pi / 2.0 <= result.dec_rad <= math.pi / 2.0:
        return False
    return True


def _signed_angle_difference(target_rad: float, actual_rad: float) -> float:
    difference = target_rad - actual_rad
    return math.atan2(math.sin(difference), math.cos(difference))


def _arcsec_or_none(value_rad: float | None) -> float | None:
    return None if value_rad is None else rad_to_arcsec(value_rad)


def _fail(message: str) -> PolarResult:
    return PolarResult(
        alt_correction_arcsec=None,
        az_correction_arcsec=None,
        residual_arcsec=None,
        confidence=None,
        message=message,
    )
