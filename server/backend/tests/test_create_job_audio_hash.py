"""create_job + find_by_audio_hash repository tests (Issue #104, Story 2.2 / 2.4).

Asserts:
  - create_job(audio_hash=...) persists the hash atomically with the row
  - get_job returns the same hash
  - find_by_audio_hash returns prior matches; NULL hashes are excluded
  - find_by_audio_hash is ordered most-recent-first
  - set_audio_hash updates an existing row (used by /audio endpoint)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database.job_repository import (
    create_job,
    find_by_audio_hash,
    get_job,
    set_audio_hash,
)


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


def test_create_job_with_audio_hash_persists_atomically(fresh_db: Path) -> None:
    """The hash is written in the same INSERT as the row (Story 2.2 AC3
    spirit — no observable window where a freshly-created job lacks its
    declared hash).
    """
    create_job(
        job_id="job-with-hash",
        source="file_import",
        client_name="test",
        language="en",
        task="transcribe",
        translation_target=None,
        audio_hash="a" * 64,
    )
    row = get_job("job-with-hash")
    assert row is not None
    assert row["audio_hash"] == "a" * 64


def test_create_job_without_hash_leaves_null(fresh_db: Path) -> None:
    create_job(
        job_id="job-no-hash",
        source="audio_upload",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
    )
    row = get_job("job-no-hash")
    assert row is not None
    assert row["audio_hash"] is None


def test_set_audio_hash_updates_existing_row(fresh_db: Path) -> None:
    """The /audio endpoint creates the row first then patches the hash in."""
    create_job(
        job_id="job-late-hash",
        source="audio_upload",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
    )
    set_audio_hash("job-late-hash", "b" * 64)
    row = get_job("job-late-hash")
    assert row is not None
    assert row["audio_hash"] == "b" * 64


# ──────────────────────────────────────────────────────────────────────────
# find_by_audio_hash
# ──────────────────────────────────────────────────────────────────────────


def test_find_by_audio_hash_returns_matches(fresh_db: Path) -> None:
    create_job(
        job_id="match-1",
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        audio_hash="cafe" * 16,  # 64 chars
    )
    create_job(
        job_id="match-2",
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        audio_hash="cafe" * 16,
    )
    create_job(
        job_id="other",
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        audio_hash="dead" * 16,
    )
    rows = find_by_audio_hash("cafe" * 16)
    ids = {r["id"] for r in rows}
    assert ids == {"match-1", "match-2"}


def test_find_by_audio_hash_excludes_null_hashes(fresh_db: Path) -> None:
    """Legacy rows with NULL audio_hash must never appear as matches."""
    create_job(
        job_id="null-hash-row",
        source="audio_upload",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
    )
    # Searching for an empty string returns []
    assert find_by_audio_hash("") == []
    # Even searching for the literal string "NULL" returns nothing
    assert find_by_audio_hash("NULL") == []


def test_find_by_audio_hash_orders_most_recent_first(fresh_db: Path) -> None:
    """Two rows with the same hash — the one with the later created_at
    (or completed_at) appears first.

    SQLite's CURRENT_TIMESTAMP has 1-second resolution, so we explicitly
    backdate the "older" row instead of sleeping (avoids a 1s test).
    """
    h = "1234" * 16
    create_job(
        job_id="older",
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        audio_hash=h,
    )
    # Backdate the "older" row to a known earlier timestamp so the
    # ORDER BY produces a deterministic result.
    with sqlite3.connect(fresh_db) as conn:
        conn.execute(
            "UPDATE transcription_jobs SET created_at = ? WHERE id = ?",
            ("2020-01-01 00:00:00", "older"),
        )
        conn.commit()
    create_job(
        job_id="newer",
        source="file_import",
        client_name=None,
        language=None,
        task="transcribe",
        translation_target=None,
        audio_hash=h,
    )
    rows = find_by_audio_hash(h)
    assert [r["id"] for r in rows] == ["newer", "older"]


def test_find_by_audio_hash_respects_limit(fresh_db: Path) -> None:
    h = "5678" * 16
    for i in range(5):
        create_job(
            job_id=f"job-{i}",
            source="file_import",
            client_name=None,
            language=None,
            task="transcribe",
            translation_target=None,
            audio_hash=h,
        )
    rows = find_by_audio_hash(h, limit=2)
    assert len(rows) == 2
