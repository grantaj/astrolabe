"""Bounded interactive workflow for manual polar-axis adjustment."""

from __future__ import annotations

import math
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


class _PolarAdjustmentWorkflow:
    """Polar-owned state machine; presentation remains at the CLI boundary."""

    def __init__(
        self, mount, camera, solver, measure: Callable[..., _PolarMeasurement]
    ):
        self._mount = mount
        self._camera = camera
        self._solver = solver
        self._measure = measure

    def run(
        self,
        *,
        ra_rotation_rad: float,
        site_latitude_rad: float,
        site_longitude_rad: float,
        site_elevation_m: float,
        exposure_s: float,
        settle_time_s: float,
        num_poses: int,
        config: PolarAdjustConfig,
        on_update: Callable[[PolarAdjustmentUpdate], None] | None,
    ) -> PolarAdjustResult:
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
            return self._failed_adjust_result(
                initial,
                az_stage=None,
                alt_stage=None,
                message=initial.message or "initial polar-axis measurement failed",
                on_update=on_update,
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
            return self._failed_adjust_result(
                initial,
                az_stage=None,
                alt_stage=None,
                message=f"initial adjustment geometry failed: {exc}",
                on_update=on_update,
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

        tracking_may_have_changed = False
        az_stage: _AxisStageResult | None = None
        alt_stage: _AxisStageResult | None = None
        try:
            # Set the restore guard before issuing the state change.  A backend
            # error after partially applying the request must still trigger a
            # best-effort restoration in ``finally``.
            tracking_may_have_changed = True
            self._mount.set_tracking(False)

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
                    on_update=on_update,
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
                    on_update=on_update,
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
                    on_update=on_update,
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
                    on_update=on_update,
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
            self._notify(
                on_update,
                PolarAdjustmentUpdate(
                    state=PolarWorkflowState.CANCELLED,
                    message="polar adjustment cancelled",
                ),
            )
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
            if tracking_may_have_changed:
                self._mount.set_tracking(original_tracking)

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
                max_solve_rms_arcsec=config.max_solve_rms_arcsec,
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
            if (
                previous_timestamp is not None
                and observation.timestamp_utc <= previous_timestamp
            ):
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
        max_solve_rms_arcsec: float,
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
        if (
            not _trustworthy_live_solve(result, max_solve_rms_arcsec)
            and hint is not None
        ):
            # Bounded fallback: retry the same frame once without a positional
            # hint.  Retaining a valid scale hint narrows the blind fallback
            # without allowing a stale position to trap the workflow.
            fallback = SolveRequest(
                image=image,
                scale_hint_arcsec=hint.scale_arcsec,
            )
            result = self._solver.solve(fallback)

        if not _trustworthy_live_solve(result, max_solve_rms_arcsec):
            if (
                result.success
                and result.rms_arcsec is not None
                and math.isfinite(result.rms_arcsec)
                and result.rms_arcsec > max_solve_rms_arcsec
            ):
                return None, "plate solve RMS exceeds the live-guidance trust limit"
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

    @staticmethod
    def _notify(
        callback: Callable[[PolarAdjustmentUpdate], None] | None,
        update: PolarAdjustmentUpdate,
    ) -> None:
        if callback is not None:
            callback(update)

    def _failed_adjust_result(
        self,
        initial: PolarResult,
        *,
        az_stage: _AxisStageResult | None,
        alt_stage: _AxisStageResult | None,
        message: str,
        on_update: Callable[[PolarAdjustmentUpdate], None] | None,
    ) -> PolarAdjustResult:
        self._notify(
            on_update,
            PolarAdjustmentUpdate(state=PolarWorkflowState.FAILED, message=message),
        )
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


def _trustworthy_live_solve(result: SolveResult, max_rms_arcsec: float) -> bool:
    if not result.success or result.ra_rad is None or result.dec_rad is None:
        return False
    if not math.isfinite(result.ra_rad) or not math.isfinite(result.dec_rad):
        return False
    if not 0.0 <= result.ra_rad < math.tau:
        return False
    if not -math.pi / 2.0 <= result.dec_rad <= math.pi / 2.0:
        return False
    if result.rms_arcsec is not None:
        if not math.isfinite(result.rms_arcsec) or result.rms_arcsec < 0.0:
            return False
        if result.rms_arcsec > max_rms_arcsec:
            return False
    return True


def _signed_angle_difference(target_rad: float, actual_rad: float) -> float:
    difference = target_rad - actual_rad
    return math.atan2(math.sin(difference), math.cos(difference))


def _arcsec_or_none(value_rad: float | None) -> float | None:
    return None if value_rad is None else rad_to_arcsec(value_rad)
