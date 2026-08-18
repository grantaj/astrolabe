from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from astrolabe.camera.base import FitsImageData
from astrolabe.camera.indi_live import IndiLiveFrameSession, _BlobFrame
from astrolabe.indi import IndiClient


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


class _FakeTransport:
    def __init__(self) -> None:
        self.closed = False

    def request_exposure(
        self, property_name: str, element_name: str, exposure_s: float
    ) -> None:
        pass

    def read_frame(self, timeout_s: float) -> _BlobFrame:
        return _BlobFrame(
            data=_fits(80, 60),
            timestamp_utc=datetime.datetime(
                2026, 8, 18, 4, 0, 0, tzinfo=datetime.timezone.utc
            ),
            format=".fits",
        )

    def close(self) -> None:
        self.closed = True


def test_bounded_session_closes_when_final_frame_is_delivered():
    transport = _FakeTransport()
    client = MagicMock(spec=IndiClient)
    client.snapshot.return_value = {}
    released: list[bool] = []

    with patch(
        "astrolabe.camera.indi_live._IndiBlobTransport", return_value=transport
    ):
        frames = IndiLiveFrameSession(
            client=client,
            host="127.0.0.1",
            port=7624,
            device="CCD Simulator",
            use_guider_exposure=False,
            exposure_s=0.1,
            frame_count=1,
            configure_camera=lambda: None,
            on_close=lambda: released.append(True),
        )
        image = next(frames)

    assert isinstance(image.data, FitsImageData)
    assert (image.width_px, image.height_px) == (80, 60)
    assert image.metadata["frame_sequence"] == 1
    assert transport.closed
    assert released == [True]
    with pytest.raises(StopIteration):
        next(frames)
