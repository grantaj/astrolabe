import math

import pytest

from astrolabe.util.math import (
    angular_separation_rad,
    clamp_unit,
    degrees_to_rad,
    hours_to_rad,
    normalize_angle_rad,
    rad_to_arcsec,
    rad_to_degrees,
    rad_to_hours,
)


def test_degree_radian_round_trip() -> None:
    value = -123.456
    assert rad_to_degrees(degrees_to_rad(value)) == pytest.approx(value)


def test_hour_radian_round_trip() -> None:
    value = 23.75
    assert rad_to_hours(hours_to_rad(value)) == pytest.approx(value)


def test_rad_to_arcsec() -> None:
    assert rad_to_arcsec(math.radians(1.0)) == pytest.approx(3600.0)


@pytest.mark.parametrize(
    ("angle", "expected"),
    [
        (0.0, 0.0),
        (2.0 * math.pi, 0.0),
        (-math.pi / 2.0, 3.0 * math.pi / 2.0),
        (5.0 * math.pi, math.pi),
    ],
)
def test_normalize_angle_rad_wraps_ra(angle: float, expected: float) -> None:
    assert normalize_angle_rad(angle) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-1.5, -1.0),
        (-1.0, -1.0),
        (0.25, 0.25),
        (1.0, 1.0),
        (1.5, 1.0),
    ],
)
def test_clamp_unit(value: float, expected: float) -> None:
    assert clamp_unit(value) == expected


def test_angular_separation_identical() -> None:
    assert angular_separation_rad(1.2, -0.4, 1.2, -0.4) == pytest.approx(0.0)


def test_angular_separation_antipodal() -> None:
    assert angular_separation_rad(0.0, 0.0, math.pi, 0.0) == pytest.approx(math.pi)


def test_angular_separation_quarter_circle() -> None:
    assert angular_separation_rad(0.0, 0.0, math.pi / 2.0, 0.0) == pytest.approx(
        math.pi / 2.0
    )


def test_angular_separation_is_symmetric_across_hemispheres() -> None:
    north = angular_separation_rad(0.2, 0.7, 1.1, 0.3)
    south = angular_separation_rad(0.2, -0.7, 1.1, -0.3)
    assert north == pytest.approx(south)
