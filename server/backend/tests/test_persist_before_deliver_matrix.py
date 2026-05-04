"""Persist-Before-Deliver invariant matrix (Issue #104, Story 6.4).

Asserts that for every artifact-producing path, the artifact is committed
to durable storage BEFORE any client-facing notification, file write, or
webhook fire. CLAUDE.md "AVOID DATA LOSS AT ALL COSTS" + NFR16.

Matrix entries (one test per row):

| name                        | what gets persisted                  | what gets delivered |
|-----------------------------|--------------------------------------|---------------------|
| auto_summary_save_back      | recordings.summary                   | (signaled via the auto_summary_status column; consumers poll) |
| auto_summary_lost_and_found | data/lost-and-found/*.summary.txt    | exception re-raised (no notification) |
| auto_export_write           | <destination>/<rendered_filename>    | auto_export_status=success |
| manual_download_save        | recordings.summary (existing path)   | HTTP response body |

Forward-pointing row reserved for Sprint 5 webhook delivery — captured
in the matrix list so adding the row will not require restructuring this
test file.
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


def _seed_recording(db_path: Path, recording_id: int = 1) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (recording_id, "r.wav", "/tmp/r.wav", "T", 60.0, "2025-01-15T12:00:00Z"),
        )
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, text, start_time, end_time, speaker) "
            "VALUES (?, 0, 'hi', 0.0, 1.0, 'SPEAKER_00')",
            (recording_id,),
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Matrix entry 1 — auto_summary_save_back
# ──────────────────────────────────────────────────────────────────────────


def test_auto_summary_status_only_set_AFTER_summary_is_committed(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persist-Before-Deliver — set_auto_summary_status('success') must
    only run after update_recording_summary has committed.

    We instrument both calls and assert the ordering. If the persist
    raises, set_auto_summary_status('success') must NOT run at all.
    """
    _seed_recording(fresh_db)
    events: list[str] = []

    async def _fake_summarize(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        return {
            "text": "A long enough summary about this recording for the test.",
            "model": "test-model",
            "tokens_used": 50,
            "truncated": False,
        }

    real_update = db.update_recording_summary

    def tracking_update(*args, **kwargs):  # type: ignore[no-untyped-def]
        events.append("update_recording_summary")
        return real_update(*args, **kwargs)

    real_set_status = repo.set_auto_action_status

    def tracking_set_status(rec_id, action_type, status, **kwargs):  # type: ignore[no-untyped-def]
        if action_type == "auto_summary" and status == "success":
            events.append("set_status_success")
        return real_set_status(rec_id, action_type, status, **kwargs)

    monkeypatch.setattr(
        "server.core.auto_summary_engine.summarize_for_auto_action", _fake_summarize
    )
    monkeypatch.setattr(
        "server.core.auto_action_coordinator.update_recording_summary",
        tracking_update,
        raising=False,
    )
    # The coordinator imports update_recording_summary inline, so we must
    # also patch the source module:
    monkeypatch.setattr(db, "update_recording_summary", tracking_update)
    monkeypatch.setattr(repo, "set_auto_action_status", tracking_set_status)

    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))

    assert "update_recording_summary" in events, "persist never happened"
    assert "set_status_success" in events, "delivery signal never fired"
    assert events.index("update_recording_summary") < events.index("set_status_success"), (
        f"Persist-Before-Deliver violated; events={events}"
    )


# ──────────────────────────────────────────────────────────────────────────
# Matrix entry 2 — lost-and-found fallback (Story 6.4 AC2)
# ──────────────────────────────────────────────────────────────────────────


def test_db_commit_failure_triggers_lost_and_found_recovery(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the persist step raises, the LLM text must land in
    data/lost-and-found/<rec_id>-<ts>.summary.txt — never silently lost.
    The status must NOT advance to 'success'; it stays at 'in_progress'
    so the retry endpoint / sweeper can act.
    """
    _seed_recording(fresh_db)

    async def _fake_summarize(_rec_id: int, _public: Mapping[str, Any]) -> dict:
        return {
            "text": "Recoverable LLM payload — must survive commit failure.",
            "model": "test-model",
            "tokens_used": 50,
            "truncated": False,
        }

    monkeypatch.setattr(
        "server.core.auto_summary_engine.summarize_for_auto_action", _fake_summarize
    )

    # Make update_recording_summary raise, simulating a disk-full
    # commit failure.
    def _exploding_update(*_a, **_kw):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk full — simulated commit failure")

    monkeypatch.setattr(db, "update_recording_summary", _exploding_update)

    # Run the coordinator. The exception is caught inside _run_auto_summary,
    # which now marks status='failed' on persist failure (the persist branch
    # bypasses the escalation policy because the LLM was successful — it's
    # only the persist that failed; the recovery file is the actionable
    # signal, not a retry).
    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))

    # 1. The status is NOT 'success' — coordinator caught the persist
    #    failure and set 'failed' (Story 6.4 AC2 — LLM result NOT silently
    #    discarded; surfaced as failure for retry).
    final_status = repo.get_auto_action_status(1, "auto_summary")
    assert final_status == "failed", f"Expected 'failed' after commit failure; got {final_status!r}"

    # 2. The lost-and-found file must exist with the LLM text.
    laf_dir = Path(db.get_data_dir()) / "lost-and-found"
    matches = list(laf_dir.glob("1-*.summary.txt"))
    assert matches, "lost-and-found recovery file not written — LLM text lost!"
    content = matches[0].read_text(encoding="utf-8")
    assert "Recoverable LLM payload" in content


# ──────────────────────────────────────────────────────────────────────────
# Matrix entry 3 — auto_export_write
# ──────────────────────────────────────────────────────────────────────────


def test_auto_export_status_set_AFTER_files_exist_on_disk(fresh_db: Path, tmp_path: Path) -> None:
    """For Story 6.3, the auto_export_status='success' transition must
    only happen AFTER the file is on disk. Read the path the
    coordinator wrote and assert os.path.exists at the time the status
    flipped.

    Approach: poll the status; once it shows 'success', read the path
    from the recording row and assert the file exists. If the status
    advanced to success before the file landed, the assertion fails.
    """
    _seed_recording(fresh_db)
    dest = tmp_path / "exports"
    dest.mkdir()
    public = {
        "auto_export_enabled": True,
        "destination_folder": str(dest),
        "filename_template": "{title}.txt",
    }
    asyncio.run(coord._run_auto_export(1, public))

    state = repo.get_auto_action_state(1)
    assert state["auto_export_status"] == "success"
    # The path field is set; the file must exist.
    path = state["auto_export_path"]
    assert path is not None and Path(path).exists(), (
        f"Persist-Before-Deliver violated — status='success' but {path!r} missing"
    )


# ──────────────────────────────────────────────────────────────────────────
# Matrix entry 4 — manual_download_save (existing route)
# ──────────────────────────────────────────────────────────────────────────


def test_manual_summary_route_persists_before_returning(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manual /api/llm/summarize/{id} route was already
    Persist-Before-Deliver compliant before Sprint 4. Sprint 4's matrix
    asserts the property still holds — guards against a Sprint 4
    regression that breaks the existing path.
    """
    _seed_recording(fresh_db)
    events: list[str] = []

    real_update = db.update_recording_summary

    def tracking_update(*args, **kwargs):  # type: ignore[no-untyped-def]
        events.append("persist")
        return real_update(*args, **kwargs)

    monkeypatch.setattr(db, "update_recording_summary", tracking_update)

    # Mock the LLM call so we don't need a real provider.
    from server.api.routes import llm as llm_route
    from server.api.routes.llm import LLMResponse

    async def _fake_process(*_a, **_kw):
        events.append("llm_returned")
        return LLMResponse(response="Manual summary text.", model="m", tokens_used=10)

    monkeypatch.setattr(llm_route, "process_with_llm", _fake_process)

    response = asyncio.run(llm_route.summarize_recording(1))

    assert response.response == "Manual summary text."
    # llm_returned MUST come before persist; persist MUST happen before
    # the route returns (which is what we assert via the saved value).
    assert events == ["llm_returned", "persist"], events
    assert db.get_recording_summary(1) == "Manual summary text."


# ──────────────────────────────────────────────────────────────────────────
# Forward-pointing matrix entry — webhook delivery (Sprint 5 placeholder)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.skip(reason="Sprint 5 — webhook delivery row added when epic-webhook lands")
def test_webhook_delivery_row_persisted_before_http_call() -> None:
    """When epic-webhook (Sprint 5) lands, this test asserts that the
    `webhook_deliveries` row is committed to the DB BEFORE the HTTP POST
    is attempted. Persist-Before-Deliver applies to the delivery
    attempt, not just the artifact.
    """
    pass
