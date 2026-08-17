"""Shared backend-free angle and spherical-geometry primitives.

All angles are radians unless the function name explicitly states another unit.
This module is deliberately dependency-free and sits at the bottom of Astrolabe's
import graph.
"""

import math

_TAU = 2.0 * math.pi


def degrees_to_rad(degrees: float) -> float:
    """Convert degrees to radians."""
    return math.radians(degrees)


def rad_to_degrees(rad: float) -> float:
    """Convert radians to degrees."""
    return math.degrees(rad)


def hours_to_rad(hours: float) -> float:
    """Convert right-ascension hours to radians."""
    return hours * math.pi / 12.0


def rad_to_hours(rad: float) -> float:
    """Convert radians to right-ascension hours without wrapping."""
    return rad * 12.0 / math.pi


def rad_to_arcsec(rad: float) -> float:
    """Convert radians to arcseconds."""
    return math.degrees(rad) * 3600.0


def normalize_angle_rad(angle: float) -> float:
    """Normalize a cyclic angle to the canonical ``[0, 2π)`` range.

    This is the canonical RA-normalization primitive. It is also suitable for
    other cyclic angles, such as azimuth and sidereal time.
    """
    return angle % _TAU


def clamp_unit(value: float) -> float:
    """Clamp a floating-point value to the inverse-trig domain ``[-1, 1]``."""
    return max(-1.0, min(1.0, value))


def angular_separation_rad(
    ra1_rad: float,
    dec1_rad: float,
    ra2_rad: float,
    dec2_rad: float,
) -> float:
    """Return great-circle separation between two ICRS directions.

    The spherical law of cosines is sufficient at Astrolabe's current
    precision requirements; clamping protects ``acos`` from floating-point
    excursions just outside its domain.
    """
    cos_sep = (
        math.sin(dec1_rad) * math.sin(dec2_rad)
        + math.cos(dec1_rad) * math.cos(dec2_rad) * math.cos(ra1_rad - ra2_rad)
    )
    return math.acos(clamp_unit(cos_sep))
