"""Regression tests for the Live Mode retry/watchdog reliability layer.

Covers bugs found in code review of the retry-with-backoff + hang-watchdog
feature (PR #300):

1. The watchdog must not treat ordinary silence as a hang — only an
   in-flight recording (VAD-detected speech with no sentence since) that
   has run past ``watchdog_timeout_seconds`` counts.
2. ``_create_recorder()`` must reseed ``_last_sentence_time`` on every
   (re)build, not just the very first one, so a retry/watchdog rebuild
   doesn't inherit a stale timestamp and immediately restart again.
3. A completed transcription must win over a pending watchdog-restart flag
   instead of being discarded (CLAUDE.md: never silently discard a
   completed transcription).
4. A recorder-rebuild failure during retry must consume the retry budget
   with backoff instead of escaping to the outer handler and ending the
   session immediately.

Run:  ../../build/.venv/bin/pytest tests/test_live_engine_retry_watchdog.py -v
"""

from __future__ import annotations

import sys
import threading
import time
import types
from typing import Any

import pytest
from server.core.live_engine import LiveModeConfig, LiveModeEngine, LiveModeState

# Generous enough that a loaded CI machine never trips it, short enough that a
# genuine hang fails the test instead of stalling the whole suite.
_WAIT = 5.0


def _install_recorder_stub(monkeypatch: pytest.MonkeyPatch, factory: Any) -> None:
    """Make the loop's lazy ``AudioToTextRecorder`` import resolve to *factory*.

    Adapted from test_gh271_live_start_synchronous.py — the loop imports
    ``server.core.stt.engine`` lazily, so a stub module in ``sys.modules``
    intercepts it without pulling in torch and the whole STT backend stack.
    """
    module = types.ModuleType("server.core.stt.engine")
    module.AudioToTextRecorder = factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "server.core.stt.engine", module)


class _CollectingRecorder:
    def __init__(self, **kwargs: Any) -> None:
        self.fed: list[bytes] = []

    def feed_audio(self, chunk: bytes, sample_rate: int = 16000) -> None:
        self.fed.append(chunk)

    def shutdown(self) -> None:
        return None


class _ScriptedRecorder:
    """Stand-in for ``AudioToTextRecorder`` whose text() replays a script.

    Each entry in *script* is either a string (returned as the completed
    sentence) or an exception instance/class (raised). Once the script is
    exhausted, ``text()`` blocks until ``shutdown()`` releases it — mirroring
    the real recorder's behavior of blocking in ``wait_audio()`` during
    silence.
    """

    def __init__(self, script: list[Any], **kwargs: Any) -> None:
        self._script = list(script)
        self._index = 0
        self._released = threading.Event()
        self.shutdown_calls = 0

    def text(self) -> str:
        if self._index < len(self._script):
            item = self._script[self._index]
            self._index += 1
            if isinstance(item, BaseException) or (
                isinstance(item, type) and issubclass(item, BaseException)
            ):
                raise item
            return item
        self._released.wait(timeout=_WAIT)
        return ""

    def feed_audio(self, chunk: bytes, sample_rate: int = 16000) -> None:
        return None

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self._released.set()


# ═══════════════════════════════════════════════════════════════════════
# 1. Watchdog must not misfire on ordinary silence
# ═══════════════════════════════════════════════════════════════════════


class TestWatchdogDoesNotMisfireOnSilence:
    def test_no_restart_when_no_recording_ever_started(self):
        """Continuous audio with no speech must never look like a hang."""
        engine = LiveModeEngine(config=LiveModeConfig(watchdog_timeout_seconds=1.0))
        engine._last_sentence_time = 0.0
        engine._last_recording_start_time = None

        # Far past the timeout — would misfire under the old "audio recency"
        # heuristic, since the feeder stamps _last_audio_time on every chunk
        # regardless of whether the user has said anything.
        engine._watchdog_tick(now=1_000.0)

        assert engine._watchdog_restart_requested is False

    def test_no_restart_when_last_recording_already_resolved_into_a_sentence(self):
        """A recording that finished normally must not look stale forever."""
        engine = LiveModeEngine(config=LiveModeConfig(watchdog_timeout_seconds=1.0))
        engine._last_recording_start_time = 10.0
        engine._last_sentence_time = 20.0  # sentence completed AFTER the start

        engine._watchdog_tick(now=1_000.0)

        assert engine._watchdog_restart_requested is False

    def test_restart_requested_when_recording_stuck_past_timeout(self):
        """An in-flight recording stuck past the timeout IS a genuine hang.

        A live recorder has to be attached: the tick deliberately no-ops when
        ``_recorder`` is None, because that means a rebuild is already running
        and there is nothing to shut down.
        """
        engine = LiveModeEngine(config=LiveModeConfig(watchdog_timeout_seconds=1.0))
        recorder = _CollectingRecorder()
        engine._recorder = recorder
        engine._last_recording_start_time = 10.0
        engine._last_sentence_time = 5.0  # last sentence predates this recording

        engine._watchdog_tick(now=10.0 + 2.0)  # past the 1s timeout

        assert engine._watchdog_restart_requested is True

    def test_no_restart_before_timeout_elapses(self):
        engine = LiveModeEngine(config=LiveModeConfig(watchdog_timeout_seconds=90.0))
        engine._last_recording_start_time = 10.0
        engine._last_sentence_time = 5.0

        engine._watchdog_tick(now=10.0 + 30.0)  # well under the 90s timeout

        assert engine._watchdog_restart_requested is False


# ═══════════════════════════════════════════════════════════════════════
# 2. _create_recorder() reseeds _last_sentence_time on every (re)build
# ═══════════════════════════════════════════════════════════════════════


class TestCreateRecorderReseedsWatchdogBaseline:
    def test_reseeds_last_sentence_time_on_rebuild(self, monkeypatch):
        """A rebuild must not inherit the old recorder's stale timestamp.

        Otherwise the watchdog immediately sees a "stale" baseline on the
        brand-new recorder and restarts it again, repeating until
        max_consecutive_errors gives up (bug #2 from the PR #300 review).
        """
        _install_recorder_stub(monkeypatch, lambda **kw: _ScriptedRecorder([], **kw))
        engine = LiveModeEngine()

        # Mock the clock instead of anchoring to the real time.monotonic():
        # its epoch is arbitrary (often boot time), so a fixed offset like
        # "-10000" is only safe if the runner's uptime exceeds 10000s — false
        # on a freshly booted CI VM (this is what broke CI: a hardcoded
        # absolute value happened to work on a long-lived dev machine but not
        # on a short-uptime runner).
        fake_clock = {"t": 100.0}
        monkeypatch.setattr(time, "monotonic", lambda: fake_clock["t"])

        # Simulate a long-stale watchdog baseline from before the rebuild.
        engine._last_sentence_time = fake_clock["t"] - 10_000.0
        engine._last_recording_start_time = fake_clock["t"] - 5.0  # "in flight" and recent

        before = engine._last_sentence_time
        fake_clock["t"] += 1.0  # advance the clock to when the rebuild happens
        engine._create_recorder()

        assert engine._last_sentence_time is not None
        assert engine._last_sentence_time > before
        # The freshly-seeded baseline must clear the "in flight" condition.
        engine._watchdog_tick(now=engine._last_sentence_time + 5_000.0)
        assert engine._watchdog_restart_requested is False


# ═══════════════════════════════════════════════════════════════════════
# 3. A completed transcription beats a pending watchdog-restart flag
# ═══════════════════════════════════════════════════════════════════════


class _RaceRecorder:
    """Reproduces the exact race in bug #3: the watchdog fires (flag set,
    ``shutdown()`` called) at the same moment inference was already about to
    complete on its own. The first ``text()`` call blocks on a signal that is
    independent of ``shutdown()`` — modeling that natural completion and the
    watchdog's shutdown are two separate, racing events — and returns a real
    sentence once released, regardless of whether shutdown() already fired.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.shutdown_calls = 0
        self._call = 0
        self._first_call_result = threading.Event()
        self._shutdown_event = threading.Event()
        self.first_call_started = threading.Event()

    def text(self) -> str:
        self._call += 1
        if self._call == 1:
            self.first_call_started.set()
            self._first_call_result.wait(timeout=_WAIT)
            return "Hello world."
        self._shutdown_event.wait(timeout=_WAIT)
        return ""

    def feed_audio(self, chunk: bytes, sample_rate: int = 16000) -> None:
        return None

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self._shutdown_event.set()


class TestCompletedTranscriptionNotDiscarded:
    def test_sentence_processed_even_when_watchdog_flag_is_set(self, monkeypatch):
        """text() winning the race against the watchdog must not be thrown away."""
        recorders: list[_RaceRecorder] = []

        def _factory(**kwargs):
            recorder = _RaceRecorder(**kwargs)
            recorders.append(recorder)
            return recorder

        _install_recorder_stub(monkeypatch, _factory)
        sentences: list[str] = []
        engine = LiveModeEngine(
            config=LiveModeConfig(watchdog_timeout_seconds=90.0),
            on_sentence=sentences.append,
        )

        try:
            assert engine.start() is True
            recorder = recorders[0]
            assert recorder.first_call_started.wait(timeout=_WAIT), (
                "transcription loop never reached the first text() call"
            )

            # Simulate the watchdog firing while text() is in flight: it sets
            # the flag and calls shutdown() — same order as _watchdog_tick.
            engine._watchdog_restart_requested = True
            recorder.shutdown()

            # ...but the underlying inference had already progressed far
            # enough to complete on its own with a real result.
            recorder._first_call_result.set()

            for _ in range(50):
                if sentences:
                    break
                threading.Event().wait(0.1)

            assert sentences == ["Hello world."], (
                "a completed transcription was silently discarded in favor of "
                "the watchdog's synthetic error"
            )
            assert engine._watchdog_restart_requested is False
        finally:
            engine.stop()


# ═══════════════════════════════════════════════════════════════════════
# 4. A recorder-rebuild failure during retry consumes the retry budget
# ═══════════════════════════════════════════════════════════════════════


class TestRebuildFailureConsumesRetryBudget:
    def test_rebuild_failures_are_retried_with_backoff_not_fatal_immediately(self, monkeypatch):
        """A model-load failure on rebuild must not crash straight to ERROR.

        Before the fix, ``_create_recorder()`` was called from inside the
        ``except`` clause, so an exception it raised propagated past that
        handler entirely and ended the session on the very first rebuild
        failure without consuming the configured retry budget.
        """
        attempts = {"count": 0}

        def _factory(**kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                # Initial build succeeds, but immediately errors out of text().
                return _ScriptedRecorder([RuntimeError("first failure")], **kwargs)
            if attempts["count"] < 4:
                # Every rebuild attempt fails until the 4th.
                raise RuntimeError("transient CUDA allocation failure")
            return _ScriptedRecorder([], **kwargs)

        _install_recorder_stub(monkeypatch, _factory)
        engine = LiveModeEngine(
            config=LiveModeConfig(
                max_consecutive_errors=10,
                retry_backoff_base_seconds=0.01,
                retry_backoff_max_seconds=0.05,
            )
        )

        try:
            assert engine.start() is True

            for _ in range(100):
                if attempts["count"] >= 4:
                    break
                threading.Event().wait(0.05)

            assert attempts["count"] >= 4, "rebuild retries stopped short of succeeding"
            assert engine.state is not LiveModeState.ERROR, (
                "a rebuild failure escaped the retry handler and ended the session"
            )
        finally:
            engine.stop()

    def test_gives_up_after_max_consecutive_errors_of_rebuild_failures(self, monkeypatch):
        """The retry budget is still finite — persistent rebuild failure gives up."""

        def _factory(**kwargs):
            raise RuntimeError("persistent CUDA failure")

        # First build must succeed so the loop reaches LISTENING, then every
        # rebuild inside the retry loop fails.
        first = {"done": False}

        def _factory_with_initial_success(**kwargs):
            if not first["done"]:
                first["done"] = True
                return _ScriptedRecorder([RuntimeError("boom")], **kwargs)
            return _factory(**kwargs)

        _install_recorder_stub(monkeypatch, _factory_with_initial_success)
        engine = LiveModeEngine(
            config=LiveModeConfig(
                max_consecutive_errors=3,
                retry_backoff_base_seconds=0.01,
                retry_backoff_max_seconds=0.02,
            )
        )

        assert engine.start() is True
        if engine._loop_thread is not None:
            engine._loop_thread.join(timeout=_WAIT)

        assert engine.state is LiveModeState.ERROR


# ═══════════════════════════════════════════════════════════════════════
# 5. A watchdog restart must rebuild even when a sentence won the race
# ═══════════════════════════════════════════════════════════════════════


class TestWatchdogRestartAlwaysRebuilds:
    def test_rebuild_happens_even_when_a_sentence_won_the_race(self, monkeypatch):
        """Salvaging the sentence must not cancel the rebuild.

        The watchdog calls ``shutdown()`` before the loop ever looks at the
        flag, so the recorder is dead whether or not a result was salvaged
        from it: every later ``text()`` returns "" immediately. Clearing the
        flag without rebuilding left the loop spinning on that dead recorder
        forever, wedged in LISTENING, with no error and no sentences.
        """
        recorders: list[_RaceRecorder] = []

        def _factory(**kwargs):
            recorder = _RaceRecorder(**kwargs)
            recorders.append(recorder)
            return recorder

        _install_recorder_stub(monkeypatch, _factory)
        sentences: list[str] = []
        engine = LiveModeEngine(
            config=LiveModeConfig(
                watchdog_timeout_seconds=90.0,
                retry_backoff_base_seconds=0.05,
                retry_backoff_max_seconds=0.05,
            ),
            on_sentence=sentences.append,
        )

        try:
            assert engine.start() is True
            recorder = recorders[0]
            assert recorder.first_call_started.wait(timeout=_WAIT)

            # Watchdog fires while inference is in flight, then inference
            # completes on its own with a real sentence.
            engine._watchdog_restart_requested = True
            recorder.shutdown()
            recorder._first_call_result.set()

            deadline = time.monotonic() + _WAIT
            while time.monotonic() < deadline and len(recorders) < 2:
                threading.Event().wait(0.05)

            assert sentences == ["Hello world."], "the salvaged sentence was lost"
            assert len(recorders) >= 2, (
                "the recorder the watchdog shut down was never rebuilt - the "
                "loop is spinning on a dead recorder"
            )
        finally:
            engine.stop()


# ═══════════════════════════════════════════════════════════════════════
# 6. An empty transcription must not latch the watchdog
# ═══════════════════════════════════════════════════════════════════════


class _EmptyResultRecorder:
    """First ``text()`` reports a VAD start and then resolves to empty text.

    Models an ordinary VAD false positive (a cough, a door, background
    chatter): speech onset is detected, but the backend finds no segments and
    the utterance transcribes to "".
    """

    def __init__(self, **kwargs: Any) -> None:
        self._on_recording_start = kwargs.get("on_recording_start")
        self._call = 0
        self._shutdown_event = threading.Event()
        self.first_result_done = threading.Event()

    def text(self) -> str:
        self._call += 1
        if self._call == 1:
            if self._on_recording_start:
                self._on_recording_start()
            self.first_result_done.set()
            return ""
        self._shutdown_event.wait(timeout=_WAIT)
        return ""

    def feed_audio(self, chunk: bytes, sample_rate: int = 16000) -> None:
        return None

    def shutdown(self) -> None:
        self._shutdown_event.set()


class TestEmptyTranscriptionDoesNotLatchWatchdog:
    def test_empty_result_clears_the_in_flight_marker(self, monkeypatch):
        """A VAD trigger resolving to "" must not look like a hang forever.

        ``_last_sentence_time`` only advances on a real sentence, so without
        clearing the in-flight marker an empty result leaves
        ``last_start > last_sentence`` true permanently, and the next ordinary
        silence past the timeout tears down a healthy recorder.
        """
        _install_recorder_stub(monkeypatch, _EmptyResultRecorder)
        engine = LiveModeEngine(config=LiveModeConfig(watchdog_timeout_seconds=1.0))

        try:
            assert engine.start() is True
            recorder = engine._recorder
            assert recorder.first_result_done.wait(timeout=_WAIT)

            deadline = time.monotonic() + _WAIT
            while time.monotonic() < deadline and engine._last_recording_start_time is not None:
                threading.Event().wait(0.05)

            assert engine._last_recording_start_time is None, (
                "an empty transcription left the recording marker latched"
            )

            # With the marker cleared, a tick far past the timeout is a no-op.
            engine._watchdog_tick(time.monotonic() + 10_000.0)
            assert engine._watchdog_restart_requested is False
        finally:
            engine.stop()


class TestWatchdogDoesNotArmDuringRebuild:
    def test_tick_is_a_noop_while_the_recorder_is_being_rebuilt(self):
        """``_create_recorder()`` leaves ``_recorder`` None for the whole model
        load. Arming there would fire the flag against nothing and make the
        fresh recorder's first empty ``text()`` raise a spurious restart."""
        engine = LiveModeEngine(config=LiveModeConfig(watchdog_timeout_seconds=1.0))
        engine._recorder = None
        engine._last_sentence_time = 5.0
        engine._last_recording_start_time = 10.0

        engine._watchdog_tick(10_000.0)

        assert engine._watchdog_restart_requested is False


# ═══════════════════════════════════════════════════════════════════════
# 7. Audio arriving during a rebuild is buffered, not dropped
# ═══════════════════════════════════════════════════════════════════════


class TestAudioBufferedDuringRebuild:
    def test_chunks_during_starting_are_held_and_flushed(self):
        """Audio produced while the recorder is rebuilt must survive.

        Dropping it silently is the data-loss failure CLAUDE.md forbids: the
        user is still speaking, and nothing tells them the words are gone.
        """
        engine = LiveModeEngine(config=LiveModeConfig())
        engine._state = LiveModeState.STARTING
        engine._recorder = None

        feeder = threading.Thread(target=engine._audio_feeder_loop, daemon=True)
        feeder.start()
        try:
            engine._audio_queue.put(b"\x01\x02")
            engine._audio_queue.put(b"\x03\x04")
            threading.Event().wait(0.3)

            recorder = _CollectingRecorder()
            engine._recorder = recorder
            engine._state = LiveModeState.LISTENING

            deadline = time.monotonic() + _WAIT
            while time.monotonic() < deadline and len(recorder.fed) < 2:
                engine._audio_queue.put(b"\x05\x06")
                threading.Event().wait(0.05)

            assert recorder.fed[:2] == [b"\x01\x02", b"\x03\x04"], (
                "audio buffered during the rebuild was dropped instead of "
                f"being flushed in order (got {recorder.fed[:2]!r})"
            )
        finally:
            engine._stop_event.set()
            feeder.join(timeout=2.0)

    def test_engine_admits_audio_while_starting(self):
        """The WebSocket route gates on is_accepting_audio, which must stay
        open during STARTING so the feeder can buffer instead of the route
        discarding the frame before it is ever queued."""
        engine = LiveModeEngine(config=LiveModeConfig())

        engine._state = LiveModeState.STARTING
        assert engine.is_accepting_audio is True
        assert engine.is_running is False

        engine._state = LiveModeState.STOPPED
        assert engine.is_accepting_audio is False
