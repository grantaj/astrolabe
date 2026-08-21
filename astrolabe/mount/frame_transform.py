from __future__ import annotations

import datetime
from dataclasses import dataclass
import math

try:
    from astropy.coordinates import FK5, SkyCoord
    from astropy.time import Time
    import astropy.units as u

    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False


def _validate_equatorial_coordinate(*, ra_rad: float, dec_rad: float) -> None:
    if not math.isfinite(ra_rad) or not math.isfinite(dec_rad):
        raise ValueError("equatorial coordinates must be finite")
    if not 0.0 <= ra_rad < math.tau:
        raise ValueError("ra_rad must be in [0, 2π)")
    if not -math.pi / 2.0 <= dec_rad <= math.pi / 2.0:
        raise ValueError("dec_rad must be in [-π/2, π/2]")


def _require_utc(time_utc: datetime.datetime) -> None:
    if time_utc.tzinfo is None or time_utc.utcoffset() != datetime.timedelta(0):
        raise ValueError("frame transformation time must be timezone-aware UTC")


def _require_astropy() -> None:
    if not ASTROPY_AVAILABLE:
        raise RuntimeError(
            "astropy is required for coordinate frame conversion. "
            "Install with: pip install astropy"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class IcrsCoordinate:
    """Canonical Astrolabe equatorial coordinate in ICRS radians."""

    ra_rad: float
    dec_rad: float

    def __post_init__(self) -> None:
        _validate_equatorial_coordinate(ra_rad=self.ra_rad, dec_rad=self.dec_rad)


@dataclass(frozen=True, slots=True, kw_only=True)
class EpochOfDateCoordinate:
    """Mount-boundary FK5 mean equator/equinox-of-date coordinate in radians."""

    ra_rad: float
    dec_rad: float

    def __post_init__(self) -> None:
        _validate_equatorial_coordinate(ra_rad=self.ra_rad, dec_rad=self.dec_rad)


def icrs_to_epoch_of_date(
    coordinate: IcrsCoordinate, time_utc: datetime.datetime
) -> EpochOfDateCoordinate:
    """Convert canonical ICRS to FK5 mean equator/equinox of date."""
    if not isinstance(coordinate, IcrsCoordinate):
        raise TypeError("coordinate must be an IcrsCoordinate")
    _require_utc(time_utc)
    _require_astropy()
    c = SkyCoord(
        ra=coordinate.ra_rad * u.rad,
        dec=coordinate.dec_rad * u.rad,
        frame="icrs",
    )
    epoch_of_date = c.transform_to(FK5(equinox=Time(time_utc)))
    return EpochOfDateCoordinate(
        ra_rad=float(epoch_of_date.ra.rad),
        dec_rad=float(epoch_of_date.dec.rad),
    )


def epoch_of_date_to_icrs(
    coordinate: EpochOfDateCoordinate, time_utc: datetime.datetime
) -> IcrsCoordinate:
    """Convert FK5 mean equator/equinox of date back to canonical ICRS."""
    if not isinstance(coordinate, EpochOfDateCoordinate):
        raise TypeError("coordinate must be an EpochOfDateCoordinate")
    _require_utc(time_utc)
    _require_astropy()
    c = SkyCoord(
        ra=coordinate.ra_rad * u.rad,
        dec=coordinate.dec_rad * u.rad,
        frame=FK5(equinox=Time(time_utc)),
    )
    icrs = c.transform_to("icrs")
    return IcrsCoordinate(
        ra_rad=float(icrs.ra.rad),
        dec_rad=float(icrs.dec.rad),
    )


def icrs_to_jnow(
    ra_rad: float, dec_rad: float, time_utc: datetime.datetime
) -> tuple[float, float]:
    """Compatibility wrapper for the historical JNow-named transform API."""
    coordinate = IcrsCoordinate(ra_rad=ra_rad % math.tau, dec_rad=dec_rad)
    epoch_of_date = icrs_to_epoch_of_date(coordinate, time_utc)
    return epoch_of_date.ra_rad, epoch_of_date.dec_rad


def jnow_to_icrs(
    ra_rad: float, dec_rad: float, time_utc: datetime.datetime
) -> tuple[float, float]:
    """Compatibility wrapper for the historical JNow-named transform API."""
    coordinate = EpochOfDateCoordinate(ra_rad=ra_rad % math.tau, dec_rad=dec_rad)
    icrs = epoch_of_date_to_icrs(coordinate, time_utc)
    return icrs.ra_rad, icrs.dec_rad
