import math

from astrolabe.util.format import (
    format_angle,
    rad_to_arcsec,
    rad_to_deg,
    rad_to_dms,
    rad_to_hms,
)


def test_rad_to_deg():
    assert rad_to_deg(math.pi) == 180.0


def test_rad_to_arcsec():
    assert rad_to_arcsec(math.radians(1.0)) == 3600.0


def test_rad_to_hms_zero():
    assert rad_to_hms(0.0) == "00:00:00.00"


def test_rad_to_hms_wrap():
    # 360 degrees -> 24h -> wrapped to 00
    assert rad_to_hms(math.radians(360.0)) == "00:00:00.00"


def test_rad_to_hms_precision():
    # 15 degrees = 1 hour
    assert rad_to_hms(math.radians(15.0), precision=1) == "01:00:00.0"


def test_rad_to_dms_positive():
    assert rad_to_dms(math.radians(10.0)) == "+10:00:00.00"


def test_rad_to_dms_negative():
    assert rad_to_dms(math.radians(-10.0)) == "-10:00:00.00"


def test_rad_to_hms_rounding_carry():
    # 23:59:59.99 with 1 decimal should round to 00:00:00.0
    seconds = (24 * 3600) - 0.04
    rad = math.radians(seconds / 240.0)
    assert rad_to_hms(rad, precision=1) == "00:00:00.0"


def test_rad_to_hms_wrap_small():
    # Slightly above 24h should wrap to small positive
    rad = math.radians(360.0) + math.radians(0.001)
    assert rad_to_hms(rad, precision=2).startswith("00:00:")


def test_rad_to_dms_small_negative():
    rad = math.radians(-0.0001)
    assert rad_to_dms(rad, precision=2).startswith("-00:00:")


def test_format_angle_unknown_style():
    try:
        format_angle(0.0, style="unknown")
    except ValueError as e:
        assert "Unknown angle style" in str(e)
    else:
        raise AssertionError("Expected ValueError for unknown style")


def test_format_angle_deg():
    assert format_angle(math.pi, style="deg", precision=1) == "180.0°"


def test_format_angle_arcsec():
    assert format_angle(math.radians(1.0), style="arcsec", precision=1) == '3600.0"'
