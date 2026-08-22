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


# Frozen FK5 parity baseline (issue #76), replacing the removed Astropy oracle.
# Generated 2026-08-22 with astropy 7.2.0 / pyerfa 2.0.1.5 / numpy 2.4.2 via
# SkyCoord(...).transform_to(FK5(equinox=Time(t))) in both directions. Rows are
# (utc_iso, ra_rad, dec_rad, expected eod ra/dec, expected icrs ra/dec).
# Do not regenerate: this is the independent evidence that the PyERFA transform
# matches FK5.
_FK5_REFERENCE_VECTORS = (
    (
        "2000-01-01T12:00:00+00:00",
        0.01,
        0.0,
        0.010000111477117955,
        4.3348678053476733e-08,
        0.009999888522886252,
        -4.3348688858150314e-08,
    ),
    (
        "2026-08-21T12:00:00+00:00",
        1.2,
        0.4,
        1.2069791994320334,
        0.40092925990486294,
        1.193026232494454,
        0.3990539113064398,
    ),
    (
        "2026-12-01T00:00:00+00:00",
        6.27,
        -0.7,
        6.276040996964818,
        -0.6973850761892281,
        6.263945529646274,
        -0.7026147160210138,
    ),
    (
        "2045-06-30T00:00:00+00:00",
        3.1,
        1.2,
        3.11058358777954,
        1.1955828919302844,
        3.0892892849763482,
        1.204415151460237,
    ),
    (
        "1975-03-15T06:45:30+00:00",
        4.5,
        -1.4,
        4.480847685342978,
        -1.3994694127188938,
        4.519250278306809,
        -1.4004853554917276,
    ),
    (
        "2035-09-21T18:30:45.500000+00:00",
        0.0,
        1.5533430342749532,
        0.008989797362169323,
        1.5568136810925137,
        6.275852614421181,
        1.5498723748268333,
    ),
    (
        "1999-12-31T23:59:30+00:00",
        2.7182818,
        -0.0001,
        2.718281605180014,
        -9.995867807762406e-05,
        2.7182819948199817,
        -0.00010004132194666857,
    ),
)


@pytest.mark.parametrize(
    (
        "utc_iso",
        "ra_rad",
        "dec_rad",
        "expected_eod_ra_rad",
        "expected_eod_dec_rad",
        "expected_icrs_ra_rad",
        "expected_icrs_dec_rad",
    ),
    _FK5_REFERENCE_VECTORS,
    ids=[row[0] for row in _FK5_REFERENCE_VECTORS],
)
def test_pyerfa_transform_matches_frozen_fk5_baseline(
    utc_iso: str,
    ra_rad: float,
    dec_rad: float,
    expected_eod_ra_rad: float,
    expected_eod_dec_rad: float,
    expected_icrs_ra_rad: float,
    expected_icrs_dec_rad: float,
):
    time_utc = datetime.datetime.fromisoformat(utc_iso)

    actual_eod = frame_transform.icrs_to_epoch_of_date(
        frame_transform.IcrsCoordinate(ra_rad=ra_rad, dec_rad=dec_rad), time_utc
    )
    assert abs(_ra_error(actual_eod.ra_rad, expected_eod_ra_rad)) < 1e-12
    assert abs(actual_eod.dec_rad - expected_eod_dec_rad) < 1e-12

    actual_icrs = frame_transform.epoch_of_date_to_icrs(
        frame_transform.EpochOfDateCoordinate(ra_rad=ra_rad, dec_rad=dec_rad), time_utc
    )
    assert abs(_ra_error(actual_icrs.ra_rad, expected_icrs_ra_rad)) < 1e-12
    assert abs(actual_icrs.dec_rad - expected_icrs_dec_rad) < 1e-12


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
