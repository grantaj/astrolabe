import datetime

import numpy as np
import pytest

from astrolabe.camera.base import CameraBackend, LiveFrameSession
from astrolabe.services.focus import (
    FocusAnalyzer,
    FocusConfig,
    FocusMeasurement,
    FocusService,
)
from astrolabe.services.focus_monitor import (
    FocusGuidanceEstimator,
    FocusGuidanceState,
    FocusMonitor,
    FocusMonitorSession,
    FocusTrendEstimator,
)
from astrolabe.solver.types import Image


def _starfield(sigma: float) -> np.ndarray:
    frame = np.full((128, 128), 1000.0)
    yy, xx = np.indices(frame.shape)
    for y, x in ((25, 25), (28, 95), (65, 65), (96, 32), (94, 102)):
        frame += 7000.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma**2))
    return frame


def _image(pixels: np.ndarray, exposure_s: float = 0.1) -> Image:
    return Image(
        data=pixels,
        width_px=pixels.shape[1],
        height_px=pixels.shape[0],
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc),
        exposure_s=exposure_s,
        metadata={},
    )


class _FakeSession(LiveFrameSession):
    def __init__(self, images: list[Image]) -> None:
        self._images = iter(images)
        self.closed = False

    def __next__(self) -> Image:
        return next(self._images)

    def close(self) -> None:
        self.closed = True


class _RaisingSession(LiveFrameSession):
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.closed = False

    def __next__(self) -> Image:
        raise self._exc

    def close(self) -> None:
        self.closed = True


class _InterruptingFocusService(FocusService):
    def measure_image(self, image) -> FocusMeasurement:
        raise KeyboardInterrupt


class _FakeCamera(CameraBackend):
    def __init__(self, images: list[Image]) -> None:
        self.session = _FakeSession(images)
        self.live_calls = []

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
        raise AssertionError("live focus monitor must not use one-shot capture")

    def live_frames(
        self,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
        frame_count: int | None = None,
    ) -> LiveFrameSession:
        self.live_calls.append((exposure_s, gain, binning, roi, frame_count))
        return self.session


def _measurement(hfr: float) -> FocusMeasurement:
    return FocusMeasurement(
        valid=True,
        hfr_px=hfr,
        hfr_mad_px=0.1,
        star_count=5,
        rejected_star_count=0,
        background=1000.0,
        noise_sigma=2.0,
    )


def _invalid_measurement() -> FocusMeasurement:
    return FocusMeasurement(
        valid=False,
        hfr_px=None,
        hfr_mad_px=None,
        star_count=0,
        rejected_star_count=0,
        background=1000.0,
        noise_sigma=2.0,
        message="no usable stars",
    )


def test_focus_monitor_consumes_live_frames_and_closes_session():
    images = [_image(_starfield(2.5)), _image(_starfield(2.0))]
    camera = _FakeCamera(images)
    focus = FocusService(analyzer=FocusAnalyzer(FocusConfig(min_stars=3)))

    with FocusMonitor(camera, focus).open(
        exposure_s=0.1,
        gain=12.0,
        binning=2,
        roi=(1, 2, 64, 64),
        frame_count=2,
    ) as monitor:
        results = list(monitor)

    assert len(results) == 2
    assert all(result.valid for result in results)
    assert results[1].hfr_px is not None
    assert results[0].hfr_px is not None
    assert results[1].hfr_px < results[0].hfr_px
    assert camera.live_calls == [(0.1, 12.0, 2, (1, 2, 64, 64), 2)]
    assert camera.session.closed


def test_focus_monitor_closes_session_when_frame_iteration_fails():
    frames = _RaisingSession(RuntimeError("frame failed"))
    monitor = FocusMonitorSession(frames, FocusService())

    with pytest.raises(RuntimeError, match="frame failed"):
        next(monitor)

    assert frames.closed


def test_focus_monitor_closes_session_when_measurement_is_interrupted():
    frames = _FakeSession([_image(_starfield(2.5))])
    monitor = FocusMonitorSession(frames, _InterruptingFocusService())

    with pytest.raises(KeyboardInterrupt):
        next(monitor)

    assert frames.closed


def test_focus_trend_estimator_uses_robust_recent_hfr_without_mutating_measurement():
    estimator = FocusTrendEstimator()
    first = _measurement(4.0)

    assert estimator.update(first) is None
    assert estimator.update(_measurement(3.8)) is None
    assert estimator.update(_measurement(3.5)) == "improving"
    assert first.hfr_px == 4.0


def test_focus_trend_estimator_reports_stable_and_worsening():
    stable = FocusTrendEstimator()
    assert stable.update(_measurement(3.00)) is None
    assert stable.update(_measurement(3.02)) is None
    assert stable.update(_measurement(3.01)) == "stable"

    worsening = FocusTrendEstimator()
    assert worsening.update(_measurement(3.0)) is None
    assert worsening.update(_measurement(3.2)) is None
    assert worsening.update(_measurement(3.4)) == "worsening"


def test_invalid_measurement_resets_focus_trend_history():
    estimator = FocusTrendEstimator()
    estimator.update(_measurement(4.0))
    estimator.update(_measurement(3.8))
    assert estimator.update(_measurement(3.5)) == "improving"

    assert estimator.update(_invalid_measurement()) is None
    assert estimator.update(_measurement(3.4)) is None
    assert estimator.update(_measurement(3.3)) is None


def test_focus_guidance_does_not_call_a_pause_best_focus():
    estimator = FocusGuidanceEstimator(window_size=3)

    assert estimator.update(_measurement(4.0)).state is FocusGuidanceState.UNKNOWN
    assert estimator.update(_measurement(3.7)).state is FocusGuidanceState.UNKNOWN
    assert estimator.update(_measurement(3.4)).state is FocusGuidanceState.IMPROVING
    assert estimator.update(_measurement(3.39)).state is FocusGuidanceState.IMPROVING

    guidance = estimator.update(_measurement(3.41))

    assert guidance.state is FocusGuidanceState.UNKNOWN
    assert guidance.best_hfr_px == pytest.approx(3.39)


def test_focus_guidance_brackets_crossing_then_recovers_best_observed_region():
    estimator = FocusGuidanceEstimator(window_size=3)
    for hfr in (4.0, 3.7, 3.4, 3.39, 3.41):
        estimator.update(_measurement(hfr))

    assert estimator.update(_measurement(3.6)).state is FocusGuidanceState.WORSENING
    assert estimator.update(_measurement(3.5)).state is FocusGuidanceState.WORSENING
    assert estimator.update(_measurement(3.42)).state is FocusGuidanceState.IMPROVING
    guidance = estimator.update(_measurement(3.40))

    assert guidance.state is FocusGuidanceState.BEST_OBSERVED
    assert guidance.best_hfr_px == pytest.approx(3.39)


def test_significantly_better_new_best_requires_fresh_bracketing():
    estimator = FocusGuidanceEstimator(window_size=3)
    for hfr in (4.0, 3.7, 3.4, 3.39, 3.41, 3.6, 3.5, 3.42, 3.40):
        estimator.update(_measurement(hfr))

    assert estimator.update(_measurement(3.0)).state is FocusGuidanceState.IMPROVING
    estimator.update(_measurement(3.01))
    guidance = estimator.update(_measurement(3.02))

    assert guidance.state is FocusGuidanceState.UNKNOWN
    assert guidance.best_hfr_px == pytest.approx(3.0)


def test_flat_noisy_startup_stays_unknown_without_improvement_and_crossing():
    estimator = FocusGuidanceEstimator(window_size=3)

    assert estimator.update(_measurement(3.00)).state is FocusGuidanceState.UNKNOWN
    assert estimator.update(_measurement(3.01)).state is FocusGuidanceState.UNKNOWN
    assert estimator.update(_measurement(2.99)).state is FocusGuidanceState.UNKNOWN
    assert estimator.update(_measurement(3.02)).state is FocusGuidanceState.UNKNOWN


def test_invalid_focus_frame_clears_guidance_and_requires_fresh_history():
    estimator = FocusGuidanceEstimator(window_size=3)
    estimator.update(_measurement(4.0))
    estimator.update(_measurement(3.7))
    assert estimator.update(_measurement(3.4)).state is FocusGuidanceState.IMPROVING

    invalid = estimator.update(_invalid_measurement())
    assert not invalid.valid
    assert invalid.state is FocusGuidanceState.UNKNOWN
    assert invalid.best_hfr_px is None
    assert estimator.update(_measurement(3.3)).state is FocusGuidanceState.UNKNOWN
    assert estimator.update(_measurement(3.2)).state is FocusGuidanceState.UNKNOWN


def test_stale_focus_history_is_discarded_before_new_guidance():
    now = [0.0]
    estimator = FocusGuidanceEstimator(
        window_size=3,
        stale_after_s=5.0,
        clock=lambda: now[0],
    )

    estimator.update(_measurement(4.0))
    now[0] = 1.0
    estimator.update(_measurement(3.7))
    now[0] = 2.0
    assert estimator.update(_measurement(3.4)).state is FocusGuidanceState.IMPROVING

    now[0] = 10.0
    guidance = estimator.update(_measurement(3.3))

    assert guidance.state is FocusGuidanceState.UNKNOWN
    assert guidance.best_hfr_px == pytest.approx(3.3)
