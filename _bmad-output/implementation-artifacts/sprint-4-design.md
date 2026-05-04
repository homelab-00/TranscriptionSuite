---
sprint: 4
date: 2026-05-04
project: TranscriptionSuite
issue: 104
epic_set: [epic-auto-actions (E6) Stories 6.1–6.11]
prereq: Sprints 1–3 merged (gh-104-prd HEAD)
budget_dev_days: 10–12
target_loc_ceiling: ≤3500 LOC (sprint prompt cap)
ac_overrides_required: yes (URL-prefix, summary-status columns, sweeper-cadence)
---

# Sprint 4 — Auto-Actions (auto-summary + auto-export + retry + idempotency) Design

This sprint implements 11 stories that all hang off **one coordinator**:
`auto_action_coordinator.py`. The coordinator owns the lifecycle of every
auto-action artifact and enforces three invariants — Persist-Before-Deliver,
idempotent retry, and the F1+F4 race-condition guard.

The "central insight" of Sprint 4 is the same as Sprint 3 but inverted:
Sprint 3 was *read-time substitution* (alias lookup); Sprint 4 is
*write-time durability* (artifact persistence). Both ride on top of the
ADR-009 state machine — Sprint 4 uses the `auto_summary_is_held` predicate
already exposed in Sprint 3 commit G.

---

## 0. Sprint 1/2/3 prerequisite verification

Audit run before this design pass:

| Prerequisite | Path | Status |
|---|---|---|
| `recording_diarization_review` table + repo | migration 010, `database/diarization_review_repository.py` | PRESENT (Sprint 1) |
| `diarization_review_lifecycle.py` (state machine) | `server/backend/core/diarization_review_lifecycle.py` | PRESENT (Sprint 3) |
| `auto_summary_is_held(recording_id)` predicate | line 124 of above | PRESENT |
| `on_auto_summary_fired(recording_id)` trigger | line 108 of above | PRESENT (no production caller — Sprint 4 wires it) |
| `on_transcription_complete(recording_id, has_low_conf)` trigger | line 79 of above | PRESENT (**no production caller** — Sprint 4 wires it; documented in §1 override) |
| `per_turn_confidence(segments, words)` helper | `server/backend/core/diarization_confidence.py` | PRESENT (Sprint 3) |
| `apply_aliases(...)` substitution helper | `server/backend/core/alias_substitution.py` | PRESENT (Sprint 3) |
| `render_and_sanitize(template, recording)` filename helper | `server/backend/core/filename_template.py:199` | PRESENT (Sprint 2) |
| `update_recording_summary(rec_id, summary, model)` persistence | `server/backend/database/database.py:372` | PRESENT |
| `recordings.summary` + `recordings.summary_model` columns | `database.py` | PRESENT |
| `LLMClient.summarize(...)` / `summarize_recording` route | `api/routes/llm.py:778` | PRESENT |
| `ProfilePublicFields` Pydantic model | `api/routes/profiles.py:62` | PRESENT (`auto_summary_enabled`, `auto_export_enabled`, `destination_folder`, `filename_template`, `export_format` all already on the model) |
| `transcription_jobs.job_profile_snapshot` JSON column | migration 009 | PRESENT (read at completion time) |
| `StatusLight` UI primitive | `dashboard/components/ui/StatusLight.tsx` | PRESENT (Sprint 1) — extend, don't rewrite |
| `useAriaAnnouncer` + ARIA live region | `dashboard/src/hooks/useAriaAnnouncer.ts`, `dashboard/components/AriaLiveRegion.tsx` | PRESENT |
| `audio_cleanup.periodic_cleanup` async-loop pattern | `database/audio_cleanup.py:18` | PRESENT (template for sweeper) |
| Migrations 008–014 in place | `database/migrations/versions/` | PRESENT (next free = **015**) |

All Sprint 4 work can build on these. The two missing wirings —
`on_transcription_complete` and `on_auto_summary_fired` — are explicit
Sprint 4 deliverables, not regressions.

---

## 1. Inline AC overrides (read first)

| AC literal text | Reality | Override |
|---|---|---|
| Story 6.9 AC1: `POST /api/recordings/{id}/auto-actions/retry` | Same router-prefix collision as Sprint 3 (no top-level `/api/recordings/*` router; recordings live under `/api/notebook/recordings/*`). | Mount as `POST /api/notebook/recordings/{id}/auto-actions/retry`. URL-shape difference is purely a prefix; the contract (path-tail + body) is intact. Same precedent as Sprint 3 (Story 4.2 aliases endpoint, Story 5.4 confidence endpoint). |
| Story 6.2 AC1: hook fires "within 2s of completion" measured by `frozen_clock` fixture | The notebook completion path runs inside `_run_transcription()` (a thread spawned via `asyncio.to_thread`); fire-and-forget dispatch is the natural shape. | Hook fires via `asyncio.create_task(coordinator.trigger_auto_actions(recording_id))` immediately after `save_longform_to_database` returns. The 2s budget is enforced by a unit test that mocks the LLM client and asserts `time.monotonic()` delta from `save_longform_to_database` return → coordinator's first LLM-client call < 2.0s. No frozen_clock needed; the LLM call itself is mocked. |
| Story 6.4 AC2: simulated DB-commit failure must not silently discard LLM result | `update_recording_summary` is one SQL statement; a failure mid-statement cannot lose anything because nothing was persisted. The "data loss" risk is a different shape: the LLM returned a 4kB summary, then `commit()` fails (disk-full or constraint). | Coordinator wraps the persist in `try: update_recording_summary(...) except Exception: log + write LLM result to a `data/lost-and-found/<rec_id>-<timestamp>.summary.txt` recovery file, then re-raise so retry can act`. Sprint 4's regression test asserts the recovery file exists. CLAUDE.md "AVOID DATA LOSS AT ALL COSTS" satisfied. |
| Story 6.6 AC1: badge uses `StatusLight` primitive (UX-DR1) | Existing `StatusLight.tsx` is a *colored dot* primitive — `status: 'active'\|'inactive'\|'warning'\|'error'\|'loading'`. It does NOT include label, retry button, or accessibility plumbing per Story 6.6. | Create `AutoActionStatusBadge.tsx` wrapping `StatusLight` + adding label, retry button, and `aria-live` plumbing. Map Story-6.6 severities to existing StatusLight statuses: `ok→active`, `warn→warning`, `error→error`, `processing→loading`, `manual_intervention_required→error`. Both layers are kept; the new component is the consumer-facing surface. |
| Story 6.8 AC2: periodic sweeper "uses existing periodic-task pattern from CLAUDE.md project-context — `async def periodic_deferred_export_sweep()` with 30s interval" | The existing pattern (`audio_cleanup.periodic_cleanup`) has a 24-hour default interval, not 30s. 30s is fine for production semantics but produces test-suite churn (sleeps add latency to every CI run). | Sweeper interval is configurable via `config.yaml::auto_actions.deferred_export_sweep_interval_s` (default **30s in production, 0.1s in tests via fixture override**). The interval is a parameter, not a hard-coded constant. |
| Story 6.11 AC3: "alias-substitution cache is fresh" | There is no in-process alias cache on the backend — alias lookups go directly to SQLite via `alias_repository.list_aliases()` on every read. The "cache freshness" condition is therefore vacuously true. | The race guard simplifies to: "no in-flight `PUT /api/recordings/{id}/aliases` mutations within the last 2s". Implemented as a module-level `_alias_mutation_at: dict[int, float]` updated by the alias-PUT route + a small asyncio.Event per recording id. |
| Story 6.11 AC1: "30s backoff" before auto-retry | A literal `await asyncio.sleep(30)` inside the coordinator blocks the calling task; if the server shuts down during the sleep, the retry is lost and we have a "did the auto-action retry happen?" mystery. | Schedule the retry via `asyncio.create_task(_delayed_retry(rec_id, action, delay_s=30))` and persist `auto_*_status='retry_pending'` BEFORE the sleep. On clean shutdown, the task is cancelled — and the row stays at `retry_pending`, picked up by the sweeper on next start (which treats `retry_pending` like `deferred` for the purposes of re-firing). No lost retries. |

**Not an override but worth recording:** `recordings` is the right table
for status columns. Per-recording auto-action state is 1:1 with recording
(no fan-out), and the column count is bounded (≤8 new columns). A separate
`recording_auto_actions` table would be over-normalized. We accept the wider
recordings row; SQLite handles it efficiently.

---

## 2. Architectural through-lines

### 2.1 The Persist-Before-Deliver invariant (Story 6.4 backbone)

```
                                LLM returns
                                    │
                                    ▼
                     ┌──────────────────────────┐
                     │  recordings.summary = X  │
                     │  status = 'success'      │   ← committed first
                     │  COMMIT                  │
                     └──────────────┬───────────┘
                                    │
                            ┌───────┴────────┐
                            ▼                ▼
                     websocket "done"   on_auto_summary_fired()
                                            │
                                            ▼
                                  status='released' (ADR-009)
```

The chain is **strictly sequential**. `update_recording_summary` already
commits inside `with get_connection() as conn:`. The coordinator must NOT
fire the websocket before that returns. **Test:** monkeypatch
`sqlite3.Connection.commit` to raise — assert the websocket event is not
emitted, the LLM result lands in `data/lost-and-found/`, and the row stays
at `auto_summary_status='processing'` so retry can act.

### 2.2 The auto-action coordinator (single source of truth)

```python
# server/backend/core/auto_action_coordinator.py — NEW
"""Auto-action coordinator (Issue #104, Stories 6.2–6.11).

Single entry point for all auto-action lifecycles. Owns:

- HOLD predicate consultation (Story 5.8, R-EL10)
- F1+F4 race-condition guard (Story 6.11, cross-feature constraint #1)
- Persist-Before-Deliver invariant (Story 6.4, NFR16)
- Per-action independence (Story 6.5)
- One auto-retry then escalate (Story 6.11, R-EL18)
- Idempotency on retry (Story 6.9, R-EL27)

NOT a singleton or a service object — a module of pure functions plus a
small in-process state for the race guard. Tests can monkeypatch
freely without container plumbing.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from server.core.diarization_review_lifecycle import (
    auto_summary_is_held,
    on_auto_summary_fired,
)
from server.core.filename_template import render_and_sanitize
from server.database import auto_action_repository as repo

logger = logging.getLogger(__name__)

# F1+F4 race-condition guard: per-recording last-mutation timestamp +
# asyncio.Event signaling "alias PUT is in-flight". The alias PUT route
# (Sprint 3 commit A) calls `notify_alias_mutation_started(rec_id)` and
# `notify_alias_mutation_finished(rec_id)`. Auto-summary consults
# `_within_alias_mutation_window(rec_id, 2.0)` and awaits the event with
# a 10s timeout if so.
_ALIAS_MUTATION_AT: dict[int, float] = {}
_ALIAS_MUTATION_EVENTS: dict[int, asyncio.Event] = {}
_RACE_GUARD_LOCK = asyncio.Lock()  # serializes _ALIAS_MUTATION_* updates


def notify_alias_mutation_started(recording_id: int) -> None:
    """Called by alias-PUT route on entry."""
    ev = _ALIAS_MUTATION_EVENTS.setdefault(recording_id, asyncio.Event())
    ev.clear()
    _ALIAS_MUTATION_AT[recording_id] = time.monotonic()


def notify_alias_mutation_finished(recording_id: int) -> None:
    """Called by alias-PUT route on exit (success OR failure)."""
    _ALIAS_MUTATION_AT[recording_id] = time.monotonic()
    ev = _ALIAS_MUTATION_EVENTS.get(recording_id)
    if ev is not None:
        ev.set()


async def _wait_for_alias_quiescence(
    recording_id: int, *, window_s: float = 2.0, timeout_s: float = 10.0
) -> bool:
    """Block until no alias mutation has happened in the last `window_s`.

    Returns True if quiet, False if timeout was hit (caller should still
    proceed — the auto-summary fallback uses whatever aliases happen to
    be committed at the time, which is correct under R-EL3).
    """
    last_at = _ALIAS_MUTATION_AT.get(recording_id)
    if last_at is None or (time.monotonic() - last_at) >= window_s:
        return True
    ev = _ALIAS_MUTATION_EVENTS.get(recording_id)
    if ev is None:
        return True
    try:
        await asyncio.wait_for(ev.wait(), timeout=timeout_s)
        return True
    except asyncio.TimeoutError:
        logger.warning(
            "auto_summary_race_guard_timeout recording_id=%d (proceeding with current aliases)",
            recording_id,
        )
        return False


async def trigger_auto_actions(
    recording_id: int, profile_snapshot: Mapping[str, Any] | None
) -> None:
    """Entry point called from notebook upload completion path.

    Reads profile snapshot toggles. Fires auto-summary and auto-export
    independently — neither blocks the other (Story 6.5). Each is its
    own asyncio.Task so an exception in one does not propagate to the
    other.
    """
    if not profile_snapshot:
        return
    public = profile_snapshot.get("public_fields") or {}
    tasks: list[asyncio.Task] = []
    if public.get("auto_summary_enabled"):
        tasks.append(asyncio.create_task(_run_auto_summary(recording_id, public)))
    if public.get("auto_export_enabled"):
        tasks.append(asyncio.create_task(_run_auto_export(recording_id, public)))
    if tasks:
        # gather() with return_exceptions=True so one failure does not
        # cancel the other. Per-task error handling lives inside each.
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run_auto_summary(recording_id: int, public: Mapping[str, Any]) -> None:
    """Story 6.2 lifecycle. HOLD-aware. Persist-Before-Deliver."""
    from server.core.llm_client import summarize_recording_for_auto_action

    # 1. HOLD check (R-EL10) — if held, mark and return.
    if auto_summary_is_held(recording_id):
        repo.set_auto_summary_status(recording_id, "held")
        return

    # 2. F1+F4 race guard (Story 6.11, cross-feature constraint #1).
    await _wait_for_alias_quiescence(recording_id)

    # 3. Mark in-flight BEFORE the LLM call so retries can detect "stuck".
    repo.set_auto_summary_status(recording_id, "in_progress")

    try:
        result = await summarize_recording_for_auto_action(recording_id, public)
    except Exception as exc:  # transient LLM failure
        await _handle_auto_action_failure(recording_id, "auto_summary", str(exc))
        return

    # 4. Empty / truncated detection (Stories 6.7).
    summary_text = result.get("text") or ""
    if len(summary_text.strip()) < 10:
        repo.set_auto_summary_status(recording_id, "summary_empty")
        # We still persist the (empty) result so the user sees what we got.
        _persist_summary_with_durability_guard(recording_id, summary_text, result.get("model"))
        return
    if result.get("truncated"):
        repo.set_auto_summary_status(recording_id, "summary_truncated")
        _persist_summary_with_durability_guard(recording_id, summary_text, result.get("model"))
        return

    # 5. Success path — Persist-Before-Deliver.
    _persist_summary_with_durability_guard(recording_id, summary_text, result.get("model"))
    repo.set_auto_summary_status(recording_id, "success")
    on_auto_summary_fired_safe(recording_id)
    # Caller layer is responsible for the websocket emit; we do not emit here.


def _persist_summary_with_durability_guard(
    recording_id: int, summary: str, model: str | None
) -> None:
    """Wrap update_recording_summary with a lost-and-found fallback.

    If commit() raises (disk-full, constraint, anything), write the LLM
    text to data/lost-and-found/<rec_id>-<ts>.summary.txt before re-raising
    so the result is recoverable. CLAUDE.md "AVOID DATA LOSS AT ALL COSTS".
    """
    from server.database.database import update_recording_summary

    try:
        update_recording_summary(recording_id, summary, model)
    except Exception:
        _write_lost_and_found(recording_id, "summary", summary)
        raise


def on_auto_summary_fired_safe(recording_id: int) -> None:
    """Wrap on_auto_summary_fired so an illegal-transition (no review row,
    or review row already at 'released') does not propagate as an error.

    The state machine is strict, but the caller — auto-summary success —
    fires regardless of whether the review row exists. If no row exists,
    the transition is a no-op; if the row is already 'released', also a
    no-op. Anything else is genuinely illegal.
    """
    from server.core.diarization_review_lifecycle import (
        IllegalReviewTransitionError,
        current_status,
    )

    status = current_status(recording_id)
    if status is None or status == "released":
        return
    if status != "completed":
        # The review row is still in 'pending' or 'in_review' — auto-summary
        # should have been HELD by step 1 of _run_auto_summary. Reaching
        # here is a real bug; log and skip the transition instead of crashing.
        logger.error(
            "auto_summary_fired_in_illegal_state recording_id=%d status=%r — "
            "HOLD predicate did not block; investigate",
            recording_id,
            status,
        )
        return
    try:
        on_auto_summary_fired(recording_id)
    except IllegalReviewTransitionError:
        logger.exception("on_auto_summary_fired raced with another transition")


async def _run_auto_export(
    recording_id: int, public: Mapping[str, Any], *, force: bool = False
) -> None:
    """Story 6.3 + 6.5 + 6.8 + 6.10 lifecycle.

    Independence (6.5): does NOT consult auto_summary status. If a summary
    exists at write-time (whether produced by auto-summary or manually),
    it gets exported alongside the transcript; if not, only the transcript
    is exported.

    Deferred-retry (6.8): destination missing → status='deferred', sweeper
    re-fires.

    Idempotent re-export (6.10): writes to .tmp sibling, then os.replace.
    """
    from server.database.database import get_recording

    recording = get_recording(recording_id)
    if not recording:
        repo.set_auto_export_status(recording_id, "failed", error="recording missing")
        return

    destination = (public.get("destination_folder") or "").strip()
    if not destination:
        repo.set_auto_export_status(recording_id, "failed", error="no destination configured")
        return

    repo.set_auto_export_status(recording_id, "in_progress")

    if not os.path.isdir(destination):
        # Story 6.8 deferred-retry on destination unavailability.
        repo.set_auto_export_status(
            recording_id,
            "deferred",
            error=f"destination not available: {destination}",
            path=destination,
        )
        return

    template = public.get("filename_template") or "{date} {title}.txt"
    rendered = render_and_sanitize(template, dict(recording))
    base = Path(destination) / rendered

    try:
        # Transcript is always written.
        await asyncio.to_thread(_write_transcript_atomic, base, recording_id)
        # Summary is written only if present in DB (Story 6.5 independence).
        summary = recording.get("summary")
        if summary:
            summary_path = base.with_suffix(base.suffix + ".summary.txt")
            await asyncio.to_thread(_write_atomic, summary_path, summary)
        repo.set_auto_export_status(recording_id, "success", path=str(base))
    except (FileNotFoundError, PermissionError, OSError) as exc:
        await _handle_auto_action_failure(recording_id, "auto_export", str(exc))


def _write_atomic(target: Path, content: str) -> None:
    """Story 6.10: write to .tmp sibling, then os.replace.

    `os.replace` is atomic on POSIX and Windows; concurrent retries either
    win or lose the race, but never produce a half-written file.
    """
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, target)


def _write_transcript_atomic(base: Path, recording_id: int) -> None:
    """Build plaintext via existing exporter and write atomically."""
    from server.core.alias_substitution import apply_aliases
    from server.core.plaintext_export import stream_plaintext
    from server.database.alias_repository import list_aliases
    from server.database.database import get_recording, get_segments

    recording = get_recording(recording_id) or {}
    segments = get_segments(recording_id)
    aliases = {a["speaker_id"]: a["alias_name"] for a in list_aliases(recording_id)}
    text = "".join(stream_plaintext(recording, apply_aliases(segments, aliases)))
    _write_atomic(base, text)


async def _handle_auto_action_failure(
    recording_id: int, action_type: str, error: str
) -> None:
    """Escalation policy (Story 6.11): one auto-retry, then manual.

    Reads `attempts` from the row. If 0 → schedule a 30s-delayed retry as
    a separate asyncio task and set status='retry_pending'. If ≥1 → set
    status='manual_intervention_required' and stop.
    """
    attempts = repo.get_auto_action_attempts(recording_id, action_type)
    if attempts >= 1:
        repo.set_auto_action_status(
            recording_id, action_type, "manual_intervention_required", error=error
        )
        return
    repo.set_auto_action_status(recording_id, action_type, "retry_pending", error=error)
    repo.increment_auto_action_attempts(recording_id, action_type)
    asyncio.create_task(_delayed_retry(recording_id, action_type, delay_s=30.0))


async def _delayed_retry(recording_id: int, action_type: str, *, delay_s: float) -> None:
    try:
        await asyncio.sleep(delay_s)
    except asyncio.CancelledError:
        return  # row stays at retry_pending; sweeper will pick it up
    await retry_auto_action_internal(recording_id, action_type)


async def retry_auto_action_internal(recording_id: int, action_type: str) -> None:
    """Idempotent retry (Story 6.9). Loads profile snapshot from the
    transcription_jobs row associated with this recording.

    Exposed via the HTTP endpoint POST /auto-actions/retry as well — both
    paths funnel here.
    """
    from server.database.job_repository import get_job_for_recording

    job = get_job_for_recording(recording_id)
    snapshot = (job or {}).get("job_profile_snapshot") or {}
    public = (snapshot.get("public_fields") or {})

    if action_type == "auto_summary":
        await _run_auto_summary(recording_id, public)
    elif action_type == "auto_export":
        await _run_auto_export(recording_id, public, force=True)
    else:
        raise ValueError(f"unknown action_type: {action_type!r}")


def _write_lost_and_found(recording_id: int, kind: str, content: str) -> None:
    """Last-resort recovery write — never raises."""
    try:
        from server.config import get_config

        cfg = get_config()
        out_dir = Path(cfg.data_dir) / "lost-and-found"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        path = out_dir / f"{recording_id}-{ts}.{kind}.txt"
        path.write_text(content, encoding="utf-8")
        logger.warning("Wrote lost-and-found recovery: %s", path)
    except Exception:
        logger.exception("lost-and-found write itself failed; LLM result may be lost")
```

The coordinator's public surface is small: `trigger_auto_actions`,
`retry_auto_action_internal`, plus the two `notify_alias_mutation_*` hooks.
Everything else is module-private.

### 2.3 Status columns on `recordings` (migration 015)

```sql
-- migration 015 — auto-action status tracking
ALTER TABLE recordings ADD COLUMN auto_summary_status TEXT;
ALTER TABLE recordings ADD COLUMN auto_summary_error TEXT;
ALTER TABLE recordings ADD COLUMN auto_summary_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE recordings ADD COLUMN auto_summary_completed_at TIMESTAMP;

ALTER TABLE recordings ADD COLUMN auto_export_status TEXT;
ALTER TABLE recordings ADD COLUMN auto_export_error TEXT;
ALTER TABLE recordings ADD COLUMN auto_export_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE recordings ADD COLUMN auto_export_path TEXT;
ALTER TABLE recordings ADD COLUMN auto_export_completed_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_recordings_auto_summary_status
    ON recordings(auto_summary_status) WHERE auto_summary_status IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_recordings_auto_export_status
    ON recordings(auto_export_status) WHERE auto_export_status IS NOT NULL;
```

**Status enum** (TEXT, no CHECK constraint per project policy — enforced
at the repository layer):

| value | meaning |
|---|---|
| `NULL` | not applicable (toggle was off, or recording predates Sprint 4) |
| `pending` | scheduled but not yet started — used by retry endpoint |
| `in_progress` | LLM call / file write in flight |
| `success` | committed; on_auto_summary_fired called |
| `summary_empty` | LLM returned <10 chars (Story 6.7 AC1) — amber |
| `summary_truncated` | LLM signaled token-limit truncation (Story 6.7 AC2) — amber |
| `held` | HOLD predicate true at trigger time (R-EL10) |
| `deferred` | export destination missing (Story 6.8) |
| `retry_pending` | one auto-retry scheduled (Story 6.11) |
| `failed` | terminal failure that has not yet escalated (transient) |
| `manual_intervention_required` | one auto-retry exhausted (Story 6.11) |

The two indexes are partial (`WHERE ... IS NOT NULL`) so they cover only
the rows the sweeper and retry endpoint actually scan.

`downgrade()` raises `RuntimeError("forward-only migration — see NFR22")`.

### 2.4 Periodic deferred-export sweeper (Story 6.8 backbone)

Modeled exactly on `database/audio_cleanup.py::periodic_cleanup`:

```python
# server/backend/core/auto_action_sweeper.py — NEW
async def periodic_deferred_export_sweep(interval_s: float = 30.0) -> None:
    """Re-fire auto-export for rows where destination came back online.

    Cancel-safe — `asyncio.CancelledError` exits cleanly; in-flight
    re-exports are NOT interrupted. Bootstrap-safe — picks up
    retry_pending and deferred rows that survived a restart (NFR24a).
    """
    while True:
        try:
            await _sweep_once()
        except Exception:
            logger.exception("deferred-export sweep failed; will retry next interval")
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            logger.info("Periodic deferred-export sweep cancelled (shutdown)")
            return


async def _sweep_once() -> None:
    rows = await asyncio.to_thread(repo.list_pending_auto_actions)
    for row in rows:
        rec_id = row["id"]
        if row["auto_export_status"] in {"deferred", "retry_pending"}:
            destination = row["auto_export_path"] or ""
            if destination and os.path.isdir(destination):
                await retry_auto_action_internal(rec_id, "auto_export")
        if row["auto_summary_status"] == "retry_pending":
            await retry_auto_action_internal(rec_id, "auto_summary")
```

Lifespan wiring is identical to `audio_cleanup` — one line in `main.py`'s
`lifespan` async-generator.

### 2.5 Idempotent retry endpoint (Story 6.9 backbone)

```python
# api/routes/notebook.py — additions
class AutoActionRetryRequest(BaseModel):
    action_type: Literal["auto_summary", "auto_export"]


class AutoActionRetryResponse(BaseModel):
    recording_id: int
    action_type: str
    status: str  # "retry_initiated" | "already_complete" | "already_in_progress"


@router.post(
    "/recordings/{recording_id}/auto-actions/retry",
    response_model=AutoActionRetryResponse,
)
async def retry_auto_action(
    recording_id: int, payload: AutoActionRetryRequest
) -> AutoActionRetryResponse:
    if not get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    current = repo.get_auto_action_status(recording_id, payload.action_type)
    # Idempotent on success — Story 6.9 AC2 / R-EL27.
    if current == "success":
        return AutoActionRetryResponse(
            recording_id=recording_id,
            action_type=payload.action_type,
            status="already_complete",
        )
    # Don't double-fire while already in-flight.
    if current in {"in_progress", "pending"}:
        return AutoActionRetryResponse(
            recording_id=recording_id,
            action_type=payload.action_type,
            status="already_in_progress",
        )

    # Reset attempts so manual retry is treated as a fresh attempt
    # (escalation only counts AUTO retries — R-EL18 specifies "automatic
    # retry exhausted", not "user gave up trying").
    repo.reset_auto_action_attempts(recording_id, payload.action_type)
    repo.set_auto_action_status(recording_id, payload.action_type, "pending")
    asyncio.create_task(retry_auto_action_internal(recording_id, payload.action_type))
    return AutoActionRetryResponse(
        recording_id=recording_id,
        action_type=payload.action_type,
        status="retry_initiated",
    )
```

HTTP-status mapping per AC1: `retry_initiated` → 202, `already_complete`
→ 200, `already_in_progress` → 200.

### 2.6 F1+F4 race-condition guard wiring

Two call sites:

```python
# api/routes/notebook.py — alias PUT route (Sprint 3 commit A)
@router.put("/recordings/{recording_id}/aliases", ...)
async def update_recording_aliases(recording_id: int, payload: AliasesPayload):
    from server.core.auto_action_coordinator import (
        notify_alias_mutation_started,
        notify_alias_mutation_finished,
    )

    notify_alias_mutation_started(recording_id)
    try:
        ...  # existing body — calls alias_repository.replace_aliases
    finally:
        notify_alias_mutation_finished(recording_id)
    ...
```

Auto-summary entry calls `_wait_for_alias_quiescence` (already shown in §2.2).

**Test** (`tests/test_auto_summary_alias_race_guard.py`):

```python
async def test_f1_waits_for_f4_propagation(monkeypatch):
    """Auto-summary fires WHILE alias PUT is in flight — must wait."""
    coordinator.notify_alias_mutation_started(rec_id=42)
    started = time.monotonic()

    async def finish_in_500ms():
        await asyncio.sleep(0.5)
        coordinator.notify_alias_mutation_finished(rec_id=42)

    asyncio.create_task(finish_in_500ms())
    await coordinator._wait_for_alias_quiescence(42, window_s=2.0, timeout_s=10.0)
    assert (time.monotonic() - started) >= 0.4  # waited for the event
```

### 2.7 Auto-action repository (`auto_action_repository.py`)

Tiny module — wraps `recordings` updates. All methods commit before
returning (Persist-Before-Deliver applies to status transitions too):

```python
def get_auto_action_status(recording_id: int, action_type: str) -> str | None: ...
def get_auto_action_attempts(recording_id: int, action_type: str) -> int: ...
def set_auto_action_status(
    recording_id: int, action_type: str, status: str | None,
    *, error: str | None = None, path: str | None = None
) -> None: ...
def set_auto_summary_status(...) -> None: ...    # specialization
def set_auto_export_status(...) -> None: ...     # specialization
def increment_auto_action_attempts(recording_id: int, action_type: str) -> None: ...
def reset_auto_action_attempts(recording_id: int, action_type: str) -> None: ...
def list_pending_auto_actions() -> list[sqlite3.Row]: ...   # for sweeper
```

The shared `set_auto_action_status` is parameterized by action_type and
funnels into the two specializations. Tests cover each specialization
+ the parameterized variant.

---

## 3. Per-story design

### Story 6.1 — Profile auto-action toggles

**Backend:** `auto_summary_enabled` and `auto_export_enabled` are already
in `ProfilePublicFields` (line 67–68 of `profiles.py`). Only addition:
`destination_folder` is already in the schema; we now WIRE it through
in the dashboard UI.

**Dashboard component:** `dashboard/components/profile/ProfileEditForm.tsx`
gets two new toggles + an inline destination-folder picker:

```tsx
<div className="flex items-center gap-2">
  <input
    id="auto-summary-toggle"
    type="checkbox"
    checked={publicFields.auto_summary_enabled}
    onChange={(e) => setField('auto_summary_enabled', e.target.checked)}
    aria-label="Auto-generate AI summary after transcription"
  />
  <label htmlFor="auto-summary-toggle">Auto-generate AI summary after transcription</label>
</div>
<div className="flex items-center gap-2">
  <input id="auto-export-toggle" ... />
  <label htmlFor="auto-export-toggle">Auto-export transcript and summary</label>
</div>
```

Default OFF (the Pydantic model already defaults to False — Lurker-safe per
AC2).

**Tests:**
- `tests/test_profile_auto_action_toggles_roundtrip.py` — POST profile with
  toggles=true → GET → assert toggles persisted in `public_fields_json`.
- Existing profile-default test re-asserts the defaults remain False.

### Story 6.2 — Auto-summary lifecycle hook

**Wire `on_transcription_complete` first** (Sprint 3 carried this as
deferred — see §0). After `save_longform_to_database` returns in
`notebook.py::_run_transcription` (~line 985):

```python
# server/backend/api/routes/notebook.py — _run_transcription, after save_longform_to_database
from server.core.diarization_review_lifecycle import on_transcription_complete
from server.core.diarization_confidence import per_turn_confidence, LOW_CONFIDENCE_THRESHOLD
from server.core.auto_action_coordinator import trigger_auto_actions

segments = get_segments(recording_id)
words = get_words(recording_id)
turns = per_turn_confidence(segments, words)
has_low = any(t["confidence"] < LOW_CONFIDENCE_THRESHOLD for t in turns)
on_transcription_complete(recording_id, has_low)

# Fire-and-forget; we do NOT await. The websocket emit later in this
# function is still synchronous wrt save_longform_to_database, which is
# what Persist-Before-Deliver requires for the TRANSCRIPT itself. The
# auto-actions are post-completion, not part of the transcript-delivery
# critical path.
asyncio.create_task(trigger_auto_actions(recording_id, job_profile_snapshot))
```

**LLM client wrapper** (`server/backend/core/llm_client.py:summarize_recording_for_auto_action`):
- Loads recording + transcription via existing helpers
- Builds full-text via `apply_aliases(...)` (Sprint 3 helper)
- Prepends `speaker_key_preface(...)` (Sprint 3 helper)
- Calls existing LLM via `llm.summarize(text, model=...)`
- Returns `{"text": str, "model": str | None, "truncated": bool}`
- The `truncated` flag is set when the upstream client signals
  `finish_reason == "length"` or the equivalent provider-specific token-cap
  signal.

**Tests:**
- `tests/test_auto_summary_lifecycle.py`
  - `test_fires_within_2s_of_completion` — mocks LLM, asserts coordinator
    invokes the LLM client within 2.0s of completion.
  - `test_held_when_low_confidence` — sets up review row at `pending`,
    triggers, asserts status=`held` + LLM never called.
  - `test_persist_before_deliver_summary_save_back` — mocks ws emit,
    asserts ws fires AFTER `update_recording_summary` commits.
  - `test_summary_save_back_persists_to_recording` — full happy path.

### Story 6.3 — Auto-export lifecycle hook

Wired via the same `trigger_auto_actions` entry — runs in parallel with
auto-summary as its own asyncio.Task (Story 6.5 independence).

**File-write contract:**
- Path = `Path(destination_folder) / render_and_sanitize(filename_template, recording)`
- Atomic write: `_write_atomic` (write `.tmp` sibling, `os.replace`)
- Summary written to `<base>.summary.txt` only if `recordings.summary` is
  non-empty at the time the export runs.

**Tests:**
- `tests/test_auto_export_lifecycle.py`
  - `test_fires_within_2s_of_summary_save_back`
  - `test_writes_files_to_destination`
  - `test_persist_before_deliver_files_exist_before_ws_emit` — reads file
    path from the ws notification and asserts `os.path.exists`.
  - `test_no_summary_means_only_transcript`
  - `test_idempotent_overwrite_no_suffix_accumulation` (preview of Story
    6.10).

### Story 6.4 — Persist-Before-Deliver invariant matrix

`tests/test_persist_before_deliver_matrix.py`:

```python
ARTIFACT_PATHS = [
    ("auto_summary",         _setup_auto_summary,         _run_auto_summary,         _verify_db_then_ws),
    ("auto_export",          _setup_auto_export,          _run_auto_export,          _verify_disk_then_ws),
    ("manual_summary_save",  _setup_manual_summary,       _run_manual_summary,       _verify_db_then_response),
    ("webhook_delivery",     _setup_webhook_delivery,     _run_webhook_delivery,     _verify_db_row_then_http_call),
]

@pytest.mark.parametrize("name,setup,run,verify", ARTIFACT_PATHS)
def test_artifact_persisted_before_delivery(name, setup, run, verify, monkeypatch):
    ctx = setup(monkeypatch)
    asyncio.run(run(ctx))
    verify(ctx)
```

The `verify_*` functions assert ordering via a recorded event log — each
fixture's `setup` patches the persistence-and-delivery primitives to
append to a shared `events: list[str]`, then the `verify` asserts the
"persist" event came before the "deliver" event.

**Failure-mode test** (Story 6.4 AC2):

```python
def test_db_commit_failure_does_not_lose_summary(monkeypatch, tmp_path):
    """LLM result is recoverable from lost-and-found if DB commit fails."""
    monkeypatch.setattr(...config.data_dir..., tmp_path)
    monkeypatch.setattr(sqlite3.Connection, "commit", _raise_on_commit)
    asyncio.run(coordinator._run_auto_summary(rec_id, public={"auto_summary_enabled": True}))
    matches = list((tmp_path / "lost-and-found").glob(f"{rec_id}-*.summary.txt"))
    assert matches, "LLM result not recoverable"
    # status stays at 'in_progress' — retry endpoint can act
    assert repo.get_auto_action_status(rec_id, "auto_summary") == "in_progress"
```

The webhook line in the matrix is forward-pointing: Sprint 5's webhook
work plugs into the same matrix without rewriting the test.

### Story 6.5 — Independence + partial success

The two coordinator tasks are launched as independent
`asyncio.create_task(...)` and joined via `asyncio.gather(*tasks,
return_exceptions=True)`. Failure in one cannot cancel the other.

**Tests:**
- `tests/test_auto_action_independence.py`
  - `test_summary_failure_does_not_block_export` — LLM raises; export
    still writes file; recording shows
    `auto_summary_status='failed'` AND `auto_export_status='success'`.
  - `test_export_failure_does_not_block_summary` — destination missing;
    `auto_summary_status='success'` AND `auto_export_status='deferred'`.
  - `test_two_independent_badges_render` — frontend test (Vitest) renders
    two `AutoActionStatusBadge` components for the same recording with
    distinct severities.

### Story 6.6 — `AutoActionStatusBadge` (UX-DR1)

**Component (`dashboard/components/recording/AutoActionStatusBadge.tsx`, new):**

```tsx
import { StatusLight } from '../ui/StatusLight';
import { useAriaAnnouncer } from '../../src/hooks/useAriaAnnouncer';

type Severity = 'ok' | 'warn' | 'error' | 'processing' | 'manual_intervention_required';

const SEVERITY_TO_STATUSLIGHT: Record<Severity, 'active' | 'warning' | 'error' | 'loading'> = {
  ok: 'active',
  warn: 'warning',
  error: 'error',
  processing: 'loading',
  manual_intervention_required: 'error',
};

interface AutoActionStatusBadgeProps {
  recordingId: number;
  recordingName: string;
  actionType: 'auto_summary' | 'auto_export';
  severity: Severity;
  message: string;
  retryable: boolean;
  onRetry?: () => void;
}

export function AutoActionStatusBadge({
  recordingId, recordingName, actionType, severity, message, retryable, onRetry,
}: AutoActionStatusBadgeProps) {
  const announce = useAriaAnnouncer();
  useEffect(() => {
    announce(`${actionType.replace('_', ' ')}: ${message}`);
  }, [actionType, message, announce]);

  return (
    <div
      role="status"
      className={`inline-flex items-center gap-2 px-2 py-1 rounded text-sm`}
      data-severity={severity}
    >
      <StatusLight status={SEVERITY_TO_STATUSLIGHT[severity]} />
      <span>{message}</span>
      {retryable && onRetry && (
        <button
          type="button"
          onClick={onRetry}
          aria-label={`Retry ${actionType.replace('_', ' ')} for ${recordingName}`}
          className="ml-1 hover:underline"
        >
          ⟳ Retry
        </button>
      )}
    </div>
  );
}
```

**Hook (`dashboard/src/hooks/useAutoActionStatus.ts`, new):**

```typescript
export function useAutoActionRetry(recordingId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (actionType: 'auto_summary' | 'auto_export') =>
      api.post(`/api/notebook/recordings/${recordingId}/auto-actions/retry`, { action_type: actionType }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['recording', recordingId] });
    },
  });
}
```

**Wiring** in `AudioNoteModal.tsx`: read `recording.auto_summary_status`
and `recording.auto_export_status`, render up to two badges.

**Auto-dismiss for `ok`:** local state with 3s timeout; the row in DB
keeps the success status, but the badge unmounts client-side.

**UI contract:** new component → `npm run ui:contract:extract → build →
validate --update-baseline → check`.

### Story 6.7 — Empty / truncated states

- Empty: `len(summary_text.strip()) < 10` → `summary_empty` (covers both
  truly-empty and "I don't have enough context" stub responses per
  R-EL16).
- Truncated: provider-specific signal in the LLM client wrapper.
  - OpenAI: `finish_reason == "length"`
  - Anthropic: `stop_reason == "max_tokens"`
  - Local Ollama: streamed token count == max_tokens at termination
- Both states still PERSIST the partial content to `recordings.summary`
  so the user can review it (Story 6.7 AC2 — "visible in AI panel").

**Tests:**
- `tests/test_auto_summary_empty_state.py` — three fixtures: 0-char,
  3-char, 9-char responses → all → `summary_empty`.
- `tests/test_auto_summary_truncated_state.py` — provider-specific
  truncation signals → `summary_truncated` + content saved.

### Story 6.8 — Deferred-retry on destination unavailability

Sweeper module already designed in §2.4. Lifespan wiring:

```python
# server/backend/main.py — lifespan
from server.core.auto_action_sweeper import periodic_deferred_export_sweep
sweep_task = asyncio.create_task(
    periodic_deferred_export_sweep(interval_s=cfg.auto_actions.deferred_export_sweep_interval_s)
)
yield
sweep_task.cancel()
```

**Config flag:** `auto_actions.deferred_export_sweep_interval_s: 30` in
`config.yaml` (default). Tests override with `0.1`.

**TOCTOU safety:** sweeper uses `os.path.isdir` as a quick pre-flight check
but the actual write inside `_run_auto_export` is still attempted —
if the destination disappears between the check and the write,
`PermissionError` / `OSError` falls through to `_handle_auto_action_failure`
and the row goes back to `deferred`.

**Test:**
- `tests/test_deferred_export_sweep.py`
  - `test_sweeper_skips_when_destination_missing` — `os.path.isdir` mocked
    to False; row stays at `deferred`.
  - `test_sweeper_refires_when_destination_returns` — first call has dir
    missing; second call has dir present; second call writes file +
    flips status to `success`.
  - `test_sweeper_cancel_safe` — task cancelled mid-`asyncio.sleep` →
    no exception, row state preserved.

### Story 6.9 — Idempotent retry endpoint + manual button

Endpoint already shown in §2.5.

**Manual retry button** is rendered by `AutoActionStatusBadge` when
`retryable` is true (i.e. status in `{failed, deferred, summary_empty,
summary_truncated, manual_intervention_required, retry_pending}`).

**Tests:**
- `tests/test_auto_action_retry_endpoint.py`
  - `test_retry_on_failed_returns_202` — failed → retry_initiated.
  - `test_retry_on_success_returns_already_complete_no_re_execution` —
    status='success' → returns 200 `already_complete`, no asyncio task
    spawned (assert via mock on `asyncio.create_task`).
  - `test_retry_on_in_progress_returns_already_in_progress` — status
    `in_progress` → 200 `already_in_progress`, also no task spawned.
  - `test_retry_resets_attempts_counter` — manual retry resets attempts so
    the auto-retry budget is fresh for the next cycle.
  - `test_retry_404_on_unknown_recording`.
  - `test_retry_400_on_unknown_action_type`.

### Story 6.10 — Idempotent re-export semantics

`_write_atomic` already does this (write `.tmp`, then `os.replace`).

**Tests:**
- `tests/test_export_idempotent_overwrite.py`
  - `test_re_export_overwrites_in_place_no_suffix` — run export twice;
    only one file at the path; no `.1` suffix.
  - `test_concurrent_retry_atomicity` — two concurrent
    `_run_auto_export` calls; the resulting file is exactly one of the
    two results, never half-written. Asserted via file-size + content
    matching ONE of the inputs.

### Story 6.11 — Escalation policy + F1+F4 race guard

Escalation already in `_handle_auto_action_failure` (§2.2). Race guard
already in `_wait_for_alias_quiescence` (§2.2).

**Tests:**
- `tests/test_auto_action_escalation.py`
  - `test_one_auto_retry_then_manual` — fail → retry_pending → 30s wait
    (mocked to 0.01s) → fail again → manual_intervention_required.
  - `test_no_retry_loop_after_manual` — sweeper called on a
    `manual_intervention_required` row → no retry happens.
- `tests/test_auto_summary_alias_race_guard.py` — already shown in §2.6.

---

## 4. Risks and Stop-Conditions

| Risk | Mitigation | Stop-condition |
|---|---|---|
| Persist-Before-Deliver violation regression | Story 6.4 matrix runs on every PR; new artifact paths must add a row | If a new artifact path lands without a matrix row, CI fails |
| Lost LLM result on commit failure | `_persist_summary_with_durability_guard` writes lost-and-found before re-raising | If lost-and-found write itself fails, log + accept (best-effort) |
| Race condition F1+F4 (alias mutation mid-summary) | `_wait_for_alias_quiescence` blocks up to 10s | If 10s timeout fires, log warning + proceed with current aliases (R-EL3 verbatim guarantee still holds — whatever was committed gets used) |
| Periodic sweeper memory growth | Sweeper iterates partial-indexed rows only; no in-memory cache | If sweeper RSS grows, profile + bound the LIMIT clause |
| Idempotency edge: success → retry → success (same DB row) | `set_auto_action_status('success')` is idempotent at the column level | If a duplicate file appears on disk, `os.replace` was bypassed; investigate |
| Sprint diff exceeds ~3500 LOC | LOC budget per commit in §7 totals ~2400 + ~1100 tests = ~3500 LOC | If commits A–H together exceed 3000 LOC, STOP and split |
| Retry storms during outage (sweeper hits manual rows) | Sweeper explicitly skips `manual_intervention_required` | If retry storms appear in logs, add per-recording rate limit |

---

## 5. Recording-deletion + cascade matrix update

| User action | DB row (recordings) | Auto-action columns (NEW Sprint 4) |
|---|---|---|
| Click Delete (default) | DELETED | All auto-action columns deleted with the row (no FK fan-out — they live ON the row itself) |

The "no leak on restore" property holds because the columns are part of
`recordings`. Restoring the row restores the columns; deleting the row
deletes them.

**Lost-and-found data is NOT auto-deleted** — these are recovery files;
they survive recording deletion intentionally so a user can recover even
after an accidental delete. Documented in `docs/data-models-server.md`
under the new "Lost-and-found recovery" subsection.

---

## 6. Out-of-sprint observations (record only)

- **Webhook delivery** (Sprint 5) plugs into the Persist-Before-Deliver
  matrix without rewriting the test (placeholder row in §3 Story 6.4).
- **Longform / file-import auto-actions** (transcription.py path) are
  STILL deferred — these paths produce `transcription_jobs` rows, not
  `recordings` rows; auto-actions only apply to recordings. Captured in
  `deferred-work.md` if not already.
- **Per-action telemetry/metrics** (e.g. histogram of LLM latencies under
  auto-summary load) is not in scope; CLAUDE.md's no-outbound-telemetry
  policy applies; local Prometheus-style logs are OK to add in a later
  sprint.
- **Auto-summary HOLD UX** during retry: if a user retries while still
  `held`, status flips back to `held` (not `failed`). The user is
  signaled by the badge text "Auto-summary held — review uncertain turns
  first". Sprint 4 surfaces this; a future sprint can add a dedicated
  message variant if confusing.

---

## 7. Commit plan recap (with LOC estimates)

| Commit | Stories | Files | Est. LOC | Notes |
|---|---|---|---|---|
| A | 6.1 | ProfileEditForm.tsx (toggles), 1 test file | ~120 | UI-light; backend already has fields |
| B | 6.2 + 6.3 | migration 015, auto_action_repository, auto_action_coordinator, llm_client wrapper, notebook.py wiring, 4 test files | ~700 | Heart of sprint |
| C | 6.4 | tests/test_persist_before_deliver_matrix.py + lost-and-found helper | ~300 | Tests-heavy |
| D | 6.5 | (no new prod code — coordinator already independent), 2 test files | ~150 | Tests-only |
| E | 6.6 | AutoActionStatusBadge.tsx, useAutoActionRetry hook, AudioNoteModal wiring, ui-contract baseline update, 2 test files | ~400 | UI-heavy |
| F | 6.7 + 6.8 | empty/truncated detection in llm_client wrapper, auto_action_sweeper.py, lifespan wiring, 4 test files | ~500 | Backend + 1 config flag |
| G | 6.9 + 6.10 | retry endpoint, idempotent _write_atomic + concurrency tests, 4 test files | ~350 | Largely API surface |
| H | 6.11 | escalation in _handle_auto_action_failure, race-guard wiring in alias PUT, 2 test files | ~300 | Pure logic |
| Final | mark 11 stories DONE in epics.md | epics.md | ~30 | Bookkeeping |

**Total ~2850 LOC + tests** — within the 3500 LOC ceiling.

---

## 8. Dependency order recap

```
   A (6.1 toggles)
   │
   ▼
   B (6.2 + 6.3 hooks)  ─► C (6.4 PBD matrix)
   │                       │
   ▼                       ▼
   D (6.5 independence)   E (6.6 badge)
   │                       │
   ▼                       ▼
   F (6.7 + 6.8 states + sweeper)
   │
   ▼
   G (6.9 + 6.10 retry endpoint + idempotency)
   │
   ▼
   H (6.11 escalation + race guard)
```

Linear order A → B → C → D → E → F → G → H satisfies all import-time and
consumer-pattern dependencies. Each commit lands as its own logical unit;
the sprint ships as one branch (`gh-104-sprint-4`) and merges to
`gh-104-prd` like Sprints 1–3.
