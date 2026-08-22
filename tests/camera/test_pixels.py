import datetime
from pathlib import Path

import numpy as np
import pytest

from astrolabe.camera.pixels import (
    fits_image_bytes,
    image_to_pixels,
    load_fits_header_cards,
    load_fits_pixels,
    write_fits_image,
)
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


@pytest.mark.parametrize(
    ("dtype", "read_dtype"),
    [
        (np.uint8, "u1"),
        # Stored signed-plus-BZERO: values preserved, dtype not. Pinned because
        # np.array_equal alone would hide it.
        (np.uint16, "float64"),
        (np.int16, ">i2"),
        (np.int32, ">i4"),
        (np.float32, ">f4"),
        (np.float64, ">f8"),
    ],
)
def test_fits_writer_round_trips_through_the_reader(tmp_path, dtype, read_dtype):
    pixels = (np.arange(12).reshape(3, 4) * 501).astype(dtype)

    path = write_fits_image(tmp_path / "round.fits", pixels)
    frame = load_fits_pixels(path)

    assert frame.pixels.shape == pixels.shape
    assert frame.pixels.dtype == np.dtype(read_dtype)
    assert np.array_equal(frame.pixels, pixels)


def test_fits_writer_pads_to_whole_2880_byte_blocks(tmp_path):
    payload = fits_image_bytes(np.zeros((3, 4), dtype=np.uint16))

    assert len(payload) % 2880 == 0
    assert payload[:6] == b"SIMPLE"


def test_fits_writer_emits_extra_header_cards_in_order(tmp_path):
    path = write_fits_image(
        tmp_path / "wcs.fits",
        np.zeros((2, 2), dtype=np.float32),
        extra_header={
            "CTYPE1": "RA---TAN",
            "CRVAL1": 266.4,
            "NSTARS": 7,
            "SOLVED": True,
        },
    )

    cards = load_fits_header_cards(path)

    assert cards[:3] == [
        "SIMPLE  =                    T",
        "BITPIX  =                  -32",
        "NAXIS   =                    2",
    ]
    assert cards[-4:] == [
        "CTYPE1  = 'RA---TAN'",
        "CRVAL1  =                266.4",
        "NSTARS  =                    7",
        "SOLVED  =                    T",
    ]
    assert all(len(card) <= 80 for card in cards)
    assert "END" not in cards


def test_fits_writer_rejects_non_2d_and_unsupported_dtypes(tmp_path):
    with pytest.raises(ValueError, match="2D monochrome"):
        fits_image_bytes(np.zeros((2, 2, 3), dtype=np.uint16))
    with pytest.raises(ValueError, match="unsupported FITS pixel dtype"):
        fits_image_bytes(np.zeros((2, 2), dtype=np.int64))


def test_load_fits_header_cards_preserves_order_and_comments(tmp_path):
    path = tmp_path / "comment.fits"
    header = b"".join(
        [
            _card("SIMPLE", "T"),
            _card("BITPIX", "8"),
            _card("NAXIS", "0"),
            b"COMMENT rendered by the narrow boundary".ljust(80),
            b"HISTORY second".ljust(80),
            b" " * 80,
            b"END".ljust(80),
        ]
    )
    path.write_bytes(header + b" " * ((-len(header)) % 2880))

    assert load_fits_header_cards(path) == [
        "SIMPLE  =                    T",
        "BITPIX  =                    8",
        "NAXIS   =                    0",
        "COMMENT rendered by the narrow boundary",
        "HISTORY second",
    ]


def test_load_fits_header_cards_rejects_a_truncated_header(tmp_path):
    path = tmp_path / "truncated.fits"
    path.write_bytes(_card("SIMPLE", "T"))

    with pytest.raises(ValueError, match="invalid FITS header"):
        load_fits_header_cards(path)


@pytest.mark.parametrize(
    "key",
    ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "BSCALE", "BZERO", "EXTEND"],
)
def test_fits_writer_rejects_reserved_structural_keywords(key):
    with pytest.raises(ValueError, match="reserved"):
        fits_image_bytes(np.zeros((2, 2), dtype=np.uint16), extra_header={key: 0})


def test_fits_writer_reserved_keyword_cannot_corrupt_pixel_values(tmp_path):
    """`BZERO: 0` would otherwise silently rescale every uint16 pixel."""
    pixels = np.array([[0, 65535], [1000, 32768]], dtype=np.uint16)

    with pytest.raises(ValueError, match="reserved"):
        write_fits_image(tmp_path / "x.fits", pixels, extra_header={"BZERO": 0})

    path = write_fits_image(tmp_path / "ok.fits", pixels)
    assert np.array_equal(load_fits_pixels(path).pixels, pixels)


def test_fits_writer_rejects_non_ascii_keywords_and_values():
    with pytest.raises(ValueError, match="invalid FITS keyword"):
        fits_image_bytes(np.zeros((2, 2), dtype=np.uint8), extra_header={"ÄBC": 1})
    with pytest.raises(ValueError, match="printable ASCII"):
        fits_image_bytes(
            np.zeros((2, 2), dtype=np.uint8), extra_header={"OBJECT": "Andrömeda"}
        )


def test_fits_writer_rejects_out_of_range_integers():
    with pytest.raises(ValueError, match="out of range"):
        fits_image_bytes(np.zeros((2, 2), dtype=np.uint8), extra_header={"BIG": 10**30})


def test_fits_writer_passes_source_cards_through_verbatim(tmp_path):
    path = write_fits_image(
        tmp_path / "hint.fits",
        np.zeros((2, 2), dtype=np.float32),
        extra_cards=[
            "OBJCTRA = '05 35 17.30'",
            "COMMENT carried from the source frame",
        ],
    )

    cards = load_fits_header_cards(path)

    assert "OBJCTRA = '05 35 17.30'" in cards
    assert "COMMENT carried from the source frame" in cards


def test_fits_writer_rejects_passthrough_cards_naming_reserved_keywords():
    with pytest.raises(ValueError, match="reserved"):
        fits_image_bytes(
            np.zeros((2, 2), dtype=np.uint16),
            extra_cards=["BZERO   =                 0.0"],
        )
