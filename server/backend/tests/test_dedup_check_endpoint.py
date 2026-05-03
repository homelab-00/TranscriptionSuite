"""Dedup-check endpoint tests (Issue #104, Stories 2.4 + 2.5; Sprint 2 Item 2).

Uses the direct-call pattern (CLAUDE.md) — handlers are invoked via
asyncio.run() and the return value is asserted directly.

Covers:
  - Story 2.4 AC1: matching hash returns matches, missing hash returns []
  - Story 2.4 idempotence: two calls with same input produce same output
  - Story 2.5 AC1: no outbound network (httpx / socket) calls escape
  - Sprint 2 Item 2: cross-flow matches across transcription_jobs + recordings
"""

from __future__ import annotations

import asyncio
import socket
import sqlite3
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


# ──────────────────────────────────────────────────────────────────────────
# Sprint 2 Item 2 — cross-flow dedup (recordings + transcription_jobs)
# ──────────────────────────────────────────────────────────────────────────


def _seed_recording(
    fresh_db: Path,
    audio_hash: str,
    *,
    filename: str = "rec.mp3",
    title: str | None = None,
    imported_at: str = "2026-05-04T12:00:00",
) -> int:
    """Insert a recordings row with the given audio_hash; return its id."""
    with sqlite3.connect(fresh_db) as conn:
        cur = conn.execute(
            """
            INSERT INTO recordings
                (filename, filepath, title, duration_seconds, recorded_at,
                 imported_at, audio_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filename,
                f"/tmp/{filename}",
                title,
                1.0,
                imported_at,
                imported_at,
                audio_hash,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def test_dedup_check_returns_recording_only_match(fresh_db: Path) -> None:
    """Hash present ONLY in recordings — match comes back tagged source=recording."""
    h = "a1" * 32
    rec_id = _seed_recording(fresh_db, h, title="Lecture A")
    body = txn_route.DedupCheckRequest(audio_hash=h)
    result = asyncio.run(txn_route.dedup_check(body))
    assert len(result.matches) == 1
    assert result.matches[0].source == "recording"
    assert result.matches[0].recording_id == str(rec_id)
    assert result.matches[0].name == "Lecture A"


def test_dedup_check_jobs_only_match_keeps_source_default(fresh_db: Path) -> None:
    """Pre-Item-2 callers see source='transcription_job' (default for jobs hits)."""
    h = "b2" * 32
    _seed(h, "job-only-1")
    body = txn_route.DedupCheckRequest(audio_hash=h)
    result = asyncio.run(txn_route.dedup_check(body))
    assert len(result.matches) == 1
    assert result.matches[0].source == "transcription_job"
    assert result.matches[0].recording_id == "job-only-1"


def test_dedup_check_returns_matches_from_both_tables(fresh_db: Path) -> None:
    """Hash present in BOTH tables — both rows surface, ordered DESC by ts."""
    h = "c3" * 32
    # Older job, newer recording — recording must come first.
    _seed(h, "older-job")
    rec_id = _seed_recording(fresh_db, h, filename="newer.mp3", imported_at="2030-01-01T00:00:00")
    body = txn_route.DedupCheckRequest(audio_hash=h)
    result = asyncio.run(txn_route.dedup_check(body))
    assert len(result.matches) == 2
    sources = [m.source for m in result.matches]
    assert "recording" in sources
    assert "transcription_job" in sources
    # Recording was imported in 2030 → must be first (DESC order).
    assert result.matches[0].source == "recording"
    assert result.matches[0].recording_id == str(rec_id)


def test_dedup_check_excludes_legacy_null_recording(fresh_db: Path) -> None:
    """A recording with NULL audio_hash never participates in dedup."""
    # Insert a legacy row (no audio_hash column value)
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            """
            INSERT INTO recordings
                (filename, filepath, duration_seconds, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            ("legacy.mp3", "/tmp/legacy.mp3", 1.0, "2026-05-04T00:00:00"),
        )
        conn.commit()
    # Querying with any hash must not return the legacy row
    body = txn_route.DedupCheckRequest(audio_hash="d4" * 32)
    result = asyncio.run(txn_route.dedup_check(body))
    assert result.matches == []
