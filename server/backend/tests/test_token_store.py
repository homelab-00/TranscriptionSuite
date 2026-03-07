"""Tests for server.core.token_store — pure logic, no ML dependencies.

Covers:
- ``hash_token`` consistency
- ``StoredToken.create`` factories (admin / regular / custom expiry)
- ``StoredToken.is_expired`` edge cases
- ``StoredToken`` serialisation round-trip
- ``TokenStore`` CRUD: generate → validate → revoke → list
- Expiry enforcement at validation time
- Role checking (``is_admin``)
- File persistence across ``TokenStore`` reloads
- v1 → v2 migration path
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from server.core.token_store import (
    CURRENT_STORE_VERSION,
    DEFAULT_TOKEN_EXPIRY_DAYS,
    StoredToken,
    TokenStore,
    hash_token,
)

# ── hash_token ────────────────────────────────────────────────────────────


class TestHashToken:
    def test_deterministic(self):
        assert hash_token("abc") == hash_token("abc")

    def test_different_inputs_differ(self):
        assert hash_token("token-a") != hash_token("token-b")

    def test_returns_hex_string(self):
        h = hash_token("hello")

        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest


# ── StoredToken.create ────────────────────────────────────────────────────


class TestStoredTokenCreate:
    def test_admin_token_never_expires(self):
        token, plaintext = StoredToken.create("admin-client", is_admin=True)

        assert token.is_admin is True
        assert token.expires_at is None
        assert token.is_revoked is False
        assert token.token_id is not None

    def test_regular_token_expires_in_30_days(self):
        before = datetime.now(UTC)
        token, _ = StoredToken.create("user-client", is_admin=False)
        after = datetime.now(UTC)

        assert token.expires_at is not None
        expiry = datetime.fromisoformat(token.expires_at)
        assert before + timedelta(days=DEFAULT_TOKEN_EXPIRY_DAYS) <= expiry
        assert expiry <= after + timedelta(days=DEFAULT_TOKEN_EXPIRY_DAYS)

    def test_custom_expiry_days(self):
        before = datetime.now(UTC)
        token, _ = StoredToken.create("custom", expiry_days=7)

        expiry = datetime.fromisoformat(token.expires_at)
        assert expiry <= before + timedelta(days=7, seconds=1)

    def test_zero_expiry_means_never(self):
        token, _ = StoredToken.create("forever", expiry_days=0)

        assert token.expires_at is None

    def test_negative_expiry_means_never(self):
        token, _ = StoredToken.create("forever-neg", expiry_days=-5)

        assert token.expires_at is None

    def test_plaintext_differs_from_stored_hash(self):
        token, plaintext = StoredToken.create("x")

        assert token.token != plaintext
        assert token.token == hash_token(plaintext)

    def test_token_id_is_16_hex_chars(self):
        token, _ = StoredToken.create("id-check")

        assert len(token.token_id) == 16
        int(token.token_id, 16)  # must be valid hex


# ── StoredToken.is_expired ────────────────────────────────────────────────


class TestStoredTokenIsExpired:
    def test_no_expiry_is_not_expired(self):
        token, _ = StoredToken.create("admin", is_admin=True)

        assert token.is_expired() is False

    def test_future_expiry_is_not_expired(self):
        token, _ = StoredToken.create("user", expiry_days=30)

        assert token.is_expired() is False

    def test_past_expiry_is_expired(self):
        token, _ = StoredToken.create("user")
        token.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

        assert token.is_expired() is True

    def test_invalid_expiry_string_is_not_expired(self):
        token, _ = StoredToken.create("user")
        token.expires_at = "not-a-date"

        assert token.is_expired() is False


# ── Serialisation round-trip ─────────────────────────────────────────────


class TestStoredTokenSerialisation:
    def test_to_dict_from_dict_round_trip(self):
        original, _ = StoredToken.create("rt-client", is_admin=True)
        d = original.to_dict()
        restored = StoredToken.from_dict(d)

        assert restored.token == original.token
        assert restored.client_name == original.client_name
        assert restored.is_admin == original.is_admin
        assert restored.expires_at == original.expires_at
        assert restored.token_id == original.token_id
        assert restored.is_revoked == original.is_revoked

    def test_from_dict_defaults_missing_optional_fields(self):
        minimal = {
            "token": "abc",
            "client_name": "legacy",
            "created_at": "2024-01-01T00:00:00+00:00",
        }

        restored = StoredToken.from_dict(minimal)

        assert restored.is_admin is False
        assert restored.is_revoked is False
        assert restored.expires_at is None
        assert restored.token_id is None


# ── TokenStore CRUD ──────────────────────────────────────────────────────


class TestTokenStoreCRUD:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> TokenStore:
        return TokenStore(store_path=tmp_path / "tokens.json")

    def test_init_creates_store_with_admin_token(self, store: TokenStore):
        tokens = store.list_tokens()

        assert len(tokens) == 1
        assert tokens[0].is_admin is True
        assert tokens[0].client_name == "admin"

    def test_generate_and_validate_token(self, store: TokenStore):
        stored, plaintext = store.generate_token("my-client")

        result = store.validate_token(plaintext)

        assert result is not None
        assert result.client_name == "my-client"

    def test_validate_unknown_token_returns_none(self, store: TokenStore):
        assert store.validate_token("nonexistent-token") is None

    def test_revoke_by_id(self, store: TokenStore):
        stored, plaintext = store.generate_token("to-revoke")

        success = store.revoke_token_by_id(stored.token_id)

        assert success is True
        assert store.validate_token(plaintext) is None

    def test_revoke_unknown_id_returns_false(self, store: TokenStore):
        assert store.revoke_token_by_id("does-not-exist") is False

    def test_is_admin_true_for_admin_token(self, store: TokenStore):
        _, plaintext = store.generate_token("admin2", is_admin=True)

        assert store.is_admin(plaintext) is True

    def test_is_admin_false_for_regular_token(self, store: TokenStore):
        _, plaintext = store.generate_token("regular")

        assert store.is_admin(plaintext) is False

    def test_is_admin_false_for_invalid_token(self, store: TokenStore):
        assert store.is_admin("bogus") is False

    def test_expired_token_fails_validation(self, store: TokenStore):
        stored, plaintext = store.generate_token("exp-test", expiry_days=1)

        # Manually set expiry into the past
        data = store._read_store()
        for t in data["tokens"]:
            if t["token"] == stored.token:
                t["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        store._write_store(data)

        assert store.validate_token(plaintext) is None

    def test_list_tokens_includes_all(self, store: TokenStore):
        store.generate_token("a")
        store.generate_token("b")

        tokens = store.list_tokens()

        # 1 initial admin + 2 generated
        assert len(tokens) == 3


# ── File persistence ─────────────────────────────────────────────────────


class TestTokenStorePersistence:
    def test_tokens_survive_reload(self, tmp_path: Path):
        path = tmp_path / "tokens.json"
        store1 = TokenStore(store_path=path)
        _, plaintext = store1.generate_token("persist-test")

        store2 = TokenStore(store_path=path)

        assert store2.validate_token(plaintext) is not None

    def test_store_file_is_valid_json(self, tmp_path: Path):
        path = tmp_path / "tokens.json"
        TokenStore(store_path=path)

        data = json.loads(path.read_text())

        assert "version" in data
        assert "tokens" in data
        assert isinstance(data["tokens"], list)


# ── v1 → v2 migration ───────────────────────────────────────────────────


class TestTokenStoreMigration:
    def test_v1_store_migrated_to_v2(self, tmp_path: Path):
        path = tmp_path / "tokens.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write a v1-style store (plaintext tokens, no version key)
        v1_data = {
            "version": 1,
            "secret_key": "old-secret",
            "tokens": [
                {
                    "token": "plaintext-admin-token",
                    "client_name": "admin",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "is_admin": True,
                    "is_revoked": False,
                }
            ],
        }
        path.write_text(json.dumps(v1_data))

        store = TokenStore(store_path=path)
        data = store._read_store()

        assert data["version"] == CURRENT_STORE_VERSION
        # Old plaintext tokens are wiped; a fresh admin token is generated
        assert len(data["tokens"]) == 1
        assert data["tokens"][0]["is_admin"] is True
        # The new token is hashed (64-char hex), not the old plaintext
        assert data["tokens"][0]["token"] != "plaintext-admin-token"
        assert len(data["tokens"][0]["token"]) == 64

    def test_v2_store_not_re_migrated(self, tmp_path: Path):
        path = tmp_path / "tokens.json"
        store1 = TokenStore(store_path=path)
        _, plaintext = store1.generate_token("keep-me")

        # Reload — should not wipe tokens
        store2 = TokenStore(store_path=path)

        assert store2.validate_token(plaintext) is not None
