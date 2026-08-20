from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from typing import Literal

import numpy as np

from astrolabe.camera.base import CameraBackend, LiveFrameSession
from astrolabe.services.focus import FocusMeasurement, FocusService

FocusTrend = Literal["improving", "stable", "worsening"]


class FocusTrendEstimator:
    """Robust short-window trend for human focus feedback."""

    def __init__(
        self,
        *,
        window_size: int = 5,
        relative_deadband: float = 0.03,
        absolute_deadband_px: float = 0.05,
    ) -> None:
        if window_size < 3:
            raise ValueError("window_size must be at least 3")
        if relative_deadband < 0 or absolute_deadband_px < 0:
            raise ValueError("trend deadbands must be non-negative")
        self._values: deque[float] = deque(maxlen=window_size)
        self._relative_deadband = relative_deadband
        self._absolute_deadband_px = absolute_deadband_px

    def update(self, measurement: FocusMeasurement) -> FocusTrend | None:
        """Return a display trend without altering the raw measurement."""

        if not measurement.valid or measurement.hfr_px is None:
            self._values.clear()
            return None

        self._values.append(measurement.hfr_px)
        if len(self._values) < 3:
            return None

        values = np.asarray(self._values, dtype=float)
        split = len(values) // 2
        older = float(np.median(values[:split]))
        newer = float(np.median(values[split:]))
        deadband = max(
            self._absolute_deadband_px,
            abs(older) * self._relative_deadband,
        )
        delta = newer - older
        if delta < -deadband:
            return "improving"
        if delta > deadband:
            return "worsening"
        return "stable"


class FocusMonitorSession(Iterator[FocusMeasurement]):
    """Focus measurements backed by one owned camera live-frame session."""

    def __init__(self, frames: LiveFrameSession, focus: FocusService) -> None:
        self._frames = frames
        self._focus = focus
        self._closed = False

    def __iter__(self) -> FocusMonitorSession:
        return self

    def __enter__(self) -> FocusMonitorSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __next__(self) -> FocusMeasurement:
        if self._closed:
            raise StopIteration
        try:
            image = next(self._frames)
        except StopIteration:
            self.close()
            raise
        return self._focus.measure_image(image)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._frames.close()


class FocusMonitor:
    """Backend-independent live focus orchestration over camera frame sessions."""

    def __init__(
        self,
        camera_backend: CameraBackend,
        focus_service: FocusService | None = None,
    ) -> None:
        self._camera = camera_backend
        self._focus = focus_service or FocusService()

    def open(
        self,
        *,
        exposure_s: float,
        gain: float | None = None,
        binning: int | None = None,
        roi: tuple[int, int, int, int] | None = None,
        frame_count: int | None = None,
    ) -> FocusMonitorSession:
        frames = self._camera.live_frames(
            exposure_s=exposure_s,
            gain=gain,
            binning=binning,
            roi=roi,
            frame_count=frame_count,
        )
        return FocusMonitorSession(frames, self._focus)
