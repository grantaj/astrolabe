import math

import numpy as np
import pytest

from astrolabe.services.focus import FocusAnalyzer, FocusConfig, FocusMeasurement


POSITIONS = ((28, 28), (28, 98), (92, 60), (88, 104), (64, 82))


def synthetic_starfield(
    *,
    sigma: float = 2.0,
    amplitudes=(5000.0, 4000.0, 6000.0, 3500.0, 4500.0),
    background: float = 1000.0,
    noise_sigma: float = 2.0,
    seed: int = 1234,
    positions=POSITIONS,
    shape=(128, 128),
):
    rng = np.random.default_rng(seed)
    frame = np.full(shape, background, dtype=float)
    if noise_sigma:
        frame += rng.normal(0.0, noise_sigma, size=shape)
    yy, xx = np.indices(shape)
    for (y, x), amplitude in zip(positions, amplitudes):
        frame += amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma**2))
    return frame


def analyzer(**kwargs):
    return FocusAnalyzer(FocusConfig(**kwargs))


def valid_hfr(result: FocusMeasurement) -> float:
    assert result.valid
    assert result.hfr_px is not None
    return result.hfr_px


def test_gaussian_star_hfr_is_close_to_half_flux_radius():
    result = analyzer().measure(synthetic_starfield(sigma=2.0))
    expected = 2.0 * math.sqrt(2.0 * math.log(2.0))
    assert valid_hfr(result) == pytest.approx(expected, abs=0.4)
    assert result.star_count == 5


def test_broader_psfs_produce_monotonically_larger_hfr():
    hfrs = [
        valid_hfr(analyzer().measure(synthetic_starfield(sigma=sigma, seed=index)))
        for index, sigma in enumerate((1.5, 2.0, 3.0), start=1)
    ]
    assert hfrs[0] < hfrs[1] < hfrs[2]


def test_brightness_does_not_materially_change_hfr():
    dim = analyzer().measure(synthetic_starfield(amplitudes=(2500.0,) * 5, seed=9))
    bright = analyzer().measure(synthetic_starfield(amplitudes=(9000.0,) * 5, seed=9))
    assert valid_hfr(dim) == pytest.approx(valid_hfr(bright), abs=0.15)


def test_constant_background_offset_does_not_change_hfr():
    low = analyzer().measure(synthetic_starfield(background=100.0, seed=4))
    high = analyzer().measure(synthetic_starfield(background=10000.0, seed=4))
    assert valid_hfr(low) == pytest.approx(valid_hfr(high), abs=0.1)


def test_modest_noise_preserves_focus_ordering():
    sharp = analyzer().measure(synthetic_starfield(sigma=1.6, noise_sigma=12.0, seed=7))
    soft = analyzer().measure(synthetic_starfield(sigma=2.8, noise_sigma=12.0, seed=7))
    assert valid_hfr(sharp) < valid_hfr(soft)


def test_median_aggregation_is_robust_to_one_broad_outlier():
    frame = synthetic_starfield()
    yy, xx = np.indices(frame.shape)
    y, x = POSITIONS[-1]
    ordinary = 4500.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * 2.0**2))
    broad = 4500.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * 3.5**2))
    frame = frame - ordinary + broad
    result = analyzer().measure(frame)
    baseline = analyzer().measure(synthetic_starfield())
    assert valid_hfr(result) == pytest.approx(valid_hfr(baseline), abs=0.25)


def test_hot_pixel_is_rejected():
    frame = synthetic_starfield()
    frame[64, 18] = 50000.0
    result = analyzer().measure(frame)
    assert result.valid
    assert result.star_count == 5
    assert result.rejected_star_count >= 1


def test_saturated_integer_star_is_rejected():
    frame = synthetic_starfield(
        amplitudes=(80000.0, 4000.0, 6000.0, 3500.0, 4500.0),
        background=0.0,
        noise_sigma=1.0,
    )
    frame = np.clip(frame, 0, 65535).astype(np.uint16)
    result = analyzer(min_stars=4).measure(frame)
    assert result.valid
    assert result.star_count == 4
    assert result.rejected_star_count >= 1


def test_edge_truncated_star_is_rejected():
    positions = ((4, 4), *POSITIONS[1:])
    result = analyzer(min_stars=4).measure(synthetic_starfield(positions=positions))
    assert result.valid
    assert result.star_count == 4
    assert result.rejected_star_count >= 1


def test_strongly_elongated_star_is_rejected():
    frame = synthetic_starfield()
    yy, xx = np.indices(frame.shape)
    frame += 7000.0 * np.exp(
        -((xx - 18) ** 2 / (2.0 * 5.0**2) + (yy - 102) ** 2 / (2.0 * 1.0**2))
    )
    result = analyzer().measure(frame)
    assert result.valid
    assert result.star_count == 5
    assert result.rejected_star_count >= 1


def test_no_stars_returns_explicit_invalid_measurement():
    frame = np.full((64, 64), 1000.0)
    result = analyzer().measure(frame)
    assert not result.valid
    assert result.hfr_px is None
    assert result.star_count == 0
    assert result.message is not None
    assert "usable stars" in result.message


def test_too_few_stars_returns_explicit_invalid_measurement():
    frame = synthetic_starfield(
        positions=POSITIONS[:2],
        amplitudes=(5000.0, 5000.0),
    )
    result = analyzer(min_stars=3).measure(frame)
    assert not result.valid
    assert result.star_count == 2
    assert result.hfr_px is None


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_non_finite_pixels_are_rejected_deterministically(bad_value):
    frame = synthetic_starfield()
    frame[0, 0] = bad_value
    result = analyzer().measure(frame)
    assert not result.valid
    assert result.hfr_px is None
    assert result.message is not None
    assert "non-finite" in result.message


def test_non_2d_input_is_invalid():
    result = analyzer().measure(np.zeros((2, 2, 2)))
    assert not result.valid
    assert result.message is not None
    assert "2D monochrome" in result.message
