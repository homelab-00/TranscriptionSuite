"""Tests for alias_repository (Issue #104, Story 4.2).

Covers list/replace, full-replace semantics, verbatim guarantee (R-EL3),
and Persist-Before-Deliver (NFR16).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database import alias_repository

pytest.importorskip("alembic")


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


def _seed_recording(db_path: Path, recording_id: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (recording_id, "x.wav", "/tmp/x.wav", 1.0, "2025-01-15T12:00:00Z"),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# list_aliases
# ──────────────────────────────────────────────────────────────────────────


def test_list_empty_when_no_aliases(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    assert alias_repository.list_aliases(1) == []


def test_list_returns_aliases_ordered_by_speaker_id(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(
        1,
        [
            {"speaker_id": "SPEAKER_02", "alias_name": "Sami"},
            {"speaker_id": "SPEAKER_00", "alias_name": "Elena"},
            {"speaker_id": "SPEAKER_01", "alias_name": "Marco"},
        ],
    )
    rows = alias_repository.list_aliases(1)
    assert [r["speaker_id"] for r in rows] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]


# ──────────────────────────────────────────────────────────────────────────
# replace_aliases — upsert semantics
# ──────────────────────────────────────────────────────────────────────────


def test_replace_inserts_new_rows(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}])
    rows = alias_repository.list_aliases(1)
    assert rows == [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}]


def test_replace_updates_existing_alias_name(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}])
    alias_repository.replace_aliases(
        1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena Vasquez"}]
    )
    rows = alias_repository.list_aliases(1)
    assert rows == [{"speaker_id": "SPEAKER_00", "alias_name": "Elena Vasquez"}]


def test_replace_deletes_omitted_speaker_ids(fresh_db: Path) -> None:
    """Full-replace semantics: rows whose speaker_id is NOT in the
    incoming payload are deleted (Story 4.2 AC2)."""
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(
        1,
        [
            {"speaker_id": "SPEAKER_00", "alias_name": "Elena"},
            {"speaker_id": "SPEAKER_01", "alias_name": "Marco"},
        ],
    )
    # Now omit SPEAKER_01 — must be removed
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}])
    rows = alias_repository.list_aliases(1)
    assert rows == [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}]


def test_replace_with_empty_list_clears_all_aliases(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}])
    alias_repository.replace_aliases(1, [])
    assert alias_repository.list_aliases(1) == []


# ──────────────────────────────────────────────────────────────────────────
# alias_map convenience
# ──────────────────────────────────────────────────────────────────────────


def test_alias_map(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(
        1,
        [
            {"speaker_id": "SPEAKER_00", "alias_name": "Elena"},
            {"speaker_id": "SPEAKER_01", "alias_name": "Marco"},
        ],
    )
    assert alias_repository.alias_map(1) == {
        "SPEAKER_00": "Elena",
        "SPEAKER_01": "Marco",
    }


# ──────────────────────────────────────────────────────────────────────────
# Verbatim guarantee (R-EL3)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "alias_name",
    [
        "Dr. María José García-López",  # diacritics + hyphen
        "山田 太郎",  # CJK + space
        "Σωκράτης",  # Greek
        "Anne-Marie O'Connell",  # apostrophe + hyphen
        "ÆØÅ Smörgåsbord 𝓍",  # Astral plane char
    ],
)
def test_verbatim_alias_name_round_trip(fresh_db: Path, alias_name: str) -> None:
    """R-EL3: alias_name stored EXACTLY as supplied (no normalization)."""
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": alias_name}])
    rows = alias_repository.list_aliases(1)
    assert rows[0]["alias_name"] == alias_name
    # Byte-equivalent — no NFC/NFD normalization
    assert rows[0]["alias_name"].encode("utf-8") == alias_name.encode("utf-8")


# ──────────────────────────────────────────────────────────────────────────
# Persist-Before-Deliver (NFR16)
# ──────────────────────────────────────────────────────────────────────────


def test_replace_commits_before_returning(fresh_db: Path) -> None:
    """The repository write commits before returning. Asserted by reading
    the row through a SECOND, independent connection that opens AFTER
    replace_aliases() returns. If the data is visible, the commit
    finished before the function returned (NFR16)."""
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}])
    # Open a fresh connection — bypasses any in-flight transaction state
    with sqlite3.connect(fresh_db) as fresh_conn:
        rows = fresh_conn.execute(
            "SELECT speaker_id, alias_name FROM recording_speaker_aliases WHERE recording_id = ?",
            (1,),
        ).fetchall()
    assert rows == [("SPEAKER_00", "Elena")]
