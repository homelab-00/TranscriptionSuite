"""Auto-action coordinator (Issue #104, Stories 6.2–6.11).

Single entry point for the auto-summary + auto-export lifecycle. Owns:

- HOLD predicate consultation (Story 5.8 / R-EL10) — already in commit B
- Per-action independence (Story 6.5) — coordinator returns_exceptions=True
- Persist-Before-Deliver invariant (Story 6.4 / NFR16) — strict ordering
  inside _run_auto_summary / _run_auto_export
- F1+F4 race-condition guard (Story 6.11) — commit H wires the actual
  alias-mutation hooks; commit B exposes the no-op stubs

Module of pure functions (no class, no service object) — tests can
monkeypatch any function without container plumbing. Same shape as
``diarization_review_lifecycle.py``.
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
    IllegalReviewTransitionError,
    auto_summary_is_held,
    current_status,
    on_auto_summary_fired,
)
from server.core.filename_template import render_and_sanitize
from server.database import auto_action_repository as repo

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# F1+F4 race guard — module-level state (Story 6.11, commit H)
# ──────────────────────────────────────────────────────────────────────────
# Commit B publishes the public surface; commit H wires the actual hooks
# from the alias PUT route. Until commit H, the dicts stay empty and
# `_wait_for_alias_quiescence` returns True immediately.

_ALIAS_MUTATION_AT: dict[int, float] = {}
_ALIAS_MUTATION_EVENTS: dict[int, asyncio.Event] = {}


def notify_alias_mutation_started(recording_id: int) -> None:
    """Called by alias-PUT route on entry (Sprint 4 commit H wires this)."""
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

    Returns True if quiet, False if timeout was hit. Caller proceeds
    either way — the auto-summary fallback uses whatever aliases happen
    to be committed at the time, which is correct under R-EL3.
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
    except TimeoutError:
        logger.warning(
            "auto_summary_race_guard_timeout recording_id=%d (proceeding with current aliases)",
            recording_id,
        )
        return False


# ──────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────


async def trigger_auto_actions(
    recording_id: int, profile_snapshot: Mapping[str, Any] | None
) -> None:
    """Entry point called from notebook upload completion path.

    Reads profile snapshot toggles. Fires auto-summary and auto-export
    independently — neither blocks the other (Story 6.5). Each is its
    own asyncio.Task so an exception in one does not propagate to the
    other.

    Caller dispatches via ``asyncio.create_task(trigger_auto_actions(...))``
    — fire-and-forget after transcript persistence. The coordinator does
    not signal completion to the websocket layer; surfaces consume the
    state via the ``recordings.auto_*_status`` columns.

    The snapshot is also persisted onto the recording row so retries +
    the deferred-export sweeper can resume with the SAME profile context
    that fired the original auto-action (no profile drift).
    """
    if not profile_snapshot:
        return
    public = profile_snapshot.get("public_fields") or {}
    if not isinstance(public, Mapping):
        logger.warning(
            "auto_action_coordinator: profile_snapshot.public_fields is %r, expected mapping",
            type(public).__name__,
        )
        return

    if public.get("auto_summary_enabled") or public.get("auto_export_enabled"):
        # Save the snapshot once — both tasks read from it via retry path
        # if needed.
        import json

        try:
            repo.save_profile_snapshot(
                recording_id, json.dumps(profile_snapshot, ensure_ascii=False, sort_keys=True)
            )
        except Exception:  # noqa: BLE001 — best-effort; snapshot loss is recoverable
            logger.exception(
                "save_profile_snapshot failed for recording %d (retry will fall back to no snapshot)",
                recording_id,
            )

    tasks: list[asyncio.Task] = []
    if public.get("auto_summary_enabled"):
        tasks.append(asyncio.create_task(_run_auto_summary(recording_id, public)))
    if public.get("auto_export_enabled"):
        tasks.append(asyncio.create_task(_run_auto_export(recording_id, public)))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ──────────────────────────────────────────────────────────────────────────
# Auto-summary (Story 6.2)
# ──────────────────────────────────────────────────────────────────────────


async def _run_auto_summary(recording_id: int, public: Mapping[str, Any]) -> None:
    """Story 6.2 lifecycle. HOLD-aware. Persist-Before-Deliver."""
    from server.core.auto_summary_engine import (
        AutoSummaryError,
        summarize_for_auto_action,
    )

    # 1. HOLD check (R-EL10) — if held, mark and return.
    if auto_summary_is_held(recording_id):
        repo.set_auto_summary_status(recording_id, "held")
        return

    # 2. F1+F4 race guard (Story 6.11). No-op until commit H wires the
    #    alias-PUT route. Including the call now keeps the timing right
    #    when the wiring lands.
    await _wait_for_alias_quiescence(recording_id)

    # 3. Mark in-flight BEFORE the LLM call so retries can detect "stuck".
    repo.set_auto_summary_status(recording_id, "in_progress")

    try:
        result = await summarize_for_auto_action(recording_id, public)
    except AutoSummaryError as exc:
        repo.set_auto_summary_status(recording_id, "failed", error=str(exc))
        return
    except Exception as exc:  # noqa: BLE001 — last-resort
        logger.exception("auto_summary unexpected exception")
        repo.set_auto_summary_status(recording_id, "failed", error=f"unexpected: {exc}")
        return

    summary_text = result.get("text") or ""

    # Story 6.7 — empty / truncated detection.
    # Empty: <10 chars after strip → 'summary_empty' (still persist what
    # we got so the user can review / retry from the UI; AC2).
    if len(summary_text.strip()) < 10:
        _persist_summary_with_durability_guard(recording_id, summary_text, result.get("model"))
        repo.set_auto_summary_status(recording_id, "summary_empty")
        return
    # Truncated: provider signaled / heuristic detected. Persist the
    # partial content (Story 6.7 AC2) so the user can either review
    # it or retry to attempt regeneration with adjusted prompt.
    if result.get("truncated"):
        _persist_summary_with_durability_guard(recording_id, summary_text, result.get("model"))
        repo.set_auto_summary_status(recording_id, "summary_truncated")
        return

    # 4. Persist BEFORE delivering (NFR16). On persist failure we LEAVE the
    #    status at 'in_progress' (set earlier) so the retry endpoint /
    #    deferred-export sweeper can pick this up — the LLM result is in
    #    data/lost-and-found/ for forensic recovery (Story 6.4 AC2).
    try:
        _persist_summary_with_durability_guard(recording_id, summary_text, result.get("model"))
    except Exception:  # noqa: BLE001 — last-resort, lost-and-found has the data
        logger.exception(
            "auto-summary persist failed for recording %d; status stays at "
            "'in_progress', LLM result in lost-and-found",
            recording_id,
        )
        # Mark 'failed' so the badge surfaces something actionable. The
        # retry endpoint resets attempts on manual retry (Story 6.9), so
        # this does not eat the user's retry budget.
        repo.set_auto_summary_status(
            recording_id, "failed", error="persist failure (LLM result in lost-and-found)"
        )
        return
    repo.set_auto_summary_status(recording_id, "success")
    _on_auto_summary_fired_safe(recording_id)


def _persist_summary_with_durability_guard(
    recording_id: int, summary: str, model: str | None
) -> None:
    """Wrap update_recording_summary with a lost-and-found fallback.

    If the persistence call raises (disk-full, constraint, anything),
    write the LLM text to ``data/lost-and-found/<rec_id>-<ts>.summary.txt``
    before re-raising so the result is recoverable. CLAUDE.md "AVOID DATA
    LOSS AT ALL COSTS".
    """
    from server.database.database import update_recording_summary

    try:
        update_recording_summary(recording_id, summary, model)
    except Exception:
        _write_lost_and_found(recording_id, "summary", summary)
        raise


def _on_auto_summary_fired_safe(recording_id: int) -> None:
    """Wrap on_auto_summary_fired so an illegal-transition (no review row,
    or review row already at 'released') does not propagate as an error.

    The state machine is strict, but the auto-summary success path fires
    regardless of whether the review row exists. If no row exists, the
    transition is a no-op; if the row is already 'released', also a
    no-op. Anything else is genuinely illegal.
    """
    status = current_status(recording_id)
    if status is None or status == "released":
        return
    if status != "completed":
        # The review row is still 'pending' or 'in_review' — auto-summary
        # should have been HELD by step 1 of _run_auto_summary. Reaching
        # here is a real bug; log and skip the transition.
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


# ──────────────────────────────────────────────────────────────────────────
# Auto-export (Story 6.3)
# ──────────────────────────────────────────────────────────────────────────


async def _run_auto_export(
    recording_id: int,
    public: Mapping[str, Any],
    *,
    force: bool = False,  # noqa: ARG001
) -> None:
    """Story 6.3 lifecycle. Persist-Before-Deliver via atomic file write.

    Commit B implements the success path + basic failure detection.
    Commit F (Story 6.8) adds deferred-retry detection for missing
    destinations. Commit G (Story 6.10) hardens the atomic-write path.
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
        await asyncio.to_thread(_write_transcript_atomic, base, recording_id)
        # Summary is exported only if it exists at write-time (Story 6.5
        # independence — auto-export does NOT wait for auto-summary).
        summary = recording.get("summary")
        if summary:
            summary_path = base.with_name(base.name + ".summary.txt")
            await asyncio.to_thread(_write_atomic, summary_path, summary)
        repo.set_auto_export_status(recording_id, "success", path=str(base))
    except (FileNotFoundError, PermissionError, OSError) as exc:
        repo.set_auto_export_status(recording_id, "failed", error=str(exc), path=destination)


def _write_atomic(target: Path, content: str) -> None:
    """Story 6.10: write to a UNIQUE temp sibling, then os.replace.

    Two concurrent writers must NOT collide on the same temp filename —
    that would leave one with a missing-source FileNotFoundError on
    replace. We use ``tempfile.NamedTemporaryFile(delete=False)`` in
    the target directory so each writer gets a unique temp path.
    ``os.replace`` is atomic on POSIX and Windows; the last writer wins
    cleanly. No half-written file is ever observable.
    """
    import tempfile

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup of the orphan temp file on failure.
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _write_transcript_atomic(base: Path, recording_id: int) -> None:
    """Build alias-aware plaintext via existing exporter, write atomically."""
    from server.core.alias_substitution import apply_aliases
    from server.core.plaintext_export import stream_plaintext
    from server.database.alias_repository import list_aliases
    from server.database.database import get_recording, get_segments

    recording = get_recording(recording_id) or {}
    segments = get_segments(recording_id)
    aliases = {a["speaker_id"]: a["alias_name"] for a in list_aliases(recording_id)}
    text = "".join(stream_plaintext(recording, apply_aliases(segments, aliases)))
    _write_atomic(base, text)


# ──────────────────────────────────────────────────────────────────────────
# Lost-and-found fallback (CLAUDE.md "AVOID DATA LOSS AT ALL COSTS")
# ──────────────────────────────────────────────────────────────────────────


def _write_lost_and_found(recording_id: int, kind: str, content: str) -> None:
    """Last-resort recovery write — never raises.

    Commit C (Story 6.4) covers this path with an explicit regression
    test asserting LLM text is recoverable when the DB commit fails.
    """
    try:
        from server.database.database import _data_dir

        # Resolve data dir lazily — `_data_dir` may have been set by the
        # config layer or by a test fixture. Both are valid.
        data_dir = _data_dir or Path.cwd() / "data"
        out_dir = Path(data_dir) / "lost-and-found"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        path = out_dir / f"{recording_id}-{ts}.{kind}.txt"
        path.write_text(content, encoding="utf-8")
        logger.warning("Wrote lost-and-found recovery: %s", path)
    except Exception:  # noqa: BLE001 — best-effort
        logger.exception("lost-and-found write itself failed; LLM result may be lost")


# ──────────────────────────────────────────────────────────────────────────
# Retry plumbing (Story 6.9 — commit G adds the HTTP endpoint; commit B
# only needs the in-process retry function for completeness)
# ──────────────────────────────────────────────────────────────────────────


async def retry_auto_action_internal(recording_id: int, action_type: str) -> None:
    """Idempotent retry — funnels HTTP retry endpoint AND the sweeper.

    Loads the profile snapshot from the recording row (saved by
    ``trigger_auto_actions`` at the original auto-action time). This
    guarantees retries use the SAME profile context — no drift if the
    user edited the profile between original auto-action and retry.
    """
    snapshot = repo.get_profile_snapshot(recording_id) or {}
    public = snapshot.get("public_fields") or {}

    if action_type == "auto_summary":
        await _run_auto_summary(recording_id, public)
    elif action_type == "auto_export":
        await _run_auto_export(recording_id, public, force=True)
    else:
        raise ValueError(f"unknown action_type: {action_type!r}")


__all__ = (
    "trigger_auto_actions",
    "retry_auto_action_internal",
    "notify_alias_mutation_started",
    "notify_alias_mutation_finished",
)
