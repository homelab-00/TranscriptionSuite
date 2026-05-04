"""Integration tests for create_job(profile_id=...) snapshot wiring (Issue #104, Story 1.3 hookup).

These tests close the gap that test_profile_snapshot_durability.py flagged:
the snapshot helper exists, but until this commit it was not actually called
by job_repository.create_job(). The deferred-work entry "Sprint 1 #5 — Story
1.3 hookup into transcription_jobs INSERT site" tracks this exact wiring.

Invariants verified here:
  - profile_id=N writes the frozen snapshot JSON + schema version into the
    transcription_jobs row (FR18 / ADR-008).
  - profile_id=None (legacy callers) leaves the snapshot columns NULL.
  - profile_id pointing at a deleted profile inserts the row WITHOUT a
    snapshot rather than failing the job — degraded but available, per the
    ADR-008 rehydration contract.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import server.database.database as db
from server.database import profile_repository
from server.database.job_repository import create_job

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


def _public() -> dict:
    return {
        "filename_template": "{date} {title}.txt",
        "destination_folder": "/tmp",
        "auto_summary_enabled": False,
        "auto_export_enabled": False,
        "summary_model_id": None,
        "summary_prompt_template": None,
        "export_format": "plaintext",
    }


def _read_job_row(db_path: Path, job_id: str) -> tuple[str | None, str | None]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT job_profile_snapshot, snapshot_schema_version FROM transcription_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    assert row is not None, f"job {job_id} not found"
    return row[0], row[1]


def test_create_job_with_profile_id_writes_snapshot(fresh_db: Path) -> None:
    """profile_id=N causes the INSERT to carry the frozen snapshot pair."""
    pid = profile_repository.create_profile(
        name="MyProfile",
        description=None,
        schema_version="1.0",
        public_fields=_public(),
    )

    create_job(
        job_id="job-with-profile",
        source="audio_upload",
        client_name="test-client",
        language="en",
        task="transcribe",
        translation_target=None,
        profile_id=pid,
    )

    snapshot_json, schema_version = _read_job_row(fresh_db, "job-with-profile")
    assert snapshot_json is not None, "snapshot must be written when profile_id is given"
    assert schema_version == "1.0"
    assert "MyProfile" in snapshot_json


def test_create_job_without_profile_id_leaves_snapshot_null(fresh_db: Path) -> None:
    """Legacy callers (no profile_id) must not regress — snapshot stays NULL."""
    create_job(
        job_id="job-legacy",
        source="audio_upload",
        client_name="test-client",
        language="en",
        task="transcribe",
        translation_target=None,
    )

    snapshot_json, schema_version = _read_job_row(fresh_db, "job-legacy")
    assert snapshot_json is None
    assert schema_version is None


def test_create_job_with_missing_profile_id_inserts_without_snapshot(
    fresh_db: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """If the profile was deleted between selection and job-start, the job
    is still created — degraded (no snapshot) but available. The worker
    falls back to legacy behaviour for that job."""
    create_job(
        job_id="job-orphan-profile",
        source="audio_upload",
        client_name="test-client",
        language="en",
        task="transcribe",
        translation_target=None,
        profile_id=999_999,  # nothing at this id
    )

    snapshot_json, schema_version = _read_job_row(fresh_db, "job-orphan-profile")
    assert snapshot_json is None
    assert schema_version is None


def test_create_job_snapshot_immune_to_post_create_profile_edit(fresh_db: Path) -> None:
    """FR18: editing the profile after the job is created does not mutate the
    job's stored snapshot. This is the same invariant as the helper-level
    test, but here verified end-to-end through the create_job path."""
    pid = profile_repository.create_profile(
        name="V1",
        description=None,
        schema_version="1.0",
        public_fields=_public(),
    )

    create_job(
        job_id="job-immune",
        source="audio_upload",
        client_name="test-client",
        language="en",
        task="transcribe",
        translation_target=None,
        profile_id=pid,
    )

    snapshot_before, _ = _read_job_row(fresh_db, "job-immune")
    assert snapshot_before is not None
    assert "V1" in snapshot_before

    profile_repository.update_profile(
        pid,
        name="V2",
        public_fields={**_public(), "filename_template": "EDITED.txt"},
    )

    snapshot_after, _ = _read_job_row(fresh_db, "job-immune")
    assert snapshot_after == snapshot_before, "stored snapshot must be immutable"
    assert "V2" not in snapshot_after
