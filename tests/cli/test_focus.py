import json
from types import SimpleNamespace

import numpy as np
import pytest

from astrolabe.cli.focus import run_focus
from astrolabe.solver.types import Image


def _starfield() -> np.ndarray:
    frame = np.full((128, 128), 1000.0)
    yy, xx = np.indices(frame.shape)
    for y, x in ((25, 25), (28, 95), (65, 65), (96, 32), (94, 102)):
        frame += 7000.0 * np.exp(
            -((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * 2.0**2)
        )
    return frame


class _FakeCamera:
    def __init__(self, pixels):
        self.pixels = pixels
        self.calls = []

    def capture(self, exposure_s, gain=None, binning=None, roi=None):
        self.calls.append((exposure_s, gain, binning, roi))
        return Image(
            data=self.pixels,
            width_px=self.pixels.shape[1],
            height_px=self.pixels.shape[0],
            timestamp_utc=None,
            exposure_s=exposure_s,
            metadata={},
        )


def _args(*, json_output=False, exposure=0.25):
    return SimpleNamespace(
        action="measure",
        input_fits=None,
        exposure=exposure,
        gain=12.0,
        binning=2,
        roi="1,2,64,64",
        min_stars=3,
        detection_sigma=5.0,
        saturation_level=None,
        json=json_output,
        log_level=None,
        config=None,
        dry_run=False,
    )


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))


def test_focus_measure_captures_camera_frame_and_reports_hfr(monkeypatch, capsys):
    camera = _FakeCamera(_starfield())
    monkeypatch.setattr("astrolabe.cli.focus.get_camera_backend", lambda config: camera)
    exit_code = run_focus(_args())
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "HFR:" in captured.out
    assert "Stars: 5 accepted" in captured.out
    assert camera.calls == [(0.25, 12.0, 2, (1, 2, 64, 64))]


def test_focus_measure_json_preserves_single_object_contract(monkeypatch, capsys):
    camera = _FakeCamera(_starfield())
    monkeypatch.setattr("astrolabe.cli.focus.get_camera_backend", lambda config: camera)
    exit_code = run_focus(_args(json_output=True))
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "focus.measure"
    assert payload["data"]["valid"] is True
    assert payload["data"]["hfr_px"] > 0
    assert payload["data"]["star_count"] == 5


def test_focus_measure_returns_recoverable_failure_for_no_stars(
    monkeypatch, capsys
):
    camera = _FakeCamera(np.full((64, 64), 1000.0))
    monkeypatch.setattr("astrolabe.cli.focus.get_camera_backend", lambda config: camera)
    exit_code = run_focus(_args(json_output=True))
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "focus_measurement_invalid"
    assert payload["data"]["valid"] is False
