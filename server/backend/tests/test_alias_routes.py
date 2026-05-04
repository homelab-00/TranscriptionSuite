"""Tests for GET/PUT /api/notebook/recordings/{id}/aliases routes
(Issue #104, Story 4.2).

Direct-call pattern (per project CLAUDE.md): import the route module,
monkeypatch the repository functions, call handlers via asyncio.run().
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from fastapi import HTTPException
from server.api.routes import notebook
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
# GET — AC1
# ──────────────────────────────────────────────────────────────────────────


def test_get_returns_empty_array_for_recording_without_aliases(
    fresh_db: Path,
) -> None:
    _seed_recording(fresh_db, 1)
    resp = asyncio.run(notebook.list_recording_aliases(1))
    assert resp.recording_id == 1
    assert resp.aliases == []


def test_get_returns_aliases_when_present(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(
        1,
        [
            {"speaker_id": "SPEAKER_00", "alias_name": "Elena"},
            {"speaker_id": "SPEAKER_01", "alias_name": "Marco"},
        ],
    )
    resp = asyncio.run(notebook.list_recording_aliases(1))
    assert resp.recording_id == 1
    assert [a.speaker_id for a in resp.aliases] == ["SPEAKER_00", "SPEAKER_01"]
    assert [a.alias_name for a in resp.aliases] == ["Elena", "Marco"]


def test_get_404_when_recording_does_not_exist(fresh_db: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.list_recording_aliases(999_999))
    assert exc.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# PUT — AC2 (full-replace upsert)
# ──────────────────────────────────────────────────────────────────────────


def test_put_inserts_new_aliases(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    payload = notebook.AliasesPayload(
        aliases=[
            notebook.AliasItem(speaker_id="SPEAKER_00", alias_name="Elena"),
            notebook.AliasItem(speaker_id="SPEAKER_01", alias_name="Marco"),
        ]
    )
    resp = asyncio.run(notebook.update_recording_aliases(1, payload))
    assert {a.speaker_id for a in resp.aliases} == {"SPEAKER_00", "SPEAKER_01"}


def test_put_updates_existing_aliases(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}])
    payload = notebook.AliasesPayload(
        aliases=[notebook.AliasItem(speaker_id="SPEAKER_00", alias_name="Elena Vasquez")]
    )
    resp = asyncio.run(notebook.update_recording_aliases(1, payload))
    assert resp.aliases[0].alias_name == "Elena Vasquez"


def test_put_full_replace_drops_omitted_speakers(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(
        1,
        [
            {"speaker_id": "SPEAKER_00", "alias_name": "Elena"},
            {"speaker_id": "SPEAKER_01", "alias_name": "Marco"},
        ],
    )
    # Send only SPEAKER_00 — SPEAKER_01 must vanish
    payload = notebook.AliasesPayload(
        aliases=[notebook.AliasItem(speaker_id="SPEAKER_00", alias_name="Elena")]
    )
    resp = asyncio.run(notebook.update_recording_aliases(1, payload))
    assert {a.speaker_id for a in resp.aliases} == {"SPEAKER_00"}


def test_put_strips_whitespace_but_preserves_unicode(fresh_db: Path) -> None:
    """The route trims surrounding whitespace (whitespace is not part of a
    speaker name) but otherwise preserves the alias_name verbatim (R-EL3)."""
    _seed_recording(fresh_db, 1)
    payload = notebook.AliasesPayload(
        aliases=[
            notebook.AliasItem(
                speaker_id="SPEAKER_00",
                alias_name="  Dr. María José García-López  ",
            )
        ]
    )
    resp = asyncio.run(notebook.update_recording_aliases(1, payload))
    assert resp.aliases[0].alias_name == "Dr. María José García-López"


def test_put_drops_empty_alias_names(fresh_db: Path) -> None:
    """Empty / whitespace-only alias_name effectively clears the row."""
    _seed_recording(fresh_db, 1)
    alias_repository.replace_aliases(1, [{"speaker_id": "SPEAKER_00", "alias_name": "Elena"}])
    payload = notebook.AliasesPayload(
        aliases=[notebook.AliasItem(speaker_id="SPEAKER_00", alias_name="   ")]
    )
    resp = asyncio.run(notebook.update_recording_aliases(1, payload))
    # Empty after strip → drop from cleaned list → full-replace deletes the row
    assert resp.aliases == []


def test_put_404_when_recording_does_not_exist(fresh_db: Path) -> None:
    payload = notebook.AliasesPayload(aliases=[])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.update_recording_aliases(999_999, payload))
    assert exc.value.status_code == 404


def test_put_400_on_empty_speaker_id(fresh_db: Path) -> None:
    """speaker_id must be a non-empty token (review feedback MEDIUM-3)."""
    _seed_recording(fresh_db, 1)
    payload = notebook.AliasesPayload(
        aliases=[notebook.AliasItem(speaker_id="", alias_name="Elena")]
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.update_recording_aliases(1, payload))
    assert exc.value.status_code == 400


def test_put_400_on_whitespace_only_speaker_id(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    payload = notebook.AliasesPayload(
        aliases=[notebook.AliasItem(speaker_id="   ", alias_name="Elena")]
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.update_recording_aliases(1, payload))
    assert exc.value.status_code == 400


def test_put_400_on_nul_byte_in_speaker_id(fresh_db: Path) -> None:
    _seed_recording(fresh_db, 1)
    payload = notebook.AliasesPayload(
        aliases=[notebook.AliasItem(speaker_id="SPEAKER\x00_00", alias_name="Elena")]
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook.update_recording_aliases(1, payload))
    assert exc.value.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# AC3 — Persist-Before-Deliver
# ──────────────────────────────────────────────────────────────────────────


def test_put_response_returned_only_after_commit(fresh_db: Path) -> None:
    """The PUT response reflects the committed state. Verified by
    opening a SEPARATE sqlite3 connection AFTER the route returns and
    confirming the row is visible — proving the commit happened
    inside the route call (NFR16)."""
    _seed_recording(fresh_db, 1)
    payload = notebook.AliasesPayload(
        aliases=[notebook.AliasItem(speaker_id="SPEAKER_00", alias_name="Elena")]
    )
    resp = asyncio.run(notebook.update_recording_aliases(1, payload))
    assert resp.aliases[0].alias_name == "Elena"

    # External read confirms the data is durable
    with sqlite3.connect(fresh_db) as fresh_conn:
        rows = fresh_conn.execute(
            "SELECT speaker_id, alias_name FROM recording_speaker_aliases WHERE recording_id = ?",
            (1,),
        ).fetchall()
    assert rows == [("SPEAKER_00", "Elena")]
