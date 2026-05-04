"""Auto-action coordinator tests (Issue #104, Stories 6.2 + 6.3).

Covers:
  - HOLD predicate respected (Story 6.2 AC3 / R-EL10)
  - Save-back persists summary BEFORE delivery (NFR16)
  - Independence: each task in its own asyncio.Task (Story 6.5 preview)
  - Auto-export writes files atomically to destination (Story 6.3)
  - Profile snapshot persisted for retry continuity
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import server.database.database as db
from server.core import auto_action_coordinator as coord
from server.database import auto_action_repository as repo

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


def _seed_recording(db_path: Path, recording_id: int = 1, *, with_segment: bool = True) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (recording_id, "r.wav", "/tmp/r.wav", "Test", 60.0, "2025-01-15T12:00:00Z"),
        )
        if with_segment:
            conn.execute(
                "INSERT INTO segments (recording_id, segment_index, text, start_time, end_time, speaker) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (recording_id, 0, "Hello world.", 0.0, 5.0, "SPEAKER_00"),
            )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# trigger_auto_actions — toggle gating
# ──────────────────────────────────────────────────────────────────────────


def test_trigger_with_no_snapshot_is_noop(fresh_db: Path) -> None:
    asyncio.run(coord.trigger_auto_actions(1, None))
    # No status set
    assert repo.get_auto_action_status(1, "auto_summary") is None
    assert repo.get_auto_action_status(1, "auto_export") is None


def test_trigger_with_both_toggles_off_is_noop(fresh_db: Path) -> None:
    _seed_recording(fresh_db)
    snapshot = {"public_fields": {"auto_summary_enabled": False, "auto_export_enabled": False}}
    asyncio.run(coord.trigger_auto_actions(1, snapshot))
    assert repo.get_auto_action_status(1, "auto_summary") is None
    assert repo.get_auto_action_status(1, "auto_export") is None


def test_trigger_persists_profile_snapshot_when_at_least_one_toggle_on(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Snapshot is saved to recording row so retries replay the same profile."""
    _seed_recording(fresh_db)
    # Make auto_summary fail fast so the test doesn't need a real LLM
    monkeypatch.setattr(coord, "_run_auto_summary", _noop_async)
    monkeypatch.setattr(coord, "_run_auto_export", _noop_async)
    snapshot = {
        "profile_id": 7,
        "public_fields": {"auto_summary_enabled": True, "auto_export_enabled": False},
    }
    asyncio.run(coord.trigger_auto_actions(1, snapshot))
    saved = repo.get_profile_snapshot(1)
    assert saved is not None
    assert saved["profile_id"] == 7


async def _noop_async(*_args: object, **_kwargs: object) -> None:
    return None


# ──────────────────────────────────────────────────────────────────────────
# Auto-summary — HOLD respected
# ──────────────────────────────────────────────────────────────────────────


def test_auto_summary_held_when_review_pending(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story 6.2 AC3 / R-EL10 — HOLD blocks LLM call entirely."""
    _seed_recording(fresh_db)
    from server.core.diarization_review_lifecycle import on_transcription_complete

    on_transcription_complete(1, has_low_confidence_turn=True)

    # If the LLM is called, this raises. Ensures HOLD short-circuits before LLM.
    async def _explode(*_a: object, **_kw: object) -> dict:
        raise AssertionError("HOLD did not block — LLM was called")

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _explode)

    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))
    assert repo.get_auto_action_status(1, "auto_summary") == "held"


# ──────────────────────────────────────────────────────────────────────────
# Auto-summary — Persist-Before-Deliver (NFR16)
# ──────────────────────────────────────────────────────────────────────────


def test_auto_summary_success_persists_then_marks_status(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order: update_recording_summary → set status=success → on_auto_summary_fired.

    The set_auto_summary_status('success') call would never reach if the
    persist failed — the lost-and-found fallback re-raises. Asserting the
    final status of 'success' implicitly proves the persist landed first.
    """
    _seed_recording(fresh_db)

    async def _fake_summarize(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        return {
            "text": "This is a long enough summary about the recording.",
            "model": "test-model",
            "tokens_used": 50,
            "truncated": False,
        }

    monkeypatch.setattr(
        "server.core.auto_summary_engine.summarize_for_auto_action", _fake_summarize
    )

    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))

    assert repo.get_auto_action_status(1, "auto_summary") == "success"
    # Saved summary readable via the existing accessor
    summary = db.get_recording_summary(1)
    assert summary == "This is a long enough summary about the recording."


def test_auto_summary_failure_marks_status_failed(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_recording(fresh_db)
    from server.core.auto_summary_engine import AutoSummaryError

    async def _fail(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        raise AutoSummaryError("LLM unreachable")

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _fail)
    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))
    state = repo.get_auto_action_state(1)
    assert state["auto_summary_status"] == "failed"
    assert "LLM unreachable" in (state["auto_summary_error"] or "")


def test_auto_summary_empty_response_marks_summary_empty(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story 6.7 preview — <10 chars surfaces as summary_empty."""
    _seed_recording(fresh_db)

    async def _short(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        return {"text": "ok", "model": "m", "tokens_used": 1, "truncated": False}

    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", _short)
    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))
    assert repo.get_auto_action_status(1, "auto_summary") == "summary_empty"
    # Even though it's "empty", we still persist what we got so the user
    # can see / retry from the UI.
    assert db.get_recording_summary(1) == "ok"


# ──────────────────────────────────────────────────────────────────────────
# Auto-export — write to destination
# ──────────────────────────────────────────────────────────────────────────


def test_auto_export_writes_transcript_and_summary(fresh_db: Path, tmp_path: Path) -> None:
    """Story 6.3 — both transcript and summary land in destination."""
    _seed_recording(fresh_db)
    # Persist a summary on the recording first
    db.update_recording_summary(1, "Test summary content.", "test-model")

    dest = tmp_path / "exports"
    dest.mkdir()
    public = {
        "auto_export_enabled": True,
        "destination_folder": str(dest),
        "filename_template": "{title}.txt",
    }
    asyncio.run(coord._run_auto_export(1, public))

    transcript_path = dest / "Test.txt"
    summary_path = dest / "Test.txt.summary.txt"
    assert transcript_path.exists()
    assert summary_path.exists()
    assert summary_path.read_text() == "Test summary content."
    assert repo.get_auto_action_status(1, "auto_export") == "success"


def test_auto_export_no_summary_means_only_transcript(fresh_db: Path, tmp_path: Path) -> None:
    """Story 6.5 independence — auto-export does not wait for summary."""
    _seed_recording(fresh_db)
    dest = tmp_path / "exports"
    dest.mkdir()
    public = {
        "auto_export_enabled": True,
        "destination_folder": str(dest),
        "filename_template": "{title}.txt",
    }
    asyncio.run(coord._run_auto_export(1, public))

    assert (dest / "Test.txt").exists()
    assert not (dest / "Test.txt.summary.txt").exists()
    assert repo.get_auto_action_status(1, "auto_export") == "success"


def test_auto_export_missing_destination_marks_deferred(fresh_db: Path, tmp_path: Path) -> None:
    """Story 6.8 preview — missing destination flips to 'deferred'."""
    _seed_recording(fresh_db)
    dest = tmp_path / "does-not-exist"
    public = {
        "auto_export_enabled": True,
        "destination_folder": str(dest),
        "filename_template": "{title}.txt",
    }
    asyncio.run(coord._run_auto_export(1, public))

    state = repo.get_auto_action_state(1)
    assert state["auto_export_status"] == "deferred"
    assert state["auto_export_path"] == str(dest)


def test_auto_export_no_destination_marks_failed(fresh_db: Path) -> None:
    _seed_recording(fresh_db)
    public = {"auto_export_enabled": True, "destination_folder": ""}
    asyncio.run(coord._run_auto_export(1, public))
    assert repo.get_auto_action_status(1, "auto_export") == "failed"


# ──────────────────────────────────────────────────────────────────────────
# Atomic write semantics
# ──────────────────────────────────────────────────────────────────────────


def test_atomic_write_uses_tmp_and_replace(tmp_path: Path) -> None:
    """Story 6.10 preview — _write_atomic should use a .tmp sibling."""
    target = tmp_path / "out.txt"
    coord._write_atomic(target, "hello")
    assert target.read_text() == "hello"
    # No .tmp leftovers
    assert not (tmp_path / "out.txt.tmp").exists()


def test_atomic_write_overwrites_existing_in_place(tmp_path: Path) -> None:
    """Story 6.10 preview — re-write at the same path overwrites; no .1 suffix."""
    target = tmp_path / "out.txt"
    coord._write_atomic(target, "first")
    coord._write_atomic(target, "second")
    assert target.read_text() == "second"
    # Only one file at the path
    siblings = list(tmp_path.glob("out.*"))
    assert siblings == [target]


# ──────────────────────────────────────────────────────────────────────────
# Race-guard stubs (commit H wires the actual hook calls)
# ──────────────────────────────────────────────────────────────────────────


def test_race_guard_no_op_when_no_mutation_recorded() -> None:
    """Without a recorded alias mutation, quiescence returns immediately."""
    # Use a recording_id that's not in the dict
    result = asyncio.run(coord._wait_for_alias_quiescence(99999))
    assert result is True


def test_race_guard_proceeds_after_quiescence_window() -> None:
    """A mutation older than `window_s` is treated as quiet."""
    coord.notify_alias_mutation_started(42)
    coord.notify_alias_mutation_finished(42)
    # Move the timestamp far into the past
    coord._ALIAS_MUTATION_AT[42] = 0.0
    result = asyncio.run(coord._wait_for_alias_quiescence(42, window_s=0.5, timeout_s=0.5))
    assert result is True
    # Cleanup module state
    coord._ALIAS_MUTATION_AT.pop(42, None)
    coord._ALIAS_MUTATION_EVENTS.pop(42, None)
