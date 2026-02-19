import datetime
import math


def _to_julian_date(dt: datetime.datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    year = dt.year
    month = dt.month
    day = dt.day + (dt.hour + (dt.minute + dt.second / 60.0) / 60.0) / 24.0
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    jd = math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5
    return jd


def _normalize_angle_rad(angle: float) -> float:
    return angle % (2.0 * math.pi)


def _gmst_rad(dt: datetime.datetime) -> float:
    jd = _to_julian_date(dt)
    d = jd - 2451545.0
    gmst_hours = 18.697374558 + 24.06570982441908 * d
    gmst_rad = math.radians((gmst_hours % 24.0) * 15.0)
    return _normalize_angle_rad(gmst_rad)


def local_sidereal_time_rad(dt: datetime.datetime, longitude_deg: float) -> float:
    return _normalize_angle_rad(_gmst_rad(dt) + math.radians(longitude_deg))


def ra_dec_to_alt_az(
    ra_rad: float,
    dec_rad: float,
    lat_rad: float,
    lon_deg: float,
    dt: datetime.datetime,
) -> tuple[float, float]:
    lst = local_sidereal_time_rad(dt, lon_deg)
    ha = _normalize_angle_rad(lst - ra_rad)
    sin_alt = math.sin(dec_rad) * math.sin(lat_rad) + math.cos(dec_rad) * math.cos(lat_rad) * math.cos(ha)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    az = math.atan2(
        -math.sin(ha),
        math.tan(dec_rad) * math.cos(lat_rad) - math.sin(lat_rad) * math.cos(ha),
    )
    az = _normalize_angle_rad(az)
    return alt, az


def sun_ra_dec_rad(dt: datetime.datetime) -> tuple[float, float]:
    jd = _to_julian_date(dt)
    n = jd - 2451545.0
    l = math.radians((280.460 + 0.9856474 * n) % 360.0)
    g = math.radians((357.528 + 0.9856003 * n) % 360.0)
    lam = l + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    return _normalize_angle_rad(ra), dec


def moon_ra_dec_rad(dt: datetime.datetime) -> tuple[float, float]:
    jd = _to_julian_date(dt)
    n = jd - 2451545.0
    l = math.radians((218.316 + 13.176396 * n) % 360.0)
    m = math.radians((134.963 + 13.064993 * n) % 360.0)
    f = math.radians((93.272 + 13.229350 * n) % 360.0)
    lam = l + math.radians(6.289) * math.sin(m)
    beta = math.radians(5.128) * math.sin(f)
    eps = math.radians(23.439 - 0.0000004 * n)
    sin_dec = math.sin(beta) * math.cos(eps) + math.cos(beta) * math.sin(eps) * math.sin(lam)
    dec = math.asin(max(-1.0, min(1.0, sin_dec)))
    y = math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps)
    x = math.cos(lam)
    ra = math.atan2(y, x)
    return _normalize_angle_rad(ra), dec


def angular_separation_rad(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    cos_sep = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
    cos_sep = max(-1.0, min(1.0, cos_sep))
    return math.acos(cos_sep)


def moon_illumination_fraction(dt: datetime.datetime) -> float:
    ra_sun, dec_sun = sun_ra_dec_rad(dt)
    ra_moon, dec_moon = moon_ra_dec_rad(dt)
    elong = angular_separation_rad(ra_sun, dec_sun, ra_moon, dec_moon)
    return (1.0 - math.cos(elong)) / 2.0
