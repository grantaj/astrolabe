from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from astrolabe.solver.types import Image

_FITS_BLOCK_BYTES = 2880
_FITS_CARD_BYTES = 80


@dataclass(frozen=True)
class PixelFrame:
    pixels: np.ndarray
    saturation_level: float | None = None


def _parse_fits_value(card: str) -> str | None:
    if len(card) < 10 or card[8:10] != "= ":
        return None
    value = card[10:].split("/", 1)[0].strip()
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].strip()
    return value


def _fits_header(path: Path) -> tuple[dict[str, str], int]:
    header: dict[str, str] = {}
    blocks = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(_FITS_BLOCK_BYTES)
            if len(block) != _FITS_BLOCK_BYTES:
                raise ValueError(f"invalid FITS header: {path}")
            blocks += 1
            for offset in range(0, _FITS_BLOCK_BYTES, _FITS_CARD_BYTES):
                card = block[offset : offset + _FITS_CARD_BYTES].decode(
                    "ascii", errors="strict"
                )
                key = card[:8].strip()
                if key == "END":
                    return header, blocks * _FITS_BLOCK_BYTES
                value = _parse_fits_value(card)
                if key and value is not None:
                    header[key] = value


def _header_int(header: dict[str, str], key: str) -> int:
    try:
        return int(header[key])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"FITS header missing/invalid {key}") from exc


def _header_float(header: dict[str, str], key: str, default: float) -> float:
    value = header.get(key)
    if value is None:
        return default
    try:
        return float(value.replace("D", "E"))
    except ValueError as exc:
        raise ValueError(f"FITS header has invalid {key}") from exc


def load_fits_pixels(path: str | Path) -> PixelFrame:
    """Read the simple 2D primary-image FITS written by INDI camera drivers."""

    fits_path = Path(path)
    header, data_offset = _fits_header(fits_path)
    if header.get("SIMPLE", "").upper() not in {"T", "TRUE"}:
        raise ValueError("only simple primary-image FITS files are supported")
    if _header_int(header, "NAXIS") != 2:
        raise ValueError("focus requires a 2D monochrome FITS primary image")

    width = _header_int(header, "NAXIS1")
    height = _header_int(header, "NAXIS2")
    if width <= 0 or height <= 0:
        raise ValueError("FITS image dimensions must be positive")

    bitpix = _header_int(header, "BITPIX")
    dtype_by_bitpix = {
        8: np.dtype(">u1"),
        16: np.dtype(">i2"),
        32: np.dtype(">i4"),
        -32: np.dtype(">f4"),
        -64: np.dtype(">f8"),
    }
    try:
        dtype = dtype_by_bitpix[bitpix]
    except KeyError as exc:
        raise ValueError(f"unsupported FITS BITPIX={bitpix}") from exc

    count = width * height
    with fits_path.open("rb") as handle:
        handle.seek(data_offset)
        payload = handle.read(count * dtype.itemsize)
    if len(payload) != count * dtype.itemsize:
        raise ValueError("FITS pixel payload is truncated")

    raw = np.frombuffer(payload, dtype=dtype, count=count).reshape((height, width))
    bscale = _header_float(header, "BSCALE", 1.0)
    bzero = _header_float(header, "BZERO", 0.0)
    if bscale != 1.0 or bzero != 0.0:
        pixels = raw.astype(np.float64) * bscale + bzero
    else:
        pixels = raw.copy()

    saturation_level = None
    if bitpix > 0:
        raw_info = np.iinfo(dtype)
        raw_saturation = raw_info.max if bscale >= 0 else raw_info.min
        saturation_level = float(raw_saturation) * bscale + bzero

    return PixelFrame(
        pixels=pixels,
        saturation_level=saturation_level,
    )


def image_to_pixels(image: Image) -> PixelFrame:
    data: Any = image.data
    if isinstance(data, np.ndarray):
        saturation = None
        if np.issubdtype(data.dtype, np.integer):
            saturation = float(np.iinfo(data.dtype).max)
        return PixelFrame(pixels=data, saturation_level=saturation)
    if isinstance(data, (str, Path)):
        return load_fits_pixels(data)
    raise ValueError(
        "focus requires Image.data to be a 2D NumPy array or a FITS file path"
    )
