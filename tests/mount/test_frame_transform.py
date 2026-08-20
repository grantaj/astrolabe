import datetime
import math

import pytest

from astrolabe.mount import frame_transform


def test_frame_transform_reports_missing_astropy(monkeypatch):
    monkeypatch.setattr(frame_transform, "ASTROPY_AVAILABLE", False)

    with pytest.raises(RuntimeError, match="astropy is required"):
        frame_transform.icrs_to_jnow(
            1.0,
            0.5,
            datetime.datetime(2026, 8, 21, tzinfo=datetime.timezone.utc),
        )


@pytest.mark.skipif(
    not frame_transform.ASTROPY_AVAILABLE,
    reason="astropy is not installed",
)
def test_frame_transform_preserves_existing_astropy_behavior():
    import astropy.units as u
    from astropy.coordinates import FK5, SkyCoord
    from astropy.time import Time

    time_utc = datetime.datetime(2026, 8, 21, 12, 0, tzinfo=datetime.timezone.utc)

    icrs_ra_rad = 1.2
    icrs_dec_rad = 0.4
    expected_jnow = SkyCoord(
        ra=icrs_ra_rad * u.rad,
        dec=icrs_dec_rad * u.rad,
        frame="icrs",
    ).transform_to(FK5(equinox=Time(time_utc)))

    jnow_ra, jnow_dec = frame_transform.icrs_to_jnow(
        icrs_ra_rad, icrs_dec_rad, time_utc
    )

    assert math.isclose(jnow_ra, expected_jnow.ra.rad, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(jnow_dec, expected_jnow.dec.rad, rel_tol=0.0, abs_tol=1e-12)

    fixed_jnow_ra_rad = 1.3
    fixed_jnow_dec_rad = 0.35
    expected_icrs = SkyCoord(
        ra=fixed_jnow_ra_rad * u.rad,
        dec=fixed_jnow_dec_rad * u.rad,
        frame=FK5(equinox=Time(time_utc)),
    ).transform_to("icrs")

    icrs_ra, icrs_dec = frame_transform.jnow_to_icrs(
        fixed_jnow_ra_rad, fixed_jnow_dec_rad, time_utc
    )

    assert math.isclose(icrs_ra, expected_icrs.ra.rad, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(icrs_dec, expected_icrs.dec.rad, rel_tol=0.0, abs_tol=1e-12)
