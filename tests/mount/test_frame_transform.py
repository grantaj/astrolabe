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
def test_frame_transform_preserves_existing_round_trip_behavior():
    time_utc = datetime.datetime(2026, 8, 21, 12, 0, tzinfo=datetime.timezone.utc)
    ra_rad = 1.2
    dec_rad = 0.4

    jnow_ra, jnow_dec = frame_transform.icrs_to_jnow(ra_rad, dec_rad, time_utc)
    round_trip_ra, round_trip_dec = frame_transform.jnow_to_icrs(
        jnow_ra, jnow_dec, time_utc
    )

    assert math.isclose(round_trip_ra, ra_rad, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(round_trip_dec, dec_rad, rel_tol=0.0, abs_tol=1e-12)
