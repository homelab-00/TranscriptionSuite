"""P0 model swap tests — Live Mode start_engine recovery guarantees.

Covers P0-SWAP-001 through P0-SWAP-003 from the QA test-design document.
These test the R-003 finally-block that guarantees main-model restoration.

Run:  ../../build/.venv/bin/pytest tests/test_p0_model_swap.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from server.api.routes import live as live_mod
from starlette.websockets import WebSocketState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_live_session(
    *,
    loop: asyncio.AbstractEventLoop,
    client_name: str = "test-client",
) -> live_mod.LiveModeSession:
    """Build a LiveModeSession with minimal stubs (bypass __init__)."""
    session = object.__new__(live_mod.LiveModeSession)
    session.websocket = MagicMock()
    session.websocket.client_state = WebSocketState.CONNECTED
    session.websocket.send_json = AsyncMock()
    session.client_name = client_name
    session._engine = None
    session._message_queue = asyncio.Queue()
    session._running = False
    session._shared_backend = None
    session._loop = loop
    return session


def _mock_model_manager(
    *,
    main_model: str = "Systran/faster-whisper-base",
    is_same: bool = True,
    backend: object | None = None,
) -> MagicMock:
    """Create a mock ModelManager with configurable behavior."""
    mm = MagicMock()
    mm.main_model_name = main_model
    mm.is_same_model = MagicMock(return_value=is_same)
    # Must match LiveModeConfig defaults exactly for can_share to be True
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


# ═══════════════════════════════════════════════════════════════════════
# P0-SWAP-001: Disconnect during model swap — main model restored
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.model_swap
class TestSwap001DisconnectDuringSwap:
    """P0-SWAP-001: CancelledError during model swap → main model restored."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self, monkeypatch):
        cfg = MagicMock()
        monkeypatch.setattr(live_mod, "get_config", lambda: cfg)
        monkeypatch.setattr(
            live_mod, "resolve_live_transcriber_model", lambda c: "Systran/faster-whisper-base"
        )
        monkeypatch.setattr(live_mod, "is_live_mode_model_supported", lambda m: True)

    async def test_cancel_during_shared_backend_restores_via_reattach(self, monkeypatch):
        """When backend was shared (detached) and cancel fires, backend is reattached."""
        shared_backend = MagicMock(name="shared-backend")
        mm = _mock_model_manager(is_same=True, backend=shared_backend)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        # Make LiveModeEngine constructor raise CancelledError to simulate disconnect
        def _raise_cancelled(*a, **kw):
            raise asyncio.CancelledError()

        monkeypatch.setattr(live_mod, "LiveModeEngine", _raise_cancelled)

        loop = asyncio.get_running_loop()
        session = _make_live_session(loop=loop)

        # CancelledError is BaseException — bypasses except Exception, runs finally,
        # then propagates.  The finally block restores the model before propagating.
        with pytest.raises(asyncio.CancelledError):
            await session.start_engine()

        # Backend should be reattached to the main engine (done in finally)
        mm.attach_transcription_backend.assert_called_once_with(shared_backend)

    async def test_cancel_during_full_unload_reloads_main(self, monkeypatch):
        """When model was fully unloaded and cancel fires, main model is reloaded."""
        mm = _mock_model_manager(is_same=False)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        def _raise_cancelled(*a, **kw):
            raise asyncio.CancelledError()

        monkeypatch.setattr(live_mod, "LiveModeEngine", _raise_cancelled)

        loop = asyncio.get_running_loop()
        session = _make_live_session(loop=loop)

        with pytest.raises(asyncio.CancelledError):
            await session.start_engine()

        # Main model should be reloaded since it was fully unloaded
        mm.load_transcription_model.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# P0-SWAP-002: start_engine() failure — backend returned to main engine
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.model_swap
class TestSwap002EngineStartFailure:
    """P0-SWAP-002: Engine init/start failure → main model restored."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self, monkeypatch):
        cfg = MagicMock()
        monkeypatch.setattr(live_mod, "get_config", lambda: cfg)
        monkeypatch.setattr(
            live_mod, "resolve_live_transcriber_model", lambda c: "Systran/faster-whisper-base"
        )
        monkeypatch.setattr(live_mod, "is_live_mode_model_supported", lambda m: True)

    async def test_engine_start_returns_false_restores_shared_backend(self, monkeypatch):
        """When engine.start() returns False, shared backend is restored."""
        shared_backend = MagicMock(name="shared-backend")
        mm = _mock_model_manager(is_same=True, backend=shared_backend)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        # Engine that always fails to start
        mock_engine = MagicMock()
        mock_engine.start.return_value = False
        mock_engine.is_running = False
        monkeypatch.setattr(
            live_mod,
            "LiveModeEngine",
            lambda **kw: mock_engine,
        )

        loop = asyncio.get_running_loop()
        session = _make_live_session(loop=loop)

        result = await session.start_engine()

        assert result is False
        # Backend reattached because _model_displaced was True when start failed
        mm.attach_transcription_backend.assert_called_once_with(shared_backend)

    async def test_engine_constructor_exception_restores_main(self, monkeypatch):
        """When LiveModeEngine constructor raises, main model is restored."""
        mm = _mock_model_manager(is_same=False)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        def _raise_error(*a, **kw):
            raise RuntimeError("Engine init failed")

        monkeypatch.setattr(live_mod, "LiveModeEngine", _raise_error)

        loop = asyncio.get_running_loop()
        session = _make_live_session(loop=loop)

        result = await session.start_engine()

        assert result is False
        mm.load_transcription_model.assert_called_once()

    async def test_engine_start_false_stops_engine_before_restore(self, monkeypatch):
        """When start() returns False, engine.stop() is called before restore."""
        shared_backend = MagicMock()
        mm = _mock_model_manager(is_same=True, backend=shared_backend)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        call_order = []
        mock_engine = MagicMock()
        mock_engine.start.return_value = False
        mock_engine.is_running = False
        mock_engine.stop.side_effect = lambda: call_order.append("stop")
        mm.attach_transcription_backend.side_effect = lambda b: call_order.append("attach")
        monkeypatch.setattr(
            live_mod,
            "LiveModeEngine",
            lambda **kw: mock_engine,
        )

        loop = asyncio.get_running_loop()
        session = _make_live_session(loop=loop)

        await session.start_engine()

        # Engine stopped before backend restore
        assert call_order == ["stop", "attach"]


# ═══════════════════════════════════════════════════════════════════════
# P0-SWAP-003: Rapid live start/stop — no backend leak, no stuck state
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.model_swap
class TestSwap003RapidStartStop:
    """P0-SWAP-003: Rapid start/stop cycles leave model_manager healthy."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self, monkeypatch):
        cfg = MagicMock()
        monkeypatch.setattr(live_mod, "get_config", lambda: cfg)
        monkeypatch.setattr(
            live_mod, "resolve_live_transcriber_model", lambda c: "Systran/faster-whisper-base"
        )
        monkeypatch.setattr(live_mod, "is_live_mode_model_supported", lambda m: True)

    async def test_five_start_stop_cycles_shared_backend(self, monkeypatch):
        """5 rapid start/stop cycles with shared backend: no leak, model healthy."""
        shared_backend = MagicMock(name="shared-backend")
        mm = _mock_model_manager(is_same=True, backend=shared_backend)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        mock_engine = MagicMock()
        mock_engine.start.return_value = True
        mock_engine.is_running = False
        mock_engine.sentence_history = []
        monkeypatch.setattr(
            live_mod,
            "LiveModeEngine",
            lambda **kw: mock_engine,
        )

        loop = asyncio.get_running_loop()

        for cycle in range(5):
            session = _make_live_session(loop=loop)

            result = await session.start_engine()
            assert result is True, f"start_engine failed on cycle {cycle}"

            await session.stop_engine()
            assert session._engine is None, f"engine not cleaned up on cycle {cycle}"
            assert not session._running, f"session still running on cycle {cycle}"

        # After 5 cycles: 5 detach + 5 reattach (stop_engine calls _restore_or_reload)
        assert mm.detach_transcription_backend.call_count == 5
        # reattach happens in stop_engine→_restore_or_reload_main_model
        assert mm.attach_transcription_backend.call_count == 5

    async def test_five_start_stop_cycles_full_unload(self, monkeypatch):
        """5 rapid start/stop cycles with full unload: model reloaded each time."""
        mm = _mock_model_manager(is_same=False)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        mock_engine = MagicMock()
        mock_engine.start.return_value = True
        mock_engine.is_running = False
        mock_engine.sentence_history = []
        monkeypatch.setattr(
            live_mod,
            "LiveModeEngine",
            lambda **kw: mock_engine,
        )

        loop = asyncio.get_running_loop()

        for cycle in range(5):
            session = _make_live_session(loop=loop)

            result = await session.start_engine()
            assert result is True, f"start_engine failed on cycle {cycle}"

            await session.stop_engine()

        # 5 unloads during start + 5 reloads during stop
        assert mm.unload_transcription_model.call_count == 5
        assert mm.load_transcription_model.call_count == 5

    async def test_alternating_success_and_failure(self, monkeypatch):
        """Mixed success/failure cycles still leave model_manager consistent."""
        shared_backend = MagicMock(name="shared-backend")
        mm = _mock_model_manager(is_same=True, backend=shared_backend)
        monkeypatch.setattr(live_mod, "get_model_manager", lambda: mm)

        call_count = 0

        def _make_engine(**kw):
            nonlocal call_count
            call_count += 1
            engine = MagicMock()
            engine.is_running = False
            engine.sentence_history = []
            # Alternate: odd cycles fail to start
            engine.start.return_value = call_count % 2 == 0
            return engine

        monkeypatch.setattr(live_mod, "LiveModeEngine", _make_engine)

        loop = asyncio.get_running_loop()

        for _cycle in range(4):
            session = _make_live_session(loop=loop)
            result = await session.start_engine()
            if result:
                await session.stop_engine()

        # Every cycle detaches the backend; restore happens via finally or stop_engine
        assert mm.detach_transcription_backend.call_count == 4
        # All 4 cycles should reattach (2 via stop_engine, 2 via finally)
        assert mm.attach_transcription_backend.call_count == 4
