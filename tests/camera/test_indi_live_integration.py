from __future__ import annotations

import statistics
import time

import pytest

from astrolabe.camera.base import FitsImageData
from astrolabe.camera.indi import IndiCameraBackend
from astrolabe.indi import IndiClient

_HOST = "127.0.0.1"
_PORT = 7624
_DEVICE = "CCD Simulator"
_EXPOSURE_S = 0.01
_BINNING = 2
_ROI = (0, 0, 320, 240)
_SIMULATOR_POLLING_MS = 25


def _set_simulator_polling_period() -> None:
    client = IndiClient(_HOST, _PORT)
    client.wait_for_device(_DEVICE)
    client.setprop(
        f"{_DEVICE}.POLLING_PERIOD.PERIOD_MS",
        str(_SIMULATOR_POLLING_MS),
        kind="n",
        soft=False,
    )


def _median_steady(samples: list[float]) -> float:
    return statistics.median(samples[5:])


@pytest.mark.integration
def test_indi_simulator_live_frames_are_low_latency_and_leave_no_files(tmp_path):
    # INDI's simulator completes exposures from its polling timer. Its stock
    # 1000 ms polling period would measure timer granularity rather than camera
    # transport, so make the simulator responsive before benchmarking either
    # Astrolabe path. This is test-fixture configuration, not live-path policy.
    _set_simulator_polling_period()

    legacy_dir = tmp_path / "legacy"
    legacy = IndiCameraBackend(
        host=_HOST,
        port=_PORT,
        device=_DEVICE,
        output_dir=legacy_dir,
        output_prefix="astrolabe_legacy_benchmark_",
    )
    legacy_durations: list[float] = []
    try:
        for _ in range(20):
            started = time.perf_counter()
            image = legacy.capture(
                exposure_s=_EXPOSURE_S,
                binning=_BINNING,
                roi=_ROI,
            )
            legacy_durations.append(time.perf_counter() - started)
            assert isinstance(image.data, str)
    finally:
        legacy.disconnect()

    live_dir = tmp_path / "live"
    camera = IndiCameraBackend(
        host=_HOST,
        port=_PORT,
        device=_DEVICE,
        output_dir=live_dir,
        output_prefix="astrolabe_live_test_",
    )
    live_durations: list[float] = []
    try:
        with camera.live_frames(
            exposure_s=_EXPOSURE_S,
            binning=_BINNING,
            roi=_ROI,
            frame_count=100,
        ) as frames:
            for _ in range(100):
                started = time.perf_counter()
                image = next(frames)
                live_durations.append(time.perf_counter() - started)
                assert isinstance(image.data, FitsImageData)
                assert image.width_px > 0
                assert image.height_px > 0
                assert image.metadata["transport"] == "indi_blob"

        assert camera.is_connected()

        # The session must not use UPLOAD_LOCAL as its frame rendezvous.
        assert list(live_dir.iterdir()) == []
        assert len(live_durations) == 100

        legacy_median_s = _median_steady(legacy_durations)
        live_median_s = _median_steady(live_durations)
        live_overhead_s = live_median_s - _EXPOSURE_S
        print(
            "camera benchmark: "
            f"legacy median={legacy_median_s * 1000:.1f} ms, "
            f"live median={live_median_s * 1000:.1f} ms, "
            f"live non-exposure overhead={live_overhead_s * 1000:.1f} ms, "
            f"speedup={legacy_median_s / live_median_s:.2f}x"
        )
        assert live_overhead_s <= 0.250
        assert live_median_s < legacy_median_s

        # Closing a live session restores the ordinary file-capture path without
        # requiring a reconnect.
        image = camera.capture(
            exposure_s=_EXPOSURE_S,
            binning=_BINNING,
            roi=_ROI,
        )
        assert isinstance(image.data, str)
    finally:
        camera.disconnect()
