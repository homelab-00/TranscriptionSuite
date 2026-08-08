# Salvage-Aware Busy Popup + Salvage Progress Notification - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a GH-239 salvage of a dropped recording holds the server's single job slot, a new recording attempt shows a confirm popup (drop the salvage and auto-restart) instead of a generic busy error, and the salvage's progress is mirrored into the notification center.

**Architecture:** A salvage flag on the backend `TranscriptionJobTracker` (exposed via the existing public `GET /api/status` and an extended `session_busy` WS payload); dashboard-side, a structured `busyInfo` state in `useTranscription` drives a `useConfirm()` popup in SessionView with cancel + wait + auto-restart, and a new app-root `useSalvageProgress` hook polls `/api/status` to upsert a progress notification. Spec: `docs/superpowers/specs/2026-08-08-salvage-popup-progress-design.md`.

**Tech Stack:** FastAPI + pytest (backend, build venv), React/TypeScript + zustand + vitest (dashboard, Node 22).

---

## Ground rules for every task

- Work in the worktree `/home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/.claude/worktrees/hazy-kindling-bear`, on branch `feat/salvage-popup-progress` (already exists; the spec is committed on it).
- Backend tests: `cd server/backend && ../../build/.venv/bin/pytest <file> -v --tb=short`. Before the final task, run the FULL suite (project rule - never just the touched files).
- Dashboard tests: `cd dashboard && nvm use` first (vitest needs Node 22), then `npx vitest run <file>`.
- Per project CLAUDE.md: run GitNexus `impact` before editing each symbol and `mcp__gitnexus__detect_changes` before each commit. The index is stale - refresh once in Task 0.
- Commits are GPG-signed; a pinentry dialog may pop up - if a commit fails with `gpg: signing failed: Timeout`, retry it (the user is around to enter the passphrase).
- NEVER add AI attribution to commits. Use the repo commit style `type(area): summary`.
- In `dashboard/components/**` comments: no apostrophes (ui-contract scanner quote-parity trap) and write "GH-239", never "#239" (color-literal false positive).
- No new instance attributes on `TranscriptionSession` - the salvage state lives on the job tracker precisely so the three fragile session test-factories stay untouched.

## File structure

| File | Change |
|---|---|
| `server/backend/core/model_manager.py` | `TranscriptionJobTracker`: `_salvage_info`, `mark_salvage()`, `get_salvage_info()`, clear in `end_job()`/`try_start_job()`, expose in `get_status()` |
| `server/backend/api/routes/websocket.py` | `finalize_interrupted_recording()` flags the tracker; `session_busy` payload gains `is_salvage`/`salvage_job_id`; honest cancel reason for salvages |
| `server/backend/tests/test_transcription_job_tracker.py` | New `TestSalvageTracking`; update exact-dict idle test |
| `server/backend/tests/test_websocket_disconnect_salvage.py` | mark_salvage call tests + cancel-reason tests |
| `server/backend/tests/test_websocket_session_busy.py` | NEW - payload shape tests |
| `dashboard/src/api/types.ts` | `SalvageInfo`, `JobTrackerStatus.salvage`, `jobTrackerFromServerStatus()` |
| `dashboard/src/stores/salvageStore.ts` | NEW - nudge/drop/ended coordination store |
| `dashboard/src/stores/__tests__/salvageStore.test.ts` | NEW |
| `dashboard/src/hooks/useTranscription.ts` | `BusyInfo` state + salvage-aware `session_busy` + monitor nudges |
| `dashboard/src/hooks/useTranscription.test.ts` | busyInfo tests |
| `dashboard/src/hooks/useSalvageProgress.ts` | NEW - poll `/api/status`, notification upserts, `waitForJobSlotFree()` |
| `dashboard/src/hooks/useSalvageProgress.test.ts` | NEW |
| `dashboard/App.tsx` | Mount `useSalvageProgress()` |
| `dashboard/components/views/SessionView.tsx` | Popup + drop flow + "Stopping" banner + recovery-banner refresh on salvage end |
| `dashboard/components/__tests__/SessionView.recovery-refresh.test.tsx` | Harness additions + salvage-popup describe block |

---

### Task 0: Setup and baselines

- [ ] **Step 0.1: Confirm branch and clean tree**

Run: `git status && git branch --show-current`
Expected: branch `feat/salvage-popup-progress`, clean tree (only the committed spec).

- [ ] **Step 0.2: Refresh the GitNexus index** (it is stale; needed for the impact/detect_changes gates)

Run from the worktree root: `node .gitnexus/run.cjs analyze`

- [ ] **Step 0.3: Impact analysis on the symbols this plan edits**

Run GitNexus `impact` (direction upstream) for: `TranscriptionJobTracker`, `handle_client_message`, `finalize_interrupted_recording`, `process_transcription`, `useTranscription`. Note the blast radius in the task log; stop and report if any comes back CRITICAL.

- [ ] **Step 0.4: Green baselines**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_transcription_job_tracker.py tests/test_websocket_disconnect_salvage.py -v --tb=short`
Expected: PASS.
Run: `cd dashboard && nvm use && npx vitest run src/hooks/useTranscription.test.ts`
Expected: PASS.

---

### Task 1: Backend - salvage state on `TranscriptionJobTracker`

**Files:**
- Modify: `server/backend/core/model_manager.py` (class `TranscriptionJobTracker`, ~lines 49-206)
- Test: `server/backend/tests/test_transcription_job_tracker.py`

- [ ] **Step 1.1: Write the failing tests**

In `test_transcription_job_tracker.py`, update the module docstring coverage list (add `- mark_salvage / get_salvage_info lifecycle`), update `test_idle_status_structure` (the exact-dict assert) by adding one key to the expected dict:

```python
            "result": None,
            "salvage": None,
```

Append a new test class at the end of the file:

```python
class TestSalvageTracking:
    """GH-239 follow-up: the tracker flags when the active job is a salvage."""

    def test_mark_salvage_records_info_for_active_job(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")

        assert tracker.mark_salvage(job_id) is True

        info = tracker.get_salvage_info()
        assert info is not None
        assert info["job_id"] == job_id
        assert info["client_name"] == "alice"
        assert info["started_at"] is not None

    def test_mark_salvage_rejects_mismatch_none_and_no_job(self):
        tracker = TranscriptionJobTracker()
        assert tracker.mark_salvage("anything") is False  # no active job
        tracker.try_start_job("alice")
        assert tracker.mark_salvage("wrong-id") is False  # mismatched id
        assert tracker.mark_salvage(None) is False  # create_job failed upstream
        assert tracker.get_salvage_info() is None

    def test_end_job_clears_salvage_info(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.mark_salvage(job_id)

        tracker.end_job(job_id)

        assert tracker.get_salvage_info() is None
        assert tracker.get_status()["salvage"] is None

    def test_new_job_clears_stale_salvage_info(self):
        tracker = TranscriptionJobTracker()
        tracker._salvage_info = {"job_id": "stale", "client_name": "x", "started_at": 0.0}

        tracker.try_start_job("bob")

        assert tracker.get_salvage_info() is None

    def test_get_status_exposes_full_salvage_job_id(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.mark_salvage(job_id)

        status = tracker.get_status()

        # FULL id on purpose (active_job_id is truncated for display): the
        # dashboard matches it against /recent rows and /result/{job_id}.
        assert status["salvage"]["job_id"] == job_id
        assert status["salvage"]["client_name"] == "alice"

    def test_get_salvage_info_returns_a_copy(self):
        tracker = TranscriptionJobTracker()
        _, job_id, _ = tracker.try_start_job("alice")
        tracker.mark_salvage(job_id)

        tracker.get_salvage_info()["job_id"] = "mutated"

        assert tracker.get_salvage_info()["job_id"] == job_id
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_transcription_job_tracker.py -v --tb=short`
Expected: FAIL - `AttributeError: ... mark_salvage` on the new class, `AssertionError` on the idle-structure dict.

- [ ] **Step 1.3: Implement**

In `model_manager.py`, inside `TranscriptionJobTracker.__init__`, after `self._result: dict[str, Any] | None = None`:

```python
        # GH-239 follow-up: set while the active job is a salvage of a dropped
        # recording, so /api/status and session_busy can tell the dashboard
        # this busy slot is recoverable, not a live user.
        self._salvage_info: dict[str, Any] | None = None
```

In `try_start_job`, inside the success branch, after `self._result = None  # Clear previous job result`:

```python
            self._salvage_info = None
```

In `end_job`, inside the matching branch, after `self._result = result`:

```python
                self._salvage_info = None
```

After `cancel_job()`, add two methods:

```python
    def mark_salvage(self, job_id: str | None) -> bool:
        """Flag the active job as a GH-239 salvage of a dropped recording.

        Returns False (and records nothing) when job_id is None or does not
        match the active job - callers treat this as best-effort.
        """
        with self._lock:
            if job_id is None or self._active_job_id != job_id:
                return False
            self._salvage_info = {
                "job_id": job_id,
                "client_name": self._active_user,
                "started_at": time.time(),
            }
            return True

    def get_salvage_info(self) -> dict[str, Any] | None:
        """Salvage metadata for the active job, or None. Returns a copy."""
        with self._lock:
            return dict(self._salvage_info) if self._salvage_info else None
```

In `get_status()`, after `"result": self._result,`:

```python
                "salvage": dict(self._salvage_info) if self._salvage_info else None,
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_transcription_job_tracker.py -v --tb=short`
Expected: PASS (all, including the updated idle-structure test).

- [ ] **Step 1.5: detect_changes + commit**

Run `mcp__gitnexus__detect_changes` (scope `all`, worktree path); expect changes confined to `TranscriptionJobTracker`. Then:

```bash
git add server/backend/core/model_manager.py server/backend/tests/test_transcription_job_tracker.py
git commit -m "feat(server): track salvage state on the transcription job tracker"
```

---

### Task 2: Backend - `finalize_interrupted_recording()` flags the tracker

**Files:**
- Modify: `server/backend/api/routes/websocket.py` (`finalize_interrupted_recording`, ~line 486)
- Test: `server/backend/tests/test_websocket_disconnect_salvage.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `test_websocket_disconnect_salvage.py`:

```python
def test_salvage_marks_the_job_tracker(monkeypatch, tmp_path):
    """The dashboard popup and progress notification hinge on this flag."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    tracker = mm_mod.get_model_manager().job_tracker
    tracker.mark_salvage.assert_called_once_with("job-001")


def test_junk_guard_does_not_mark_salvage(monkeypatch, tmp_path):
    """Below the salvage minimum nothing runs, so nothing must be flagged."""
    _patch_transcription(monkeypatch, tmp_path)
    session = _make_session(audio_seconds=1.0)

    asyncio.run(session.finalize_interrupted_recording())

    tracker = mm_mod.get_model_manager().job_tracker
    tracker.mark_salvage.assert_not_called()
```

(`mm_mod` and `_patch_transcription` already exist in this file; the patched `get_model_manager` lambda returns the same `MagicMock` manager every call, so `mark_salvage` is auto-mocked.)

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_disconnect_salvage.py -v --tb=short`
Expected: the first new test FAILS (`mark_salvage` never called); the second passes trivially (that is fine - it pins the guard).

- [ ] **Step 2.3: Implement**

In `websocket.py`, in `finalize_interrupted_recording()`, directly after the `self._salvage_reason = (...)` assignment and before `try: await self.process_transcription()`:

```python
        # Flag the tracker so /api/status and session_busy can tell the
        # dashboard this busy slot is a salvage rather than a live user
        # (drop-popup + progress notification). Best-effort: a tracker whose
        # job does not match (create_job failed earlier) just declines.
        try:
            from server.core.model_manager import get_model_manager

            get_model_manager().job_tracker.mark_salvage(self._current_job_id)
        except Exception as _ms_err:
            logger.warning("Failed to flag salvage on the job tracker: %s", _ms_err)
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_disconnect_salvage.py -v --tb=short`
Expected: PASS.

- [ ] **Step 2.5: detect_changes + commit**

```bash
git add server/backend/api/routes/websocket.py server/backend/tests/test_websocket_disconnect_salvage.py
git commit -m "feat(server): flag the job tracker when finalizing an interrupted recording"
```

---

### Task 3: Backend - salvage-aware `session_busy` payload

**Files:**
- Modify: `server/backend/api/routes/websocket.py` (`handle_client_message` busy branch, ~line 1035)
- Test: `server/backend/tests/test_websocket_session_busy.py` (NEW)

- [ ] **Step 3.1: Write the failing tests**

Create `server/backend/tests/test_websocket_session_busy.py`:

```python
"""session_busy payload carries salvage awareness (GH-239 follow-up).

The dashboard branches on is_salvage: a salvage-held slot opens the
drop-confirmation popup; a live user's job keeps the generic busy error.
salvage_job_id must be the FULL id - the client matches it against /recent
and /result/{job_id}.

Run:  ../../build/.venv/bin/pytest tests/test_websocket_session_busy.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import server.api.routes.websocket as ws_mod


def _session():
    # Plain MagicMock, NOT spec=TranscriptionSession: `spec` builds its allowed
    # attribute set from dir(cls), which excludes anything assigned in __init__.
    session = MagicMock()
    session.client_name = "test-client"
    session._current_job_id = None
    session.start_recording = AsyncMock()
    session.send_message = AsyncMock()
    return session


def _busy_payload(salvage_info: dict[str, Any] | None) -> dict[str, Any]:
    """Drive a `start` frame into a busy tracker; return the session_busy payload."""
    session = _session()
    model_manager = MagicMock()
    model_manager.job_tracker.try_start_job.return_value = (False, None, "other-user")
    model_manager.job_tracker.get_salvage_info.return_value = salvage_info

    with patch("server.core.model_manager.get_model_manager", return_value=model_manager):
        asyncio.run(ws_mod.handle_client_message(session, {"type": "start", "data": {}}))

    assert session.send_message.await_count == 1
    msg_type, payload = session.send_message.await_args.args
    assert msg_type == "session_busy"
    assert session.start_recording.await_count == 0
    return payload


def test_busy_without_salvage_is_not_flagged():
    payload = _busy_payload(None)
    assert payload == {
        "active_user": "other-user",
        "is_salvage": False,
        "salvage_job_id": None,
    }


def test_busy_with_salvage_carries_the_full_job_id():
    payload = _busy_payload(
        {"job_id": "11111111-2222-3333-4444-555555555555", "client_name": "other-user", "started_at": 1.0}
    )
    assert payload == {
        "active_user": "other-user",
        "is_salvage": True,
        "salvage_job_id": "11111111-2222-3333-4444-555555555555",
    }
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_session_busy.py -v --tb=short`
Expected: FAIL - payload equals `{"active_user": "other-user"}` (missing keys).

- [ ] **Step 3.3: Implement**

In `handle_client_message`, replace the busy branch:

```python
        if not success:
            # Another transcription is running - send session_busy but keep connection open
            await session.send_message("session_busy", {"active_user": active_user})
```

with:

```python
        if not success:
            # Another transcription is running - send session_busy but keep the
            # connection open. is_salvage lets the dashboard offer dropping a
            # GH-239 salvage instead of dead-ending; a live user's job stays a
            # generic busy. salvage_job_id is the FULL id (the client matches
            # it against /recent and /result/{job_id}).
            salvage = model_manager.job_tracker.get_salvage_info()
            await session.send_message(
                "session_busy",
                {
                    "active_user": active_user,
                    "is_salvage": salvage is not None,
                    "salvage_job_id": salvage["job_id"] if salvage else None,
                },
            )
```

(The `logger.info(...)` and `return` lines below stay unchanged.)

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_session_busy.py tests/test_websocket_notebook_autoadd.py tests/test_websocket_diarization_start.py -v --tb=short`
Expected: PASS (the two neighbouring start-path files prove no regression).

- [ ] **Step 3.5: detect_changes + commit**

```bash
git add server/backend/api/routes/websocket.py server/backend/tests/test_websocket_session_busy.py
git commit -m "feat(server): mark session_busy payloads with salvage awareness"
```

---

### Task 4: Backend - honest error message when a salvage is cancelled

**Files:**
- Modify: `server/backend/api/routes/websocket.py` (`process_transcription` except branch, ~line 371)
- Test: `server/backend/tests/test_websocket_disconnect_salvage.py`

- [ ] **Step 4.1: Write the failing tests**

Append to `test_websocket_disconnect_salvage.py` (the file already imports `mm_mod`; `TranscriptionCancelledError` lives there):

```python
def test_cancelled_salvage_persists_honest_reason(monkeypatch, tmp_path):
    """POST /cancel is the only thing that can stop a salvage - the job row
    must say so (and point at retry), not blame a client disconnect."""
    engine = _patch_transcription(monkeypatch, tmp_path)
    engine.transcribe_file.side_effect = mm_mod.TranscriptionCancelledError("cancelled")
    session = _make_session(audio_seconds=5.0)

    asyncio.run(session.finalize_interrupted_recording())

    ws_mod._mark_failed.assert_called_once_with(
        "job-001", "Salvage cancelled by user - audio saved for retry"
    )


def test_cancelled_normal_run_keeps_disconnect_reason(monkeypatch, tmp_path):
    engine = _patch_transcription(monkeypatch, tmp_path)
    engine.transcribe_file.side_effect = mm_mod.TranscriptionCancelledError("cancelled")
    session = _make_session(audio_seconds=5.0, is_recording=False)

    asyncio.run(session.process_transcription())

    ws_mod._mark_failed.assert_called_once_with("job-001", "Cancelled: client disconnected")
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_disconnect_salvage.py -v --tb=short`
Expected: the salvage test FAILS (message is `"Cancelled: client disconnected"`); the normal-run test passes.

- [ ] **Step 4.3: Implement**

In `process_transcription`'s except block, replace:

```python
            if isinstance(e, TranscriptionCancelledError):
                logger.info(f"Transcription cancelled (client disconnected) for {self.client_name}")
                if self._current_job_id:
                    try:
                        _mark_failed(self._current_job_id, "Cancelled: client disconnected")
```

with:

```python
            if isinstance(e, TranscriptionCancelledError):
                # An explicit POST /cancel is the only signal that can stop a
                # salvage (the disconnect term is muted for it) - record that,
                # and point at the retry the persisted WAV makes possible.
                reason = (
                    "Salvage cancelled by user - audio saved for retry"
                    if self._salvage_reason
                    else "Cancelled: client disconnected"
                )
                logger.info(f"Transcription cancelled for {self.client_name}: {reason}")
                if self._current_job_id:
                    try:
                        _mark_failed(self._current_job_id, reason)
```

(The `except Exception as _mf_err:` / `logger.warning(...)` lines below stay unchanged.)

- [ ] **Step 4.4: Run tests, then the FULL backend suite**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/test_websocket_disconnect_salvage.py -v --tb=short`
Expected: PASS.
Run: `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short`
Expected: PASS (full suite - project rule). Fix any fallout before committing.

- [ ] **Step 4.5: detect_changes + commit**

```bash
git add server/backend/api/routes/websocket.py server/backend/tests/test_websocket_disconnect_salvage.py
git commit -m "fix(server): persist an honest error message when a salvage is cancelled"
```

---

### Task 5: Dashboard - types + salvage store

**Files:**
- Modify: `dashboard/src/api/types.ts` (~line 262, `JobTrackerStatus` block)
- Create: `dashboard/src/stores/salvageStore.ts`
- Test: `dashboard/src/stores/__tests__/salvageStore.test.ts` (NEW)

- [ ] **Step 5.1: Write the failing store tests**

Create `dashboard/src/stores/__tests__/salvageStore.test.ts`:

```typescript
/**
 * salvageStore tests (GH-239 follow-up).
 *
 * The store coordinates three parties: useTranscription/SessionView request
 * immediate checks and record a user-requested drop; useSalvageProgress
 * consumes the drop marker and stamps lastCompletedAt when a salvage ends;
 * SessionView refreshes the recovery banner on that stamp.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { useSalvageStore } from '../salvageStore';

beforeEach(() => {
  useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
});

describe('salvageStore', () => {
  it('requestCheck bumps the nonce', () => {
    useSalvageStore.getState().requestCheck();
    useSalvageStore.getState().requestCheck();
    expect(useSalvageStore.getState().checkNonce).toBe(2);
  });

  it('markDropRequested / clearDropRequested round-trip', () => {
    useSalvageStore.getState().markDropRequested('job-1');
    expect(useSalvageStore.getState().dropRequestedJobId).toBe('job-1');
    useSalvageStore.getState().clearDropRequested();
    expect(useSalvageStore.getState().dropRequestedJobId).toBeNull();
  });

  it('markSalvageEnded stamps lastCompletedAt', () => {
    expect(useSalvageStore.getState().lastCompletedAt).toBeNull();
    useSalvageStore.getState().markSalvageEnded();
    expect(useSalvageStore.getState().lastCompletedAt).not.toBeNull();
  });
});
```

- [ ] **Step 5.2: Run to verify failure**

Run: `cd dashboard && nvm use && npx vitest run src/stores/__tests__/salvageStore.test.ts`
Expected: FAIL - cannot resolve `../salvageStore`.

- [ ] **Step 5.3: Implement the store**

Create `dashboard/src/stores/salvageStore.ts`:

```typescript
/**
 * Salvage coordination store (GH-239 follow-up).
 *
 * Glue between the salvage progress monitor (useSalvageProgress) and the
 * parts of the app that learn about salvages first:
 *   - checkNonce: bumped to request an immediate /api/status check
 *     (session_busy with is_salvage, unexpected socket close).
 *   - dropRequestedJobId: set by the SessionView popup before it cancels a
 *     salvage, so the monitor renders "stopped" instead of probing outcome.
 *   - lastCompletedAt: stamped when a salvage ends; SessionView refreshes
 *     the recovery banner on change.
 */

import { create } from 'zustand';

interface SalvageStoreState {
  checkNonce: number;
  dropRequestedJobId: string | null;
  lastCompletedAt: number | null;
  requestCheck: () => void;
  markDropRequested: (jobId: string) => void;
  clearDropRequested: () => void;
  markSalvageEnded: () => void;
}

export const useSalvageStore = create<SalvageStoreState>((set) => ({
  checkNonce: 0,
  dropRequestedJobId: null,
  lastCompletedAt: null,
  requestCheck: () => set((s) => ({ checkNonce: s.checkNonce + 1 })),
  markDropRequested: (jobId) => set({ dropRequestedJobId: jobId }),
  clearDropRequested: () => set({ dropRequestedJobId: null }),
  markSalvageEnded: () => set({ lastCompletedAt: Date.now() }),
}));
```

- [ ] **Step 5.4: Add the API types**

In `dashboard/src/api/types.ts`, directly above the `JobTrackerStatus` interface, add:

```typescript
/** GH-239 follow-up: present while the server salvages a dropped recording. */
export interface SalvageInfo {
  /** FULL job id (active_job_id is truncated for display; this one is not) -
   *  matched against /recent rows and /result/{job_id}. */
  job_id: string;
  client_name: string | null;
  started_at: number | null;
}
```

Inside `JobTrackerStatus`, after `result: JobTrackerResult | null;`, add:

```typescript
  /** Set while the active job is a GH-239 salvage of a dropped recording. */
  salvage?: SalvageInfo | null;
```

Directly below `jobTrackerFromAdminStatus`, add:

```typescript
/** Narrow accessor for the loosely-typed /api/status models blob (GH-239). */
export function jobTrackerFromServerStatus(
  status: { models?: unknown } | null | undefined,
): JobTrackerStatus | undefined {
  return (status?.models as { job_tracker?: JobTrackerStatus } | undefined)?.job_tracker;
}
```

- [ ] **Step 5.5: Run tests to verify they pass**

Run: `cd dashboard && npx vitest run src/stores/__tests__/salvageStore.test.ts`
Expected: PASS. Also `npx tsc --noEmit -p .` if the project exposes it (otherwise vitest's transform surfaces type errors in dependent files later).

- [ ] **Step 5.6: detect_changes + commit**

```bash
git add dashboard/src/stores/salvageStore.ts dashboard/src/stores/__tests__/salvageStore.test.ts dashboard/src/api/types.ts
git commit -m "feat(dashboard): add salvage coordination store and status typings"
```

---

### Task 6: Dashboard - structured `busyInfo` in `useTranscription`

**Files:**
- Modify: `dashboard/src/hooks/useTranscription.ts`
- Test: `dashboard/src/hooks/useTranscription.test.ts`

- [ ] **Step 6.1: Write the failing tests**

In `useTranscription.test.ts`, next to the existing `sets session_busy as error with active user info` test (~line 301), add:

```typescript
    it('salvage-busy sets busyInfo and returns to idle instead of error', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'laptop', is_salvage: true, salvage_job_id: 'salv-1' },
        });
      });

      expect(result.current.status).toBe('idle');
      expect(result.current.error).toBeNull();
      expect(result.current.busyInfo).toEqual({
        activeUser: 'laptop',
        isSalvage: true,
        salvageJobId: 'salv-1',
      });
      expect(lastSocket.disconnect).toHaveBeenCalled();
    });

    it('session_busy without is_salvage keeps the generic error and no busyInfo', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'other-client' },
        });
      });

      expect(result.current.status).toBe('error');
      expect(result.current.busyInfo).toBeNull();
    });

    it('clearBusyInfo and reset both clear busyInfo', () => {
      const { result } = renderHook(() => useTranscription());

      act(() => {
        result.current.start();
      });
      act(() => {
        lastSocketCbs.onMessage!({ type: 'auth_ok' });
      });
      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'laptop', is_salvage: true, salvage_job_id: null },
        });
      });
      expect(result.current.busyInfo).not.toBeNull();

      act(() => {
        result.current.clearBusyInfo();
      });
      expect(result.current.busyInfo).toBeNull();

      act(() => {
        lastSocketCbs.onMessage!({
          type: 'session_busy',
          data: { active_user: 'laptop', is_salvage: true, salvage_job_id: null },
        });
      });
      act(() => {
        result.current.reset();
      });
      expect(result.current.busyInfo).toBeNull();
    });
```

- [ ] **Step 6.2: Run to verify failure**

Run: `cd dashboard && npx vitest run src/hooks/useTranscription.test.ts`
Expected: FAIL - `busyInfo`/`clearBusyInfo` are undefined; salvage-busy currently lands in `error`.

- [ ] **Step 6.3: Implement**

In `useTranscription.ts`:

1. Import (after the `apiClient` import): `import { useSalvageStore } from '../stores/salvageStore';`

2. After the `TranscriptionStatus` type, add:

```typescript
/** Structured payload of a salvage-caused session_busy rejection (GH-239). */
export interface BusyInfo {
  activeUser: string;
  isSalvage: boolean;
  salvageJobId: string | null;
}
```

3. In the `TranscriptionState` interface, after `error: string | null;`:

```typescript
  /** Set when `start` was rejected because a salvage holds the job slot. */
  busyInfo: BusyInfo | null;
  /** Consume the busy event once the popup flow has taken over. */
  clearBusyInfo: () => void;
```

4. In the hook body, next to the other `useState` calls: `const [busyInfo, setBusyInfo] = useState<BusyInfo | null>(null);`

5. Replace the `session_busy` case with:

```typescript
        case 'session_busy': {
          const activeUser = (msg.data?.active_user as string) ?? 'another session';
          if (msg.data?.is_salvage === true) {
            // GH-239 follow-up: a salvage holds the slot - hand the decision
            // to the SessionView popup instead of dead-ending in the error box.
            setBusyInfo({
              activeUser,
              isSalvage: true,
              salvageJobId: (msg.data?.salvage_job_id as string | null | undefined) ?? null,
            });
            useSalvageStore.getState().requestCheck();
            setStatusTracked('idle');
          } else {
            setError(`Server busy — ${activeUser} is active`);
            setStatusTracked('error');
          }
          socketRef.current?.disconnect();
          break;
        }
```

(Keep the existing em dash in the error string - it is shipped UI text asserted by tests.)

6. In `start()`, after `setError(null);` add `setBusyInfo(null);`. Same in `reset()`.

7. In `onClose`, directly after `const wasRecording = statusRef.current === 'recording';`:

```typescript
          if (wasRecording || statusRef.current === 'processing') {
            // GH-239: the server may be about to salvage this - wake the
            // monitor so the progress notification appears promptly.
            useSalvageStore.getState().requestCheck();
          }
```

8. Add `const clearBusyInfo = useCallback(() => setBusyInfo(null), []);` near `reset`, and add `busyInfo,` and `clearBusyInfo,` to the hook's returned object (after `error,`).

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `cd dashboard && npx vitest run src/hooks/useTranscription.test.ts`
Expected: PASS - including the pre-existing `session_busy` test, untouched.

- [ ] **Step 6.5: detect_changes + commit**

```bash
git add dashboard/src/hooks/useTranscription.ts dashboard/src/hooks/useTranscription.test.ts
git commit -m "feat(dashboard): expose structured busyInfo from useTranscription for salvage-busy rejections"
```

---

### Task 7: Dashboard - `useSalvageProgress` monitor + `waitForJobSlotFree` + app-root mount

**Files:**
- Create: `dashboard/src/hooks/useSalvageProgress.ts`
- Modify: `dashboard/App.tsx` (~line 125)
- Test: `dashboard/src/hooks/useSalvageProgress.test.ts` (NEW)

- [ ] **Step 7.1: Write the failing tests**

Create `dashboard/src/hooks/useSalvageProgress.test.ts`:

```typescript
/**
 * useSalvageProgress tests (GH-239 follow-up).
 *
 * The monitor mirrors an in-progress salvage (from GET /api/status) into the
 * notification center and resolves the outcome when it ends. Critical trap
 * pinned here: completion must be confirmed via /recent, NEVER via
 * GET /result/{id} - a 200 there marks the job delivered and removes it from
 * the recovery banner.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  useSalvageProgress,
  waitForJobSlotFree,
  ACTIVE_POLL_MS,
} from './useSalvageProgress';
import { useNotificationsStore } from '../stores/notificationsStore';
import { useSalvageStore } from '../stores/salvageStore';
import { apiClient } from '../api/client';
import { jobTrackerFromServerStatus } from '../api/types';

vi.mock('../api/client', () => ({
  apiClient: {
    getStatus: vi.fn(),
    fetchRecentUndelivered: vi.fn(),
    fetchTranscriptionResult: vi.fn(),
  },
}));

const mockedApi = vi.mocked(apiClient);

const SALVAGE = { job_id: 'salv-full', client_name: 'laptop', started_at: 1 };

function statusWith(salvage: unknown, extra: Record<string, unknown> = {}) {
  return {
    models: {
      job_tracker: {
        is_busy: salvage !== null,
        active_user: 'laptop',
        active_job_id: 'salv-ful',
        cancellation_requested: false,
        progress: null,
        started_at: null,
        result: null,
        salvage,
        ...extra,
      },
    },
  } as never;
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

function salvageNotification() {
  return useNotificationsStore
    .getState()
    .notifications.find((n) => n.id === 'salvage-salv-full');
}

beforeEach(() => {
  vi.useFakeTimers();
  useNotificationsStore.setState({ notifications: [] });
  useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
  mockedApi.getStatus.mockResolvedValue(statusWith(null));
  mockedApi.fetchRecentUndelivered.mockResolvedValue({ ok: true, json: async () => [] } as never);
  mockedApi.fetchTranscriptionResult.mockResolvedValue({
    status: 404,
    json: async () => ({}),
  } as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('jobTrackerFromServerStatus', () => {
  it('digs the tracker out of the models blob', () => {
    expect(jobTrackerFromServerStatus(statusWith(SALVAGE))?.salvage).toEqual(SALVAGE);
    expect(jobTrackerFromServerStatus(null)).toBeUndefined();
    expect(jobTrackerFromServerStatus({} as never)).toBeUndefined();
  });
});

describe('useSalvageProgress', () => {
  it('mirrors an active salvage into the notification center with percent progress', async () => {
    mockedApi.getStatus.mockResolvedValue(
      statusWith(SALVAGE, {
        progress: { current: 30, total: 60, message: '', phase: 'transcribing' },
      }),
    );
    renderHook(() => useSalvageProgress());
    await flush();

    const n = salvageNotification();
    expect(n?.status).toBe('active');
    expect(n?.category).toBe('transcription');
    expect(n?.progress).toBe(50);
    expect(n?.detail).toContain('laptop');
  });

  it('renders a dropped salvage as stopped without probing the result endpoints', async () => {
    mockedApi.getStatus
      .mockResolvedValueOnce(statusWith(SALVAGE))
      .mockResolvedValue(statusWith(null));
    useSalvageStore.getState().markDropRequested('salv-full');
    renderHook(() => useSalvageProgress());
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS);
    });

    const n = salvageNotification();
    expect(n?.status).toBe('complete');
    expect(n?.title).toBe('Recovery stopped');
    expect(mockedApi.fetchRecentUndelivered).not.toHaveBeenCalled();
    expect(mockedApi.fetchTranscriptionResult).not.toHaveBeenCalled();
    expect(useSalvageStore.getState().dropRequestedJobId).toBeNull();
    expect(useSalvageStore.getState().lastCompletedAt).not.toBeNull();
  });

  it('confirms completion via /recent and never touches /result (mark_delivered trap)', async () => {
    mockedApi.getStatus
      .mockResolvedValueOnce(statusWith(SALVAGE))
      .mockResolvedValue(statusWith(null));
    mockedApi.fetchRecentUndelivered.mockResolvedValue({
      ok: true,
      json: async () => [{ job_id: 'salv-full', completed_at: 'x', text_preview: 'hi' }],
    } as never);
    renderHook(() => useSalvageProgress());
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS);
    });

    const n = salvageNotification();
    expect(n?.status).toBe('complete');
    expect(n?.title).toBe('Recording recovered');
    expect(mockedApi.fetchTranscriptionResult).not.toHaveBeenCalled();
    expect(useSalvageStore.getState().lastCompletedAt).not.toBeNull();
  });

  it('reports a failed salvage with the server reason (410 detail)', async () => {
    mockedApi.getStatus
      .mockResolvedValueOnce(statusWith(SALVAGE))
      .mockResolvedValue(statusWith(null));
    mockedApi.fetchTranscriptionResult.mockResolvedValue({
      status: 410,
      json: async () => ({ detail: 'CUDA out of memory' }),
    } as never);
    renderHook(() => useSalvageProgress());
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS);
    });

    const n = salvageNotification();
    expect(n?.status).toBe('error');
    expect(n?.error).toBe('CUDA out of memory');
  });

  it('requestCheck triggers an immediate poll', async () => {
    renderHook(() => useSalvageProgress());
    await flush();
    const calls = mockedApi.getStatus.mock.calls.length;

    act(() => {
      useSalvageStore.getState().requestCheck();
    });
    await flush();

    expect(mockedApi.getStatus.mock.calls.length).toBeGreaterThan(calls);
  });
});

describe('waitForJobSlotFree', () => {
  it('resolves true immediately when the tracker is free', async () => {
    mockedApi.getStatus.mockResolvedValue(statusWith(null));
    await expect(waitForJobSlotFree(5_000, 1_000)).resolves.toBe(true);
  });

  it('gives up after the deadline while busy', async () => {
    mockedApi.getStatus.mockResolvedValue(statusWith(SALVAGE));
    const pending = waitForJobSlotFree(3_000, 1_000);
    await vi.advanceTimersByTimeAsync(4_000);
    await expect(pending).resolves.toBe(false);
  });
});
```

- [ ] **Step 7.2: Run to verify failure**

Run: `cd dashboard && npx vitest run src/hooks/useSalvageProgress.test.ts`
Expected: FAIL - cannot resolve `./useSalvageProgress`.

- [ ] **Step 7.3: Implement the hook**

Create `dashboard/src/hooks/useSalvageProgress.ts`:

```typescript
/**
 * useSalvageProgress - watches the server for an in-progress salvage of a
 * dropped recording (GH-239) and mirrors it into the notification center.
 *
 * Polls GET /api/status (public; carries job_tracker.salvage + progress):
 * every IDLE_POLL_MS normally, ACTIVE_POLL_MS while a salvage runs, with
 * immediate re-checks on window focus and salvageStore.requestCheck().
 * Mounted exactly once at the app root (App.tsx), like useNotificationBridge.
 *
 * Outcome resolution when a salvage ends, in order:
 *   1. dropRequestedJobId matches -> "Recovery stopped" (no server probes).
 *   2. Listed by GET /recent      -> "Recording recovered". NEVER confirm via
 *      GET /result/{id}: a 200 marks the job delivered and would remove it
 *      from the recovery banner while nobody has seen it.
 *   3. GET /result/{id} 410       -> failed, with the server reason.
 *   4. Anything else (403/404: another client's job) -> generic finish.
 */

import { useEffect, useRef } from 'react';

import { apiClient } from '../api/client';
import { jobTrackerFromServerStatus, type SalvageInfo } from '../api/types';
import { useNotificationsStore } from '../stores/notificationsStore';
import { useSalvageStore } from '../stores/salvageStore';

export const IDLE_POLL_MS = 15_000;
export const ACTIVE_POLL_MS = 2_000;

const PHASE_LABELS: Record<string, string> = {
  loading_model: 'Loading model',
  transcribing: 'Transcribing',
  diarizing: 'Identifying speakers',
  transcribing_diarizing: 'Transcribing and identifying speakers',
};

const notifId = (jobId: string) => `salvage-${jobId}`;

/**
 * Poll /api/status until the single job slot frees up. Checks immediately
 * (so an already-free server resolves without sleeping), then every
 * intervalMs until timeoutMs. Missing tracker info counts as free - the UI
 * must not deadlock on an old server.
 */
export async function waitForJobSlotFree(
  timeoutMs = 120_000,
  intervalMs = 1_000,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      const tracker = jobTrackerFromServerStatus(await apiClient.getStatus());
      if (!tracker || !tracker.is_busy) return true;
    } catch {
      // Transient fetch failure - keep waiting until the deadline.
    }
    if (Date.now() >= deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export function useSalvageProgress(): void {
  const activeSalvageRef = useRef<SalvageInfo | null>(null);
  const checkNonce = useSalvageStore((s) => s.checkNonce);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const resolveOutcome = async (ended: SalvageInfo): Promise<void> => {
      const store = useNotificationsStore.getState();
      const salvageStore = useSalvageStore.getState();
      const id = notifId(ended.job_id);
      try {
        if (salvageStore.dropRequestedJobId === ended.job_id) {
          salvageStore.clearDropRequested();
          store.notify({
            id,
            category: 'transcription',
            title: 'Recovery stopped',
            detail: 'Recording saved - retry available',
            status: 'complete',
          });
          return;
        }
        const recentResp = await apiClient.fetchRecentUndelivered();
        const recent: unknown = recentResp.ok ? await recentResp.json() : [];
        if (
          Array.isArray(recent) &&
          recent.some((j) => (j as { job_id?: string })?.job_id === ended.job_id)
        ) {
          store.notify({
            id,
            category: 'transcription',
            title: 'Recording recovered',
            detail: 'Transcript available in Main Transcription',
            status: 'complete',
          });
          return;
        }
        const resp = await apiClient.fetchTranscriptionResult(ended.job_id);
        if (resp.status === 410) {
          const body = (await resp.json().catch(() => null)) as { detail?: string } | null;
          store.notify({
            id,
            category: 'transcription',
            title: 'Recovery failed',
            status: 'error',
            error: body?.detail ?? 'The salvage transcription failed',
          });
          return;
        }
        store.notify({
          id,
          category: 'transcription',
          title: 'Recovery finished',
          status: 'complete',
        });
      } catch {
        store.notify({
          id,
          category: 'transcription',
          title: 'Recovery finished',
          status: 'complete',
        });
      } finally {
        salvageStore.markSalvageEnded();
      }
    };

    const tick = async (): Promise<void> => {
      let delay = activeSalvageRef.current ? ACTIVE_POLL_MS : IDLE_POLL_MS;
      try {
        const tracker = jobTrackerFromServerStatus(await apiClient.getStatus());
        if (disposed) return;
        const salvage = tracker?.salvage ?? null;
        if (salvage) {
          activeSalvageRef.current = salvage;
          const progress = tracker?.progress ?? null;
          const percent =
            progress && progress.total > 0
              ? Math.round((progress.current / progress.total) * 100)
              : undefined;
          const phase = progress?.phase
            ? (PHASE_LABELS[progress.phase] ?? progress.phase)
            : null;
          useNotificationsStore.getState().notify({
            id: notifId(salvage.job_id),
            category: 'transcription',
            title: 'Recovering interrupted recording',
            detail: [salvage.client_name, phase].filter(Boolean).join(' - '),
            status: 'active',
            ...(percent !== undefined ? { progress: percent } : {}),
          });
          delay = ACTIVE_POLL_MS;
        } else if (activeSalvageRef.current) {
          const ended = activeSalvageRef.current;
          activeSalvageRef.current = null;
          await resolveOutcome(ended);
          delay = IDLE_POLL_MS;
        }
      } catch {
        // Server unreachable - app-level indicators cover it; retry next tick.
      }
      if (!disposed) {
        timer = setTimeout(() => void tick(), delay);
      }
    };

    void tick();
    const onFocus = () => {
      if (timer) clearTimeout(timer);
      void tick();
    };
    window.addEventListener('focus', onFocus);
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [checkNonce]);
}
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `cd dashboard && npx vitest run src/hooks/useSalvageProgress.test.ts`
Expected: PASS.

- [ ] **Step 7.5: Mount at the app root**

In `dashboard/App.tsx`: add `import { useSalvageProgress } from './src/hooks/useSalvageProgress';` next to the `useNotificationBridge` import (~line 35), and inside `AppInner`, directly under `useNotificationBridge();` (~line 125):

```typescript
  // GH-239 follow-up: mirror server-side salvage progress into notifications.
  useSalvageProgress();
```

- [ ] **Step 7.6: detect_changes + commit**

```bash
git add dashboard/src/hooks/useSalvageProgress.ts dashboard/src/hooks/useSalvageProgress.test.ts dashboard/App.tsx
git commit -m "feat(dashboard): salvage progress notification monitor polled from /api/status"
```

---

### Task 8: Dashboard - SessionView popup, drop flow, and banner refresh

**Files:**
- Modify: `dashboard/components/views/SessionView.tsx`
- Test: `dashboard/components/__tests__/SessionView.recovery-refresh.test.tsx`

- [ ] **Step 8.1: Extend the test harness (failing tests)**

In `SessionView.recovery-refresh.test.tsx`:

1. Extend the RTL import: `import { render, screen, waitFor, fireEvent, within, act } from '@testing-library/react';`
2. Add to `mockTranscription` (after `jobId: null as string | null,`):

```typescript
  busyInfo: null as null | { activeUser: string; isSalvage: boolean; salvageJobId: string | null },
  clearBusyInfo: vi.fn(),
```

3. In the `vi.hoisted` block, add to the returned object: `mockGetStatus: vi.fn(), mockCancelTranscription: vi.fn(),` and destructure them in the `const { ... } = vi.hoisted(...)` binding.
4. In the `vi.mock('../../src/api/client', ...)` factory, replace `cancelTranscription: vi.fn(),` with `cancelTranscription: (...a: unknown[]) => mockCancelTranscription(...a),` and add `getStatus: (...a: unknown[]) => mockGetStatus(...a),`.
5. Add `import { useSalvageStore } from '../../src/stores/salvageStore';` after the `SessionView` import.
6. In the top-level `beforeEach`, add:

```typescript
    mockTranscription.busyInfo = null;
    mockGetStatus.mockResolvedValue({
      models: { job_tracker: { is_busy: false, salvage: null } },
    });
    mockCancelTranscription.mockResolvedValue({
      success: true,
      cancelled_user: 'laptop',
      message: '',
    });
    useSalvageStore.setState({ checkNonce: 0, dropRequestedJobId: null, lastCompletedAt: null });
```

7. Append a new describe block:

```typescript
describe('SessionView - salvage drop popup (GH-239 follow-up)', () => {
  const BUSY = { activeUser: 'laptop', isSalvage: true, salvageJobId: 'salv-1' };

  it('opens the confirm dialog when start bounced off an active salvage', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    expect(await screen.findByText(/interrupted recording/)).toBeInTheDocument();
    expect(mockTranscription.clearBusyInfo).toHaveBeenCalled();
  });

  it('drop flow: cancels the salvage, marks the drop, and restarts recording', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    fireEvent.click(await screen.findByText('Stop and record'));

    await waitFor(() => expect(mockCancelTranscription).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockTranscription.start).toHaveBeenCalledTimes(1));
    expect(useSalvageStore.getState().dropRequestedJobId).toBe('salv-1');
  });

  it('declining leaves the salvage alone', async () => {
    mockTranscription.busyInfo = { ...BUSY };
    renderSessionView();

    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByText('Cancel'));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mockCancelTranscription).not.toHaveBeenCalled();
    expect(mockTranscription.start).not.toHaveBeenCalled();
  });

  it('refreshes the recovery banner when a salvage ends', async () => {
    renderSessionView();
    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalled());
    mockFetchRecentUndelivered.mockClear();

    act(() => {
      useSalvageStore.getState().markSalvageEnded();
    });

    await waitFor(() => expect(mockFetchRecentUndelivered).toHaveBeenCalled());
  });
});
```

- [ ] **Step 8.2: Run to verify failure**

Run: `cd dashboard && npx vitest run components/__tests__/SessionView.recovery-refresh.test.tsx`
Expected: the new describe FAILS (no dialog appears, no refresh on markSalvageEnded); the pre-existing recovery tests still PASS.

- [ ] **Step 8.3: Implement in SessionView.tsx**

1. Imports: add `import { createPortal } from 'react-dom';` under the React import; add with the other src imports:

```typescript
import { useConfirm } from '../../src/hooks/useConfirm';
import { useSalvageStore } from '../../src/stores/salvageStore';
import { waitForJobSlotFree } from '../../src/hooks/useSalvageProgress';
import type { BusyInfo } from '../../src/hooks/useTranscription';
```

2. Under `const transcription = useTranscription();` (~line 227):

```typescript
  const { confirm, dialog: confirmDialog } = useConfirm();
  const [droppingSalvage, setDroppingSalvage] = useState(false);
```

3. Directly AFTER the `handleStartRecording` useCallback (it is referenced here):

```typescript
  // GH-239 follow-up: a start attempt bounced off an in-progress salvage.
  // Ask instead of dead-ending; on confirm, cancel it, wait out the slot
  // (non-whisper.cpp backends only observe the cancel after compute ends),
  // then restart the recording automatically.
  const handleSalvageBusy = useCallback(
    async (info: BusyInfo) => {
      const ok = await confirm(
        `The server is still transcribing an interrupted recording (from ${info.activeUser}). ` +
          'Stop it and start your new recording? The interrupted audio is saved and can be retried later.',
        { title: 'Recovery in progress', confirmLabel: 'Stop and record', danger: true },
      );
      if (!ok) return;
      if (info.salvageJobId) {
        useSalvageStore.getState().markDropRequested(info.salvageJobId);
      }
      setDroppingSalvage(true);
      try {
        try {
          // success:false just means the salvage finished on its own - the
          // slot is free (or about to be), so proceed either way.
          await apiClient.cancelTranscription();
        } catch {
          toast.error('Could not stop the recovery job', {
            description: 'The server did not accept the cancel request. Try again.',
          });
          return;
        }
        const freed = await waitForJobSlotFree();
        if (!freed) {
          toast.error('Could not free the server', {
            description: 'The recovery job did not stop in time. Try again in a moment.',
          });
          return;
        }
        handleStartRecording();
      } finally {
        setDroppingSalvage(false);
      }
    },
    [confirm, handleStartRecording],
  );

  useEffect(() => {
    const info = transcription.busyInfo;
    if (!info?.isSalvage) return;
    transcription.clearBusyInfo();
    void handleSalvageBusy(info);
  }, [transcription.busyInfo, transcription.clearBusyInfo, handleSalvageBusy]);
```

4. Next to the existing `refreshRecoveryJobs` trigger effects (~line 1350):

```typescript
  // GH-239: a salvage that ends while this view is open should surface its
  // result immediately, not on the next window focus.
  const lastSalvageEndedAt = useSalvageStore((s) => s.lastCompletedAt);
  useEffect(() => {
    if (lastSalvageEndedAt !== null) refreshRecoveryJobs();
  }, [lastSalvageEndedAt, refreshRecoveryJobs]);
```

5. JSX - directly above the `{transcription.error && (` alert block (~line 2272):

```tsx
                    {droppingSalvage && (
                      <div
                        data-testid="salvage-stopping"
                        role="status"
                        className="flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
                      >
                        <Loader2 size={14} className="animate-spin" />
                        <span>Stopping the recovery job... Your recording will start automatically.</span>
                      </div>
                    )}
```

6. JSX - at the end of the component's root fragment/element (mirroring NotebookView line 457):

```tsx
      {confirmDialog && createPortal(confirmDialog, document.body)}
```

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `cd dashboard && npx vitest run components/__tests__/SessionView.recovery-refresh.test.tsx`
Expected: PASS (all describes).

- [ ] **Step 8.5: detect_changes + commit**

```bash
git add dashboard/components/views/SessionView.tsx dashboard/components/__tests__/SessionView.recovery-refresh.test.tsx
git commit -m "feat(dashboard, ui): salvage drop confirmation popup with automatic recording restart"
```

---

### Task 9: UI contract, full suites, wrap-up

- [ ] **Step 9.1: UI contract workflow** (SessionView gained class tokens - the check alone will fail)

Follow `.claude/skills/ui-contract/SKILL.md` exactly. From `dashboard/`: `npm run ui:contract:extract`, `npm run ui:contract:build`, bump `meta.spec_version` (minor) in the contract YAML, run the validate script with `--update-baseline`, then `npm run ui:contract:check`.
Expected: check PASSES. If it reports `stale_in_contract` on unrelated tokens, check the quote-parity trap (apostrophes in comments) before touching the contract.

- [ ] **Step 9.2: Full dashboard suite**

Run: `cd dashboard && npx vitest run`
Expected: PASS.

- [ ] **Step 9.3: Full backend suite (again, final gate)**

Run: `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short`
Expected: PASS.

- [ ] **Step 9.4: Final detect_changes + commit any stragglers**

Run `mcp__gitnexus__detect_changes` (scope `compare`, base_ref `main`) and confirm the affected symbols are exactly the ones in the File structure table. Commit anything uncommitted (e.g. the contract YAML):

```bash
git add dashboard/ui-contract
git commit -m "chore(dashboard, ui): update ui-contract baseline for the salvage popup"
```

- [ ] **Step 9.5: Manual smoke checklist** (hardware; record in the PR body as pending if not run now)

1. Start a recording, kill the dashboard mid-recording, reopen: progress notification appears and completes; recovery banner shows the salvaged transcript without refocusing.
2. While a salvage runs, press Start Recording: popup appears; Confirm cancels, shows the amber "Stopping" banner, and the new recording starts by itself.
3. Decline path: salvage continues, notification keeps updating.
4. Busy from a second device recording normally: generic red busy error, no popup.
