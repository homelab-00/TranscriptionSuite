"""Re-export endpoint tests (Issue #104, Story 3.6).

Covers:
  - AC1: notice rendering is a frontend concern; not tested here
  - AC2: forward-only — existing on-disk file is NOT touched by re-export
  - AC3: POST /api/notebook/recordings/{id}/reexport renders against the
    given profile's template, writes a new file, returns its path
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import server.database.database as db
from fastapi import HTTPException
from server.api.routes import notebook as notebook_route
from server.database import profile_repository

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


def _seed_recording(title: str = "Sample lecture") -> int:
    """Insert a recording + a couple of segments so reexport has content."""
    import sqlite3

    db_path = db.get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO recordings (filename, filepath, duration_seconds, "
            "recorded_at, title) VALUES (?, ?, ?, ?, ?)",
            ("input.wav", "/tmp/input.wav", 12.34, "2026-05-08T10:00:00Z", title),
        )
        rec_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, text, "
            "start_time, end_time) VALUES (?, ?, ?, ?, ?)",
            (rec_id, 0, "First sentence.", 0.0, 1.0),
        )
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, text, "
            "start_time, end_time, speaker) VALUES (?, ?, ?, ?, ?, ?)",
            (rec_id, 1, "Second sentence.", 1.0, 2.0, "Alice"),
        )
        conn.commit()
    return rec_id


def _seed_profile(template: str, destination: str) -> int:
    """Create a profile via the repository (commit-before-return guarantee)."""
    return profile_repository.create_profile(
        name="Sprint2 test",
        description=None,
        schema_version="1.0",
        public_fields={
            "filename_template": template,
            "destination_folder": destination,
            "auto_summary_enabled": False,
            "auto_export_enabled": False,
            "summary_model_id": None,
            "summary_prompt_template": None,
            "export_format": "plaintext",
        },
    )


# ──────────────────────────────────────────────────────────────────────────
# AC3.6.AC3 — POST renders + writes to disk
# ──────────────────────────────────────────────────────────────────────────


def test_reexport_writes_file_and_returns_path(fresh_db: Path, tmp_path: Path) -> None:
    rec_id = _seed_recording(title="Important meeting")
    destination = tmp_path / "exports"
    destination.mkdir()
    profile_id = _seed_profile(template="{date} - {title}.txt", destination=str(destination))

    body = notebook_route.ReexportRequest(profile_id=profile_id)
    result = asyncio.run(notebook_route.reexport_recording(rec_id, body))

    assert result.status == "reexported"
    assert result.filename == "2026-05-08 - Important meeting.txt"
    target = Path(result.path)
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    # FR9 paragraph format
    assert "**Alice:**" in content
    assert "First sentence." in content
    assert "Second sentence." in content


def test_reexport_returns_404_for_unknown_recording(fresh_db: Path) -> None:
    profile_id = _seed_profile("{title}.txt", "/tmp")
    body = notebook_route.ReexportRequest(profile_id=profile_id)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook_route.reexport_recording(99999, body))
    assert exc.value.status_code == 404


def test_reexport_returns_404_for_unknown_profile(fresh_db: Path) -> None:
    rec_id = _seed_recording()
    body = notebook_route.ReexportRequest(profile_id=99999)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook_route.reexport_recording(rec_id, body))
    assert exc.value.status_code == 404


def test_reexport_rejects_empty_destination(fresh_db: Path) -> None:
    rec_id = _seed_recording()
    profile_id = _seed_profile(template="{title}.txt", destination="")
    body = notebook_route.ReexportRequest(profile_id=profile_id)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(notebook_route.reexport_recording(rec_id, body))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "destination_folder_unset"


# ──────────────────────────────────────────────────────────────────────────
# AC3.6.AC2 — forward-only (does NOT delete prior export file)
# ──────────────────────────────────────────────────────────────────────────


def test_reexport_does_not_delete_prior_file(fresh_db: Path, tmp_path: Path) -> None:
    """A pre-existing file with a different name (from an earlier template)
    must remain on disk after re-export.
    """
    rec_id = _seed_recording(title="meeting")
    destination = tmp_path / "exports"
    destination.mkdir()
    legacy_path = destination / "old-name-template.txt"
    legacy_path.write_text("legacy content", encoding="utf-8")

    profile_id = _seed_profile(template="new-{title}.txt", destination=str(destination))
    body = notebook_route.ReexportRequest(profile_id=profile_id)
    result = asyncio.run(notebook_route.reexport_recording(rec_id, body))

    # Both files exist
    assert Path(result.path).exists()
    assert Path(result.path).name == "new-meeting.txt"
    assert legacy_path.exists()
    assert legacy_path.read_text(encoding="utf-8") == "legacy content"
