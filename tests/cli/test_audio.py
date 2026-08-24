from __future__ import annotations

from array import array

import pytest

from astrolabe.cli.audio import (
    AudioSink,
    _backend_names,
    _render_cue_frames,
    _render_cue_pcm,
)
from astrolabe.cli.feedback import AudioCue
from astrolabe.errors import BackendError


class FakeDevice:
    def __init__(self) -> None:
        self.running = False
        self.stream = None
        self.start_calls = 0
        self.stop_calls = 0
        self.close_calls = 0

    def start(self, stream) -> None:
        self.stream = stream
        self.start_calls += 1
        self.running = True

    def request(self, frame_count: int) -> array[int]:
        assert self.stream is not None
        return self.stream.send(frame_count)

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False

    def close(self) -> None:
        self.close_calls += 1


def _pulse(
    frequency_hz: float = 440.0,
    *,
    interval_s: float = 0.25,
) -> AudioCue:
    return AudioCue(
        frequencies_hz=(frequency_hz,),
        pulse_duration_s=0.08,
        interval_s=interval_s,
    )


def _continuous(frequency_hz: float = 660.0) -> AudioCue:
    return AudioCue(
        frequencies_hz=(frequency_hz,),
        pulse_duration_s=0.08,
        interval_s=None,
        continuous=True,
    )


def test_rendered_pulse_repeats_at_requested_cadence() -> None:
    cue = AudioCue(
        frequencies_hz=(100.0,),
        pulse_duration_s=0.05,
        interval_s=0.2,
    )

    samples = _render_cue_pcm(cue, sample_rate_hz=1000, duration_s=0.5)

    assert any(samples[5:45])
    assert not any(samples[60:190])
    assert any(samples[205:245])
    assert not any(samples[260:390])
    assert any(samples[405:445])


def test_chunk_rendering_preserves_cadence_and_phase() -> None:
    cue = _pulse(137.0, interval_s=0.12)
    whole = _render_cue_frames(
        cue,
        sample_rate_hz=1000,
        start_frame=0,
        frame_count=500,
    )
    chunks = array("h")
    for start, count in ((0, 137), (137, 89), (226, 274)):
        chunks.extend(
            _render_cue_frames(
                cue,
                sample_rate_hz=1000,
                start_frame=start,
                frame_count=count,
            )
        )

    assert chunks == whole


def test_new_cue_supersedes_without_restarting_device() -> None:
    device = FakeDevice()
    sink = AudioSink(device)
    sink.play(_pulse(440.0))
    first = device.request(256)

    sink.play(_pulse(880.0))
    second = device.request(256)

    assert first != second
    assert device.start_calls == 1
    assert device.stop_calls == 0
    sink.close()


def test_none_silences_without_stopping_device() -> None:
    device = FakeDevice()
    sink = AudioSink(device)
    sink.play(_pulse())
    assert any(device.request(256))

    sink.play(None)

    assert not any(device.request(256))
    assert device.running
    sink.close()


def test_continuous_cue_remains_one_session_beyond_old_file_boundary() -> None:
    device = FakeDevice()
    sink = AudioSink(device)
    sink.play(_continuous())

    for _ in range(800):
        samples = device.request(256)
        assert len(samples) == 256

    assert device.start_calls == 1
    assert device.stop_calls == 0
    assert device.running
    sink.close()


def test_repeated_updates_do_not_restart_session() -> None:
    device = FakeDevice()
    sink = AudioSink(device)

    for index in range(20):
        sink.play(_pulse(440.0 + index, interval_s=0.2 + index * 0.01))
        device.request(64)

    assert device.start_calls == 1
    assert device.stop_calls == 0
    sink.close()


def test_close_stops_and_closes_device() -> None:
    device = FakeDevice()
    sink = AudioSink(device)
    sink.play(_pulse())

    sink.close()

    assert device.stop_calls == 1
    assert device.close_calls == 1
    assert not device.running


def test_unexpected_device_stop_is_reported() -> None:
    device = FakeDevice()
    sink = AudioSink(device)
    device.running = False

    with pytest.raises(BackendError, match="stopped unexpectedly"):
        sink.check()

    sink.close()


def test_startup_failure_closes_device() -> None:
    class FailingStartDevice(FakeDevice):
        def start(self, stream) -> None:
            raise RuntimeError("device disappeared")

    device = FailingStartDevice()

    with pytest.raises(BackendError, match="device disappeared"):
        AudioSink(device)

    assert device.close_calls == 1


def test_shutdown_failure_is_reported() -> None:
    class FailingStopDevice(FakeDevice):
        def stop(self) -> None:
            raise RuntimeError("cannot stop")

    sink = AudioSink(FailingStopDevice())

    with pytest.raises(BackendError, match="cannot stop"):
        sink.close()


def test_context_shutdown_failure_does_not_mask_active_exception() -> None:
    class FailingStopDevice(FakeDevice):
        def stop(self) -> None:
            raise RuntimeError("cannot stop")

    with pytest.raises(ValueError, match="primary") as caught:
        with AudioSink(FailingStopDevice()):
            raise ValueError("primary")

    notes = getattr(caught.value, "__notes__", [])
    assert any("Audio shutdown also failed" in note for note in notes)


def test_supported_platform_backends_are_explicit() -> None:
    assert _backend_names("darwin") == ("COREAUDIO",)
    assert _backend_names("linux") == ("PULSEAUDIO", "ALSA", "JACK")
    with pytest.raises(BackendError, match="unsupported"):
        _backend_names("win32")
