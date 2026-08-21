import datetime

import numpy as np

from astrolabe.camera.base import FitsImageData
from astrolabe.camera.pixels import image_to_pixels
from astrolabe.solver.types import Image


def _card(key: str, value: str) -> bytes:
    return f"{key:<8}= {value:>20}".ljust(80).encode("ascii")


def _u16_fits(pixels: np.ndarray) -> bytes:
    physical = np.asarray(pixels, dtype=np.uint16)
    raw = (physical.astype(np.int32) - 32768).astype(">i2")
    cards = [
        _card("SIMPLE", "T"),
        _card("BITPIX", "16"),
        _card("NAXIS", "2"),
        _card("NAXIS1", str(physical.shape[1])),
        _card("NAXIS2", str(physical.shape[0])),
        _card("BSCALE", "1"),
        _card("BZERO", "32768"),
        b"END".ljust(80),
    ]
    header = b"".join(cards)
    header += b" " * ((-len(header)) % 2880)
    payload = raw.tobytes(order="C")
    payload += b"\0" * ((-len(payload)) % 2880)
    return header + payload


def test_image_to_pixels_accepts_live_fits_image_data():
    expected = np.array([[0, 1, 32768], [40000, 50000, 65535]], dtype=np.uint16)
    image = Image(
        data=FitsImageData(_u16_fits(expected)),
        width_px=3,
        height_px=2,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=0.1,
        metadata={"transport": "indi_blob"},
    )

    frame = image_to_pixels(image)

    np.testing.assert_array_equal(frame.pixels, expected.astype(float))
    assert frame.saturation_level == 65535.0
