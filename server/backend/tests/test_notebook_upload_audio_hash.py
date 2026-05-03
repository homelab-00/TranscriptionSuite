"""Notebook upload audio_hash persistence tests
(Issue #104, Sprint 2 carve-out — Item 2).

Sprint 2 wired the streaming SHA-256 hash to /api/transcribe/import; this
suite exercises the matching plumbing on the notebook side:

  - save_longform_to_database persists the hash atomically with the row
  - find_recordings_by_audio_hash returns the row by its hash
  - dedup_query.find_duplicates_anywhere merges recordings + jobs results
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database.database import (
    find_recordings_by_audio_hash,
    save_longform_to_database,
)
from server.database.dedup_query import find_duplicates_anywhere
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


def _make_audio_path(tmp_path: Path, name: str = "fake.mp3") -> Path:
    """Save_longform_to_database only uses the path's name/string — no actual
    audio file is required for these tests (we don't call ffmpeg)."""
    p = tmp_path / name
    p.write_bytes(b"\x00")
    return p


# ──────────────────────────────────────────────────────────────────────────
# save_longform_to_database persists audio_hash atomically
# ──────────────────────────────────────────────────────────────────────────


def test_save_longform_persists_audio_hash(fresh_db: Path, tmp_path: Path) -> None:
    h = "f1" * 32
    audio = _make_audio_path(tmp_path)
    rec_id = save_longform_to_database(
        audio_path=audio,
        duration_seconds=1.0,
        transcription_text="hello",
        audio_hash=h,
    )
    assert rec_id is not None and rec_id > 0
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute("SELECT audio_hash FROM recordings WHERE id = ?", (rec_id,)).fetchone()
    assert row is not None
    assert row[0] == h


def test_save_longform_default_hash_is_null(fresh_db: Path, tmp_path: Path) -> None:
    """Backwards compatibility: callers that omit audio_hash get NULL."""
    audio = _make_audio_path(tmp_path)
    rec_id = save_longform_to_database(
        audio_path=audio,
        duration_seconds=1.0,
        transcription_text="hello",
    )
    assert rec_id is not None
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute("SELECT audio_hash FROM recordings WHERE id = ?", (rec_id,)).fetchone()
    assert row is not None
    assert row[0] is None


# ──────────────────────────────────────────────────────────────────────────
# find_recordings_by_audio_hash
# ──────────────────────────────────────────────────────────────────────────


def test_find_recordings_returns_match(fresh_db: Path, tmp_path: Path) -> None:
    h = "f2" * 32
    rec_id = save_longform_to_database(
        audio_path=_make_audio_path(tmp_path),
        duration_seconds=1.0,
        transcription_text="hello",
        audio_hash=h,
    )
    rows = find_recordings_by_audio_hash(h)
    assert len(rows) == 1
    assert rows[0]["id"] == rec_id
    assert rows[0]["audio_hash"] == h


def test_find_recordings_empty_hash_returns_empty(fresh_db: Path) -> None:
    assert find_recordings_by_audio_hash("") == []


def test_find_recordings_excludes_null_hashes(fresh_db: Path, tmp_path: Path) -> None:
    save_longform_to_database(
        audio_path=_make_audio_path(tmp_path, name="nullhash.mp3"),
        duration_seconds=1.0,
        transcription_text="hello",
    )
    # Querying with arbitrary "NULL"-shaped strings must not match the row
    assert find_recordings_by_audio_hash("NULL") == []


def test_find_recordings_orders_most_recent_first(fresh_db: Path, tmp_path: Path) -> None:
    h = "f3" * 32
    older = save_longform_to_database(
        audio_path=_make_audio_path(tmp_path, name="older.mp3"),
        duration_seconds=1.0,
        transcription_text="x",
        audio_hash=h,
    )
    newer = save_longform_to_database(
        audio_path=_make_audio_path(tmp_path, name="newer.mp3"),
        duration_seconds=1.0,
        transcription_text="y",
        audio_hash=h,
    )
    rows = find_recordings_by_audio_hash(h)
    assert len(rows) == 2
    assert rows[0]["id"] == newer
    assert rows[1]["id"] == older


# ──────────────────────────────────────────────────────────────────────────
# find_duplicates_anywhere merges both tables
# ──────────────────────────────────────────────────────────────────────────


def test_find_duplicates_anywhere_jobs_only(fresh_db: Path) -> None:
    h = "f4" * 32
    create_job(
        job_id="job-x",
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        audio_hash=h,
    )
    matches = find_duplicates_anywhere(h)
    assert len(matches) == 1
    assert matches[0]["source"] == "transcription_job"
    assert matches[0]["id"] == "job-x"


def test_find_duplicates_anywhere_recordings_only(fresh_db: Path, tmp_path: Path) -> None:
    h = "f5" * 32
    rec_id = save_longform_to_database(
        audio_path=_make_audio_path(tmp_path),
        duration_seconds=1.0,
        transcription_text="hello",
        title="Note",
        audio_hash=h,
    )
    matches = find_duplicates_anywhere(h)
    assert len(matches) == 1
    assert matches[0]["source"] == "recording"
    assert matches[0]["id"] == str(rec_id)
    assert matches[0]["name"] == "Note"


def test_find_duplicates_anywhere_merges_both_sources(fresh_db: Path, tmp_path: Path) -> None:
    h = "f6" * 32
    create_job(
        job_id="job-merge",
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        audio_hash=h,
    )
    rec_id = save_longform_to_database(
        audio_path=_make_audio_path(tmp_path),
        duration_seconds=1.0,
        transcription_text="hi",
        title="Note",
        audio_hash=h,
    )
    matches = find_duplicates_anywhere(h)
    sources = sorted(m["source"] for m in matches)
    ids = {m["source"]: m["id"] for m in matches}
    assert sources == ["recording", "transcription_job"]
    assert ids["transcription_job"] == "job-merge"
    assert ids["recording"] == str(rec_id)


def test_find_duplicates_anywhere_respects_limit(fresh_db: Path, tmp_path: Path) -> None:
    h = "f7" * 32
    # Seed 3 jobs + 3 recordings — request limit=2 → exactly 2 results.
    for i in range(3):
        create_job(
            job_id=f"j-{i}",
            source="file_import",
            client_name=None,
            language=None,
            task="transcribe",
            translation_target=None,
            audio_hash=h,
        )
    for i in range(3):
        save_longform_to_database(
            audio_path=_make_audio_path(tmp_path, name=f"r-{i}.mp3"),
            duration_seconds=1.0,
            transcription_text="x",
            audio_hash=h,
        )
    matches = find_duplicates_anywhere(h, limit=2)
    assert len(matches) == 2


def test_find_duplicates_anywhere_empty_hash(fresh_db: Path) -> None:
    assert find_duplicates_anywhere("") == []
