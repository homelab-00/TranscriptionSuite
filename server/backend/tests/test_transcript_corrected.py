"""Tests for the non-destructive corrected-transcript feature.

Covers:
  - repo `update_recording_corrected_transcript` set + clear (incl. falsy → NULL)
  - `Recording.to_dict()` includes the new additive field
  - `PATCH /recordings/{id}/transcript` route via the direct-call pattern

The original segments / word-timestamps are never touched — this only writes
the additive `transcript_corrected` column (data-loss invariant).
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from fastapi import HTTPException
from server.api.routes import notebook

# A minimal recordings table that includes the migration-017 column.
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL UNIQUE,
    title TEXT,
    duration_seconds REAL NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    word_count INTEGER DEFAULT 0,
    has_diarization INTEGER DEFAULT 0,
    summary TEXT,
    summary_model TEXT,
    transcript_corrected TEXT,
    transcription_backend TEXT
);
"""


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the database module at a fresh SQLite file with one recording."""
    data_dir = tmp_path / "data"
    db_dir = data_dir / "database"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "notebook.db"

    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO recordings (id, filename, filepath, duration_seconds, recorded_at) "
        "VALUES (1, 'a.mp3', '/audio/a.mp3', 10.0, '2026-05-30T10:00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "_data_dir", data_dir)
    monkeypatch.setattr(db, "_db_path", db_path)


def _read_corrected(recording_id: int) -> str | None:
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT transcript_corrected FROM recordings WHERE id = ?", (recording_id,))
        row = cur.fetchone()
        return row[0] if row else None


# ── Repo layer ──────────────────────────────────────────────────────────────


def test_update_sets_corrected_transcript(isolated_db) -> None:
    assert db.update_recording_corrected_transcript(1, "hand corrected") is True
    assert _read_corrected(1) == "hand corrected"


def test_update_clears_with_none(isolated_db) -> None:
    db.update_recording_corrected_transcript(1, "hand corrected")
    assert db.update_recording_corrected_transcript(1, None) is True
    assert _read_corrected(1) is None


def test_update_empty_string_stores_null(isolated_db) -> None:
    db.update_recording_corrected_transcript(1, "hand corrected")
    assert db.update_recording_corrected_transcript(1, "") is True
    assert _read_corrected(1) is None


def test_update_missing_recording_returns_false(isolated_db) -> None:
    assert db.update_recording_corrected_transcript(999, "x") is False


# ── Recording.to_dict ─────────────────────────────────────────────────────────


def test_to_dict_includes_transcript_corrected() -> None:
    rec = db.Recording({"id": 1, "transcript_corrected": "edited"})
    assert rec.to_dict()["transcript_corrected"] == "edited"


def test_to_dict_defaults_transcript_corrected_to_none() -> None:
    rec = db.Recording({"id": 1})
    assert rec.to_dict()["transcript_corrected"] is None


# ── Route handler (direct-call pattern) ────────────────────────────────────────


def _recording(recording_id: int = 1) -> dict:
    return {"id": recording_id, "filename": "a.mp3", "filepath": "/audio/a.mp3"}


def test_route_sets_transcript(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(notebook, "get_recording", _recording)

    def fake_update(rid: int, text: str | None) -> bool:
        captured["rid"] = rid
        captured["text"] = text
        return True

    monkeypatch.setattr(notebook, "update_recording_corrected_transcript", fake_update)

    body = notebook.TranscriptUpdate(transcript="fixed text")
    result = asyncio.run(notebook.update_transcript_patch(1, body))

    assert result == {"status": "updated", "id": 1, "transcript_corrected": "fixed text"}
    assert captured == {"rid": 1, "text": "fixed text"}


def test_route_clears_transcript(monkeypatch) -> None:
    monkeypatch.setattr(notebook, "get_recording", _recording)
    monkeypatch.setattr(notebook, "update_recording_corrected_transcript", lambda rid, text: True)

    body = notebook.TranscriptUpdate(transcript=None)
    result = asyncio.run(notebook.update_transcript_patch(1, body))

    assert result["transcript_corrected"] is None


def test_route_normalizes_whitespace_to_null(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(notebook, "get_recording", _recording)

    def fake_update(rid: int, text: str | None) -> bool:
        captured["text"] = text
        return True

    monkeypatch.setattr(notebook, "update_recording_corrected_transcript", fake_update)

    body = notebook.TranscriptUpdate(transcript="   \n\t  ")
    result = asyncio.run(notebook.update_transcript_patch(1, body))

    # Whitespace-only is normalized to NULL for both the repo call and the echo.
    assert captured["text"] is None
    assert result["transcript_corrected"] is None


def test_route_404_when_recording_missing(monkeypatch) -> None:
    monkeypatch.setattr(notebook, "get_recording", lambda rid: None)

    body = notebook.TranscriptUpdate(transcript="x")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.update_transcript_patch(999, body))
    assert exc.value.status_code == 404


def test_route_500_on_repo_failure(monkeypatch) -> None:
    monkeypatch.setattr(notebook, "get_recording", _recording)
    monkeypatch.setattr(notebook, "update_recording_corrected_transcript", lambda rid, text: False)

    body = notebook.TranscriptUpdate(transcript="x")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.update_transcript_patch(1, body))
    assert exc.value.status_code == 500
