import datetime
import json
import sys
from types import SimpleNamespace

import numpy as np

from astrolabe.camera.base import CameraBackend, LiveFrameSession
from astrolabe.cli.focus import run_focus
from astrolabe.cli.main import main
from astrolabe.solver.types import Image


def _starfield(sigma: float) -> np.ndarray:
    frame = np.full((128, 128), 1000.0)
    yy, xx = np.indices(frame.shape)
    for y, x in ((25, 25), (28, 95), (65, 65), (96, 32), (94, 102)):
        frame += 7000.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma**2))
    return frame


def _image(sigma: float) -> Image:
    pixels = _starfield(sigma)
    return Image(
        data=pixels,
        width_px=pixels.shape[1],
        height_px=pixels.shape[0],
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=0.1,
        metadata={},
    )


class _FakeSession(LiveFrameSession):
    def __init__(
        self, images: list[Image], *, interrupt_after: int | None = None
    ) -> None:
        self._images = images
        self._index = 0
        self._interrupt_after = interrupt_after
        self.closed = False

    def __next__(self) -> Image:
        if self._interrupt_after is not None and self._index >= self._interrupt_after:
            raise KeyboardInterrupt
        if self._index >= len(self._images):
            raise StopIteration
        image = self._images[self._index]
        self._index += 1
        return image

    def close(self) -> None:
        self.closed = True


class _FakeCamera(CameraBackend):
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.calls = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def capture(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
    ) -> Image:
        raise AssertionError("monitor must use live_frames")

    def live_frames(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
        frame_count: int | None = None,
    ) -> LiveFrameSession:
        self.calls.append((exposure_s, gain, binning, roi, frame_count))
        return self.session


def _args(*, json_output: bool = False, frames: int | None = 3):
    return SimpleNamespace(
        action="monitor",
        exposure=0.1,
        gain=12.0,
        binning=2,
        roi="1,2,64,64",
        frames=frames,
        min_stars=3,
        detection_sigma=5.0,
        saturation_level=None,
        json=json_output,
        log_level=None,
        config=None,
        dry_run=False,
    )


def _config():
    return SimpleNamespace(camera_default_exposure_s=0.5)


def test_focus_monitor_reports_live_hfr_and_trend(monkeypatch, capsys):
    session = _FakeSession([_image(3.0), _image(2.5), _image(2.0)])
    camera = _FakeCamera(session)
    monkeypatch.setattr("astrolabe.cli.focus.load_config", lambda path: _config())
    monkeypatch.setattr("astrolabe.cli.focus.get_camera_backend", lambda config: camera)

    exit_code = run_focus(_args())
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.count("HFR ") == 3
    assert "stars 5" in output
    assert "improving" in output
    assert camera.calls == [(0.1, 12.0, 2, (1, 2, 64, 64), 3)]
    assert session.closed


def test_focus_monitor_ctrl_c_closes_live_session(monkeypatch, capsys):
    session = _FakeSession([_image(2.0)], interrupt_after=1)
    camera = _FakeCamera(session)
    monkeypatch.setattr("astrolabe.cli.focus.load_config", lambda path: _config())
    monkeypatch.setattr("astrolabe.cli.focus.get_camera_backend", lambda config: camera)

    assert run_focus(_args(frames=None)) == 0
    assert "HFR " in capsys.readouterr().out
    assert session.closed


def test_focus_monitor_json_is_one_structured_error(monkeypatch, capsys):
    monkeypatch.setattr("astrolabe.cli.focus.load_config", lambda path: _config())

    exit_code = run_focus(_args(json_output=True))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["command"] == "focus.monitor"
    assert payload["error"]["code"] == "invalid_argument"


def test_main_parser_exposes_focus_monitor(monkeypatch, capsys):
    monkeypatch.setattr("astrolabe.cli.focus.load_config", lambda path: _config())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "astrolabe",
            "--json",
            "focus",
            "monitor",
            "--exposure",
            "0.1",
            "--frames",
            "1",
        ],
    )

    exit_code = main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["command"] == "focus.monitor"
