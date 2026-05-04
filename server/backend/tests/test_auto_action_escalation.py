"""Story 6.11 — escalation policy + F1+F4 race-condition guard.

Escalation (R-EL18, NFR19):
  AC1: First failure schedules ONE auto-retry after a 30s backoff.
  AC2: Second failure escalates to 'manual_intervention_required'.
  AC2: No retry loop — sweeper does not re-fire 'manual_intervention_required'.

Race guard (cross-feature constraint #1):
  AC3: Auto-summary trigger waits for in-flight alias PUT to complete
       (within 2s window, with 10s timeout fallback).
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

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


def _seed(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recordings (id, filename, filepath, title, duration_seconds, recorded_at) "
            "VALUES (1, 'r.wav', '/tmp/r.wav', 'T', 60.0, '2025-01-15T12:00:00Z')"
        )
        conn.execute(
            "INSERT INTO segments (recording_id, segment_index, text, start_time, end_time, speaker) "
            "VALUES (1, 0, 'hi', 0.0, 1.0, 'SPEAKER_00')"
        )
        conn.commit()


# ──────────────────────────────────────────────────────────────────────────
# Escalation — AC1 + AC2
# ──────────────────────────────────────────────────────────────────────────


def test_first_failure_schedules_retry_pending(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First failure → status=retry_pending, attempts=1, retry scheduled."""
    _seed(fresh_db)

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(coord, "_delayed_retry", _noop)

    asyncio.run(coord._handle_auto_action_failure(1, "auto_summary", "transient"))
    state = repo.get_auto_action_state(1)
    assert state["auto_summary_status"] == "retry_pending"
    assert state["auto_summary_attempts"] == 1
    assert "transient" in (state["auto_summary_error"] or "")


def test_second_failure_escalates_to_manual(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second consecutive failure → status=manual_intervention_required."""
    _seed(fresh_db)

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(coord, "_delayed_retry", _noop)

    # First failure
    asyncio.run(coord._handle_auto_action_failure(1, "auto_summary", "first"))
    assert repo.get_auto_action_status(1, "auto_summary") == "retry_pending"
    assert repo.get_auto_action_attempts(1, "auto_summary") == 1

    # Second failure — escalates
    asyncio.run(coord._handle_auto_action_failure(1, "auto_summary", "second"))
    state = repo.get_auto_action_state(1)
    assert state["auto_summary_status"] == "manual_intervention_required"
    assert state["auto_summary_attempts"] == 2
    assert "second" in (state["auto_summary_error"] or "")


def test_export_escalation_preserves_destination_path(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escalation must keep auto_export_path so the badge can show the
    failed destination."""
    _seed(fresh_db)

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(coord, "_delayed_retry", _noop)

    asyncio.run(
        coord._handle_auto_action_failure(1, "auto_export", "permission denied", path="/mnt/usb")
    )
    asyncio.run(
        coord._handle_auto_action_failure(1, "auto_export", "permission denied", path="/mnt/usb")
    )
    state = repo.get_auto_action_state(1)
    assert state["auto_export_status"] == "manual_intervention_required"
    assert state["auto_export_path"] == "/mnt/usb"


# ──────────────────────────────────────────────────────────────────────────
# No retry loop after manual
# ──────────────────────────────────────────────────────────────────────────


def test_sweeper_skips_manual_intervention_required(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sweeper does not auto-retry rows in manual_intervention_required."""
    from server.core import auto_action_sweeper as sweeper

    _seed(fresh_db)
    repo.set_auto_export_status(
        1, "manual_intervention_required", error="exhausted", path="/mnt/usb"
    )

    fired = [False]

    async def _should_not_fire(_rec_id, _action_type):
        fired[0] = True

    monkeypatch.setattr(coord, "retry_auto_action_internal", _should_not_fire)
    asyncio.run(sweeper._sweep_once())
    assert fired[0] is False
    assert repo.get_auto_action_status(1, "auto_export") == "manual_intervention_required"


# ──────────────────────────────────────────────────────────────────────────
# F1+F4 race guard — AC3
# ──────────────────────────────────────────────────────────────────────────


def test_f1_waits_for_f4_alias_propagation() -> None:
    """Story 6.11 AC3 — auto-summary's quiescence wait blocks while an
    alias PUT is in flight, then proceeds when the PUT signals completion.
    """
    rec_id = 42

    async def runner() -> None:
        coord.notify_alias_mutation_started(rec_id)
        started = time.monotonic()

        async def finish_after_delay() -> None:
            await asyncio.sleep(0.2)
            coord.notify_alias_mutation_finished(rec_id)

        asyncio.create_task(finish_after_delay())
        result = await coord._wait_for_alias_quiescence(rec_id, window_s=2.0, timeout_s=5.0)
        elapsed = time.monotonic() - started

        # The waiter blocked until the event fired (~200ms)
        assert result is True
        assert elapsed >= 0.15

    asyncio.run(runner())

    # Cleanup module state
    coord._ALIAS_MUTATION_AT.pop(rec_id, None)
    coord._ALIAS_MUTATION_EVENTS.pop(rec_id, None)


def test_race_guard_timeout_fallback_proceeds() -> None:
    """If the alias PUT never completes within timeout_s, the waiter
    returns False and the caller proceeds anyway (using whatever aliases
    are committed). R-EL3 verbatim guarantee still holds."""
    rec_id = 43

    async def runner() -> None:
        coord.notify_alias_mutation_started(rec_id)
        # No `notify_alias_mutation_finished` — simulate a stuck PUT
        result = await coord._wait_for_alias_quiescence(rec_id, window_s=2.0, timeout_s=0.1)
        # Timeout fired; result=False but we proceed
        assert result is False

    asyncio.run(runner())

    coord._ALIAS_MUTATION_AT.pop(rec_id, None)
    coord._ALIAS_MUTATION_EVENTS.pop(rec_id, None)


def test_race_guard_outside_window_proceeds_immediately() -> None:
    """If the alias mutation finished more than window_s ago, the waiter
    returns True immediately — no blocking."""
    rec_id = 44

    async def runner() -> None:
        coord.notify_alias_mutation_started(rec_id)
        coord.notify_alias_mutation_finished(rec_id)
        # Backdate the timestamp far past the window
        coord._ALIAS_MUTATION_AT[rec_id] = 0.0

        started = time.monotonic()
        result = await coord._wait_for_alias_quiescence(rec_id, window_s=1.0, timeout_s=5.0)
        elapsed = time.monotonic() - started
        assert result is True
        assert elapsed < 0.05  # immediate

    asyncio.run(runner())

    coord._ALIAS_MUTATION_AT.pop(rec_id, None)
    coord._ALIAS_MUTATION_EVENTS.pop(rec_id, None)


# ──────────────────────────────────────────────────────────────────────────
# Coordinator integration — auto-summary calls quiescence guard
# ──────────────────────────────────────────────────────────────────────────


def test_run_auto_summary_calls_quiescence_guard(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inside _run_auto_summary, _wait_for_alias_quiescence is called
    BEFORE the LLM. A patched waiter records the call ordering."""
    _seed(fresh_db)

    events: list[str] = []

    async def fake_quiescence(*_a, **_kw):
        events.append("quiescence")
        return True

    async def fake_summary(_rec_id, _public):
        events.append("llm")
        return {"text": "Done.", "model": "m", "tokens_used": 5, "truncated": False}

    monkeypatch.setattr(coord, "_wait_for_alias_quiescence", fake_quiescence)
    monkeypatch.setattr("server.core.auto_summary_engine.summarize_for_auto_action", fake_summary)

    asyncio.run(coord._run_auto_summary(1, {"auto_summary_enabled": True}))

    assert events == ["quiescence", "llm"], f"order violated; events={events}"
