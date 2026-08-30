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
        """An in-flight recording stuck past the timeout IS a genuine hang."""
        engine = LiveModeEngine(config=LiveModeConfig(watchdog_timeout_seconds=1.0))
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

        # Simulate a long-stale watchdog baseline from before the rebuild.
        engine._last_sentence_time = 0.0
        engine._last_recording_start_time = 5_000.0  # "in flight" and ancient

        before = engine._last_sentence_time
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
