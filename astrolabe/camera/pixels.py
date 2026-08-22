from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from astrolabe.camera.base import FitsImageData
from astrolabe.camera.types import Image

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


def _read_header_cards(
    handle: BinaryIO, source: str, *, keep_end: bool = False
) -> tuple[list[str], int]:
    cards: list[str] = []
    blocks = 0
    handle.seek(0)
    while True:
        block = handle.read(_FITS_BLOCK_BYTES)
        if len(block) != _FITS_BLOCK_BYTES:
            raise ValueError(f"invalid FITS header: {source}")
        blocks += 1
        for offset in range(0, _FITS_BLOCK_BYTES, _FITS_CARD_BYTES):
            raw = block[offset : offset + _FITS_CARD_BYTES]
            try:
                card = raw.decode("ascii", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError(f"invalid FITS header: {source}") from exc
            if blocks == 1 and offset == 0 and card[:8].strip() != "SIMPLE":
                raise ValueError(
                    f"FITS primary header must begin with SIMPLE: {source}"
                )
            if card[:8].strip() == "END":
                if keep_end:
                    cards.append(card)
                return cards, blocks * _FITS_BLOCK_BYTES
            cards.append(card)


def _fits_header(handle: BinaryIO, source: str) -> tuple[dict[str, str], int]:
    cards, data_offset = _read_header_cards(handle, source)
    header: dict[str, str] = {}
    for card in cards:
        key = card[:8].strip()
        value = _parse_fits_value(card)
        if key and value is not None:
            header[key] = value
    return header, data_offset


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


def _read_fits_pixels(handle: BinaryIO, source: str) -> PixelFrame:
    header, data_offset = _fits_header(handle, source)
    if header.get("SIMPLE", "").upper() not in {"T", "TRUE"}:
        raise ValueError("only simple primary-image FITS files are supported")
    if _header_int(header, "NAXIS") != 2:
        raise ValueError("a 2D monochrome FITS primary image is required")

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
    handle.seek(data_offset)
    payload = handle.read(count * dtype.itemsize)
    if len(payload) != count * dtype.itemsize:
        raise ValueError("FITS pixel payload is truncated")

    # frombuffer is read-only; callers mutate.
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


def load_fits_pixels(path: str | Path) -> PixelFrame:
    """Read the simple 2D primary-image FITS written by INDI camera drivers."""

    fits_path = Path(path)
    with fits_path.open("rb") as handle:
        return _read_fits_pixels(handle, str(fits_path))


def load_fits_bytes(data: bytes) -> PixelFrame:
    """Read an in-memory simple 2D primary-image FITS payload."""

    return _read_fits_pixels(BytesIO(data), "in-memory FITS")


def load_fits_header_cards(path: str | Path) -> list[str]:
    """Read the primary header as ordered right-stripped cards, blank cards and ``END`` dropped."""

    fits_path = Path(path)
    with fits_path.open("rb") as handle:
        cards, _ = _read_header_cards(handle, str(fits_path))
    return [stripped for card in cards if (stripped := card.rstrip())]


def fits_header_text(path: str | Path) -> str:
    """Serialise the primary header verbatim: 80-column cards through ``END``, block-padded."""

    fits_path = Path(path)
    with fits_path.open("rb") as handle:
        cards, _ = _read_header_cards(handle, str(fits_path), keep_end=True)
    text = "\n".join(cards)
    return text + " " * (-len(text) % _FITS_BLOCK_BYTES)


# The standard set, wider than the camera subset `_read_fits_pixels` decodes.
_STANDARD_BITPIX = frozenset({8, 16, 32, 64, -32, -64})


def validate_fits_structure(path: str | Path) -> None:
    """Check the primary HDU declares a well-formed data unit, without decoding it."""

    fits_path = Path(path)
    with fits_path.open("rb") as handle:
        header, data_offset = _fits_header(handle, str(fits_path))
    if header.get("SIMPLE", "").upper() not in {"T", "TRUE"}:
        raise ValueError(f"not a simple FITS primary HDU: {fits_path}")

    bitpix = _header_int(header, "BITPIX")
    if bitpix not in _STANDARD_BITPIX:
        raise ValueError(f"unsupported FITS BITPIX={bitpix}")

    naxis = _header_int(header, "NAXIS")
    if naxis < 0:
        raise ValueError("FITS NAXIS must be non-negative")

    count = 1
    for axis in range(1, naxis + 1):
        length = _header_int(header, f"NAXIS{axis}")
        if length < 0:
            raise ValueError(f"FITS NAXIS{axis} must be non-negative")
        count *= length

    declared = 0 if naxis == 0 else count * abs(bitpix) // 8
    if fits_path.stat().st_size - data_offset < declared:
        raise ValueError(f"FITS pixel payload is truncated: {fits_path}")


_BITPIX_BY_DTYPE = {
    np.dtype("uint8"): 8,
    np.dtype("int16"): 16,
    np.dtype("uint16"): 16,
    np.dtype("int32"): 32,
    np.dtype("float32"): -32,
    np.dtype("float64"): -64,
}
_UNSIGNED_BZERO = {np.dtype("uint16"): 32768.0}

# A caller-supplied duplicate would be appended after the mandatory cards and win
# in the reader's header dict.
_RESERVED_KEYWORDS = frozenset(
    {"SIMPLE", "BITPIX", "NAXIS", "BSCALE", "BZERO", "END", "EXTEND"}
)
_NAXIS_KEYWORD = re.compile(r"NAXIS\d+")
_KEYWORD = re.compile(r"[A-Z0-9_-]{1,8}")
_PRINTABLE_ASCII = re.compile(r"[ -~]*")

_INT_MIN = -(2**63)
_INT_MAX = 2**63


def _format_value(value: bool | int | float | str) -> str:
    """Render a header value in FITS fixed format, right-justified to column 30.

    Quotes are doubled on write; ``_parse_fits_value`` does not un-double on read.
    """

    if isinstance(value, bool):
        return ("T" if value else "F").rjust(20)
    if isinstance(value, int):
        if not _INT_MIN <= value < _INT_MAX:
            raise ValueError(f"FITS integer header value out of range: {value}")
        return str(value).rjust(20)
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("FITS header values must be finite")
        return repr(value).upper().rjust(20)
    if not _PRINTABLE_ASCII.fullmatch(value):
        raise ValueError(f"FITS string header value must be printable ASCII: {value!r}")
    quoted = "'" + value.replace("'", "''").ljust(8) + "'"
    return quoted.ljust(20)


def _check_keyword(name: str) -> None:
    if not _KEYWORD.fullmatch(name):
        raise ValueError(f"invalid FITS keyword: {name!r}")
    if name in _RESERVED_KEYWORDS or _NAXIS_KEYWORD.fullmatch(name):
        raise ValueError(f"FITS keyword is written by the encoder and reserved: {name}")


def _format_card(key: str, value: bool | int | float | str) -> str:
    name = key.upper()
    _check_keyword(name)
    card = f"{name:<8}= {_format_value(value)}"
    if len(card) > _FITS_CARD_BYTES:
        raise ValueError(f"FITS card too long for keyword: {name}")
    return card.ljust(_FITS_CARD_BYTES)


def _structural_card(key: str, value: bool | int | float) -> str:
    return f"{key:<8}= {_format_value(value)}".ljust(_FITS_CARD_BYTES)


def _passthrough_card(card: str) -> str:
    """Validate a verbatim 80-column card supplied by a caller."""

    if not _PRINTABLE_ASCII.fullmatch(card):
        raise ValueError(f"FITS card must be printable ASCII: {card!r}")
    if len(card) > _FITS_CARD_BYTES:
        raise ValueError(f"FITS card too long: {card!r}")
    name = card[:8].strip()
    if name and name not in {"COMMENT", "HISTORY"}:
        _check_keyword(name)
    return card.ljust(_FITS_CARD_BYTES)


def _pad_to_block(payload: bytes, fill: bytes) -> bytes:
    remainder = len(payload) % _FITS_BLOCK_BYTES
    if remainder == 0:
        return payload
    return payload + fill * (_FITS_BLOCK_BYTES - remainder)


def fits_image_bytes(
    pixels: np.ndarray,
    *,
    extra_header: Mapping[str, bool | int | float | str] | None = None,
    extra_cards: Sequence[str] | None = None,
) -> bytes:
    """Encode a 2D array as a simple primary-image FITS payload.

    Value-preserving, not dtype-preserving: uint16 is stored signed-plus-``BZERO``
    and reads back as float64.
    """

    if pixels.ndim != 2:
        raise ValueError("a 2D monochrome FITS primary image is required")
    if pixels.shape[0] <= 0 or pixels.shape[1] <= 0:
        raise ValueError("FITS image dimensions must be positive")

    dtype = pixels.dtype
    # The reader returns big-endian views, so accept either byte order.
    native = dtype.newbyteorder("=")
    try:
        bitpix = _BITPIX_BY_DTYPE[native]
    except KeyError as exc:
        raise ValueError(f"unsupported FITS pixel dtype: {dtype}") from exc

    height, width = pixels.shape
    bzero = _UNSIGNED_BZERO.get(native)
    if bzero is None:
        raw = pixels.astype(native.newbyteorder(">"))
    else:
        raw = (pixels.astype(np.int64) - int(bzero)).astype(">i2")

    cards = [
        _structural_card("SIMPLE", True),
        _structural_card("BITPIX", bitpix),
        _structural_card("NAXIS", 2),
        _structural_card("NAXIS1", int(width)),
        _structural_card("NAXIS2", int(height)),
    ]
    if bzero is not None:
        cards.append(_structural_card("BZERO", bzero))
        cards.append(_structural_card("BSCALE", 1.0))
    cards.extend(
        _format_card(key, value) for key, value in (extra_header or {}).items()
    )
    cards.extend(_passthrough_card(card) for card in (extra_cards or ()))
    cards.append("END".ljust(_FITS_CARD_BYTES))

    header = _pad_to_block("".join(cards).encode("ascii"), b" ")
    data = _pad_to_block(raw.tobytes(), b"\x00")
    return header + data


def write_fits_image(
    path: str | Path,
    pixels: np.ndarray,
    *,
    extra_header: Mapping[str, bool | int | float | str] | None = None,
    extra_cards: Sequence[str] | None = None,
) -> Path:
    """Write a simple 2D primary-image FITS file and return its path."""

    fits_path = Path(path)
    fits_path.write_bytes(
        fits_image_bytes(pixels, extra_header=extra_header, extra_cards=extra_cards)
    )
    return fits_path


def image_to_pixels(image: Image) -> PixelFrame:
    data: Any = image.data
    if isinstance(data, np.ndarray):
        saturation = None
        if np.issubdtype(data.dtype, np.integer):
            saturation = float(np.iinfo(data.dtype).max)
        return PixelFrame(pixels=data, saturation_level=saturation)
    if isinstance(data, FitsImageData):
        return load_fits_bytes(data.data)
    if isinstance(data, (str, Path)):
        return load_fits_pixels(data)
    raise ValueError("Image.data must be pixels, FitsImageData, or a FITS file path")
