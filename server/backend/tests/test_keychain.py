"""Tests for server.utils.keychain (Issue #104, Story 1.7).

Uses the ``fake_keyring`` fixture from conftest.py; never touches the
real OS keychain (AC5).
"""

from __future__ import annotations

import pytest
from server.utils import keychain
from server.utils.keychain import KeychainUnavailableError


def test_set_and_get_round_trip(fake_keyring) -> None:
    """AC2 — set/get against the in-memory keyring."""
    keychain.set("profile.123.webhook_token", "supersecret")
    assert keychain.get("profile.123.webhook_token") == "supersecret"


def test_get_missing_returns_none(fake_keyring) -> None:
    """A key that has never been set returns None (not raises)."""
    assert keychain.get("profile.999.never_set") is None


def test_delete_removes_entry(fake_keyring) -> None:
    """AC2 — delete clears the entry; subsequent get returns None."""
    keychain.set("profile.42.api_key", "keyval")
    keychain.delete("profile.42.api_key")
    assert keychain.get("profile.42.api_key") is None


def test_delete_missing_is_silent(fake_keyring) -> None:
    """Best-effort delete: missing entries don't raise."""
    keychain.delete("profile.42.never_set")  # no exception


def test_unavailable_backend_raises_actionable_error(monkeypatch) -> None:
    """AC3 — when no OS backend is available AND the fallback flag is NOT
    set, set() raises KeychainUnavailableError with the documented hint."""
    # Install a backend that always raises NoKeyringError on writes
    import keyring
    import keyring.backend
    from keyring.errors import NoKeyringError

    class _AlwaysFailBackend(keyring.backend.KeyringBackend):
        priority = 100  # type: ignore[assignment]

        def set_password(self, service, username, password):  # noqa: ARG002
            raise NoKeyringError("no backend")

        def get_password(self, service, username):  # noqa: ARG002
            raise NoKeyringError("no backend")

        def delete_password(self, service, username):  # noqa: ARG002
            raise NoKeyringError("no backend")

    prev = keyring.get_keyring()
    keyring.set_keyring(_AlwaysFailBackend())
    monkeypatch.delenv("KEYRING_BACKEND_FALLBACK", raising=False)

    try:
        with pytest.raises(KeychainUnavailableError) as exc:
            keychain.set("profile.X.token", "value")
        assert "KEYRING_BACKEND_FALLBACK=encrypted_file" in str(exc.value)
        assert "deployment-guide.md" in str(exc.value)
    finally:
        keyring.set_keyring(prev)


def test_get_with_unavailable_backend_returns_none(monkeypatch) -> None:
    """Read side is best-effort: an unavailable backend yields None, not
    an exception (so callers don't have to wrap every read)."""
    import keyring
    import keyring.backend
    from keyring.errors import NoKeyringError

    class _AlwaysFailBackend(keyring.backend.KeyringBackend):
        priority = 100  # type: ignore[assignment]

        def set_password(self, service, username, password):  # noqa: ARG002
            raise NoKeyringError("no backend")

        def get_password(self, service, username):  # noqa: ARG002
            raise NoKeyringError("no backend")

        def delete_password(self, service, username):  # noqa: ARG002
            raise NoKeyringError("no backend")

    prev = keyring.get_keyring()
    keyring.set_keyring(_AlwaysFailBackend())
    monkeypatch.delenv("KEYRING_BACKEND_FALLBACK", raising=False)

    try:
        assert keychain.get("profile.X.token") is None
    finally:
        keyring.set_keyring(prev)


def test_fake_keyring_isolates_real_keychain(fake_keyring) -> None:
    """AC5 — verify the fixture really swaps the backend so writes don't
    touch the host's real keychain. Marker test that pins the fixture
    contract Story 1.7 depends on."""

    keychain.set("isolation.test", "marker")
    # The active backend SHOULD be the in-memory one provided by fake_keyring.
    # No assertion on the type name (private), but we can prove isolation by
    # asserting the fixture-installed backend has the value, then a fresh
    # backend instance does not.
    assert keychain.get("isolation.test") == "marker"
    fake_keyring.delete(keychain._SERVICE_PREFIX, "isolation.test")
    assert keychain.get("isolation.test") is None
