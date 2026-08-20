from __future__ import annotations

import base64
import binascii
import codecs
import datetime
import math
import socket
import time
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from typing import Callable, Iterator, cast
from xml.sax.saxutils import escape, quoteattr

from astrolabe.errors import BackendError
from astrolabe.indi import IndiClient
from astrolabe.solver.types import Image

from .base import FitsImageData, LiveFrameSession

_FITS_CARD_BYTES = 80
_FITS_HEADER_SCAN_LIMIT = 1024 * 1024


@dataclass(frozen=True)
class _BlobFrame:
    data: bytes
    timestamp_utc: datetime.datetime
    format: str


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_indi_timestamp(value: str | None) -> datetime.datetime:
    if not value:
        return datetime.datetime.now(datetime.timezone.utc)
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.datetime.now(datetime.timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _fits_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < _FITS_CARD_BYTES or not payload.startswith(b"SIMPLE"):
        raise BackendError("INDI returned an invalid FITS BLOB")

    values: dict[str, str] = {}
    limit = min(len(payload), _FITS_HEADER_SCAN_LIMIT)
    found_end = False
    for offset in range(0, limit - _FITS_CARD_BYTES + 1, _FITS_CARD_BYTES):
        try:
            card = payload[offset : offset + _FITS_CARD_BYTES].decode("ascii")
        except UnicodeDecodeError as exc:
            raise BackendError("INDI returned a non-ASCII FITS header") from exc
        key = card[:8].strip()
        if key == "END":
            found_end = True
            break
        if len(card) >= 10 and card[8:10] == "= ":
            values[key] = card[10:].split("/", 1)[0].strip()

    if not found_end:
        raise BackendError("INDI returned a FITS BLOB without an END header card")
    try:
        naxis = int(values.get("NAXIS", "0"))
        width = int(values.get("NAXIS1", "0"))
        height = int(values.get("NAXIS2", "0"))
    except ValueError as exc:
        raise BackendError("INDI returned invalid FITS image dimensions") from exc
    if naxis < 2 or width <= 0 or height <= 0:
        raise BackendError("INDI returned a FITS BLOB without a 2D image")
    return width, height


class _IndiBlobTransport:
    """Narrow persistent INDI XML connection used only for camera BLOB frames."""

    def __init__(
        self,
        host: str,
        port: int,
        device: str,
        blob_property: str,
        *,
        connect_timeout_s: float = 5.0,
    ) -> None:
        self._device = device
        self._blob_property = blob_property
        try:
            self._socket = socket.create_connection(
                (host, port), timeout=connect_timeout_s
            )
        except OSError as exc:
            raise BackendError(
                f"could not open INDI live-frame connection to {host}:{port}"
            ) from exc
        self._closed = False
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._parser = ET.XMLPullParser(events=("start", "end"))
        self._root: ET.Element | None = None
        self._parser.feed("<astrolabe-indi-stream>")
        self._drain_events()
        try:
            self._send(
                f'<getProperties version="1.7" device={quoteattr(device)}/>\n'
                f"<enableBLOB device={quoteattr(device)} "
                f"name={quoteattr(blob_property)}>Only</enableBLOB>\n"
            )
        except BaseException:
            self.close()
            raise

    def _send(self, text: str) -> None:
        if self._closed:
            raise BackendError("INDI live-frame connection is closed")
        try:
            self._socket.sendall(text.encode("utf-8"))
        except OSError as exc:
            raise BackendError(
                "failed to send command on INDI live connection"
            ) from exc

    def request_exposure(
        self, property_name: str, element_name: str, exposure_s: float
    ) -> None:
        self._send(
            f"<newNumberVector device={quoteattr(self._device)} "
            f"name={quoteattr(property_name)}>"
            f"<oneNumber name={quoteattr(element_name)}>"
            f"{escape(format(exposure_s, '.12g'))}"
            "</oneNumber></newNumberVector>\n"
        )

    def _decode_blob_vector(self, elem: ET.Element) -> _BlobFrame | None:
        if elem.attrib.get("device") != self._device:
            return None
        if elem.attrib.get("name") != self._blob_property:
            return None

        blob = None
        for child in elem:
            if _tag_name(child.tag) != "oneBLOB":
                continue
            if child.attrib.get("name") == self._blob_property:
                blob = child
                break
            if blob is None:
                blob = child
        if blob is None:
            raise BackendError("INDI BLOB vector contained no image payload")

        blob_format = blob.attrib.get("format", "").lower()
        encoded = "".join((blob.text or "").split())
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise BackendError("INDI returned invalid base64 BLOB data") from exc

        if blob_format == ".fits.z":
            try:
                payload = zlib.decompress(payload)
            except zlib.error as exc:
                raise BackendError(
                    "INDI returned an invalid compressed FITS BLOB"
                ) from exc
            blob_format = ".fits"
        if blob_format != ".fits":
            raise BackendError(
                f"unsupported INDI live-frame BLOB format: {blob_format or '<empty>'}"
            )

        return _BlobFrame(
            data=payload,
            timestamp_utc=_parse_indi_timestamp(elem.attrib.get("timestamp")),
            format=blob_format,
        )

    def _drain_events(self) -> _BlobFrame | None:
        frame = None
        events = cast(
            Iterator[tuple[str, ET.Element]],
            self._parser.read_events(),
        )
        for event, elem in events:
            if event == "start" and self._root is None:
                self._root = elem
                continue
            if event != "end":
                continue
            if _tag_name(elem.tag) == "setBLOBVector":
                frame = self._decode_blob_vector(elem) or frame
            if self._root is not None and elem in self._root:
                self._root.remove(elem)
        return frame

    def read_frame(self, timeout_s: float) -> _BlobFrame:
        deadline = time.monotonic() + timeout_s
        while True:
            frame = self._drain_events()
            if frame is not None:
                return frame
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendError("timed out waiting for INDI live-frame BLOB")
            self._socket.settimeout(remaining)
            try:
                chunk = self._socket.recv(64 * 1024)
            except TimeoutError as exc:
                raise BackendError(
                    "timed out waiting for INDI live-frame BLOB"
                ) from exc
            except OSError as exc:
                raise BackendError("INDI live-frame connection failed") from exc
            if not chunk:
                raise BackendError("INDI live-frame connection closed by server")
            try:
                text = self._decoder.decode(chunk)
                self._parser.feed(text)
            except (UnicodeDecodeError, ET.ParseError) as exc:
                raise BackendError("invalid XML on INDI live-frame connection") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._socket.close()


class IndiLiveFrameSession(LiveFrameSession):
    def __init__(
        self,
        *,
        client: IndiClient,
        host: str,
        port: int,
        device: str,
        use_guider_exposure: bool,
        exposure_s: float,
        frame_count: int | None,
        configure_camera: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        if not math.isfinite(exposure_s) or exposure_s <= 0:
            raise ValueError("exposure_s must be finite and > 0")
        if frame_count is not None and frame_count <= 0:
            raise ValueError("frame_count must be > 0 when provided")

        self._client = client
        self._device = device
        self._exposure_s = exposure_s
        self._frame_count = frame_count
        self._on_close = on_close
        self._closed = False
        self._frame_index = 0
        self._transport: _IndiBlobTransport | None = None
        self._previous_upload = client.snapshot(device)
        self._upload_keys = {
            "client": f"{device}.UPLOAD_MODE.UPLOAD_CLIENT",
            "local": f"{device}.UPLOAD_MODE.UPLOAD_LOCAL",
            "both": f"{device}.UPLOAD_MODE.UPLOAD_BOTH",
        }
        self._exposure_property = (
            "GUIDER_EXPOSURE" if use_guider_exposure else "CCD_EXPOSURE"
        )
        self._exposure_element = (
            "GUIDER_EXPOSURE_VALUE" if use_guider_exposure else "CCD_EXPOSURE_VALUE"
        )
        self._blob_property = "CCD2" if use_guider_exposure else "CCD1"

        try:
            self._configure_upload_mode()
            configure_camera()
            self._transport = _IndiBlobTransport(
                host=host,
                port=port,
                device=device,
                blob_property=self._blob_property,
            )
        except BaseException:
            self._restore_upload_mode()
            self._closed = True
            self._on_close()
            raise

    def _configure_upload_mode(self) -> None:
        known = set(self._previous_upload)
        if self._upload_keys["local"] in known:
            self._client.setprop(self._upload_keys["local"], "Off", kind="s", soft=True)
        if self._upload_keys["both"] in known:
            self._client.setprop(self._upload_keys["both"], "Off", kind="s", soft=True)
        self._client.setprop(
            self._upload_keys["client"],
            "On",
            kind="s",
            soft=self._upload_keys["client"] not in known,
        )

    def _restore_upload_mode(self) -> None:
        for key in self._upload_keys.values():
            previous = self._previous_upload.get(key)
            if previous in {"On", "Off"}:
                self._client.setprop(key, previous, kind="s", soft=True)

    def __next__(self) -> Image:
        if self._closed:
            raise StopIteration
        if self._frame_count is not None and self._frame_index >= self._frame_count:
            self.close()
            raise StopIteration

        transport = self._transport
        if transport is None:
            self.close()
            raise BackendError("INDI live-frame transport is unavailable")
        try:
            transport.request_exposure(
                self._exposure_property, self._exposure_element, self._exposure_s
            )
            blob = transport.read_frame(max(5.0, self._exposure_s + 5.0))
            width, height = _fits_dimensions(blob.data)
        except BaseException:
            self.close()
            raise

        self._frame_index += 1
        image = Image(
            data=FitsImageData(blob.data),
            width_px=width,
            height_px=height,
            timestamp_utc=blob.timestamp_utc,
            exposure_s=self._exposure_s,
            metadata={
                "device": self._device,
                "transport": "indi_blob",
                "indi_blob_property": self._blob_property,
                "indi_blob_format": blob.format,
                "frame_sequence": self._frame_index,
            },
        )
        if self._frame_count is not None and self._frame_index >= self._frame_count:
            self.close()
        return image

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._transport is not None:
                self._transport.close()
        finally:
            try:
                self._restore_upload_mode()
            finally:
                self._on_close()
