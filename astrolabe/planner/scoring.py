import math
from dataclasses import dataclass


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
    sun_alt_min_deg: float,
    sun_sep_deg: float,
    target_type: str,
    mag: float | None,
    size_arcmin: float | None,
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
        sun_alt_min_deg=sun_alt_min_deg,
        sun_sep_deg=sun_sep_deg,
    )
    sky = _score_visibility(
        target_type=target_type,
        mag=mag,
        size_arcmin=size_arcmin,
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
    sun_alt_min_deg: float,
    sun_sep_deg: float,
) -> float:
    if sun_alt_min_deg <= -18.0:
        return 1.0
    if sun_alt_min_deg >= -12.0:
        base = 0.2
    else:
        base = 1.0 - (sun_alt_min_deg + 18.0) / 6.0
    sep_factor = _clamp(1.0 - (sun_sep_deg / 180.0))
    penalty = base * sep_factor
    return _clamp(1.0 - penalty)


def _score_visibility(
    *,
    target_type: str,
    mag: float | None,
    size_arcmin: float | None,
    surface_brightness: float | None,
    altitude_deg: float,
    sqm: float | None,
    bortle: int | None,
    aperture_mm: float | None,
) -> float:
    if target_type in ("planet", "moon", "sun"):
        return 1.0
    sqm_val = _sqm_from_inputs(sqm, bortle)
    if sqm_val is None:
        return 1.0
    mu_sky = _sky_brightness_eff(sqm_val, altitude_deg)

    if _is_point_like(target_type, size_arcmin):
        if mag is None:
            return 1.0
        lm = _limiting_magnitude(sqm_val, aperture_mm)
        margin = lm - mag
        return _score_limiting_mag(margin)

    mu_obj = surface_brightness
    if mu_obj is None:
        if mag is None or size_arcmin is None:
            return 1.0
        beta = 1.5 if _is_nebula_type(target_type) else 2.5
        mu_obj = _estimate_surface_brightness(mag, size_arcmin, size_arcmin, beta=beta)
    mu_obj = _apply_structure_boost(mu_obj, target_type)
    delta = mu_obj - mu_sky
    return _score_contrast(delta)


def _sqm_from_inputs(sqm: float | None, bortle: int | None) -> float | None:
    if sqm is not None:
        return sqm
    if bortle is None:
        return None
    # Approximate SQM from Bortle (rough mapping)
    mapping = {
        1: 21.9,
        2: 21.7,
        3: 21.3,
        4: 20.8,
        5: 20.3,
        6: 19.6,
        7: 18.9,
        8: 18.3,
        9: 17.8,
    }
    return mapping.get(max(1, min(9, bortle)), 20.3)


def _sky_brightness_eff(sqm: float, altitude_deg: float) -> float:
    alt = max(5.0, min(90.0, altitude_deg))
    x = 1.0 / math.sin(math.radians(alt))
    c = 0.8
    return sqm - c * (x - 1.0)


def _estimate_surface_brightness(mag: float, a_arcmin: float, b_arcmin: float, beta: float = 2.5) -> float:
    a_sec = a_arcmin * 60.0
    b_sec = b_arcmin * 60.0
    area = math.pi * (a_sec / 2.0) * (b_sec / 2.0)
    if area <= 0:
        return mag
    return mag + beta * math.log10(area)


def _score_contrast(delta_mu: float) -> float:
    if delta_mu <= 0:
        return 1.0
    alpha = 1.2
    return math.exp(-alpha * delta_mu)


def _limiting_magnitude(sqm: float, aperture_mm: float | None) -> float:
    nelm = sqm - 14.0
    if aperture_mm is None:
        aperture_mm = 80.0
    lm = nelm + 5.0 * math.log10(aperture_mm) - 5.0
    return lm


def _score_limiting_mag(margin: float) -> float:
    if margin >= 0:
        return 1.0
    return math.exp(margin)


def _is_point_like(target_type: str, size_arcmin: float | None) -> bool:
    t = target_type.lower()
    if "star" in t or "double" in t:
        return True
    if "open" in t and "cluster" in t:
        return True
    if "planetary" in t and (size_arcmin is not None and size_arcmin < 2.0):
        return True
    if size_arcmin is not None and size_arcmin < 2.0:
        return True
    return False


def _apply_structure_boost(mu_mean: float, target_type: str) -> float:
    t = target_type.lower()
    if "emission" in t or "reflection" in t or "nebula" in t:
        return mu_mean - 1.0
    if "globular" in t:
        return mu_mean - 1.0
    return mu_mean


def _is_nebula_type(target_type: str) -> bool:
    t = target_type.lower()
    return "nebula" in t


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
