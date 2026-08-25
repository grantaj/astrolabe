from astrolabe.cli.focus_feedback import FocusAudioCueMapper
from astrolabe.services.focus_monitor import FocusGuidance, FocusGuidanceState


def _guidance(state: FocusGuidanceState, *, valid: bool = True) -> FocusGuidance:
    return FocusGuidance(
        state=state,
        valid=valid,
        hfr_px=3.0 if valid else None,
        best_hfr_px=3.0 if valid else None,
    )


def test_unknown_focus_guidance_has_distinct_two_tone_cue() -> None:
    mapper = FocusAudioCueMapper()

    cue = mapper.map(_guidance(FocusGuidanceState.UNKNOWN))

    assert cue is not None
    assert cue.frequencies_hz == (440.0, 660.0)
    assert cue.interval_s == 1.2
    assert not cue.continuous


def test_improving_and_worsening_focus_use_distinct_temporal_quality_tones() -> None:
    mapper = FocusAudioCueMapper()

    improving = mapper.map(_guidance(FocusGuidanceState.IMPROVING))
    worsening = mapper.map(_guidance(FocusGuidanceState.WORSENING))

    assert improving is not None
    assert worsening is not None
    assert improving.frequencies_hz == (880.0,)
    assert worsening.frequencies_hz == (440.0,)
    assert improving.interval_s == worsening.interval_s == 0.30
    assert not improving.continuous
    assert not worsening.continuous


def test_best_observed_focus_uses_continuous_middle_tone() -> None:
    mapper = FocusAudioCueMapper()

    cue = mapper.map(_guidance(FocusGuidanceState.BEST_OBSERVED))

    assert cue is not None
    assert cue.frequencies_hz == (660.0,)
    assert cue.interval_s is None
    assert cue.continuous


def test_invalid_focus_guidance_is_silence() -> None:
    mapper = FocusAudioCueMapper()

    assert mapper.map(_guidance(FocusGuidanceState.UNKNOWN, valid=False)) is None
