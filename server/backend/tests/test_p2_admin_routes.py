"""Tests for Admin config routes: update_config and get_full_config.

[P2] Covers P2-ROUTE-003: config PATCH validation, config tree retrieval.

Follows the direct-call pattern: monkeypatch require_admin, config_tree
functions, and app.state, call handlers directly via asyncio.run().
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from server.api.routes import admin

# ── Helpers ──────────────────────────────────────────────────────────────────


class _MockRequest:
    """Stand-in for FastAPI Request with configurable JSON body and app.state."""

    def __init__(self, body: dict | None = None, *, config: object | None = None):
        self._body = body or {}
        # Simulate request.app.state.config
        _config = config or SimpleNamespace(loaded_from="/tmp/config.yaml")
        self.app = SimpleNamespace(state=SimpleNamespace(config=_config))
        # require_admin needs request.client
        self.client = SimpleNamespace(host="127.0.0.1")
        self.headers = {}
        self.cookies = {}

    async def json(self):
        return self._body


def _fake_config(loaded_from: str = "/tmp/config.yaml") -> SimpleNamespace:
    """Minimal ServerConfig stand-in with loaded_from."""
    return SimpleNamespace(loaded_from=loaded_from)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_admin(monkeypatch):
    """Patch require_admin to always return True (bypass auth for tests)."""
    monkeypatch.setattr(admin, "require_admin", lambda _request: True)


# ── P2-ROUTE-003: Admin Config Routes ───────────────────────────────────────


@pytest.mark.p2
class TestP2Route003UpdateConfig:
    """[P2] PATCH /api/admin/config — update config values."""

    def test_valid_patch_returns_results_and_tree(self, monkeypatch):
        """Valid updates dict returns merged results + parsed tree."""
        apply_results = {"server.host": "applied"}
        tree = {"sections": [{"name": "server", "fields": []}]}

        # Patch the lazily-imported config_tree functions at module level
        import server.config_tree as ct_mod

        monkeypatch.setattr(ct_mod, "apply_config_updates", lambda _path, _updates: apply_results)
        monkeypatch.setattr(ct_mod, "parse_config_tree", lambda _path: tree)

        req = _MockRequest({"updates": {"server.host": "0.0.0.0"}})
        result = asyncio.run(admin.update_config(req))

        assert result["results"] == {"server.host": "applied"}
        assert "sections" in result

    def test_400_on_empty_updates(self):
        """Empty updates dict raises 400."""
        req = _MockRequest({"updates": {}})

        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin.update_config(req))
        assert exc.value.status_code == 400
        assert "non-empty" in exc.value.detail

    def test_400_on_missing_updates_key(self):
        """Request body without 'updates' key raises 400."""
        req = _MockRequest({"something_else": "value"})

        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin.update_config(req))
        assert exc.value.status_code == 400


@pytest.mark.p2
class TestP2Route003GetFullConfig:
    """[P2] GET /api/admin/config/full — return config tree structure."""

    def test_returns_config_tree(self, monkeypatch):
        """Returns the parsed config tree from config_tree module."""
        tree = {
            "sections": [
                {
                    "name": "server",
                    "fields": [{"key": "host", "value": "0.0.0.0", "type": "string"}],
                }
            ]
        }

        import server.config_tree as ct_mod

        monkeypatch.setattr(ct_mod, "parse_config_tree", lambda _path: tree)

        req = _MockRequest(config=_fake_config("/tmp/config.yaml"))
        result = asyncio.run(admin.get_full_config(req))

        assert "sections" in result
        assert result["sections"][0]["name"] == "server"
