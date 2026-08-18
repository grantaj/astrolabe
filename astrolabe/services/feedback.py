"""Generic semantic feedback for scalar manual adjustments."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum


class FeedbackDirection(str, Enum):
    """Direction in which the user should move an adjustment."""

    NEGATIVE = "negative"
    POSITIVE = "positive"
    CENTERED = "centered"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FeedbackConfig:
    """Configuration for a scalar manual-adjustment feedback session."""

    tolerance: float = 0.05
    useful_range: float = 1.0
    smoothing_alpha: float = 1.0
    center_hysteresis_fraction: float = 0.25
    direction_hysteresis: float = 0.0
    stale_after_s: float = 2.0

    def __post_init__(self) -> None:
        numeric = {
            "tolerance": self.tolerance,
            "useful_range": self.useful_range,
            "smoothing_alpha": self.smoothing_alpha,
            "center_hysteresis_fraction": self.center_hysteresis_fraction,
            "direction_hysteresis": self.direction_hysteresis,
            "stale_after_s": self.stale_after_s,
        }
        for name, value in numeric.items():
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.tolerance <= 0.0:
            raise ValueError("tolerance must be > 0")
        if self.useful_range <= self.tolerance:
            raise ValueError("useful_range must be greater than tolerance")
        if not 0.0 < self.smoothing_alpha <= 1.0:
            raise ValueError("smoothing_alpha must be in (0, 1]")
        if self.center_hysteresis_fraction < 0.0:
            raise ValueError("center_hysteresis_fraction must be >= 0")
        if self.direction_hysteresis < 0.0:
            raise ValueError("direction_hysteresis must be >= 0")
        if self.stale_after_s <= 0.0:
            raise ValueError("stale_after_s must be > 0")


@dataclass(frozen=True)
class FeedbackState:
    """Domain-independent semantic feedback produced by a session."""

    direction: FeedbackDirection
    proximity: float | None
    valid: bool
    stale: bool = False
    guidance: float | None = None
    age_s: float | None = None


class FeedbackSession:
    """Convert signed manual-adjustment guidance into stable feedback state.

    A finite numeric guidance value is a signed correction: its sign says which
    way the user should move and zero is the target. ``None`` means the caller
    does not yet know an actionable direction or distance, for example while a
    focusing optimiser is probing. Measurement and direction discovery remain
    upstream responsibilities.
    """

    def __init__(
        self,
        config: FeedbackConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or FeedbackConfig()
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self._filtered_guidance: float | None = None
        self._last_update_s: float | None = None
        self._last_state = FeedbackState(
            direction=FeedbackDirection.UNKNOWN,
            proximity=None,
            valid=False,
        )

    def update(
        self,
        guidance: float | None,
        *,
        valid: bool = True,
    ) -> FeedbackState:
        """Consume one guidance update and return the current semantic state.

        ``guidance=None`` with ``valid=True`` is a valid but non-actionable
        unknown state. ``valid=False`` or a non-finite numeric value produces an
        invalid state and therefore no adjustment cue.
        """
        now_s = self._clock()

        if not valid or (guidance is not None and not math.isfinite(guidance)):
            self._filtered_guidance = None
            self._last_update_s = None
            self._last_state = FeedbackState(
                direction=FeedbackDirection.UNKNOWN,
                proximity=None,
                valid=False,
            )
            return self._last_state

        if (
            self._last_update_s is not None
            and now_s - self._last_update_s > self.config.stale_after_s
        ):
            self._filtered_guidance = None
            self._last_state = FeedbackState(
                direction=FeedbackDirection.UNKNOWN,
                proximity=None,
                valid=False,
            )

        self._last_update_s = now_s
        if guidance is None:
            self._filtered_guidance = None
            self._last_state = FeedbackState(
                direction=FeedbackDirection.UNKNOWN,
                proximity=None,
                valid=True,
                age_s=0.0,
            )
            return self._last_state

        filtered = self._smooth(guidance)
        direction = self._direction(filtered)
        proximity = (
            1.0
            if direction is FeedbackDirection.CENTERED
            else self._proximity(filtered)
        )
        self._last_state = FeedbackState(
            direction=direction,
            proximity=proximity,
            valid=True,
            guidance=filtered,
            age_s=0.0,
        )
        return self._last_state

    def state(self) -> FeedbackState:
        """Return current state, marking the latest valid update stale if needed."""
        if not self._last_state.valid or self._last_update_s is None:
            return self._last_state

        age_s = max(0.0, self._clock() - self._last_update_s)
        if age_s <= self.config.stale_after_s:
            return replace(self._last_state, age_s=age_s)
        return replace(
            self._last_state,
            direction=FeedbackDirection.UNKNOWN,
            proximity=None,
            valid=False,
            stale=True,
            guidance=None,
            age_s=age_s,
        )

    def _smooth(self, guidance: float) -> float:
        alpha = self.config.smoothing_alpha
        if self._filtered_guidance is None:
            filtered = guidance
        else:
            filtered = alpha * guidance + (1.0 - alpha) * self._filtered_guidance
        self._filtered_guidance = filtered
        return filtered

    def _direction(self, guidance: float) -> FeedbackDirection:
        previous = self._last_state.direction
        center_limit = self.config.tolerance
        if previous is FeedbackDirection.CENTERED:
            center_limit *= 1.0 + self.config.center_hysteresis_fraction

        if abs(guidance) <= center_limit:
            return FeedbackDirection.CENTERED

        hysteresis = self.config.direction_hysteresis
        if previous is FeedbackDirection.POSITIVE and -hysteresis < guidance < 0.0:
            return FeedbackDirection.POSITIVE
        if previous is FeedbackDirection.NEGATIVE and 0.0 < guidance < hysteresis:
            return FeedbackDirection.NEGATIVE

        if guidance > 0.0:
            return FeedbackDirection.POSITIVE
        return FeedbackDirection.NEGATIVE

    def _proximity(self, guidance: float) -> float:
        magnitude = abs(guidance)
        if magnitude <= self.config.tolerance:
            return 1.0
        if magnitude >= self.config.useful_range:
            return 0.0
        span = self.config.useful_range - self.config.tolerance
        return 1.0 - (magnitude - self.config.tolerance) / span
