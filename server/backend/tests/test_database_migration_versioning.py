"""Regression tests for Alembic version stamping during init_db()."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import server.database.database as db

pytest.importorskip("alembic")


def _read_alembic_versions(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        ).fetchall()
    return [str(row[0]) for row in rows]


def test_init_db_stamps_head_and_remains_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    # Isolate module-level database path globals for this test.
    monkeypatch.setattr(db, "_data_dir", None)
    monkeypatch.setattr(db, "_db_path", None)

    db.set_data_directory(data_dir)

    db.init_db()
    assert _read_alembic_versions(db.get_db_path()) == ["004"]

    db.init_db()
    assert _read_alembic_versions(db.get_db_path()) == ["004"]
