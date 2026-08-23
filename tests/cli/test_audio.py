import threading

import pytest

from astrolabe.cli.audio import (
    AudioSink,
    SystemTonePlayer,
    _render_cue_pcm,
    _select_player_command,
)
from astrolabe.cli.feedback import AudioCue
from astrolabe.errors import BackendError


class FakeHandle:
    def __init__(self, on_stop=None) -> None:
        self.returncode: int | None = None
        self.stopped = threading.Event()
        self._on_stop = on_stop

    def poll(self) -> int | None:
        return self.returncode

    def stop(self) -> None:
        if self.stopped.is_set():
            return
        self.stopped.set()
        if self._on_stop is not None:
            self._on_stop()


class FakePlayer:
    def __init__(self) -> None:
        self.probe_calls = 0
        self.started: list[tuple[AudioCue, FakeHandle]] = []
        self.closed = False
        self.active = 0
        self.max_active = 0
        self._condition = threading.Condition()

    def probe(self) -> None:
        self.probe_calls += 1

    def start(self, cue: AudioCue) -> FakeHandle:
        def stopped() -> None:
            with self._condition:
                self.active -= 1
                self._condition.notify_all()

        handle = FakeHandle(on_stop=stopped)
        with self._condition:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.append((cue, handle))
            self._condition.notify_all()
        return handle

    def close(self) -> None:
        with self._condition:
            self.closed = True
            self._condition.notify_all()

    def wait_for_starts(self, count: int) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: len(self.started) >= count,
                timeout=1.0,
            )


class FailingStartPlayer(FakePlayer):
    def __init__(self) -> None:
        super().__init__()
        self.start_attempted = threading.Event()

    def start(self, cue: AudioCue) -> FakeHandle:
        self.start_attempted.set()
        raise RuntimeError("device disappeared")


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


def test_new_cue_supersedes_active_cue() -> None:
    player = FakePlayer()
    sink = AudioSink(player)
    first = _pulse(440.0)
    second = _pulse(880.0)

    sink.play(first)
    assert player.wait_for_starts(1)
    first_handle = player.started[0][1]

    sink.play(second)
    assert first_handle.stopped.wait(timeout=1.0)
    assert player.wait_for_starts(2)
    assert player.started[1][0] == second

    sink.close()


def test_none_silences_active_cue() -> None:
    player = FakePlayer()
    sink = AudioSink(player)
    sink.play(_pulse())
    assert player.wait_for_starts(1)
    handle = player.started[0][1]

    sink.play(None)

    assert handle.stopped.wait(timeout=1.0)
    sink.close()


def test_continuous_cue_stays_on_one_active_playback() -> None:
    player = FakePlayer()
    sink = AudioSink(player)
    cue = _continuous()

    sink.play(cue)
    assert player.wait_for_starts(1)
    for _ in range(20):
        sink.play(cue)

    assert len(player.started) == 1
    assert player.max_active == 1
    sink.close()


def test_repeated_cue_updates_keep_one_worker_and_one_active_playback() -> None:
    player = FakePlayer()
    sink = AudioSink(player)
    worker = sink._thread

    for index in range(12):
        sink.play(_pulse(440.0 + index, interval_s=0.2 + index * 0.01))
        assert player.wait_for_starts(index + 1)

    assert sink._thread is worker
    assert player.max_active == 1
    sink.close()


def test_close_stops_playback_and_worker() -> None:
    player = FakePlayer()
    sink = AudioSink(player)
    sink.play(_pulse())
    assert player.wait_for_starts(1)
    handle = player.started[0][1]

    sink.close()

    assert handle.stopped.is_set()
    assert player.closed
    assert not sink._thread.is_alive()


def test_runtime_player_exception_is_contained_and_reported() -> None:
    player = FailingStartPlayer()
    sink = AudioSink(player)

    sink.play(_pulse())
    assert player.start_attempted.wait(timeout=1.0)
    with sink._condition:
        assert sink._condition.wait_for(lambda: sink._failure is not None, timeout=1.0)

    with pytest.raises(BackendError, match="device disappeared"):
        sink.check()
    sink.close()
    assert player.closed


def test_startup_probe_failure_closes_player() -> None:
    class FailingProbePlayer(FakePlayer):
        def probe(self) -> None:
            raise BackendError("no output device")

    player = FailingProbePlayer()

    with pytest.raises(BackendError, match="no output device"):
        AudioSink(player)

    assert player.closed


def test_platform_player_selection_prefers_native_current_stack() -> None:
    available = {
        "afplay": "/usr/bin/afplay",
        "pw-play": "/usr/bin/pw-play",
        "paplay": "/usr/bin/paplay",
        "aplay": "/usr/bin/aplay",
    }

    assert _select_player_command("darwin", available.get) == "/usr/bin/afplay"
    assert _select_player_command("linux", available.get) == "/usr/bin/pw-play"


def test_linux_player_selection_falls_back_without_pipewire_tool() -> None:
    available = {"paplay": "/usr/bin/paplay", "aplay": "/usr/bin/aplay"}

    assert _select_player_command("linux", available.get) == "/usr/bin/paplay"


def test_unsupported_or_missing_player_is_explicit() -> None:
    with pytest.raises(BackendError, match="unsupported"):
        _select_player_command("win32", lambda _name: None)
    with pytest.raises(BackendError, match="No supported audio player"):
        _select_player_command("linux", lambda _name: None)


def test_system_player_close_removes_temporary_audio_files() -> None:
    player = SystemTonePlayer("unused")
    directory = player._directory
    assert directory.exists()

    player.close()

    assert not directory.exists()
