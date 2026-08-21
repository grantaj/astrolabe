from __future__ import annotations

import datetime

try:
    from astropy.coordinates import FK5, SkyCoord
    from astropy.time import Time
    import astropy.units as u

    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False


def icrs_to_jnow(
    ra_rad: float, dec_rad: float, time_utc: datetime.datetime
) -> tuple[float, float]:
    """Convert Astrolabe's canonical ICRS radians to the mount's JNow frame."""
    if not ASTROPY_AVAILABLE:
        raise RuntimeError(
            "astropy is required for coordinate frame conversion. "
            "Install with: pip install astropy"
        )
    c = SkyCoord(ra=ra_rad * u.rad, dec=dec_rad * u.rad, frame="icrs")
    jnow = c.transform_to(FK5(equinox=Time(time_utc)))
    return jnow.ra.rad, jnow.dec.rad


def jnow_to_icrs(
    ra_rad: float, dec_rad: float, time_utc: datetime.datetime
) -> tuple[float, float]:
    """Convert mount JNow radians back to Astrolabe's canonical ICRS frame."""
    if not ASTROPY_AVAILABLE:
        raise RuntimeError(
            "astropy is required for coordinate frame conversion. "
            "Install with: pip install astropy"
        )
    c = SkyCoord(
        ra=ra_rad * u.rad, dec=dec_rad * u.rad, frame=FK5(equinox=Time(time_utc))
    )
    icrs = c.transform_to("icrs")
    return icrs.ra.rad, icrs.dec.rad
