import math


def score_visibility(
    *,
    target_type: str,
    mag: float | None,
    size_arcmin: float | None,
    size_major_arcmin: float | None,
    size_minor_arcmin: float | None,
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
        if size_major_arcmin is not None and size_minor_arcmin is not None:
            maj_arcmin = size_major_arcmin
            min_arcmin = size_minor_arcmin
        elif size_minor_arcmin is not None:
            maj_arcmin = (size_arcmin * 2.0) - size_minor_arcmin
            if maj_arcmin <= 0:
                maj_arcmin = max(size_arcmin, size_minor_arcmin)
            min_arcmin = size_minor_arcmin
        else:
            maj_arcmin = size_arcmin
            min_arcmin = size_arcmin
        mu_obj = _estimate_surface_brightness(mag, maj_arcmin, min_arcmin, beta=beta)
    mu_obj = _apply_structure_boost(mu_obj, target_type)
    delta = mu_obj - mu_sky
    return _score_contrast(delta)


def _sqm_from_inputs(sqm: float | None, bortle: int | None) -> float | None:
    if sqm is not None:
        return sqm
    if bortle is None:
        return None
    # Midpoints of Bortle class SQM ranges from:
    # https://pmc.ncbi.nlm.nih.gov/articles/PMC10564792/ (Table 1)
    mapping = {
        1: 21.875,
        2: 21.675,
        3: 21.45,
        4: 20.8,
        5: 19.775,
        6: 18.875,
        7: 18.25,
        8: 17.9,
        9: 17.9,
    }
    return mapping.get(max(1, min(9, bortle)), 20.3)


def _sky_brightness_eff(sqm: float, altitude_deg: float) -> float:
    alt = max(5.0, min(90.0, altitude_deg))
    x = 1.0 / math.sin(math.radians(alt))
    c = 0.8
    return sqm - c * (x - 1.0)


def _estimate_surface_brightness(
    mag: float,
    a_arcmin: float,
    b_arcmin: float,
    beta: float = 2.5,
) -> float:
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
