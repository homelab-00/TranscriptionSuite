"""Smoke tests for the Story 1.1 Day-1 fixtures.

Each test verifies a single fixture is wired correctly. The names follow
the ``test_<fixture>_self_check`` convention required by AC1.

These tests are also the canary that the banned-API gate (TID251) is
correctly scoped: they intentionally call ``datetime.now()`` and similar
banned APIs **inside** ``# noqa: TID251`` markers to verify that the
fixture freezes / replaces the banned behavior. Without ``# noqa`` the
imports would be the violation, not the fixture wiring.
"""

from __future__ import annotations

import socket

import pytest

# ---------------------------------------------------------------------------
# frozen_clock
# ---------------------------------------------------------------------------


def test_frozen_clock_self_check(frozen_clock) -> None:
    from datetime import UTC, datetime

    # The two ``datetime.now()`` calls below intentionally invoke a
    # banned API to verify ``frozen_clock`` actually freezes wall time.
    now = datetime.now(UTC)  # noqa: TID251
    assert now.year == 2025
    assert now.month == 1
    assert now.day == 15
    assert now.hour == 12

    frozen_clock.tick(60)
    advanced = datetime.now(UTC)  # noqa: TID251
    assert (advanced - now).total_seconds() == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# fake_keyring
# ---------------------------------------------------------------------------


def test_fake_keyring_self_check(fake_keyring) -> None:
    import keyring

    # The active backend should be our fake.
    assert keyring.get_keyring().__class__.__name__ == "_InMemoryKeyringBackend"

    keyring.set_password("svc.test", "alice", "s3cret")
    assert keyring.get_password("svc.test", "alice") == "s3cret"

    keyring.delete_password("svc.test", "alice")
    assert keyring.get_password("svc.test", "alice") is None


# ---------------------------------------------------------------------------
# private_ip_resolver
# ---------------------------------------------------------------------------


def test_private_ip_resolver_self_check(private_ip_resolver) -> None:
    private_ip_resolver.add("metadata.local", "169.254.169.254")
    private_ip_resolver.add("internal-only.example.com", "10.0.0.5")

    addrs = socket.getaddrinfo("metadata.local", 80)
    assert addrs[0][4][0] == "169.254.169.254"

    addrs2 = socket.getaddrinfo("internal-only.example.com", 443)
    assert addrs2[0][4][0] == "10.0.0.5"

    # Hostnames not in the override map fall through to the real resolver.
    private_ip_resolver.clear()
    private_ip_resolver.add("metadata.local", "169.254.169.254")
    real_addrs = socket.getaddrinfo("127.0.0.1", 0)
    assert real_addrs  # real resolver succeeded for loopback


# ---------------------------------------------------------------------------
# webhook_mock_receiver
# ---------------------------------------------------------------------------


async def test_webhook_mock_receiver_self_check(webhook_mock_receiver) -> None:
    import aiohttp

    payload = {"hello": "world", "n": 3}
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_mock_receiver.url, json=payload) as resp:
            assert resp.status == 200
            body = await resp.json()
            assert body == {"ok": True}

    assert len(webhook_mock_receiver.requests) == 1
    req = webhook_mock_receiver.requests[0]
    assert req["method"] == "POST"
    assert req["body"] == payload

    # Program a 503 for the next request and re-POST.
    webhook_mock_receiver.set_response(503)
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_mock_receiver.url, json={}) as resp:
            assert resp.status == 503

    # Program a redirect.
    webhook_mock_receiver.set_redirect("https://elsewhere.example/post")
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_mock_receiver.url, json={}, allow_redirects=False) as resp:
            assert resp.status == 302
            assert resp.headers["Location"] == "https://elsewhere.example/post"


# ---------------------------------------------------------------------------
# profile_snapshot_golden
# ---------------------------------------------------------------------------


def test_profile_snapshot_golden_self_check(profile_snapshot_golden) -> None:
    minimal = profile_snapshot_golden("minimal")
    assert minimal["schema_version"] == "1.0"
    assert minimal["name"] == "minimal"
    assert "filename_template" in minimal["public_fields"]

    full = profile_snapshot_golden("full")
    assert full["name"] == "full"
    assert full["public_fields"]["auto_summary_enabled"] is True
    # Private fields are stored only as keychain references, never plaintext.
    for ref in full["private_field_refs"].values():
        assert ref.startswith("ref:keyring:")

    # assert_matches helper: identical dict passes silently; differing dict fails.
    profile_snapshot_golden.assert_matches(minimal, "minimal")

    with pytest.raises(AssertionError):
        profile_snapshot_golden.assert_matches({"different": True}, "minimal")
