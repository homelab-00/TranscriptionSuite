import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from starlette.websockets import WebSocketState

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if "server" not in sys.modules:
    server_pkg = ModuleType("server")
    server_pkg.__path__ = [str(BACKEND_ROOT)]
    server_pkg.__version__ = "test"
    sys.modules["server"] = server_pkg

utils = importlib.import_module("server.api.routes.utils")


class _StubWebSocket:
    def __init__(self, host: str, auth_message: dict) -> None:
        self.client = SimpleNamespace(host=host)
        self.client_state = WebSocketState.CONNECTED
        self._auth_message = auth_message
        self.sent_messages: list[dict] = []
        self.closed = False

    async def receive_json(self) -> dict:
        return self._auth_message

    async def send_json(self, payload: dict) -> None:
        self.sent_messages.append(payload)

    async def close(self) -> None:
        self.closed = True


def _request_with_host(host: str):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def test_websocket_auth_allows_docker_gateway_local_bypass(monkeypatch) -> None:
    monkeypatch.setattr(utils, "TLS_MODE", False)
    monkeypatch.setattr(utils, "RUNNING_IN_DOCKER", True)

    def _unexpected_validate(_token):
        raise AssertionError("Token validation should be skipped for Docker gateway bypass")

    monkeypatch.setattr(utils, "validate_auth_token", _unexpected_validate)

    ws = _StubWebSocket("172.18.0.1", {"type": "auth", "data": {"token": ""}})
    result = asyncio.run(
        utils.authenticate_websocket_from_message(
            ws,
            allow_localhost_bypass=True,
        )
    )

    assert result is not None
    assert result.is_localhost_bypass is True
    assert result.client_name == "localhost-user"
    assert ws.sent_messages == []
    assert ws.closed is False


def test_websocket_auth_missing_token_returns_clear_message(monkeypatch) -> None:
    monkeypatch.setattr(utils, "TLS_MODE", False)
    monkeypatch.setattr(utils, "RUNNING_IN_DOCKER", True)
    monkeypatch.setattr(utils, "validate_auth_token", lambda _token: None)

    ws = _StubWebSocket("172.18.0.2", {"type": "auth", "data": {"token": ""}})
    result = asyncio.run(
        utils.authenticate_websocket_from_message(
            ws,
            allow_localhost_bypass=True,
        )
    )

    assert result is None
    assert ws.closed is True
    assert len(ws.sent_messages) == 1
    payload = ws.sent_messages[0]
    assert payload["type"] == "auth_fail"
    assert "token required" in payload["data"]["message"].lower()


def test_require_admin_allows_docker_gateway_in_local_mode(monkeypatch) -> None:
    monkeypatch.setattr(utils, "TLS_MODE", False)
    monkeypatch.setattr(utils, "RUNNING_IN_DOCKER", True)
    monkeypatch.setattr(utils, "get_authenticated_token", lambda _request: None)

    assert utils.require_admin(_request_with_host("172.18.0.1")) is True


def test_require_admin_does_not_bypass_non_gateway_private_ip(monkeypatch) -> None:
    monkeypatch.setattr(utils, "TLS_MODE", False)
    monkeypatch.setattr(utils, "RUNNING_IN_DOCKER", True)
    monkeypatch.setattr(utils, "get_authenticated_token", lambda _request: None)

    assert utils.require_admin(_request_with_host("172.18.0.2")) is False
