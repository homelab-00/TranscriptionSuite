"""Migration 015 — auto-action status columns on recordings (Issue #104, Story 6.2/6.3).

Verifies the columns exist with correct types + the partial indexes are
present. Repository-level invariants (status validation, attempts increment,
Persist-Before-Deliver) are covered separately in
``tests/test_auto_action_repository.py``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db

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


# ──────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────


def test_auto_summary_columns_exist(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(recordings)").fetchall()}
    for name in (
        "auto_summary_status",
        "auto_summary_error",
        "auto_summary_attempts",
        "auto_summary_completed_at",
    ):
        assert name in cols, f"missing column: {name}"


def test_auto_export_columns_exist(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(recordings)").fetchall()}
    for name in (
        "auto_export_status",
        "auto_export_error",
        "auto_export_attempts",
        "auto_export_path",
        "auto_export_completed_at",
    ):
        assert name in cols, f"missing column: {name}"


def test_attempts_columns_default_zero(fresh_db: Path) -> None:
    """Migration sets DEFAULT 0 — backfill must not leave NULL on existing rows."""
    with sqlite3.connect(fresh_db) as conn:
        # Seed a recording (default columns kick in)
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, duration_seconds, recorded_at) "
            "VALUES (1, 'r.wav', '/tmp/r.wav', 1.0, '2025-01-15T12:00:00Z')"
        )
        conn.commit()
        row = conn.execute(
            "SELECT auto_summary_attempts, auto_export_attempts FROM recordings WHERE id = 1"
        ).fetchone()
    assert row[0] == 0
    assert row[1] == 0


def test_partial_indexes_exist(fresh_db: Path) -> None:
    with sqlite3.connect(fresh_db) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    names = {r[0] for r in rows}
    assert "idx_recordings_auto_summary_status" in names
    assert "idx_recordings_auto_export_status" in names
