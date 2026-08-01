"""GH-271: Live Mode must not report a successful start before the recorder exists.

``LiveModeEngine.start()`` used to return ``True`` as soon as it had spawned the
transcription thread.  The recorder - and with it the model load - is built on
that thread, so a bad model name, a missing backend dependency or a CUDA OOM
reached the caller as a *successful* start and only surfaced later as an
out-of-band ``state: ERROR`` message.  ``start_engine`` also cleared its
``_model_displaced`` flag on that false success, leaving the main engine
detached for the whole session.

These tests drive the REAL asynchronous initialization.  The pre-existing tests
in ``test_p0_model_swap.py`` mock ``LiveModeEngine.start()`` itself to return
``False`` or raise synchronously - a shape the real implementation never
produced - so they never exercised this path.

Run:  ../../build/.venv/bin/pytest tests/test_gh271_live_start_synchronous.py -v
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from server.api.routes import live as live_mod
from server.core.live_engine import LiveModeConfig, LiveModeEngine, LiveModeState
from starlette.websockets import WebSocketState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Generous enough that a loaded CI machine never trips it, short enough that a
# genuine hang fails the test instead of stalling the whole suite.
_WAIT = 5.0


class _FakeRecorder:
    """Stand-in for ``AudioToTextRecorder`` whose ``text()`` blocks until shutdown.

    Mirrors the real contract the transcription loop depends on: ``text()``
    blocks until a sentence is available (here: until ``shutdown()`` releases
    it), and ``shutdown()`` is what unblocks it.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.shutdown_calls = 0
        self._released = threading.Event()

    def text(self) -> str:
        self._released.wait(timeout=_WAIT)
        return ""

    def feed_audio(self, chunk: bytes, sample_rate: int = 16000) -> None:
        return None

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self._released.set()


def _install_recorder_stub(monkeypatch: pytest.MonkeyPatch, factory: Any) -> None:
    """Make the loop's lazy ``AudioToTextRecorder`` import resolve to *factory*.

    ``_transcription_loop`` imports ``server.core.stt.engine`` lazily, so a stub
    module in ``sys.modules`` intercepts it without importing the real module
    (which pulls in torch and the whole STT backend stack).
    """
    module = types.ModuleType("server.core.stt.engine")
    module.AudioToTextRecorder = factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "server.core.stt.engine", module)


def _make_live_session(
    *,
    loop: asyncio.AbstractEventLoop,
    client_name: str = "test-client",
) -> live_mod.LiveModeSession:
    """Build a LiveModeSession with minimal stubs (bypass __init__)."""
    session = object.__new__(live_mod.LiveModeSession)
    session.websocket = MagicMock()
    session.websocket.client_state = WebSocketState.CONNECTED
    session.websocket.application_state = WebSocketState.CONNECTED
    session.websocket.send_json = AsyncMock()
    session.client_name = client_name
    session._engine = None
    session._message_queue = asyncio.Queue()
    session._running = False
    session._engine_started = False
    session._shared_backend = None
    session._loop = loop
    return session


def _mock_model_manager(
    *,
    main_model: str = "Systran/faster-whisper-base",
    is_same: bool = True,
    backend: object | None = None,
) -> MagicMock:
    """Create a mock ModelManager whose load params match LiveModeConfig defaults."""
    mm = MagicMock()
    mm.main_model_name = main_model
    mm.is_same_model = MagicMock(return_value=is_same)
    mm.get_transcription_load_params = MagicMock(
        return_value={
            "device": "cuda",
            "compute_type": "default",
            "gpu_device_index": 0,
            "batch_size": 16,
        }
    )
    mm.detach_transcription_backend = MagicMock(return_value=backend or MagicMock())
    mm.attach_transcription_backend = MagicMock()
    mm.unload_transcription_model = MagicMock()
    mm.load_transcription_model = MagicMock()
    return mm


def _messages(session: live_mod.LiveModeSession, msg_type: str) -> list[dict]:
    """Return the ``data`` payloads of every message of *msg_type* sent so far."""
    return [
        call.args[0]["data"]
        for call in session.websocket.send_json.call_args_list
        if call.args and call.args[0].get("type") == msg_type
    ]


# ═══════════════════════════════════════════════════════════════════════
# Engine level: start() reports the real initialization outcome
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.live_mode
class TestEngineStartReportsRealOutcome:
    def test_start_returns_false_when_recorder_construction_fails(self, monkeypatch):
        """A model that cannot load must make start() report failure, not success."""
        boom = RuntimeError("Unable to load model 'nope/nope'")

        def _factory(**kwargs):
            raise boom

        _install_recorder_stub(monkeypatch, _factory)
        engine = LiveModeEngine(config=LiveModeConfig(model="nope/nope"))

        assert engine.start() is False
        assert engine.start_error is boom
        assert engine.state is LiveModeState.ERROR
        assert engine.is_running is False

    def test_start_returns_true_once_the_recorder_is_listening(self, monkeypatch):
        """The success path still works and only returns after LISTENING."""
        recorders: list[_FakeRecorder] = []

        def _factory(**kwargs):
            recorder = _FakeRecorder(**kwargs)
            recorders.append(recorder)
            return recorder

        _install_recorder_stub(monkeypatch, _factory)
        engine = LiveModeEngine(config=LiveModeConfig(model="Systran/faster-whisper-base"))

        try:
            assert engine.start() is True
            assert engine.start_error is None
            assert engine.state is LiveModeState.LISTENING
            assert engine.is_running is True
            assert len(recorders) == 1
        finally:
            engine.stop()

    def test_error_state_is_published_before_start_returns(self, monkeypatch):
        """The ERROR state is settled before the caller is released (no race)."""
        states: list[LiveModeState] = []

        def _factory(**kwargs):
            raise RuntimeError("backend dependency missing")

        _install_recorder_stub(monkeypatch, _factory)
        engine = LiveModeEngine(on_state_change=states.append)

        assert engine.start() is False
        assert states[0] is LiveModeState.STARTING
        assert states[-1] is LiveModeState.ERROR

    def test_start_times_out_when_initialization_hangs(self, monkeypatch):
        """A hung load resolves to a definite failure instead of a false success."""
        release = threading.Event()

        def _factory(**kwargs):
            release.wait(timeout=_WAIT)
            return _FakeRecorder(**kwargs)

        _install_recorder_stub(monkeypatch, _factory)
        engine = LiveModeEngine()

        try:
            assert engine.start(timeout=0.2) is False
            assert isinstance(engine.start_error, TimeoutError)
        finally:
            release.set()
            engine.stop()

    def test_late_initialization_does_not_advertise_listening(self, monkeypatch):
        """A recorder that arrives after the timeout must not flip to LISTENING.

        Otherwise the client would start streaming audio into a session the
        caller has already given up on.
        """
        release = threading.Event()
        states: list[LiveModeState] = []

        def _factory(**kwargs):
            release.wait(timeout=_WAIT)
            return _FakeRecorder(**kwargs)

        _install_recorder_stub(monkeypatch, _factory)
        engine = LiveModeEngine(on_state_change=states.append)

        assert engine.start(timeout=0.2) is False
        release.set()
        if engine._loop_thread is not None:
            engine._loop_thread.join(timeout=_WAIT)

        assert LiveModeState.LISTENING not in states
        assert engine.is_running is False

    def test_failed_start_releases_the_audio_feeder_thread(self, monkeypatch):
        """A failed start must not leak the feeder daemon thread."""

        def _factory(**kwargs):
            raise RuntimeError("boom")

        _install_recorder_stub(monkeypatch, _factory)
        engine = LiveModeEngine()

        assert engine.start() is False

        feeder = engine._feeder_thread
        assert feeder is not None
        feeder.join(timeout=_WAIT)
        assert not feeder.is_alive(), "audio feeder thread outlived a failed start"


# ═══════════════════════════════════════════════════════════════════════
# Route level: start_engine() sees the real failure and restores the model
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.model_swap
class TestStartEngineSurfacesRealInitFailure:
    @pytest.fixture(autouse=True)
    def _patch_deps(self, monkeypatch):
        cfg = MagicMock()
        monkeypatch.setattr(live_mod, "get_config", lambda: cfg)
        monkeypatch.setattr(
            live_mod, "resolve_live_transcriber_model", lambda c: "Systran/faster-whisper-base"
        )
        monkeypatch.setattr(live_mod, "is_live_mode_model_supported", lambda m: True)

    async def test_shared_backend_is_returned_when_the_model_fails_to_load(self, monkeypatch):
        """Shared-backend path: a background load failure reattaches the backend."""

        def _factory(**kwargs):
            raise RuntimeError("CUDA failed with error out of memory")

        _install_recorder_stub(monkeypatch, _factory)
        shared_backend = MagicMock(name="shared-backend")
        mm = _mock_model_manager(is_same=True, backend=shared_backend)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        session = _make_live_session(loop=asyncio.get_running_loop())

        assert await session.start_engine() is False
        assert session._running is False
        mm.attach_transcription_backend.assert_called_once_with(shared_backend)

    async def test_error_message_carries_the_underlying_failure(self, monkeypatch):
        """The client is told WHY the start failed, on the start response path."""

        def _factory(**kwargs):
            raise RuntimeError("CUDA failed with error out of memory")

        _install_recorder_stub(monkeypatch, _factory)
        mm = _mock_model_manager(is_same=True, backend=MagicMock())
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        session = _make_live_session(loop=asyncio.get_running_loop())

        assert await session.start_engine() is False

        errors = [str(data.get("message", "")) for data in _messages(session, "error")]
        assert any("out of memory" in message for message in errors), errors

    async def test_main_model_is_reloaded_when_the_live_model_fails_to_load(self, monkeypatch):
        """Full-unload path: a background load failure reloads the main model."""

        def _factory(**kwargs):
            raise RuntimeError("Unable to load model")

        _install_recorder_stub(monkeypatch, _factory)
        mm = _mock_model_manager(is_same=False)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        session = _make_live_session(loop=asyncio.get_running_loop())

        assert await session.start_engine() is False
        mm.load_transcription_model.assert_called_once()

    async def test_state_messages_survive_a_slow_model_load(self, monkeypatch):
        """The message pump must outlive the start-up window.

        ``process_messages`` exits when it goes idle while ``_running`` is
        False - which is exactly the state the session is in for the whole
        duration of a model load.  If it exits there, every state message the
        engine queues (STARTING, LISTENING, and later sentences) is stranded
        and the client never learns Live Mode came up.
        """
        gate = threading.Event()

        def _factory(**kwargs):
            gate.wait(timeout=_WAIT)
            return _FakeRecorder(**kwargs)

        _install_recorder_stub(monkeypatch, _factory)
        mm = _mock_model_manager(is_same=True, backend=MagicMock())
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        session = _make_live_session(loop=asyncio.get_running_loop())
        pump = asyncio.create_task(session.process_messages())
        # Idle for longer than the pump's 0.1s poll timeout while the session
        # has not started yet - the window a slow model load lives in.
        await asyncio.sleep(0.3)

        gate.set()
        try:
            assert await session.start_engine() is True
            await asyncio.sleep(0.3)  # let the pump drain the queue

            states = [data.get("state") for data in _messages(session, "state")]
            assert "LISTENING" in states, f"state messages were stranded: {states}"
        finally:
            pump.cancel()
            await session.stop_engine()

    async def test_message_pump_still_exits_once_the_session_is_over(self, monkeypatch):
        """Guard the other half of the pump's exit condition.

        Widening it must not turn the pump into a task that never finishes on
        its own after the engine has stopped.
        """
        _install_recorder_stub(monkeypatch, lambda **kwargs: _FakeRecorder(**kwargs))
        mm = _mock_model_manager(is_same=True, backend=MagicMock())
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        session = _make_live_session(loop=asyncio.get_running_loop())
        pump = asyncio.create_task(session.process_messages())

        assert await session.start_engine() is True
        await session.stop_engine()

        await asyncio.wait_for(pump, timeout=_WAIT)

    async def test_successful_initialization_still_marks_the_session_running(self, monkeypatch):
        """Regression guard: the happy path is unchanged with a real engine."""
        _install_recorder_stub(monkeypatch, lambda **kwargs: _FakeRecorder(**kwargs))
        shared_backend = MagicMock(name="shared-backend")
        mm = _mock_model_manager(is_same=True, backend=shared_backend)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        session = _make_live_session(loop=asyncio.get_running_loop())

        assert await session.start_engine() is True
        assert session._running is True
        # The engine owns the backend for the duration of the session.
        mm.attach_transcription_backend.assert_not_called()

        await session.stop_engine()
        mm.attach_transcription_backend.assert_called_once_with(shared_backend)
