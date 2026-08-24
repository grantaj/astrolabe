"""Real non-blocking audio playback for CLI feedback cues."""

from __future__ import annotations

import math
import sys
import threading
from array import array
from collections.abc import Generator
from typing import Protocol

from astrolabe.cli.feedback import AudioCue
from astrolabe.errors import BackendError

_SAMPLE_RATE_HZ = 44_100
_BUFFER_SIZE_MS = 20
_ATTACK_RELEASE_S = 0.005
_VOLUME = 0.12


class _PlaybackDevice(Protocol):
    """Narrow streaming-device boundary used by :class:`AudioSink`."""

    @property
    def running(self) -> bool: ...

    def start(self, stream: Generator[array[int], int, None]) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class _MiniaudioPlaybackDevice:
    """One persistent miniaudio playback device."""

    def __init__(self, *, platform_name: str | None = None) -> None:
        platform_name = platform_name or sys.platform
        backend_names = _backend_names(platform_name)
        try:
            import miniaudio

            backends = [getattr(miniaudio.Backend, name) for name in backend_names]
            self._device = miniaudio.PlaybackDevice(
                output_format=miniaudio.SampleFormat.SIGNED16,
                nchannels=1,
                sample_rate=_SAMPLE_RATE_HZ,
                buffersize_msec=_BUFFER_SIZE_MS,
                backends=backends,
                app_name="Astrolabe",
            )
        except Exception as exc:
            raise BackendError(f"Could not open the default audio output: {exc}") from exc

    @property
    def running(self) -> bool:
        return bool(self._device.running)

    def start(self, stream: Generator[array[int], int, None]) -> None:
        try:
            self._device.start(stream)
        except Exception as exc:
            raise BackendError(f"Could not start audio playback: {exc}") from exc

    def stop(self) -> None:
        try:
            self._device.stop()
        except Exception as exc:
            raise BackendError(f"Could not stop audio playback: {exc}") from exc

    def close(self) -> None:
        self._device.close()


class AudioSink:
    """One-session non-blocking sink for backend-neutral :class:`AudioCue` values."""

    def __init__(self, device: _PlaybackDevice | None = None) -> None:
        self._lock = threading.Lock()
        self._cue: AudioCue | None = None
        self._revision = 0
        self._closed = False
        self._failure: BackendError | None = None
        self._device = device or _MiniaudioPlaybackDevice()
        self._stream = self._sample_stream()
        next(self._stream)
        try:
            self._device.start(self._stream)
        except Exception as exc:
            failure = _as_backend_error("Audio playback startup failed", exc)
            try:
                self._device.close()
            except Exception as close_exc:
                failure.add_note(f"Audio device cleanup also failed: {close_exc}")
            raise failure from exc

    def play(self, cue: AudioCue | None) -> None:
        """Replace the active cue without blocking the caller on playback."""
        if cue is not None:
            _validate_cue(cue)
        with self._lock:
            if self._closed:
                raise BackendError("Audio sink is closed")
            self._raise_if_failed_locked()
            self._check_running_locked()
            if cue == self._cue:
                return
            self._cue = cue
            self._revision += 1

    def check(self) -> None:
        """Raise a contained runtime playback failure in the calling thread."""
        with self._lock:
            self._raise_if_failed_locked()
            if not self._closed:
                self._check_running_locked()

    def close(self) -> None:
        """Silence playback and release the one persistent audio session."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cue = None
            self._revision += 1

        failure: BackendError | None = None
        try:
            self._device.stop()
        except Exception as exc:
            failure = _as_backend_error("Audio playback shutdown failed", exc)
        try:
            self._device.close()
        except Exception as exc:
            close_failure = _as_backend_error("Audio device cleanup failed", exc)
            if failure is None:
                failure = close_failure
            else:
                failure.add_note(str(close_failure))
        if failure is not None:
            with self._lock:
                if self._failure is None:
                    self._failure = failure
            raise failure

    def __enter__(self) -> AudioSink:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.close()
        except BackendError as close_exc:
            if exc is None:
                raise
            exc.add_note(f"Audio shutdown also failed: {close_exc}")

    def _sample_stream(self) -> Generator[array[int], int, None]:
        required_frames = yield array("h")
        active_revision = -1
        frame_index = 0
        while True:
            with self._lock:
                if self._closed:
                    return
                cue = self._cue
                revision = self._revision
            if revision != active_revision:
                active_revision = revision
                frame_index = 0
            if cue is None:
                samples = array("h", [0]) * required_frames
            else:
                samples = _render_cue_frames(
                    cue,
                    sample_rate_hz=_SAMPLE_RATE_HZ,
                    start_frame=frame_index,
                    frame_count=required_frames,
                )
                frame_index += required_frames
            required_frames = yield samples

    def _check_running_locked(self) -> None:
        if not self._device.running:
            failure = BackendError("Audio playback stopped unexpectedly")
            self._failure = failure
            self._cue = None
            self._revision += 1
            raise failure

    def _raise_if_failed_locked(self) -> None:
        if self._failure is not None:
            raise self._failure


def _backend_names(platform_name: str) -> tuple[str, ...]:
    if platform_name == "darwin":
        return ("COREAUDIO",)
    if platform_name.startswith("linux"):
        return ("PULSEAUDIO", "ALSA", "JACK")
    raise BackendError(
        f"Audio playback is unsupported on platform {platform_name!r}; "
        "Linux and macOS are supported"
    )


def _as_backend_error(prefix: str, exc: Exception) -> BackendError:
    if isinstance(exc, BackendError):
        return exc
    return BackendError(f"{prefix}: {exc}")


def _render_cue_pcm(
    cue: AudioCue,
    *,
    sample_rate_hz: int,
    duration_s: float,
) -> array[int]:
    """Render a bounded cue segment for deterministic tests."""
    _validate_cue(cue)
    if sample_rate_hz <= 0 or duration_s <= 0.0:
        raise ValueError("sample rate and duration must be > 0")
    frame_count = max(1, int(round(duration_s * sample_rate_hz)))
    return _render_cue_frames(
        cue,
        sample_rate_hz=sample_rate_hz,
        start_frame=0,
        frame_count=frame_count,
    )


def _render_cue_frames(
    cue: AudioCue,
    *,
    sample_rate_hz: int,
    start_frame: int,
    frame_count: int,
) -> array[int]:
    """Render one chunk while preserving phase/cadence across callback boundaries."""
    _validate_cue(cue)
    if sample_rate_hz <= 0:
        raise ValueError("sample rate must be > 0")
    if start_frame < 0 or frame_count < 0:
        raise ValueError("start_frame and frame_count must be >= 0")

    amplitude = int(round(32767.0 * _VOLUME))
    samples = array("h")
    for frame in range(start_frame, start_frame + frame_count):
        t = frame / sample_rate_hz
        if cue.continuous:
            ramp = min(1.0, t / _ATTACK_RELEASE_S)
            value = int(
                round(
                    amplitude
                    * ramp
                    * math.sin(math.tau * cue.frequencies_hz[0] * t)
                )
            )
        else:
            assert cue.interval_s is not None
            pulse_t = t % cue.interval_s
            value = _pulse_value(cue, pulse_t, amplitude)
        samples.append(value)
    return samples


def _pulse_value(cue: AudioCue, pulse_t: float, amplitude: int) -> int:
    if pulse_t >= cue.pulse_duration_s:
        return 0
    segment_s = cue.pulse_duration_s / len(cue.frequencies_hz)
    segment = min(int(pulse_t / segment_s), len(cue.frequencies_hz) - 1)
    local_t = pulse_t - segment * segment_s
    return _tone_value(local_t, cue.frequencies_hz[segment], amplitude, segment_s)


def _tone_value(
    t: float, frequency_hz: float, amplitude: int, duration_s: float
) -> int:
    ramp = min(
        1.0,
        t / _ATTACK_RELEASE_S,
        max(0.0, duration_s - t) / _ATTACK_RELEASE_S,
    )
    return int(round(amplitude * ramp * math.sin(math.tau * frequency_hz * t)))


def _validate_cue(cue: AudioCue) -> None:
    if not cue.frequencies_hz:
        raise ValueError("audio cue requires at least one frequency")
    if any(
        not math.isfinite(frequency) or frequency <= 0.0
        for frequency in cue.frequencies_hz
    ):
        raise ValueError("audio cue frequencies must be finite and > 0")
    if not math.isfinite(cue.pulse_duration_s) or cue.pulse_duration_s <= 0.0:
        raise ValueError("audio cue pulse duration must be finite and > 0")
    if cue.continuous:
        if cue.interval_s is not None:
            raise ValueError("continuous audio cue must not specify an interval")
        return
    if cue.interval_s is None:
        raise ValueError("pulsed audio cue requires an interval")
    if not math.isfinite(cue.interval_s) or cue.interval_s <= 0.0:
        raise ValueError("audio cue interval must be finite and > 0")
