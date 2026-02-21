import datetime
import math

from .base import CatalogProvider
from astrolabe.planner.astro import moon_ra_dec_rad, moon_illumination_fraction, days_since_j2000
from astrolabe.planner.types import Target


class SolarSystemProvider(CatalogProvider):
    name = "solar_system"

    def list_targets(self):
        raise NotImplementedError("Use list_solar_system_targets(window_start_utc, window_end_utc)")


def list_solar_system_targets(
    window_start_utc: datetime.datetime,
    window_end_utc: datetime.datetime,
) -> list[Target]:
    mid = window_start_utc + (window_end_utc - window_start_utc) / 2
    d = days_since_j2000(mid)

    earth = _planet_heliocentric("earth", d)
    ra_moon, dec_moon = moon_ra_dec_rad(mid)
    illum = moon_illumination_fraction(mid)
    moon = Target(
        id="MOON",
        name="Moon",
        common_name="Moon",
        ra_deg=math.degrees(ra_moon),
        dec_deg=math.degrees(dec_moon),
        type="moon",
        mag=-12.7,
        size_arcmin=30.0,
        surface_brightness=None,
        tags=("solar_system", "showpiece", "moon", f"illum_{int(illum*100)}"),
    )
    targets = [moon]
    for planet in ("mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"):
        ra_deg, dec_deg = _planet_ra_dec(planet, d, earth)
        if ra_deg is None or dec_deg is None:
            continue
        info = PLANET_INFO[planet]
        tags = ["solar_system", "planet"]
        if planet in ("venus", "mars", "jupiter", "saturn"):
            tags.append("showpiece")
        targets.append(
            Target(
                id=planet.upper(),
                name=info["name"],
                common_name=info["name"],
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                type="planet",
                mag=info["mag"],
                size_arcmin=info["size_arcmin"],
                surface_brightness=None,
                tags=tuple(tags),
            )
        )

    return targets


PLANET_INFO = {
    "mercury": {"name": "Mercury", "mag": -0.5, "size_arcmin": 0.20},
    "venus": {"name": "Venus", "mag": -4.0, "size_arcmin": 0.30},
    "mars": {"name": "Mars", "mag": -1.0, "size_arcmin": 0.15},
    "jupiter": {"name": "Jupiter", "mag": -2.5, "size_arcmin": 0.50},
    "saturn": {"name": "Saturn", "mag": -0.5, "size_arcmin": 0.40},
    "uranus": {"name": "Uranus", "mag": 5.7, "size_arcmin": 0.07},
    "neptune": {"name": "Neptune", "mag": 7.8, "size_arcmin": 0.05},
}

# NOTE: The `mag` and `size_arcmin` values above are approximate average
# values for the planets. Apparent magnitudes and angular sizes vary with
# distance and phase; if higher accuracy is required these should be
# computed from ephemerides rather than static constants.


# The days-since-J2000 calculation is provided by `days_since_j2000`
# in `astrolabe/planner/astro.py` to avoid duplication.


def _planet_ra_dec(planet: str, d: float, earth_xyz: tuple[float, float, float]) -> tuple[float | None, float | None]:
    xh, yh, zh = _planet_heliocentric(planet, d)
    xe, ye, ze = earth_xyz
    xg = xh - xe
    yg = yh - ye
    zg = zh - ze
    oblecl = math.radians(23.4393 - 3.563e-7 * d)
    xequat = xg
    yequat = yg * math.cos(oblecl) - zg * math.sin(oblecl)
    zequat = yg * math.sin(oblecl) + zg * math.cos(oblecl)
    ra = math.atan2(yequat, xequat)
    dec = math.atan2(zequat, math.sqrt(xequat * xequat + yequat * yequat))
    return (math.degrees(ra) % 360.0), math.degrees(dec)


def _planet_heliocentric(planet: str, d: float) -> tuple[float, float, float]:
    elems = _planet_elements(planet, d)
    n = math.radians(elems["N"])
    i = math.radians(elems["i"])
    w = math.radians(elems["w"])
    a = elems["a"]
    e = elems["e"]
    m = math.radians(elems["M"])

    e_anom = _solve_kepler(m, e)
    xv = a * (math.cos(e_anom) - e)
    yv = a * (math.sqrt(1.0 - e * e) * math.sin(e_anom))
    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)

    xh = r * (math.cos(n) * math.cos(v + w) - math.sin(n) * math.sin(v + w) * math.cos(i))
    yh = r * (math.sin(n) * math.cos(v + w) + math.cos(n) * math.sin(v + w) * math.cos(i))
    zh = r * (math.sin(v + w) * math.sin(i))
    return xh, yh, zh


def _solve_kepler(m: float, e: float) -> float:
    e_anom = m
    for _ in range(8):
        e_anom = e_anom - (e_anom - e * math.sin(e_anom) - m) / (1 - e * math.cos(e_anom))
    return e_anom


def _planet_elements(planet: str, d: float) -> dict:
    if planet == "mercury":
        return {"N": 48.3313 + 3.24587e-5 * d, "i": 7.0047 + 5.00e-8 * d, "w": 29.1241 + 1.01444e-5 * d, "a": 0.387098, "e": 0.205635 + 5.59e-10 * d, "M": 168.6562 + 4.0923344368 * d}
    if planet == "venus":
        return {"N": 76.6799 + 2.46590e-5 * d, "i": 3.3946 + 2.75e-8 * d, "w": 54.8910 + 1.38374e-5 * d, "a": 0.723330, "e": 0.006773 - 1.302e-9 * d, "M": 48.0052 + 1.6021302244 * d}
    if planet == "earth":
        return {"N": 0.0, "i": 0.0, "w": 282.9404 + 4.70935e-5 * d, "a": 1.0, "e": 0.016709 - 1.151e-9 * d, "M": 356.0470 + 0.9856002585 * d}
    if planet == "mars":
        return {"N": 49.5574 + 2.11081e-5 * d, "i": 1.8497 - 1.78e-8 * d, "w": 286.5016 + 2.92961e-5 * d, "a": 1.523688, "e": 0.093405 + 2.516e-9 * d, "M": 18.6021 + 0.5240207766 * d}
    if planet == "jupiter":
        return {"N": 100.4542 + 2.76854e-5 * d, "i": 1.3030 - 1.557e-7 * d, "w": 273.8777 + 1.64505e-5 * d, "a": 5.20256, "e": 0.048498 + 4.469e-9 * d, "M": 19.8950 + 0.0830853001 * d}
    if planet == "saturn":
        return {"N": 113.6634 + 2.38980e-5 * d, "i": 2.4886 - 1.081e-7 * d, "w": 339.3939 + 2.97661e-5 * d, "a": 9.55475, "e": 0.055546 - 9.499e-9 * d, "M": 316.9670 + 0.0334442282 * d}
    if planet == "uranus":
        return {"N": 74.0005 + 1.3978e-5 * d, "i": 0.7733 + 1.9e-8 * d, "w": 96.6612 + 3.0565e-5 * d, "a": 19.18171 - 1.55e-8 * d, "e": 0.047318 + 7.45e-9 * d, "M": 142.5905 + 0.011725806 * d}
    if planet == "neptune":
        return {"N": 131.7806 + 3.0173e-5 * d, "i": 1.7700 - 2.55e-7 * d, "w": 272.8461 - 6.027e-6 * d, "a": 30.05826 + 3.313e-8 * d, "e": 0.008606 + 2.15e-9 * d, "M": 260.2471 + 0.005995147 * d}
    raise ValueError(f"Unknown planet: {planet}")
