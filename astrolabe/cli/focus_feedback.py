"""Presentation mapping for truthful no-look focus guidance."""

import math
from dataclasses import dataclass

from astrolabe.cli.feedback import AudioCue, AudioCueConfig
from astrolabe.services.focus_monitor import FocusGuidance, FocusGuidanceState


@dataclass(frozen=True)
class FocusAudioCueConfig:
    """Audio presentation for temporal focus-quality guidance."""

    trend_interval_s: float = 0.30

    def __post_init__(self) -> None:
        if not math.isfinite(self.trend_interval_s) or self.trend_interval_s <= 0.0:
            raise ValueError("trend_interval_s must be finite and > 0")


class FocusAudioCueMapper:
    """Map focus-quality trend states to distinct no-look cues.

    High and low pulsed tones mean improving and worsening image quality in the
    user's current motion; they do not encode a physical focuser direction.
    The continuous middle tone means only that the focus estimator has bracketed
    a local best by improvement followed by worsening and has returned stably
    near that best-observed HFR.
    """

    def __init__(
        self,
        cue_config: AudioCueConfig | None = None,
        focus_config: FocusAudioCueConfig | None = None,
    ) -> None:
        self.cues = cue_config or AudioCueConfig()
        self.config = focus_config or FocusAudioCueConfig()

    def map(self, guidance: FocusGuidance) -> AudioCue | None:
        if not guidance.valid:
            return None

        if guidance.state is FocusGuidanceState.UNKNOWN:
            return AudioCue(
                frequencies_hz=self.cues.unknown_hz,
                pulse_duration_s=self.cues.pulse_duration_s,
                interval_s=self.cues.unknown_interval_s,
            )

        if guidance.state is FocusGuidanceState.BEST_OBSERVED:
            return AudioCue(
                frequencies_hz=(self.cues.centered_hz,),
                pulse_duration_s=self.cues.pulse_duration_s,
                interval_s=None,
                continuous=True,
            )

        frequency_hz = (
            self.cues.positive_hz
            if guidance.state is FocusGuidanceState.IMPROVING
            else self.cues.negative_hz
        )
        return AudioCue(
            frequencies_hz=(frequency_hz,),
            pulse_duration_s=self.cues.pulse_duration_s,
            interval_s=self.config.trend_interval_s,
        )
