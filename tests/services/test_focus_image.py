import datetime
from pathlib import Path

import numpy as np

from astrolabe.services.focus import FocusService
from astrolabe.solver.types import Image


def _card(key: str, value: str) -> bytes:
    return f"{key:<8}= {value:>20}".ljust(80).encode("ascii")


def _write_u16_fits(path: Path, pixels: np.ndarray) -> None:
    physical = np.clip(pixels, 0, 65535).astype(np.uint16)
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


def _camera_like_starfield() -> np.ndarray:
    frame = np.full((128, 128), 1200.0)
    yy, xx = np.indices(frame.shape)
    for y, x, amplitude in (
        (25, 25, 9000),
        (28, 95, 7000),
        (65, 65, 8500),
        (96, 32, 7500),
        (94, 102, 8000),
    ):
        frame += amplitude * np.exp(
            -((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * 2.0**2)
        )
    return frame


def test_focus_service_consumes_current_indi_camera_fits_path_contract(tmp_path):
    path = tmp_path / "astrolabe_capture_.fits"
    _write_u16_fits(path, _camera_like_starfield())
    image = Image(
        data=str(path),
        width_px=0,
        height_px=0,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=0.5,
        metadata={"device": "CCD Simulator"},
    )
    result = FocusService().measure_image(image)
    assert result.valid
    assert result.star_count == 5
    assert 1.5 < result.hfr_px < 3.0


class _FakeCamera:
    def __init__(self, image):
        self.image = image
        self.calls = []

    def capture(self, exposure_s, gain=None, binning=None, roi=None):
        self.calls.append((exposure_s, gain, binning, roi))
        return self.image


def test_capture_and_measure_passes_focus_capture_controls(tmp_path):
    path = tmp_path / "capture.fits"
    _write_u16_fits(path, _camera_like_starfield())
    image = Image(
        data=str(path),
        width_px=0,
        height_px=0,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=0.25,
        metadata={},
    )
    camera = _FakeCamera(image)
    result = FocusService(camera).capture_and_measure(
        0.25,
        gain=11.0,
        binning=2,
        roi=(10, 20, 320, 240),
    )
    assert result.valid
    assert camera.calls == [(0.25, 11.0, 2, (10, 20, 320, 240))]
