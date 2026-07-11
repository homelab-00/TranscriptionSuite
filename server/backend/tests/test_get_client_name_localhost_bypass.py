"""Tests for ``get_client_name`` localhost-bypass identity (GH #202).

A >1 MB transcription result is persisted by the WebSocket handler, which — on a
local, non-TLS deployment — stamps the job with ``client_name="localhost-user"``
via the localhost auth bypass (``authenticate_websocket_*`` in
``server.api.routes.utils``), *without* consulting any token.

The HTTP recovery endpoint ``GET /api/transcribe/result/{job_id}`` derives the
caller identity from ``get_client_name`` and 403s when it differs from the job's
owner.  For the legitimate local owner to retrieve their own result,
``get_client_name`` must apply the *same* localhost bypass with the *same*
precedence (bypass before token).  These tests pin that contract.
"""

import types

from server.api.routes import utils


class _FakeClient:
    def __init__(self, host: str | None) -> None:
        self.host = host


class _FakeRequest:
    """Minimal Request stand-in exposing ``.client.host``/``.headers``/``.cookies``."""

    def __init__(
        self,
        host: str | None,
        headers: dict | None = None,
        cookies: dict | None = None,
    ) -> None:
        self.client = _FakeClient(host) if host is not None else None
        self.headers = headers or {}
        self.cookies = cookies or {}


def test_local_non_tls_tokenless_request_resolves_to_localhost_user(monkeypatch):
    """A token-less loopback request maps to 'localhost-user' (was 'Unknown Client')."""
    monkeypatch.setattr(utils, "TLS_MODE", False)
    req = _FakeRequest("127.0.0.1")
    assert utils.get_client_name(req) == "localhost-user"


def test_local_bypass_takes_precedence_over_token(monkeypatch):
    """Even with a valid token, a local non-TLS request is 'localhost-user'.

    This mirrors the WebSocket bypass (which ignores the token on localhost) so
    that HTTP identity matches the persisted job owner.
    """
    monkeypatch.setattr(utils, "TLS_MODE", False)
    monkeypatch.setattr(
        utils,
        "validate_auth_token",
        lambda _t: types.SimpleNamespace(client_name="alice", is_admin=False),
    )
    req = _FakeRequest("127.0.0.1", headers={"Authorization": "Bearer tok"})
    assert utils.get_client_name(req) == "localhost-user"


def test_tls_mode_disables_localhost_bypass(monkeypatch):
    """Under TLS the bypass must NOT apply — token identity is preserved."""
    monkeypatch.setattr(utils, "TLS_MODE", True)
    monkeypatch.setattr(
        utils,
        "validate_auth_token",
        lambda _t: types.SimpleNamespace(client_name="alice", is_admin=False),
    )
    req = _FakeRequest("127.0.0.1", headers={"Authorization": "Bearer tok"})
    assert utils.get_client_name(req) == "alice"


def test_remote_request_with_token_uses_token_name(monkeypatch):
    """A non-local request with a valid token keeps the token's client name."""
    monkeypatch.setattr(utils, "TLS_MODE", False)
    monkeypatch.setattr(
        utils,
        "validate_auth_token",
        lambda _t: types.SimpleNamespace(client_name="alice", is_admin=False),
    )
    req = _FakeRequest("8.8.8.8", headers={"Authorization": "Bearer tok"})
    assert utils.get_client_name(req) == "alice"


def test_remote_request_without_token_is_unknown(monkeypatch):
    """A non-local request with no valid token stays 'Unknown Client'."""
    monkeypatch.setattr(utils, "TLS_MODE", False)
    monkeypatch.setattr(utils, "validate_auth_token", lambda _t: None)
    req = _FakeRequest("8.8.8.8")
    assert utils.get_client_name(req) == "Unknown Client"
