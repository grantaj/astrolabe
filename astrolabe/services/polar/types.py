import datetime
import math
from dataclasses import dataclass, field
from enum import Enum

from astrolabe.services.feedback import FeedbackConfig, FeedbackState


@dataclass
class PolarResult:
    alt_correction_arcsec: float | None
    az_correction_arcsec: float | None
    residual_arcsec: float | None
    confidence: float | None
    message: str | None = None


class PolarAxis(str, Enum):
    """Mechanical polar-alignment axis currently being adjusted."""

    AZ = "az"
    ALT = "alt"


class PolarWorkflowState(str, Enum):
    """Explicit states in the interactive polar-adjustment workflow."""

    MEASURE_INITIAL_AXIS = "measure_initial_axis"
    PREPARE_ADJUSTMENT = "prepare_adjustment"
    ADJUST_AZ = "adjust_az"
    AZ_ON_TARGET = "az_on_target"
    REBASE_FOR_ALT = "rebase_for_alt"
    ADJUST_ALT = "adjust_alt"
    ALT_ON_TARGET = "alt_on_target"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _default_feedback_config() -> FeedbackConfig:
    return FeedbackConfig(
        tolerance=math.radians(30.0 / 3600.0),
        useful_range=math.radians(2.0),
        smoothing_alpha=0.5,
        center_hysteresis_fraction=0.25,
        direction_hysteresis=math.radians(5.0 / 3600.0),
        stale_after_s=30.0,
    )


@dataclass(frozen=True)
class PolarAdjustConfig:
    """Controls for bounded, one-axis-at-a-time live polar adjustment.

    All angular values are radians.  The generic feedback configuration owns
    tolerance, smoothing, hysteresis, proximity and staleness semantics; the
    remaining fields are polar-workflow trust and resource bounds.
    """

    feedback: FeedbackConfig = field(default_factory=_default_feedback_config)
    search_radius_rad: float = math.radians(2.0)
    cross_track_limit_rad: float = math.radians(2.0 / 60.0)
    max_step_rad: float = math.radians(5.0)
    max_solve_rms_arcsec: float = 10.0
    stable_samples: int = 3
    max_consecutive_failures: int = 3
    max_samples_per_axis: int = 120

    def __post_init__(self) -> None:
        angular = {
            "search_radius_rad": self.search_radius_rad,
            "cross_track_limit_rad": self.cross_track_limit_rad,
            "max_step_rad": self.max_step_rad,
        }
        for name, value in angular.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and > 0")
        if (
            not math.isfinite(self.max_solve_rms_arcsec)
            or self.max_solve_rms_arcsec <= 0.0
        ):
            raise ValueError("max_solve_rms_arcsec must be finite and > 0")
        if self.stable_samples < 2:
            raise ValueError("stable_samples must be >= 2")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")
        if self.max_samples_per_axis < self.stable_samples:
            raise ValueError("max_samples_per_axis must be >= stable_samples")


@dataclass(frozen=True)
class PolarAdjustmentUpdate:
    """One semantic update from the live polar-adjustment workflow."""

    state: PolarWorkflowState
    axis: PolarAxis | None = None
    feedback: FeedbackState | None = None
    remaining_correction_rad: float | None = None
    applied_correction_rad: float | None = None
    cross_track_rad: float | None = None
    message: str | None = None


@dataclass(frozen=True)
class PolarAdjustResult:
    """Terminal result of a bounded interactive polar-adjustment run."""

    success: bool
    state: PolarWorkflowState
    initial: PolarResult
    az_remaining_arcsec: float | None = None
    alt_remaining_arcsec: float | None = None
    az_samples: int = 0
    alt_samples: int = 0
    message: str | None = None


@dataclass
class _PoseObservation:
    """Result of a single capture→solve at one RA position."""

    ra_rad: float
    dec_rad: float
    rms_arcsec: float | None
    timestamp_utc: datetime.datetime


@dataclass
class _CircleFitResult:
    """Result of fitting a small circle to three or more pose observations."""

    pole_ra_rad: float
    pole_dec_rad: float
    radius_rad: float
    residual_rad: float


@dataclass(frozen=True)
class _PolarMeasurement:
    """Compatibility-preserving detailed result retained for live adjustment."""

    result: PolarResult
    poses: tuple[_PoseObservation, ...]
    fit: _CircleFitResult | None
