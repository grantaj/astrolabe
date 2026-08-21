import datetime
import math
from typing import Any, cast

import pytest

from astrolabe.mount import frame_transform


UTC_TIME = datetime.datetime(2026, 8, 21, 12, 0, tzinfo=datetime.timezone.utc)


def _ra_error(left_rad: float, right_rad: float) -> float:
    delta = left_rad - right_rad
    return (delta + math.pi) % math.tau - math.pi


def test_frame_types_reject_wrong_frame_and_obvious_unit_errors():
    icrs = frame_transform.IcrsCoordinate(ra_rad=1.0, dec_rad=0.5)
    eod = frame_transform.EpochOfDateCoordinate(ra_rad=1.0, dec_rad=0.5)

    with pytest.raises(TypeError, match="IcrsCoordinate"):
        frame_transform.icrs_to_epoch_of_date(cast(Any, eod), UTC_TIME)
    with pytest.raises(TypeError, match="EpochOfDateCoordinate"):
        frame_transform.epoch_of_date_to_icrs(cast(Any, icrs), UTC_TIME)

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


@pytest.mark.parametrize(
    ("time_utc", "ra_rad", "dec_rad"),
    [
        (datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.timezone.utc), 0.01, 0.0),
        (UTC_TIME, 1.2, 0.4),
        (datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc), 6.27, -0.7),
        (datetime.datetime(2045, 6, 30, tzinfo=datetime.timezone.utc), 3.1, 1.2),
    ],
)
def test_pyerfa_transform_matches_astropy_fk5_baseline(
    time_utc: datetime.datetime, ra_rad: float, dec_rad: float
):
    pytest.importorskip("astropy")
    import astropy.units as u
    from astropy.coordinates import FK5, SkyCoord
    from astropy.time import Time

    icrs = frame_transform.IcrsCoordinate(ra_rad=ra_rad, dec_rad=dec_rad)
    expected_eod = SkyCoord(
        ra=ra_rad * u.rad,
        dec=dec_rad * u.rad,
        frame="icrs",
    ).transform_to(FK5(equinox=Time(time_utc)))

    actual_eod = frame_transform.icrs_to_epoch_of_date(icrs, time_utc)

    assert abs(_ra_error(actual_eod.ra_rad, expected_eod.ra.rad)) < 1e-12
    assert abs(actual_eod.dec_rad - expected_eod.dec.rad) < 1e-12

    eod = frame_transform.EpochOfDateCoordinate(ra_rad=ra_rad, dec_rad=dec_rad)
    expected_icrs = SkyCoord(
        ra=ra_rad * u.rad,
        dec=dec_rad * u.rad,
        frame=FK5(equinox=Time(time_utc)),
    ).transform_to("icrs")

    actual_icrs = frame_transform.epoch_of_date_to_icrs(eod, time_utc)

    assert abs(_ra_error(actual_icrs.ra_rad, expected_icrs.ra.rad)) < 1e-12
    assert abs(actual_icrs.dec_rad - expected_icrs.dec.rad) < 1e-12


def test_pyerfa_transform_round_trip():
    coordinate = frame_transform.IcrsCoordinate(ra_rad=6.27, dec_rad=-0.7)
    epoch_of_date = frame_transform.icrs_to_epoch_of_date(coordinate, UTC_TIME)
    round_trip = frame_transform.epoch_of_date_to_icrs(epoch_of_date, UTC_TIME)

    assert abs(_ra_error(round_trip.ra_rad, coordinate.ra_rad)) < 1e-14
    assert abs(round_trip.dec_rad - coordinate.dec_rad) < 1e-14


def test_legacy_jnow_wrapper_preserves_ra_normalization():
    wrapped = frame_transform.icrs_to_jnow(-math.pi / 2.0, 0.25, UTC_TIME)
    typed = frame_transform.icrs_to_epoch_of_date(
        frame_transform.IcrsCoordinate(ra_rad=3.0 * math.pi / 2.0, dec_rad=0.25),
        UTC_TIME,
    )

    assert math.isclose(wrapped[0], typed.ra_rad, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(wrapped[1], typed.dec_rad, rel_tol=0.0, abs_tol=1e-12)
