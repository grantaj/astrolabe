import datetime
from pathlib import Path

import numpy as np
import pytest

from astrolabe.camera.pixels import image_to_pixels, load_fits_pixels
from astrolabe.solver.types import Image


def _card(key: str, value: str) -> bytes:
    return f"{key:<8}= {value:>20}".ljust(80).encode("ascii")


def _write_u16_fits(path: Path, pixels: np.ndarray) -> None:
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
    path.write_bytes(header + payload)


def test_load_fits_pixels_handles_unsigned_16_bit_indi_style_image(tmp_path):
    expected = np.array([[0, 1, 32768], [40000, 50000, 65535]], dtype=np.uint16)
    path = tmp_path / "camera.fits"
    _write_u16_fits(path, expected)
    frame = load_fits_pixels(path)
    np.testing.assert_array_equal(frame.pixels, expected.astype(float))
    assert frame.saturation_level == 65535.0


def test_load_fits_pixels_negative_bscale_uses_raw_minimum_for_saturation(tmp_path):
    raw = np.array([[-32768, -1], [0, 32767]], dtype=">i2")
    path = tmp_path / "negative-scale.fits"
    cards = [
        _card("SIMPLE", "T"),
        _card("BITPIX", "16"),
        _card("NAXIS", "2"),
        _card("NAXIS1", "2"),
        _card("NAXIS2", "2"),
        _card("BSCALE", "-1"),
        _card("BZERO", "0"),
        b"END".ljust(80),
    ]
    header = b"".join(cards)
    header += b" " * ((-len(header)) % 2880)
    payload = raw.tobytes(order="C")
    payload += b"\0" * ((-len(payload)) % 2880)
    path.write_bytes(header + payload)

    frame = load_fits_pixels(path)

    np.testing.assert_array_equal(
        frame.pixels,
        np.array([[32768.0, 1.0], [0.0, -32767.0]]),
    )
    assert frame.saturation_level == 32768.0


def test_image_to_pixels_accepts_in_memory_camera_frame():
    pixels = np.arange(16, dtype=np.uint16).reshape((4, 4))
    image = Image(
        data=pixels,
        width_px=4,
        height_px=4,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=1.0,
        metadata={},
    )
    frame = image_to_pixels(image)
    assert frame.pixels is pixels
    assert frame.saturation_level == 65535.0


def test_fits_loader_rejects_non_2d_primary_image(tmp_path):
    path = tmp_path / "bad.fits"
    cards = [
        _card("SIMPLE", "T"),
        _card("BITPIX", "16"),
        _card("NAXIS", "1"),
        _card("NAXIS1", "4"),
        b"END".ljust(80),
    ]
    header = b"".join(cards)
    header += b" " * ((-len(header)) % 2880)
    path.write_bytes(header + b"\0" * 2880)
    with pytest.raises(ValueError, match="2D monochrome"):
        load_fits_pixels(path)
