import math

import pytest

from astrolabe.cli.feedback import (
    AudioCueConfig,
    AudioCueMapper,
    format_feedback,
)
from astrolabe.services.feedback import (
    FeedbackConfig,
    FeedbackDirection,
    FeedbackSession,
    FeedbackState,
)


def test_audio_uses_distinct_pitch_for_signed_directions() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))
    mapper = AudioCueMapper()

    positive = mapper.map(session.update(4.0))
    negative = mapper.map(session.update(-4.0))

    assert positive is not None
    assert negative is not None
    assert positive.frequencies_hz != negative.frequencies_hz


def test_audio_cadence_accelerates_as_target_approaches() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))
    mapper = AudioCueMapper()

    far = mapper.map(session.update(9.0))
    near = mapper.map(session.update(1.0))

    assert far is not None and far.interval_s is not None
    assert near is not None and near.interval_s is not None
    assert near.interval_s < far.interval_s


def test_audio_unknown_direction_uses_neutral_two_tone_cue() -> None:
    session = FeedbackSession()
    mapper = AudioCueMapper()

    cue = mapper.map(session.update(None))

    assert cue is not None
    assert len(cue.frequencies_hz) == 2
    assert not cue.continuous


def test_audio_centered_state_is_distinct_and_continuous() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))
    mapper = AudioCueMapper()

    cue = mapper.map(session.update(0.05))

    assert cue is not None
    assert cue.continuous
    assert cue.interval_s is None


def test_audio_silences_invalid_and_stale_states() -> None:
    class Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    session = FeedbackSession(FeedbackConfig(stale_after_s=1.0), clock=clock)
    mapper = AudioCueMapper()

    assert mapper.map(session.update(0.5, valid=False)) is None

    session.update(0.5)
    clock.now = 1.1
    assert mapper.map(session.state()) is None


def test_terminal_format_distinguishes_all_semantic_states() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))

    assert format_feedback(session.update(4.0)).startswith("+ positive")
    assert format_feedback(session.update(-4.0)).startswith("- negative")
    assert format_feedback(session.update(0.0)).startswith("= centered")
    assert format_feedback(session.update(None)) == "? unknown"
    assert format_feedback(session.update(0.5, valid=False)) == "! invalid"


def test_audio_config_rejects_nonfinite_or_nonpositive_values() -> None:
    with pytest.raises(ValueError, match="finite and > 0"):
        AudioCueConfig(positive_hz=math.nan)
    with pytest.raises(ValueError, match="finite and > 0"):
        AudioCueConfig(far_interval_s=math.inf)
    with pytest.raises(ValueError, match="finite and > 0"):
        AudioCueConfig(near_interval_s=0.0)
    with pytest.raises(ValueError, match="finite and > 0"):
        AudioCueConfig(pulse_duration_s=-1.0)


def test_audio_config_requires_far_interval_greater_than_near() -> None:
    with pytest.raises(ValueError, match="far_interval_s"):
        AudioCueConfig(far_interval_s=0.1, near_interval_s=0.2)


@pytest.mark.parametrize(
    "malformed",
    [
        FeedbackState(
            direction=FeedbackDirection.POSITIVE,
            proximity=None,
            valid=True,
            guidance=1.0,
        ),
        FeedbackState(
            direction=FeedbackDirection.CENTERED,
            proximity=None,
            valid=True,
            guidance=0.0,
        ),
        FeedbackState(
            direction=FeedbackDirection.UNKNOWN,
            proximity=0.5,
            valid=True,
        ),
        FeedbackState(
            direction=FeedbackDirection.NEGATIVE,
            proximity=math.nan,
            valid=True,
            guidance=-1.0,
        ),
        FeedbackState(
            direction=FeedbackDirection.POSITIVE,
            proximity=-0.1,
            valid=True,
            guidance=1.0,
        ),
        FeedbackState(
            direction=FeedbackDirection.POSITIVE,
            proximity=1.1,
            valid=True,
            guidance=1.0,
        ),
        FeedbackState(
            direction=FeedbackDirection.CENTERED,
            proximity=0.9,
            valid=True,
            guidance=0.0,
        ),
    ],
)
def test_presenters_reject_malformed_valid_state(malformed: FeedbackState) -> None:
    mapper = AudioCueMapper()

    with pytest.raises(ValueError):
        mapper.map(malformed)
    with pytest.raises(ValueError):
        format_feedback(malformed)
