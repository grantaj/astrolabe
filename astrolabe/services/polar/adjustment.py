"""Pure geometry for live one-axis polar adjustment.

Solved celestial positions are ICRS.  During manual base adjustment the mount
is not tracking, so each solved position is transformed at its own observation
time into the observer's local horizon frame before motion is inferred.  ERFA
owns the standards-heavy ICRS-to-observed transformation; the remaining
rotation geometry is deliberately small and expressed in radians.
"""

from __future__ import annotations

import datetime
import math

import erfa

from astrolabe.util.math import clamp_unit

_Vec3 = tuple[float, float, float]

# In local ENU coordinates a positive mechanical azimuth adjustment (east)
# is a right-handed rotation around negative Up.
AZ_ADJUSTMENT_AXIS: _Vec3 = (0.0, 0.0, -1.0)


def _dot(a: _Vec3, b: _Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: _Vec3, b: _Vec3) -> _Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(v: _Vec3) -> float:
    return math.sqrt(_dot(v, v))


def _normalize(v: _Vec3) -> _Vec3:
    norm = _norm(v)
    if norm < 1e-15:
        raise ValueError("cannot normalize a zero-length vector")
    return (v[0] / norm, v[1] / norm, v[2] / norm)


def _scale(v: _Vec3, scale: float) -> _Vec3:
    return (v[0] * scale, v[1] * scale, v[2] * scale)


def _sub(a: _Vec3, b: _Vec3) -> _Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _require_utc(timestamp_utc: datetime.datetime) -> None:
    if timestamp_utc.tzinfo is None or timestamp_utc.utcoffset() != datetime.timedelta(
        0
    ):
        raise ValueError("observation timestamp must be timezone-aware UTC")


def _utc_jd(timestamp_utc: datetime.datetime) -> tuple[float, float]:
    _require_utc(timestamp_utc)
    seconds = timestamp_utc.second + timestamp_utc.microsecond / 1_000_000.0
    utc1, utc2 = erfa.dtf2d(
        "UTC",
        timestamp_utc.year,
        timestamp_utc.month,
        timestamp_utc.day,
        timestamp_utc.hour,
        timestamp_utc.minute,
        seconds,
    )
    return float(utc1), float(utc2)


def radec_to_horizon_vector(
    ra_rad: float,
    dec_rad: float,
    timestamp_utc: datetime.datetime,
    *,
    latitude_rad: float,
    longitude_rad: float,
    elevation_m: float = 0.0,
) -> _Vec3:
    """Convert an ICRS direction to a local East/North/Up unit vector.

    Refraction, polar motion and DUT1 are intentionally omitted because this
    workflow needs a stable geometric frame rather than an atmospheric
    apparent position.  ERFA still supplies the IAU bias/precession/nutation
    and Earth-rotation chain, avoiding a bespoke sidereal-time model.
    """
    values = (ra_rad, dec_rad, latitude_rad, longitude_rad, elevation_m)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("coordinate and site values must be finite")
    if not 0.0 <= ra_rad < math.tau:
        raise ValueError("ra_rad must be in [0, 2π)")
    if not -math.pi / 2.0 <= dec_rad <= math.pi / 2.0:
        raise ValueError("dec_rad must be in [-π/2, π/2]")
    if not -math.pi / 2.0 <= latitude_rad <= math.pi / 2.0:
        raise ValueError("latitude_rad must be in [-π/2, π/2]")

    utc1, utc2 = _utc_jd(timestamp_utc)
    aob, zob, _hob, _dob, _rob, _eo = erfa.atco13(
        ra_rad,
        dec_rad,
        0.0,
        0.0,
        0.0,
        0.0,
        utc1,
        utc2,
        0.0,
        longitude_rad,
        latitude_rad,
        elevation_m,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.55,
    )
    azimuth_rad = float(aob)
    altitude_rad = math.pi / 2.0 - float(zob)
    cos_altitude = math.cos(altitude_rad)
    return _normalize(
        (
            cos_altitude * math.sin(azimuth_rad),
            cos_altitude * math.cos(azimuth_rad),
            math.sin(altitude_rad),
        )
    )


def ideal_pole_horizon_vector(latitude_rad: float) -> _Vec3:
    """Return the physical celestial pole in the observer's horizon frame."""
    if not math.isfinite(latitude_rad):
        raise ValueError("latitude_rad must be finite")
    if not -math.pi / 2.0 <= latitude_rad <= math.pi / 2.0:
        raise ValueError("latitude_rad must be in [-π/2, π/2]")
    hemisphere = 1.0 if latitude_rad >= 0.0 else -1.0
    return (
        0.0,
        hemisphere * math.cos(latitude_rad),
        hemisphere * math.sin(latitude_rad),
    )


def rotate_about_axis(vector: _Vec3, axis: _Vec3, angle_rad: float) -> _Vec3:
    """Rotate a unit direction using Rodrigues' formula."""
    if not math.isfinite(angle_rad):
        raise ValueError("angle_rad must be finite")
    k = _normalize(axis)
    cosine = math.cos(angle_rad)
    sine = math.sin(angle_rad)
    rotated = (
        vector[0] * cosine
        + _cross(k, vector)[0] * sine
        + k[0] * _dot(k, vector) * (1.0 - cosine),
        vector[1] * cosine
        + _cross(k, vector)[1] * sine
        + k[1] * _dot(k, vector) * (1.0 - cosine),
        vector[2] * cosine
        + _cross(k, vector)[2] * sine
        + k[2] * _dot(k, vector) * (1.0 - cosine),
    )
    return _normalize(rotated)


def angular_separation_vectors(a: _Vec3, b: _Vec3) -> float:
    """Return the unsigned angular separation of two unit directions."""
    return math.acos(clamp_unit(_dot(_normalize(a), _normalize(b))))


def infer_rotation_about_axis(
    reference: _Vec3,
    current: _Vec3,
    axis: _Vec3,
) -> tuple[float, float]:
    """Infer signed base rotation and cross-track residual.

    Returns ``(applied_rad, cross_track_rad)``.  The signed rotation is found
    from the two directions projected into the plane perpendicular to the
    mechanical adjustment axis.  ``cross_track_rad`` is the angular mismatch
    between the current direction and the direction predicted by that pure
    one-axis rotation.
    """
    k = _normalize(axis)
    reference = _normalize(reference)
    current = _normalize(current)

    reference_plane = _sub(reference, _scale(k, _dot(reference, k)))
    current_plane = _sub(current, _scale(k, _dot(current, k)))
    if _norm(reference_plane) < 1e-8 or _norm(current_plane) < 1e-8:
        raise ValueError("field direction is too close to the adjustment axis")

    reference_plane = _normalize(reference_plane)
    current_plane = _normalize(current_plane)
    sine = _dot(k, _cross(reference_plane, current_plane))
    cosine = clamp_unit(_dot(reference_plane, current_plane))
    applied_rad = math.atan2(sine, cosine)

    predicted = rotate_about_axis(reference, k, applied_rad)
    cross_track_rad = angular_separation_vectors(predicted, current)
    return applied_rad, cross_track_rad


def altitude_adjustment_axis(polar_axis: _Vec3) -> _Vec3:
    """Return the horizontal axis whose positive rotation raises the pole."""
    polar_axis = _normalize(polar_axis)
    horizontal_norm = math.hypot(polar_axis[0], polar_axis[1])
    if horizontal_norm < 1e-8:
        raise ValueError("polar axis altitude is too close to 90 degrees")
    return (
        polar_axis[1] / horizontal_norm,
        -polar_axis[0] / horizontal_norm,
        0.0,
    )
