import math

import pytest

from astrolabe.services.feedback import (
    FeedbackConfig,
    FeedbackDirection,
    FeedbackSession,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_large_signed_guidance_reports_direction() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))

    assert session.update(8.0).direction is FeedbackDirection.POSITIVE
    assert session.update(-8.0).direction is FeedbackDirection.NEGATIVE


def test_zero_guidance_is_centered() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))

    state = session.update(0.0)

    assert state.direction is FeedbackDirection.CENTERED
    assert state.proximity == 1.0


def test_proximity_increases_monotonically_as_guidance_decreases() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))

    states = [session.update(value) for value in (10.0, 7.0, 4.0, 1.0)]
    proximities = [state.proximity for state in states]
    assert all(value is not None for value in proximities)
    assert proximities == sorted(proximities)


def test_proximity_is_continuous_at_tolerance_boundary() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=1.0, useful_range=10.0))

    inside = session.update(1.0)
    outside = session.update(1.000001)

    assert inside.proximity == pytest.approx(1.0)
    assert outside.proximity == pytest.approx(1.0, abs=1e-6)


def test_unknown_guidance_does_not_invent_direction_or_proximity() -> None:
    session = FeedbackSession()

    state = session.update(None)

    assert state.valid
    assert state.direction is FeedbackDirection.UNKNOWN
    assert state.proximity is None
    assert state.guidance is None


def test_unknown_can_transition_to_known_direction() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))

    session.update(None)
    state = session.update(-3.0)

    assert state.direction is FeedbackDirection.NEGATIVE


def test_unknown_resets_smoothing_history() -> None:
    session = FeedbackSession(
        FeedbackConfig(tolerance=0.1, useful_range=10.0, smoothing_alpha=0.5)
    )
    session.update(4.0)
    session.update(None)

    state = session.update(-2.0)

    assert state.guidance == pytest.approx(-2.0)


def test_center_hysteresis_prevents_target_chatter() -> None:
    config = FeedbackConfig(
        tolerance=1.0,
        useful_range=10.0,
        center_hysteresis_fraction=0.5,
    )
    session = FeedbackSession(config)

    assert session.update(0.5).direction is FeedbackDirection.CENTERED
    held = session.update(1.3)
    assert held.direction is FeedbackDirection.CENTERED
    assert held.proximity == pytest.approx(1.0)
    assert session.update(1.6).direction is FeedbackDirection.POSITIVE


def test_direction_hysteresis_delays_sign_flip() -> None:
    config = FeedbackConfig(
        tolerance=0.1,
        useful_range=10.0,
        direction_hysteresis=0.5,
    )
    session = FeedbackSession(config)

    assert session.update(2.0).direction is FeedbackDirection.POSITIVE
    assert session.update(-0.3).direction is FeedbackDirection.POSITIVE
    assert session.update(-0.6).direction is FeedbackDirection.NEGATIVE


def test_crossing_zero_enters_center_before_reversing() -> None:
    session = FeedbackSession(FeedbackConfig(tolerance=0.1, useful_range=10.0))

    assert session.update(1.0).direction is FeedbackDirection.POSITIVE
    assert session.update(-0.05).direction is FeedbackDirection.CENTERED
    assert session.update(-1.0).direction is FeedbackDirection.NEGATIVE


def test_smoothing_filters_noisy_updates() -> None:
    config = FeedbackConfig(
        tolerance=0.1,
        useful_range=10.0,
        smoothing_alpha=0.5,
    )
    session = FeedbackSession(config)

    session.update(4.0)
    state = session.update(2.0)

    assert state.guidance == pytest.approx(3.0)


def test_invalid_measurements_are_not_actionable() -> None:
    session = FeedbackSession()

    for value in (math.nan, math.inf):
        state = session.update(value)
        assert not state.valid
        assert state.direction is FeedbackDirection.UNKNOWN
        assert state.proximity is None

    state = session.update(0.5, valid=False)
    assert not state.valid
    assert state.direction is FeedbackDirection.UNKNOWN


def test_stale_measurement_becomes_non_actionable() -> None:
    clock = FakeClock()
    session = FeedbackSession(
        FeedbackConfig(tolerance=0.1, useful_range=10.0, stale_after_s=2.0),
        clock=clock,
    )
    session.update(3.0)

    clock.now = 2.1
    state = session.state()

    assert not state.valid
    assert state.stale
    assert state.direction is FeedbackDirection.UNKNOWN
    assert state.proximity is None
    assert state.age_s == pytest.approx(2.1)


def test_unknown_state_can_also_become_stale() -> None:
    clock = FakeClock()
    session = FeedbackSession(FeedbackConfig(stale_after_s=1.0), clock=clock)
    session.update(None)

    clock.now = 1.1
    state = session.state()

    assert state.stale
    assert not state.valid


def test_reset_returns_to_invalid_unknown_state() -> None:
    session = FeedbackSession()
    session.update(0.0)

    session.reset()

    state = session.state()
    assert not state.valid
    assert state.direction is FeedbackDirection.UNKNOWN


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tolerance": 0.0}, "tolerance"),
        ({"tolerance": math.nan}, "tolerance"),
        ({"tolerance": 1.0, "useful_range": 1.0}, "useful_range"),
        ({"smoothing_alpha": 0.0}, "smoothing_alpha"),
        ({"center_hysteresis_fraction": -0.1}, "center_hysteresis_fraction"),
        ({"direction_hysteresis": -0.1}, "direction_hysteresis"),
        ({"stale_after_s": 0.0}, "stale_after_s"),
    ],
)
def test_config_rejects_invalid_values(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        FeedbackConfig(**kwargs)
