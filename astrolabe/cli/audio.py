"""Real non-blocking audio playback for CLI feedback cues."""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from array import array
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from astrolabe.cli.feedback import AudioCue
from astrolabe.errors import BackendError

_SAMPLE_RATE_HZ = 44_100
_PATTERN_DURATION_S = 4.0
_PROBE_DURATION_S = 0.02
_ATTACK_RELEASE_S = 0.005
_VOLUME = 0.12
_WORKER_POLL_S = 0.02
_PROCESS_STOP_TIMEOUT_S = 0.05


class PlaybackHandle(Protocol):
    """One active low-level playback operation."""

    def poll(self) -> int | None: ...

    def stop(self) -> None: ...


class TonePlayer(Protocol):
    """Small low-level boundary used by :class:`AudioSink`."""

    def probe(self) -> None: ...

    def start(self, cue: AudioCue) -> PlaybackHandle: ...

    def close(self) -> None: ...


class _ProcessHandle:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    def poll(self) -> int | None:
        return self._process.poll()

    def stop(self) -> None:
        if self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=_PROCESS_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self._process.kill()
            try:
                self._process.wait(timeout=_PROCESS_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                pass


class SystemTonePlayer:
    """Play generated WAV files with a small platform-native/system player."""

    def __init__(self, command: str) -> None:
        self._command = command
        self._tempdir = tempfile.TemporaryDirectory(prefix="astrolabe-audio-")
        self._directory = Path(self._tempdir.name)
        self._closed = False

    @classmethod
    def discover(
        cls,
        *,
        platform_name: str | None = None,
        which: Callable[[str], str | None] | None = None,
    ) -> SystemTonePlayer:
        platform_name = platform_name or sys.platform
        which = which or shutil.which
        command = _select_player_command(platform_name, which)
        return cls(command)

    def probe(self) -> None:
        self._ensure_open()
        path = self._directory / "probe.wav"
        _write_silence_wav(path, duration_s=_PROBE_DURATION_S)
        process = self._spawn(path, capture_stderr=True)
        try:
            _, stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired as exc:
            process.terminate()
            try:
                process.wait(timeout=_PROCESS_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                process.kill()
            raise BackendError("Audio playback probe did not complete") from exc
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise BackendError(
                f"Audio player failed to open the default output device{suffix}"
            )

    def start(self, cue: AudioCue) -> PlaybackHandle:
        self._ensure_open()
        path = self._directory / "cue.wav"
        _write_cue_wav(path, cue)
        return _ProcessHandle(self._spawn(path, capture_stderr=False))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._tempdir.cleanup()

    def _spawn(
        self, path: Path, *, capture_stderr: bool
    ) -> subprocess.Popen[bytes]:
        stderr = subprocess.PIPE if capture_stderr else subprocess.DEVNULL
        try:
            return subprocess.Popen(
                [self._command, str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
            )
        except OSError as exc:
            raise BackendError(
                f"Could not start audio player {self._command!r}: {exc}"
            ) from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise BackendError("Audio player is closed")


class AudioSink:
    """Single-worker non-blocking sink for backend-neutral :class:`AudioCue` values."""

    def __init__(self, player: TonePlayer | None = None) -> None:
        self._player = player or SystemTonePlayer.discover()
        try:
            self._player.probe()
        except Exception:
            self._player.close()
            raise
        self._condition = threading.Condition()
        self._cue: AudioCue | None = None
        self._revision = 0
        self._closed = False
        self._failure: BackendError | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="astrolabe-audio",
            daemon=True,
        )
        try:
            self._thread.start()
        except Exception:
            self._player.close()
            raise

    def play(self, cue: AudioCue | None) -> None:
        """Replace the active cue without blocking the caller on playback."""
        with self._condition:
            self._raise_if_failed_locked()
            if self._closed:
                raise BackendError("Audio sink is closed")
            if cue == self._cue:
                return
            self._cue = cue
            self._revision += 1
            self._condition.notify_all()

    def check(self) -> None:
        """Raise a contained runtime playback failure in the calling thread."""
        with self._condition:
            self._raise_if_failed_locked()

    def close(self) -> None:
        """Silence playback, stop the worker, and release player resources."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._cue = None
            self._revision += 1
            self._condition.notify_all()
        self._thread.join()

    def __enter__(self) -> AudioSink:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _run(self) -> None:
        active: PlaybackHandle | None = None
        active_revision = -1
        try:
            while True:
                with self._condition:
                    if self._closed:
                        break
                    cue = self._cue
                    revision = self._revision

                if active is not None and (cue is None or revision != active_revision):
                    active.stop()
                    active = None

                if cue is not None and active is None:
                    try:
                        active = self._player.start(cue)
                    except Exception as exc:  # playback failures stay at this boundary
                        self._record_failure(exc)
                        break
                    active_revision = revision

                with self._condition:
                    if self._closed:
                        break
                    if self._revision != active_revision and active is not None:
                        continue
                    self._condition.wait(
                        timeout=_WORKER_POLL_S if active is not None else None
                    )
                    if self._closed:
                        break
                    if active is not None and self._revision != active_revision:
                        continue

                if active is None:
                    continue
                returncode = active.poll()
                if returncode is None:
                    continue
                active = None
                if returncode != 0:
                    self._record_failure(
                        BackendError(
                            f"Audio player exited unexpectedly with status {returncode}"
                        )
                    )
                    break
        finally:
            if active is not None:
                active.stop()
            self._player.close()

    def _record_failure(self, exc: Exception) -> None:
        failure = (
            exc
            if isinstance(exc, BackendError)
            else BackendError(f"Audio playback failed: {exc}")
        )
        with self._condition:
            self._failure = failure
            self._cue = None
            self._revision += 1
            self._condition.notify_all()

    def _raise_if_failed_locked(self) -> None:
        if self._failure is not None:
            raise self._failure


def _select_player_command(
    platform_name: str, which: Callable[[str], str | None]
) -> str:
    if platform_name == "darwin":
        candidates = ("afplay",)
    elif platform_name.startswith("linux"):
        candidates = ("pw-play", "paplay", "aplay")
    else:
        raise BackendError(
            f"Audio playback is unsupported on platform {platform_name!r}; "
            "Linux and macOS are supported"
        )

    for candidate in candidates:
        command = which(candidate)
        if command is not None:
            return command
    names = ", ".join(candidates)
    raise BackendError(f"No supported audio player found; install one of: {names}")


def _write_silence_wav(path: Path, *, duration_s: float) -> None:
    frame_count = max(1, int(round(duration_s * _SAMPLE_RATE_HZ)))
    _write_pcm_wav(path, array("h", [0]) * frame_count)


def _write_cue_wav(path: Path, cue: AudioCue) -> None:
    _validate_cue(cue)
    samples = _render_cue_pcm(
        cue,
        sample_rate_hz=_SAMPLE_RATE_HZ,
        duration_s=_PATTERN_DURATION_S,
    )
    _write_pcm_wav(path, samples)


def _write_pcm_wav(path: Path, samples: array[int]) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(_SAMPLE_RATE_HZ)
        stream.writeframes(samples.tobytes())


def _render_cue_pcm(
    cue: AudioCue,
    *,
    sample_rate_hz: int,
    duration_s: float,
) -> array[int]:
    """Render one bounded repeating cue pattern as signed 16-bit mono PCM."""
    _validate_cue(cue)
    if sample_rate_hz <= 0 or duration_s <= 0.0:
        raise ValueError("sample rate and duration must be > 0")

    frame_count = max(1, int(round(duration_s * sample_rate_hz)))
    amplitude = int(round(32767.0 * _VOLUME))
    samples = array("h")
    for frame in range(frame_count):
        t = frame / sample_rate_hz
        if cue.continuous:
            value = _tone_value(
                t,
                cue.frequencies_hz[0],
                amplitude,
                duration_s,
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


def _tone_value(t: float, frequency_hz: float, amplitude: int, duration_s: float) -> int:
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
