import datetime
import math
from typing import Any, cast

import numpy as np
import pytest

from astrolabe.mount import frame_transform


UTC_TIME = datetime.datetime(2026, 8, 21, 12, 0, tzinfo=datetime.timezone.utc)


def test_frame_transform_reports_missing_astropy(monkeypatch):
    monkeypatch.setattr(frame_transform, "ASTROPY_AVAILABLE", False)

    with pytest.raises(RuntimeError, match="astropy is required"):
        frame_transform.icrs_to_epoch_of_date(
            frame_transform.IcrsCoordinate(ra_rad=1.0, dec_rad=0.5),
            UTC_TIME,
        )


def test_frame_types_reject_wrong_frame_and_obvious_unit_errors():
    eod = frame_transform.EpochOfDateCoordinate(ra_rad=1.0, dec_rad=0.5)
    with pytest.raises(TypeError, match="IcrsCoordinate"):
        frame_transform.icrs_to_epoch_of_date(cast(Any, eod), UTC_TIME)

    with pytest.raises(ValueError, match="ra_rad"):
        frame_transform.IcrsCoordinate(ra_rad=180.0, dec_rad=0.5)
    with pytest.raises(ValueError, match="dec_rad"):
        frame_transform.IcrsCoordinate(ra_rad=1.0, dec_rad=45.0)


def test_frame_transform_requires_explicit_utc_time():
    coordinate = frame_transform.IcrsCoordinate(ra_rad=1.0, dec_rad=0.5)

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        frame_transform.icrs_to_epoch_of_date(
            coordinate,
            datetime.datetime(2026, 8, 21, 12, 0),
        )
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        frame_transform.icrs_to_epoch_of_date(
            coordinate,
            datetime.datetime(
                2026,
                8,
                21,
                12,
                0,
                tzinfo=datetime.timezone(datetime.timedelta(hours=9, minutes=30)),
            ),
        )


@pytest.mark.skipif(
    not frame_transform.ASTROPY_AVAILABLE,
    reason="astropy is not installed",
)
def test_typed_transform_preserves_existing_astropy_behavior():
    import astropy.units as u
    from astropy.coordinates import FK5, SkyCoord
    from astropy.time import Time

    icrs = frame_transform.IcrsCoordinate(ra_rad=1.2, dec_rad=0.4)
    expected_jnow = SkyCoord(
        ra=icrs.ra_rad * u.rad,
        dec=icrs.dec_rad * u.rad,
        frame="icrs",
    ).transform_to(FK5(equinox=Time(UTC_TIME)))

    epoch_of_date = frame_transform.icrs_to_epoch_of_date(icrs, UTC_TIME)

    assert math.isclose(
        epoch_of_date.ra_rad, expected_jnow.ra.rad, rel_tol=0.0, abs_tol=1e-12
    )
    assert math.isclose(
        epoch_of_date.dec_rad, expected_jnow.dec.rad, rel_tol=0.0, abs_tol=1e-12
    )

    fixed_eod = frame_transform.EpochOfDateCoordinate(ra_rad=1.3, dec_rad=0.35)
    expected_icrs = SkyCoord(
        ra=fixed_eod.ra_rad * u.rad,
        dec=fixed_eod.dec_rad * u.rad,
        frame=FK5(equinox=Time(UTC_TIME)),
    ).transform_to("icrs")

    round_trip = frame_transform.epoch_of_date_to_icrs(fixed_eod, UTC_TIME)

    assert math.isclose(
        round_trip.ra_rad, expected_icrs.ra.rad, rel_tol=0.0, abs_tol=1e-12
    )
    assert math.isclose(
        round_trip.dec_rad, expected_icrs.dec.rad, rel_tol=0.0, abs_tol=1e-12
    )


def _axis_rotation(angle_rad: float, axis: str) -> np.ndarray:
    s = math.sin(angle_rad)
    c = math.cos(angle_rad)
    if axis == "x":
        return np.array([[1.0, 0.0, 0.0], [0.0, c, s], [0.0, -s, c]])
    if axis == "y":
        return np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])
    if axis == "z":
        return np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    raise ValueError(f"unknown rotation axis: {axis}")


def _icrs_fk5_bias_matrix() -> np.ndarray:
    mas_to_rad = math.radians(1.0 / 3_600_000.0)
    eta0 = -19.9 * mas_to_rad
    xi0 = 9.1 * mas_to_rad
    da0 = -22.9 * mas_to_rad
    return (
        _axis_rotation(-eta0, "x")
        @ _axis_rotation(xi0, "y")
        @ _axis_rotation(da0, "z")
    )


def _erfa_tt_jd(time_utc: datetime.datetime) -> tuple[float, float]:
    erfa = pytest.importorskip("erfa")
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


def _erfa_icrs_to_epoch_of_date(
    coordinate: frame_transform.IcrsCoordinate, time_utc: datetime.datetime
) -> frame_transform.EpochOfDateCoordinate:
    erfa = pytest.importorskip("erfa")
    tt1, tt2 = _erfa_tt_jd(time_utc)
    _, precession, _ = erfa.bp06(tt1, tt2)
    vector = erfa.s2c(coordinate.ra_rad, coordinate.dec_rad)
    transformed = precession @ _icrs_fk5_bias_matrix() @ vector
    ra_rad, dec_rad = erfa.c2s(transformed)
    return frame_transform.EpochOfDateCoordinate(
        ra_rad=float(erfa.anp(ra_rad)),
        dec_rad=float(dec_rad),
    )


@pytest.mark.skipif(
    not frame_transform.ASTROPY_AVAILABLE,
    reason="astropy is not installed",
)
@pytest.mark.parametrize(
    ("time_utc", "ra_rad", "dec_rad"),
    [
        (datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.timezone.utc), 0.01, 0.0),
        (UTC_TIME, 1.2, 0.4),
        (datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc), 6.27, -0.7),
        (datetime.datetime(2045, 6, 30, tzinfo=datetime.timezone.utc), 3.1, 1.2),
    ],
)
def test_pyerfa_candidate_matches_current_astropy_transform(
    time_utc: datetime.datetime, ra_rad: float, dec_rad: float
):
    coordinate = frame_transform.IcrsCoordinate(ra_rad=ra_rad, dec_rad=dec_rad)

    astropy_result = frame_transform.icrs_to_epoch_of_date(coordinate, time_utc)
    erfa_result = _erfa_icrs_to_epoch_of_date(coordinate, time_utc)

    ra_delta = astropy_result.ra_rad - erfa_result.ra_rad
    ra_error = (ra_delta + math.pi) % math.tau - math.pi
    assert abs(ra_error) < 1e-12
    assert abs(astropy_result.dec_rad - erfa_result.dec_rad) < 1e-12


def test_legacy_jnow_wrapper_preserves_ra_normalization():
    if not frame_transform.ASTROPY_AVAILABLE:
        pytest.skip("astropy is not installed")

    wrapped = frame_transform.icrs_to_jnow(-math.pi / 2.0, 0.25, UTC_TIME)
    typed = frame_transform.icrs_to_epoch_of_date(
        frame_transform.IcrsCoordinate(ra_rad=3.0 * math.pi / 2.0, dec_rad=0.25),
        UTC_TIME,
    )

    assert math.isclose(wrapped[0], typed.ra_rad, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(wrapped[1], typed.dec_rad, rel_tol=0.0, abs_tol=1e-12)
