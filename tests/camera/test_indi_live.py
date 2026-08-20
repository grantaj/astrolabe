from __future__ import annotations

import base64
import datetime
import socket
import zlib
from unittest.mock import patch

import pytest

from astrolabe.camera.base import CameraBackend, FitsImageData, LiveFrameSession
from astrolabe.camera.indi import IndiCameraBackend
from astrolabe.camera.indi_live import _IndiBlobTransport
from astrolabe.errors import BackendError
from astrolabe.solver.types import Image


def _fits(width: int = 64, height: int = 48) -> bytes:
    cards = [
        "SIMPLE  =                    T",
        "BITPIX  =                   16",
        "NAXIS   =                    2",
        f"NAXIS1  = {width:20d}",
        f"NAXIS2  = {height:20d}",
        "END",
    ]
    header = "".join(card.ljust(80) for card in cards).encode("ascii")
    return header.ljust(2880, b" ")


def _blob_xml(
    payload: bytes,
    *,
    blob_format: str = ".fits",
    timestamp: str = "2026-08-17T01:02:03Z",
) -> bytes:
    encoded = base64.b64encode(payload).decode("ascii")
    return (
        f'<setBLOBVector device="CCD Simulator" name="CCD1" '
        f'timestamp="{timestamp}">'
        f'<oneBLOB name="CCD1" size="{len(payload)}" format="{blob_format}">'
        f"{encoded}</oneBLOB></setBLOBVector>"
    ).encode("ascii")


class _FakeSocket:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.sent: list[bytes] = []
        self.closed = False
        self.timeouts: list[float] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, size: int) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)

    def shutdown(self, how: int) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_blob_transport_scopes_subscription_and_requests_exposure():
    fake = _FakeSocket([_blob_xml(_fits())])
    with patch(
        "astrolabe.camera.indi_live.socket.create_connection", return_value=fake
    ):
        transport = _IndiBlobTransport("127.0.0.1", 7624, "CCD Simulator", "CCD1")
        transport.request_exposure("CCD_EXPOSURE", "CCD_EXPOSURE_VALUE", 0.25)
        frame = transport.read_frame(2.0)
        transport.close()

    sent = b"".join(fake.sent).decode("utf-8")
    assert '<enableBLOB device="CCD Simulator" name="CCD1">Only</enableBLOB>' in sent
    assert '<newNumberVector device="CCD Simulator" name="CCD_EXPOSURE">' in sent
    assert '<oneNumber name="CCD_EXPOSURE_VALUE">0.25</oneNumber>' in sent
    assert frame.data == _fits()
    assert frame.format == ".fits"
    assert frame.timestamp_utc == datetime.datetime(
        2026, 8, 17, 1, 2, 3, tzinfo=datetime.timezone.utc
    )
    assert fake.closed


def test_blob_transport_handles_split_xml_chunks():
    message = _blob_xml(_fits())
    fake = _FakeSocket([message[:97], message[97:733], message[733:]])
    with patch(
        "astrolabe.camera.indi_live.socket.create_connection", return_value=fake
    ):
        transport = _IndiBlobTransport("127.0.0.1", 7624, "CCD Simulator", "CCD1")
        frame = transport.read_frame(2.0)
    assert frame.data == _fits()


def test_blob_transport_ignores_unrelated_or_stale_property_traffic():
    wrong = _blob_xml(_fits()).replace(b'name="CCD1"', b'name="OTHER"', 1)
    right = _blob_xml(_fits(22, 11))
    fake = _FakeSocket([wrong, right])
    with patch(
        "astrolabe.camera.indi_live.socket.create_connection", return_value=fake
    ):
        transport = _IndiBlobTransport("127.0.0.1", 7624, "CCD Simulator", "CCD1")
        frame = transport.read_frame(2.0)
    assert frame.data == _fits(22, 11)


def test_blob_transport_bounds_backlog_to_latest_matching_frame():
    first = _blob_xml(_fits(10, 10))
    latest = _blob_xml(_fits(20, 20))
    fake = _FakeSocket([first + latest])
    with patch(
        "astrolabe.camera.indi_live.socket.create_connection", return_value=fake
    ):
        transport = _IndiBlobTransport("127.0.0.1", 7624, "CCD Simulator", "CCD1")
        frame = transport.read_frame(2.0)
    assert frame.data == _fits(20, 20)


def test_blob_transport_decompresses_fits_z():
    raw = _fits(32, 24)
    compressed = zlib.compress(raw)
    fake = _FakeSocket([_blob_xml(compressed, blob_format=".fits.z")])
    with patch(
        "astrolabe.camera.indi_live.socket.create_connection", return_value=fake
    ):
        transport = _IndiBlobTransport("127.0.0.1", 7624, "CCD Simulator", "CCD1")
        frame = transport.read_frame(2.0)
    assert frame.data == raw
    assert frame.format == ".fits"


def test_blob_transport_rejects_unsupported_format():
    fake = _FakeSocket([_blob_xml(b"video", blob_format=".stream")])
    with patch(
        "astrolabe.camera.indi_live.socket.create_connection", return_value=fake
    ):
        transport = _IndiBlobTransport("127.0.0.1", 7624, "CCD Simulator", "CCD1")
        with pytest.raises(BackendError, match="unsupported.*BLOB format"):
            transport.read_frame(2.0)


def test_live_session_delivers_ordered_in_memory_frames_and_restores_upload_mode():
    first = _blob_xml(_fits(80, 60), timestamp="2026-08-17T01:02:03Z")
    second = _blob_xml(_fits(40, 30), timestamp="2026-08-17T01:02:04Z")
    fake = _FakeSocket([first, second])
    camera = IndiCameraBackend(
        host="127.0.0.1",
        port=7624,
        device="CCD Simulator",
        output_dir=None,
    )
    camera._connected = True
    camera._gain_prop = "CCD_GAIN.GAIN"
    previous_upload = {
        "CCD Simulator.UPLOAD_MODE.UPLOAD_CLIENT": "Off",
        "CCD Simulator.UPLOAD_MODE.UPLOAD_LOCAL": "On",
        "CCD Simulator.UPLOAD_MODE.UPLOAD_BOTH": "Off",
    }

    with (
        patch.object(camera._client, "snapshot", return_value=previous_upload),
        patch.object(camera._client, "setprop") as mock_setprop,
        patch("astrolabe.camera.indi_live.socket.create_connection", return_value=fake),
    ):
        with camera.live_frames(
            exposure_s=0.1,
            gain=12.0,
            binning=2,
            roi=(1, 2, 80, 60),
            frame_count=2,
        ) as frames:
            images = list(frames)

    assert [(image.width_px, image.height_px) for image in images] == [
        (80, 60),
        (40, 30),
    ]
    assert [image.metadata["frame_sequence"] for image in images] == [1, 2]
    assert all(isinstance(image.data, FitsImageData) for image in images)
    assert all(image.metadata["transport"] == "indi_blob" for image in images)
    set_calls = [(call.args[0], call.args[1]) for call in mock_setprop.call_args_list]
    assert ("CCD Simulator.CCD_GAIN.GAIN", "12.0") in set_calls
    assert ("CCD Simulator.CCD_BINNING.HOR_BIN", "2") in set_calls
    assert ("CCD Simulator.CCD_FRAME.WIDTH", "80") in set_calls
    assert ("CCD Simulator.UPLOAD_MODE.UPLOAD_CLIENT", "Off") in set_calls
    assert ("CCD Simulator.UPLOAD_MODE.UPLOAD_LOCAL", "On") in set_calls
    assert camera._live_session is None


def test_live_session_owns_camera_until_closed():
    fake = _FakeSocket([_blob_xml(_fits())])
    camera = IndiCameraBackend("127.0.0.1", 7624, "CCD Simulator")
    camera._connected = True

    with (
        patch.object(camera._client, "snapshot", return_value={}),
        patch.object(camera._client, "setprop"),
        patch("astrolabe.camera.indi_live.socket.create_connection", return_value=fake),
    ):
        frames = camera.live_frames(0.1)
        with pytest.raises(BackendError, match="active live-frame session"):
            camera.capture(0.1)
        with pytest.raises(BackendError, match="already has an active"):
            camera.live_frames(0.1)
        frames.close()
    assert camera._live_session is None


def test_acquisition_failure_closes_session_and_releases_camera():
    fake = _FakeSocket([_blob_xml(b"video", blob_format=".stream")])
    camera = IndiCameraBackend("127.0.0.1", 7624, "CCD Simulator")
    camera._connected = True

    with (
        patch.object(camera._client, "snapshot", return_value={}),
        patch.object(camera._client, "setprop"),
        patch("astrolabe.camera.indi_live.socket.create_connection", return_value=fake),
    ):
        frames = camera.live_frames(0.1)
        with pytest.raises(BackendError):
            next(frames)
    assert fake.closed
    assert camera._live_session is None


class _SequenceSession(LiveFrameSession):
    def __init__(self, images: list[Image]):
        self._images = iter(images)
        self.closed = False

    def __next__(self) -> Image:
        return next(self._images)

    def close(self) -> None:
        self.closed = True


class _FakeCamera(CameraBackend):
    def __init__(self, images: list[Image]):
        self.images = images

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def capture(self, exposure_s, gain=None, binning=None, roi=None) -> Image:
        return self.images[0]

    def live_frames(
        self, exposure_s, gain=None, binning=None, roi=None, frame_count=None
    ) -> LiveFrameSession:
        images = self.images if frame_count is None else self.images[:frame_count]
        return _SequenceSession(images)


def test_fake_camera_can_drive_live_frame_contract_without_indi():
    images = [
        Image(
            data=f"frame-{index}",
            width_px=10,
            height_px=10,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
            exposure_s=0.1,
            metadata={},
        )
        for index in range(3)
    ]
    camera = _FakeCamera(images)
    with camera.live_frames(0.1, frame_count=2) as frames:
        assert [image.data for image in frames] == ["frame-0", "frame-1"]
