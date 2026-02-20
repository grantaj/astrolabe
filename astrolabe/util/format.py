import math
from typing import Tuple


def rad_to_deg(rad: float) -> float:
    return math.degrees(rad)


def rad_to_arcsec(rad: float) -> float:
    return math.degrees(rad) * 3600.0


def _wrap_hours(hours: float) -> float:
    return hours % 24.0


def _split_dms(angle_deg: float, precision: int) -> Tuple[int, int, int, float]:
    sign = -1 if angle_deg < 0 else 1
    a = abs(angle_deg)
    total_seconds = round(a * 3600.0, precision)
    deg = int(total_seconds // 3600)
    rem = total_seconds - deg * 3600
    minutes = int(rem // 60)
    seconds = rem - minutes * 60
    return sign, deg, minutes, seconds


def _split_hms(hours: float, precision: int) -> Tuple[int, int, float]:
    h = _wrap_hours(hours)
    total_seconds = round(h * 3600.0, precision) % (24.0 * 3600.0)
    hours_int = int(total_seconds // 3600)
    rem = total_seconds - hours_int * 3600
    minutes = int(rem // 60)
    seconds = rem - minutes * 60
    return hours_int, minutes, seconds


def rad_to_hms(rad: float, precision: int = 2) -> str:
    hours = math.degrees(rad) / 15.0
    h, m, s = _split_hms(hours, precision)
    s_fmt = f"{s:0{3 + precision}.{precision}f}"
    return f"{h:02d}:{m:02d}:{s_fmt}"


def rad_to_dms(rad: float, precision: int = 2) -> str:
    deg = math.degrees(rad)
    sign_val, d, m, s = _split_dms(deg, precision)
    sign = "-" if sign_val < 0 else "+"
    s_fmt = f"{s:0{3 + precision}.{precision}f}"
    return f"{sign}{d:02d}:{m:02d}:{s_fmt}"


def format_angle(rad: float, style: str = "deg", precision: int = 2) -> str:
    if style == "deg":
        return f"{rad_to_deg(rad):.{precision}f}°"
    if style == "arcsec":
        return f'{rad_to_arcsec(rad):.{precision}f}"'
    if style == "hms":
        return rad_to_hms(rad, precision=precision)
    if style == "dms":
        return rad_to_dms(rad, precision=precision)
    raise ValueError(f"Unknown angle style: {style}")
