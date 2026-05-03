"""Recording deletion + on-disk artifact cleanup tests (Issue #104, Story 3.7).

Covers:
  - AC2: default (delete_artifacts=False) — DB row gone, audio file gone,
    on-disk transcript/summary EXPORTS untouched
  - AC3: opt-in (delete_artifacts=True with artifact_profile_id=N) —
    server derives the artifact path from the supplied profile's
    template + destination, renders + sanitizes, unlinks; failures
    surface in artifact_failures but do NOT block the DB delete (R-EL32)

Implementation note: notebook ``recordings`` rows don't carry a profile
snapshot, so the renderer supplies the *active* profile id at delete
time. The server fetches that profile and renders the path. If the
recording was originally exported with a different profile, the
derived path won't match — the file stays on disk, the user can clean
it up manually. See sprint-2-design.md §1.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from fastapi import HTTPException
from server.api.routes import notebook as notebook_route

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


def _seed_recording(fresh_db: Path, tmp_path: Path, *, title: str = "meeting") -> tuple[int, Path]:
    """Insert a recording with a real audio file on disk. Returns
    (recording_id, audio_path)."""
    audio_path = tmp_path / f"{title}.wav"
    audio_path.write_bytes(b"fake wav data")
    with sqlite3.connect(fresh_db) as conn:
        cursor = conn.execute(
            "INSERT INTO recordings (filename, filepath, duration_seconds, "
            "recorded_at, title) VALUES (?, ?, ?, ?, ?)",
            (
                f"{title}.wav",
                str(audio_path),
                12.34,
                "2026-05-08T10:00:00Z",
                title,
            ),
        )
        rec_id = cursor.lastrowid
        conn.commit()
    return rec_id, audio_path


# ──────────────────────────────────────────────────────────────────────────
# AC3.7.AC2 — default leaves on-disk artifacts UNTOUCHED
# ──────────────────────────────────────────────────────────────────────────


def test_default_delete_keeps_on_disk_artifacts(fresh_db: Path, tmp_path: Path) -> None:
    rec_id, audio_path = _seed_recording(fresh_db, tmp_path)
    artifact = tmp_path / "exports" / "transcript.txt"
    artifact.parent.mkdir()
    artifact.write_text("transcript content", encoding="utf-8")

    # Default — no delete_artifacts, no artifact_path
    result = asyncio.run(
        notebook_route.remove_recording(rec_id, delete_artifacts=False, artifact_profile_id=None)
    )

    assert result["status"] == "deleted"
    assert result["artifact_failures"] == []
    # Audio gone (existing behavior)
    assert not audio_path.exists()
    # Transcript file PRESERVED — the whole point of the default
    assert artifact.exists()
    assert artifact.read_text(encoding="utf-8") == "transcript content"


def _seed_profile(template: str, destination: str) -> int:
    """Helper — create a profile with the given template + destination."""
    from server.database import profile_repository

    return profile_repository.create_profile(
        name="ArtifactCleanupTest",
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


def test_explicit_unchecked_does_not_delete_artifact(fresh_db: Path, tmp_path: Path) -> None:
    """delete_artifacts=False with a profile_id STILL preserves the
    artifact — the boolean is the gate.
    """
    rec_id, _ = _seed_recording(fresh_db, tmp_path, title="meeting")
    destination = tmp_path / "exports"
    destination.mkdir()
    artifact = destination / "2026-05-08 - meeting.txt"
    artifact.write_text("summary content", encoding="utf-8")
    profile_id = _seed_profile(template="{date} - {title}.txt", destination=str(destination))

    result = asyncio.run(
        notebook_route.remove_recording(
            rec_id, delete_artifacts=False, artifact_profile_id=profile_id
        )
    )

    assert result["status"] == "deleted"
    assert artifact.exists()


# ──────────────────────────────────────────────────────────────────────────
# AC3.7.AC3 — opt-in derives + deletes the artifact path
# ──────────────────────────────────────────────────────────────────────────


def test_opt_in_delete_removes_derived_artifact(fresh_db: Path, tmp_path: Path) -> None:
    """The server renders the artifact filename from the supplied
    profile's template + destination_folder, finds the matching file
    on disk, and unlinks it.
    """
    rec_id, audio_path = _seed_recording(fresh_db, tmp_path, title="meeting")
    destination = tmp_path / "exports"
    destination.mkdir()
    # The exact path the server will derive: render_and_sanitize against
    # `{date} - {title}.txt` with date=2026-05-08, title="meeting"
    artifact = destination / "2026-05-08 - meeting.txt"
    artifact.write_text("transcript content", encoding="utf-8")
    profile_id = _seed_profile(template="{date} - {title}.txt", destination=str(destination))

    result = asyncio.run(
        notebook_route.remove_recording(
            rec_id,
            delete_artifacts=True,
            artifact_profile_id=profile_id,
        )
    )

    assert result["status"] == "deleted"
    assert result["artifact_failures"] == []
    assert not audio_path.exists()
    assert not artifact.exists()


def test_opt_in_delete_with_missing_profile_is_no_op_for_artifacts(
    fresh_db: Path, tmp_path: Path
) -> None:
    """Unknown profile id → no artifact derivation possible. DB + audio
    still deleted; no error raised."""
    rec_id, audio_path = _seed_recording(fresh_db, tmp_path)

    result = asyncio.run(
        notebook_route.remove_recording(
            rec_id,
            delete_artifacts=True,
            artifact_profile_id=99999,
        )
    )

    assert result["status"] == "deleted"
    assert result["artifact_failures"] == []
    assert not audio_path.exists()


def test_opt_in_delete_with_missing_artifact_no_failure(fresh_db: Path, tmp_path: Path) -> None:
    """Missing on-disk file (e.g. user pre-deleted it) is silent
    success — the .exists() guard skips."""
    rec_id, _ = _seed_recording(fresh_db, tmp_path, title="meeting")
    destination = tmp_path / "exports"
    destination.mkdir()  # destination exists but the artifact doesn't
    profile_id = _seed_profile(template="{date} - {title}.txt", destination=str(destination))

    result = asyncio.run(
        notebook_route.remove_recording(
            rec_id,
            delete_artifacts=True,
            artifact_profile_id=profile_id,
        )
    )

    assert result["status"] == "deleted"
    assert result["artifact_failures"] == []


def test_opt_in_delete_with_no_destination_folder_is_no_op(fresh_db: Path, tmp_path: Path) -> None:
    """Profile with no destination_folder configured → no path can be
    derived, no unlinks attempted."""
    rec_id, _ = _seed_recording(fresh_db, tmp_path)
    profile_id = _seed_profile(template="{date} - {title}.txt", destination="")

    result = asyncio.run(
        notebook_route.remove_recording(
            rec_id,
            delete_artifacts=True,
            artifact_profile_id=profile_id,
        )
    )

    assert result["status"] == "deleted"
    assert result["artifact_failures"] == []


# ──────────────────────────────────────────────────────────────────────────
# AC3.7.AC3 — failures surface but do NOT block the DB delete
# ──────────────────────────────────────────────────────────────────────────


def test_artifact_failure_does_not_block_db_delete(
    fresh_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate a permission-denied unlink on the derived artifact path.

    The DB row is still deleted; the failure is captured in
    artifact_failures rather than raised.
    """
    rec_id, audio_path = _seed_recording(fresh_db, tmp_path, title="meeting")
    destination = tmp_path / "exports"
    destination.mkdir()
    artifact = destination / "2026-05-08 - meeting.txt"
    artifact.write_text("content", encoding="utf-8")
    profile_id = _seed_profile(template="{date} - {title}.txt", destination=str(destination))

    real_unlink = Path.unlink

    def _maybe_failing_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if str(self) == str(artifact):
            raise PermissionError("simulated permission denied")
        return real_unlink(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "unlink", _maybe_failing_unlink)

    result = asyncio.run(
        notebook_route.remove_recording(
            rec_id,
            delete_artifacts=True,
            artifact_profile_id=profile_id,
        )
    )

    assert result["status"] == "deleted"
    assert str(artifact) in result["artifact_failures"]
    assert not audio_path.exists()  # other files still deleted


# ──────────────────────────────────────────────────────────────────────────
# Edge — 404 for unknown recording (existing behavior preserved)
# ──────────────────────────────────────────────────────────────────────────


def test_delete_unknown_recording_returns_404(fresh_db: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            notebook_route.remove_recording(99999, delete_artifacts=False, artifact_profile_id=None)
        )
    assert exc.value.status_code == 404
