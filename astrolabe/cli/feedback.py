"""CLI-facing presentation helpers for manual-adjustment feedback."""

import math
from dataclasses import dataclass

from astrolabe.services.feedback import FeedbackDirection, FeedbackState


@dataclass(frozen=True)
class AudioCueConfig:
    """Tone vocabulary and cadence for no-look feedback cues."""

    negative_hz: float = 440.0
    positive_hz: float = 880.0
    centered_hz: float = 660.0
    unknown_hz: tuple[float, float] = (440.0, 660.0)
    far_interval_s: float = 1.0
    near_interval_s: float = 0.12
    unknown_interval_s: float = 1.2
    pulse_duration_s: float = 0.08

    def __post_init__(self) -> None:
        positive_values = (
            self.negative_hz,
            self.positive_hz,
            self.centered_hz,
            *self.unknown_hz,
            self.far_interval_s,
            self.near_interval_s,
            self.unknown_interval_s,
            self.pulse_duration_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive_values):
            raise ValueError("audio cue values must be finite and > 0")
        if self.far_interval_s <= self.near_interval_s:
            raise ValueError("far_interval_s must be greater than near_interval_s")


@dataclass(frozen=True)
class AudioCue:
    """Backend-independent cue for an audio sink or scheduler."""

    frequencies_hz: tuple[float, ...]
    pulse_duration_s: float
    interval_s: float | None
    continuous: bool = False


def _validate_feedback_state(state: FeedbackState) -> None:
    """Validate proximity invariants shared by terminal and audio presentation."""
    if not state.valid:
        return

    if state.direction is FeedbackDirection.UNKNOWN:
        if state.proximity is not None:
            raise ValueError("unknown feedback state must not have proximity")
        return

    if state.proximity is None:
        raise ValueError(f"{state.direction.value} feedback state requires proximity")
    if not math.isfinite(state.proximity) or not 0.0 <= state.proximity <= 1.0:
        raise ValueError("feedback proximity must be finite and in [0, 1]")
    if state.direction is FeedbackDirection.CENTERED and state.proximity != 1.0:
        raise ValueError("centered feedback state requires proximity 1.0")


class AudioCueMapper:
    """Map semantic feedback state to parking-sensor-style audio cues."""

    def __init__(self, config: AudioCueConfig | None = None) -> None:
        self.config = config or AudioCueConfig()

    def map(self, state: FeedbackState) -> AudioCue | None:
        if not state.valid:
            return None

        _validate_feedback_state(state)

        if state.direction is FeedbackDirection.CENTERED:
            return AudioCue(
                frequencies_hz=(self.config.centered_hz,),
                pulse_duration_s=self.config.pulse_duration_s,
                interval_s=None,
                continuous=True,
            )

        if state.direction is FeedbackDirection.UNKNOWN:
            return AudioCue(
                frequencies_hz=self.config.unknown_hz,
                pulse_duration_s=self.config.pulse_duration_s,
                interval_s=self.config.unknown_interval_s,
            )

        assert state.proximity is not None
        frequency = (
            self.config.positive_hz
            if state.direction is FeedbackDirection.POSITIVE
            else self.config.negative_hz
        )
        interval = self.config.far_interval_s - state.proximity * (
            self.config.far_interval_s - self.config.near_interval_s
        )
        return AudioCue(
            frequencies_hz=(frequency,),
            pulse_duration_s=self.config.pulse_duration_s,
            interval_s=interval,
        )


def format_feedback(state: FeedbackState) -> str:
    """Format semantic feedback for terminal display."""
    if state.stale:
        return "! stale"
    if not state.valid:
        return "! invalid"

    _validate_feedback_state(state)

    marker = {
        FeedbackDirection.NEGATIVE: "-",
        FeedbackDirection.POSITIVE: "+",
        FeedbackDirection.CENTERED: "=",
        FeedbackDirection.UNKNOWN: "?",
    }[state.direction]
    if state.proximity is None:
        return f"{marker} {state.direction.value}"
    return f"{marker} {state.direction.value} {state.proximity:.0%}"
