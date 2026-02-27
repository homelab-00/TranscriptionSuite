"""Tests for Live Mode model backend constraints."""

import asyncio
import sys
from pathlib import Path
from types import ModuleType

import pytest
from starlette.websockets import WebSocketState

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if "server" not in sys.modules:
    server_pkg = ModuleType("server")
    server_pkg.__path__ = [str(BACKEND_ROOT)]
    server_pkg.__version__ = "test"
    sys.modules["server"] = server_pkg


def test_live_mode_accepts_whisper_models_only() -> None:
    pytest.importorskip("fastapi")
    from server.api.routes.live import is_live_mode_model_supported

    assert is_live_mode_model_supported("Systran/faster-whisper-large-v3")
    assert is_live_mode_model_supported("Systran/faster-whisper-small")

    assert not is_live_mode_model_supported("nvidia/parakeet-tdt-0.6b-v3")
    assert not is_live_mode_model_supported("nvidia/canary-1b-v2")
    assert not is_live_mode_model_supported("microsoft/VibeVoice-ASR")
    assert not is_live_mode_model_supported("scerz/VibeVoice-ASR-4bit")
    assert not is_live_mode_model_supported("")
    assert not is_live_mode_model_supported("__none__")


def test_live_mode_start_returns_409_style_error_when_model_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("fastapi")
    from server.api.routes.live import LiveModeSession

    class FakeWebSocket:
        client_state = WebSocketState.CONNECTED
        application_state = WebSocketState.CONNECTED

        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    fake_ws = FakeWebSocket()

    # Force disabled/empty live model resolution and avoid config dependencies.
    monkeypatch.setattr("server.api.routes.live.get_config", object)
    monkeypatch.setattr("server.api.routes.live.resolve_live_transcriber_model", lambda _: "")

    async def _run_start() -> bool:
        session = LiveModeSession(websocket=fake_ws, client_name="tester")
        return await session.start_engine(None)

    started = asyncio.run(_run_start())

    assert started is False
    assert fake_ws.sent
    payload = fake_ws.sent[-1]
    assert payload["type"] == "error"
    assert payload["data"]["status_code"] == 409
    assert "Live model not selected" in payload["data"]["message"]
