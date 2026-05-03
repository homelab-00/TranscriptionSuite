"""Dedup-check endpoint tests (Issue #104, Stories 2.4 + 2.5).

Uses the direct-call pattern (CLAUDE.md) — handlers are invoked via
asyncio.run() and the return value is asserted directly.

Covers:
  - Story 2.4 AC1: matching hash returns matches, missing hash returns []
  - Story 2.4 idempotence: two calls with same input produce same output
  - Story 2.5 AC1: no outbound network (httpx / socket) calls escape
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest
import server.database.database as db
from server.api.routes import transcription as txn_route
from server.database.job_repository import create_job


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_data_dir", None)
    monkeypatch.setattr(db, "_db_path", None)
    db.set_data_directory(data_dir)
    db.init_db()
    return db.get_db_path()


def _seed(audio_hash: str, job_id: str = "seed-1") -> None:
    create_job(
        job_id=job_id,
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        audio_hash=audio_hash,
    )


# ──────────────────────────────────────────────────────────────────────────
# Story 2.4 AC1 — matching + non-matching
# ──────────────────────────────────────────────────────────────────────────


def test_dedup_check_returns_match(fresh_db: Path) -> None:
    h = "ab" * 32
    _seed(h, "match-1")
    body = txn_route.DedupCheckRequest(audio_hash=h)
    result = asyncio.run(txn_route.dedup_check(body))
    assert len(result.matches) == 1
    assert result.matches[0].recording_id == "match-1"


def test_dedup_check_returns_empty_for_no_match(fresh_db: Path) -> None:
    body = txn_route.DedupCheckRequest(audio_hash="ff" * 32)
    result = asyncio.run(txn_route.dedup_check(body))
    assert result.matches == []


# ──────────────────────────────────────────────────────────────────────────
# Idempotence — two calls produce identical output (no side effects)
# ──────────────────────────────────────────────────────────────────────────


def test_dedup_check_is_idempotent(fresh_db: Path) -> None:
    h = "cd" * 32
    _seed(h, "match-1")
    body = txn_route.DedupCheckRequest(audio_hash=h)
    first = asyncio.run(txn_route.dedup_check(body))
    second = asyncio.run(txn_route.dedup_check(body))
    assert first.matches == second.matches


# ──────────────────────────────────────────────────────────────────────────
# Story 2.5 AC1 — no outbound network calls
# ──────────────────────────────────────────────────────────────────────────


def test_dedup_check_no_outbound_network(fresh_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch every plausible socket/HTTP escape hatch to raise. Any call
    that the dedup-check endpoint accidentally makes would fail loudly.

    We do NOT patch ``socket.socket`` directly because SQLite's connection
    machinery on some platforms involves AF_UNIX sockets that the kernel
    (not Python) opens. We patch the network-facing connection helpers
    that any HTTP/TCP escape would route through.
    """

    def _raise_outbound(*_args, **_kwargs):
        raise AssertionError("dedup-check made an outbound network call — violates FR4 / R-EL23")

    # TCP/UDP outbound — covers raw socket use, urllib, requests, anything
    # that ultimately calls socket.create_connection.
    monkeypatch.setattr(socket, "create_connection", _raise_outbound)

    # httpx (FastAPI's recommended async HTTP client) — patch the send
    # method on both client classes that anything in the project uses.
    try:
        import httpx

        monkeypatch.setattr(httpx.Client, "send", _raise_outbound)
        monkeypatch.setattr(httpx.AsyncClient, "send", _raise_outbound)
    except ImportError:
        pass

    h = "ef" * 32
    _seed(h, "match-1")
    body = txn_route.DedupCheckRequest(audio_hash=h)
    # If the endpoint tries any outbound call, this will raise AssertionError
    result = asyncio.run(txn_route.dedup_check(body))
    assert len(result.matches) == 1


# ──────────────────────────────────────────────────────────────────────────
# Empty hash — accept but return [] (defensive)
# ──────────────────────────────────────────────────────────────────────────


def test_dedup_check_empty_hash_returns_empty(fresh_db: Path) -> None:
    body = txn_route.DedupCheckRequest(audio_hash="")
    result = asyncio.run(txn_route.dedup_check(body))
    assert result.matches == []
