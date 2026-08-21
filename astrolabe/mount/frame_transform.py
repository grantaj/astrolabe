from __future__ import annotations

import datetime
from dataclasses import dataclass
import math

import erfa
import numpy as np


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


# ERFA models the fixed FK5 J2000.0 orientation with respect to the Hipparcos
# frame. Hipparcos is aligned to ICRS for this purpose, so the transpose is the
# ICRS -> FK5 frame-bias rotation required before epoch-of-date precession.
_FK5_TO_ICRS_BIAS, _ = erfa.fk5hip()
_ICRS_TO_FK5_BIAS = _FK5_TO_ICRS_BIAS.T


def _tt_jd(time_utc: datetime.datetime) -> tuple[float, float]:
    """Convert an explicit UTC datetime to the two-part TT Julian date ERFA needs."""
    seconds = time_utc.second + time_utc.microsecond / 1_000_000.0
    utc1, utc2 = erfa.dtf2d(
        "UTC",
        time_utc.year,
        time_utc.month,
        time_utc.day,
        time_utc.hour,
        time_utc.minute,
        seconds,
    )
    tai1, tai2 = erfa.utctai(utc1, utc2)
    return erfa.taitt(tai1, tai2)


def _icrs_to_epoch_matrix(time_utc: datetime.datetime) -> np.ndarray:
    tt1, tt2 = _tt_jd(time_utc)
    _, precession, _ = erfa.bp06(tt1, tt2)
    return precession @ _ICRS_TO_FK5_BIAS


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

    vector = erfa.s2c(coordinate.ra_rad, coordinate.dec_rad)
    transformed = _icrs_to_epoch_matrix(time_utc) @ vector
    ra_rad, dec_rad = erfa.c2s(transformed)
    return EpochOfDateCoordinate(
        ra_rad=float(erfa.anp(ra_rad)),
        dec_rad=float(dec_rad),
    )


def epoch_of_date_to_icrs(
    coordinate: EpochOfDateCoordinate, time_utc: datetime.datetime
) -> IcrsCoordinate:
    """Convert FK5 mean equator/equinox of date back to canonical ICRS."""
    if not isinstance(coordinate, EpochOfDateCoordinate):
        raise TypeError("coordinate must be an EpochOfDateCoordinate")
    _require_utc(time_utc)

    vector = erfa.s2c(coordinate.ra_rad, coordinate.dec_rad)
    transformed = _icrs_to_epoch_matrix(time_utc).T @ vector
    ra_rad, dec_rad = erfa.c2s(transformed)
    return IcrsCoordinate(
        ra_rad=float(erfa.anp(ra_rad)),
        dec_rad=float(dec_rad),
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
