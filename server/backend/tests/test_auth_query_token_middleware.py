"""
Tests for AuthenticationMiddleware query-token fallback behavior.

The fallback must only apply to notebook media endpoints that need tokenized URLs:
- /api/notebook/recordings/{id}/audio
- /api/notebook/recordings/{id}/export
"""

import sys
from pathlib import Path
from types import ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if "server" not in sys.modules:
    server_pkg = ModuleType("server")
    server_pkg.__path__ = [str(BACKEND_ROOT)]
    server_pkg.__version__ = "test"
    sys.modules["server"] = server_pkg

from server.api.main import AuthenticationMiddleware


class _StubTokenStore:
    def __init__(self, valid_token: str) -> None:
        self.valid_token = valid_token

    def validate_token(self, token: str):
        if token == self.valid_token:
            return {"client_name": "pytest"}
        return None


def _build_client(monkeypatch, valid_token: str = "valid-token") -> TestClient:
    import server.api.main as main_module

    monkeypatch.setattr(
        main_module,
        "get_token_store",
        lambda: _StubTokenStore(valid_token),
    )

    app = FastAPI()
    app.add_middleware(AuthenticationMiddleware)

    @app.get("/api/notebook/recordings/1/audio")
    async def audio():
        return {"ok": True}

    @app.get("/api/notebook/recordings/1/export")
    async def export():
        return {"ok": True}

    @app.get("/api/notebook/calendar")
    async def calendar():
        return {"ok": True}

    return TestClient(app)


def test_query_token_allows_audio_route(monkeypatch):
    client = _build_client(monkeypatch)
    response = client.get("/api/notebook/recordings/1/audio?token=valid-token")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_query_token_allows_export_route(monkeypatch):
    client = _build_client(monkeypatch)
    response = client.get("/api/notebook/recordings/1/export?format=txt&token=valid-token")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_query_token_is_rejected_for_non_media_route(monkeypatch):
    client = _build_client(monkeypatch)
    response = client.get("/api/notebook/calendar?token=valid-token")
    assert response.status_code == 401
    assert "authentication required" in response.json()["detail"].lower()


def test_invalid_query_token_returns_401(monkeypatch):
    client = _build_client(monkeypatch)
    response = client.get("/api/notebook/recordings/1/audio?token=invalid-token")
    assert response.status_code == 401
    assert "authentication required" in response.json()["detail"].lower()
