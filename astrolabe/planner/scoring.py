import math
from dataclasses import dataclass

from .visibility import score_visibility
from astrolabe.errors import NotImplementedFeature


@dataclass
class ScoreComponents:
    alt: float
    duration: float
    moon: float
    size: float
    mag: float
    type_bonus: float

    def total(self, weights: dict[str, float]) -> float:
        return (
            self.alt * weights["alt"]
            + self.duration * weights["duration"]
            + self.moon * weights["moon"]
            + self.size * weights["size"]
            + self.mag * weights["mag"]
            + self.type_bonus * weights["type"]
        )


def score_target(
    *,
    max_alt_deg: float,
    min_alt_deg: float,
    time_above_min_min: float,
    window_duration_min: float,
    moon_sep_deg: float,
    moon_illum: float,
    moon_alt_deg: float,
    moon_up_fraction: float,
    sun_alt_deg: float,
    sun_sep_deg: float,
    target_type: str,
    mag: float | None,
    size_arcmin: float | None,
    size_major_arcmin: float | None,
    size_minor_arcmin: float | None,
    surface_brightness: float | None = None,
    mode: str,
    moon_sep_min_deg: float,
    moon_sep_strict_deg: float,
    moon_illum_strict_threshold: float,
    bortle: int | None = None,
    sqm: float | None = None,
    aperture_mm: float | None = None,
) -> tuple[float, dict[str, float]]:
    weights = _weights_for_mode(mode)
    is_solar = target_type in ("planet", "moon", "sun")
    alt_score = _score_alt(max_alt_deg, min_alt_deg)
    dur_score = _score_duration(time_above_min_min, window_duration_min)
    moon_score = _score_moon(
        moon_sep_deg=moon_sep_deg,
        moon_illum=moon_illum,
        moon_alt_deg=moon_alt_deg,
        moon_up_fraction=moon_up_fraction,
        min_sep=moon_sep_min_deg,
        strict_sep=moon_sep_strict_deg,
        strict_threshold=moon_illum_strict_threshold,
        is_solar=is_solar,
    )
    sun_glow = _score_sun_glow(
        sun_alt_deg=sun_alt_deg,
        sun_sep_deg=sun_sep_deg,
    )
    sky = score_visibility(
        target_type=target_type,
        mag=mag,
        size_arcmin=size_arcmin,
        size_major_arcmin=size_major_arcmin,
        size_minor_arcmin=size_minor_arcmin,
        surface_brightness=surface_brightness,
        altitude_deg=max_alt_deg,
        sqm=sqm,
        bortle=bortle,
        aperture_mm=aperture_mm,
    )
    if is_solar:
        size_score = 1.0
        mag_score = 1.0
        type_bonus = 1.0
    else:
        size_score = _score_size(size_arcmin, mode)
        mag_score = _score_mag(mag, mode)
        type_bonus = _score_type_bonus(target_type, moon_illum)
    components = ScoreComponents(
        alt=alt_score,
        duration=dur_score,
        moon=moon_score,
        size=size_score,
        mag=mag_score,
        type_bonus=type_bonus,
    )
    total = components.total(weights) * sun_glow * sky
    score = max(0.0, min(1.0, total)) * 100.0
    return score, {
        "alt": alt_score,
        "duration": dur_score,
        "moon": moon_score,
        "size": size_score,
        "mag": mag_score,
        "type": type_bonus,
        "sun_glow": sun_glow,
        "visibility": sky,
    }


def _weights_for_mode(mode: str) -> dict[str, float]:
    if mode == "photo":
        return {
            "alt": 0.25,
            "duration": 0.25,
            "moon": 0.25,
            "size": 0.15,
            "mag": 0.05,
            "type": 0.05,
        }
    return {
        "alt": 0.25,
        "duration": 0.20,
        "moon": 0.20,
        "size": 0.10,
        "mag": 0.15,
        "type": 0.10,
    }


def _score_alt(max_alt_deg: float, min_alt_deg: float) -> float:
    if max_alt_deg <= min_alt_deg:
        return 0.0
    return _clamp((max_alt_deg - min_alt_deg) / max(1.0, 90.0 - min_alt_deg))


def _score_duration(time_above_min_min: float, window_duration_min: float) -> float:
    if window_duration_min <= 0:
        return 0.0
    return _clamp(time_above_min_min / window_duration_min)


def _score_moon(
    *,
    moon_sep_deg: float,
    moon_illum: float,
    moon_alt_deg: float,
    moon_up_fraction: float,
    min_sep: float,
    strict_sep: float,
    strict_threshold: float,
    is_solar: bool = False,
) -> float:
    if is_solar:
        return 1.0
    if moon_alt_deg < 0:
        return 1.0
    if moon_up_fraction <= 0:
        return 1.0
    sep_low = min_sep
    sep_high = strict_sep if moon_illum >= strict_threshold else min_sep
    if sep_high <= sep_low:
        score = 1.0 if moon_sep_deg >= sep_low else 0.0
        return _blend_moon_fraction(score, moon_up_fraction)
    if moon_sep_deg <= sep_low:
        return _blend_moon_fraction(0.0, moon_up_fraction)
    if moon_sep_deg >= sep_high:
        return _blend_moon_fraction(1.0, moon_up_fraction)
    return _blend_moon_fraction(_clamp((moon_sep_deg - sep_low) / (sep_high - sep_low)), moon_up_fraction)


def _blend_moon_fraction(score: float, moon_up_fraction: float) -> float:
    return (score * moon_up_fraction) + (1.0 - moon_up_fraction)


def _score_sun_glow(
    sun_alt_deg: float,
    sun_sep_deg: float,
) -> float:
    if sun_alt_deg <= -18.0:
        return 1.0
    if sun_alt_deg >= -12.0:
        base = 0.2
    else:
        base = 1.0 - (sun_alt_deg + 18.0) / 6.0
    sep_factor = _clamp(1.0 - (sun_sep_deg / 180.0))
    penalty = base * sep_factor
    return _clamp(1.0 - penalty)




def _score_size(size_arcmin: float | None, mode: str) -> float:
    if size_arcmin is None:
        return 0.5
    pref_min, pref_max = _preferred_size_range(mode)
    if size_arcmin < pref_min:
        return _clamp(size_arcmin / pref_min)
    if size_arcmin > pref_max:
        return _clamp(pref_max / size_arcmin)
    return 1.0


def _preferred_size_range(mode: str) -> tuple[float, float]:
    if mode == "photo":
        return 5.0, 60.0
    return 10.0, 120.0


def _score_mag(mag: float | None, mode: str) -> float:
    if mag is None:
        return 0.5
    if mode == "photo":
        bright = 6.0
        faint = 12.0
    else:
        bright = 4.0
        faint = 10.0
    if mag <= bright:
        return 1.0
    if mag >= faint:
        return 0.0
    return _clamp(1.0 - (mag - bright) / (faint - bright))


def _score_type_bonus(target_type: str, moon_illum: float) -> float:
    t = target_type.lower()
    if moon_illum >= 0.7:
        if "cluster" in t:
            return 1.0
        if "planetary" in t:
            return 0.6
    return 0.4


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_targets(*args, **kwargs):
    raise NotImplementedFeature("Planner scoring not implemented")
