from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Literal

import numpy as np

from astrolabe.camera.base import CameraBackend, LiveFrameSession
from astrolabe.services.focus import FocusMeasurement, FocusService

FocusTrend = Literal["improving", "stable", "worsening"]


class FocusGuidanceState(str, Enum):
    """Truthful no-look focus state inferred from HFR history only."""

    UNKNOWN = "unknown"
    IMPROVING = "improving"
    BEST_OBSERVED = "best-observed"
    WORSENING = "worsening"


@dataclass(frozen=True)
class FocusGuidance:
    """Focus-domain guidance without pretending to know focuser direction."""

    state: FocusGuidanceState
    valid: bool
    hfr_px: float | None
    best_hfr_px: float | None


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

    def reset(self) -> None:
        self._values.clear()

    def recent_min(self) -> float | None:
        """Return the lowest HFR in the active trend window."""

        return min(self._values) if self._values else None

    def update(self, measurement: FocusMeasurement) -> FocusTrend | None:
        """Return a display trend without altering the raw measurement."""

        if not measurement.valid or measurement.hfr_px is None:
            self.reset()
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


class FocusGuidanceEstimator:
    """Infer practical focus guidance from temporal HFR evidence only.

    Manual focusing provides no focuser position or physical direction. This
    estimator therefore never emits a signed correction. It reports whether
    image quality is improving or worsening in the user's current motion. A
    region is called ``BEST_OBSERVED`` only after a real improvement run has
    been followed by worsening across that run's candidate minimum, which
    brackets the best observed region, and the current HFR has then returned
    stably near that bracketed best.
    """

    def __init__(
        self,
        *,
        window_size: int = 5,
        relative_deadband: float = 0.03,
        absolute_deadband_px: float = 0.05,
        stale_after_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(stale_after_s) or stale_after_s <= 0.0:
            raise ValueError("stale_after_s must be finite and > 0")
        self._trend = FocusTrendEstimator(
            window_size=window_size,
            relative_deadband=relative_deadband,
            absolute_deadband_px=absolute_deadband_px,
        )
        self._relative_deadband = relative_deadband
        self._absolute_deadband_px = absolute_deadband_px
        self._stale_after_s = stale_after_s
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self._trend.reset()
        self._best_hfr_px: float | None = None
        self._improving_candidate_hfr_px: float | None = None
        self._bracketed_best_hfr_px: float | None = None
        self._last_update_s: float | None = None

    def update(self, measurement: FocusMeasurement) -> FocusGuidance:
        now_s = self._clock()
        if (
            self._last_update_s is not None
            and now_s - self._last_update_s > self._stale_after_s
        ):
            self.reset()

        if (
            not measurement.valid
            or measurement.hfr_px is None
            or not math.isfinite(measurement.hfr_px)
        ):
            self.reset()
            return FocusGuidance(
                state=FocusGuidanceState.UNKNOWN,
                valid=False,
                hfr_px=None,
                best_hfr_px=None,
            )

        hfr_px = measurement.hfr_px
        trend = self._trend.update(measurement)
        self._record_best(hfr_px)

        if trend == "improving":
            recent_min = self._trend.recent_min()
            assert recent_min is not None
            self._record_improving_candidate(recent_min)
            state = FocusGuidanceState.IMPROVING
        elif trend == "worsening":
            self._bracket_candidate_if_crossed(hfr_px)
            self._improving_candidate_hfr_px = None
            state = FocusGuidanceState.WORSENING
        elif trend == "stable":
            if self._improving_candidate_hfr_px is not None:
                self._record_improving_candidate(hfr_px)
            if self._is_at_bracketed_best(hfr_px):
                state = FocusGuidanceState.BEST_OBSERVED
            else:
                state = FocusGuidanceState.UNKNOWN
        else:
            state = FocusGuidanceState.UNKNOWN

        self._last_update_s = now_s
        return FocusGuidance(
            state=state,
            valid=True,
            hfr_px=hfr_px,
            best_hfr_px=self._best_hfr_px,
        )

    def _record_best(self, hfr_px: float) -> None:
        if self._best_hfr_px is None:
            self._best_hfr_px = hfr_px
            return

        previous_best = self._best_hfr_px
        if hfr_px < previous_best - self._deadband(previous_best):
            self._bracketed_best_hfr_px = None
        if hfr_px < previous_best:
            self._best_hfr_px = hfr_px

    def _record_improving_candidate(self, hfr_px: float) -> None:
        if (
            self._improving_candidate_hfr_px is None
            or hfr_px < self._improving_candidate_hfr_px
        ):
            self._improving_candidate_hfr_px = hfr_px

    def _bracket_candidate_if_crossed(self, hfr_px: float) -> None:
        candidate = self._improving_candidate_hfr_px
        if candidate is None or self._best_hfr_px is None:
            return
        if hfr_px <= candidate + self._deadband(candidate):
            return
        if candidate > self._best_hfr_px + self._deadband(self._best_hfr_px):
            return
        self._bracketed_best_hfr_px = candidate

    def _is_at_bracketed_best(self, hfr_px: float) -> bool:
        if self._best_hfr_px is None or self._bracketed_best_hfr_px is None:
            return False
        if hfr_px > self._best_hfr_px + self._deadband(self._best_hfr_px):
            return False
        return (
            abs(hfr_px - self._bracketed_best_hfr_px)
            <= self._deadband(self._bracketed_best_hfr_px)
        )

    def _deadband(self, hfr_px: float) -> float:
        return max(
            self._absolute_deadband_px,
            abs(hfr_px) * self._relative_deadband,
        )


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
            return self._focus.measure_image(image)
        except StopIteration:
            self.close()
            raise
        except BaseException:
            self.close()
            raise

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
