---
title: 'R-001/R-003 blocker safety fixes'
type: 'bugfix'
created: '2026-04-05'
status: 'done'
baseline_commit: '19e246f'
context:
  - docs/testing/test-design-architecture.md
  - CLAUDE.md
---

<frozen-after-approval>

## Intent

**Problem:** Two testability blockers prevent writing reliable durability and model-swap tests. (1) In `websocket.py`, if `save_result()` fails but WS delivery succeeds, the job stays in `processing` forever — orphan recovery relies on timeout instead of explicit state. (2) In `live.py`, `asyncio.CancelledError` (a `BaseException`) bypasses the `except Exception` handler, so a WS disconnect during model swap leaves the server without a loaded model.

**Approach:** Add a post-delivery zombie-job guard in the WS handler (R-001) and a flag-guarded `finally` block in `start_engine()` (R-003) to guarantee model restoration on any exit path.

## Boundaries & Constraints

**Always:**
- Preserve existing "persist before deliver" semantics — never re-order save/deliver
- Keep `mark_failed()` calls best-effort (catch + log, no re-raise)
- R-003 finally must be a no-op on the success path (engine owns the model)

**Ask First:**
- Any change to the `save_result()` failure semantics (currently intentionally does not abort delivery)

**Never:**
- Change API behavior or WebSocket message format
- Add new dependencies or imports
- Modify the durability state machine (create → save → deliver)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| R-001: save_result fails, delivery succeeds | DB write error during save_result | Job marked `failed` with descriptive message after delivery completes | mark_failed is best-effort (catch + log) |
| R-001: save_result fails, delivery also fails | DB write error + WS disconnect | Existing except block calls mark_failed (no change needed) | Already handled |
| R-001: save_result succeeds | Normal path | mark_delivered called as before (no change) | N/A |
| R-003: CancelledError during model swap | WS disconnect after unload, before engine.start() | finally block calls _restore_or_reload_main_model() | Restore is best-effort (catch + log) |
| R-003: Exception during engine setup | Runtime error in LiveModeEngine() | finally block restores model (same as current except, now also catches BaseException) | Restore is best-effort |
| R-003: engine.start() succeeds | Normal path | _model_displaced cleared to False; finally is no-op | N/A |
| R-003: engine.start() returns False | Engine refuses to start | finally block restores model | Restore is best-effort |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/websocket.py` -- WS transcription handler; R-001 fix site (after line ~320)
- `server/backend/api/routes/live.py` -- Live mode session; R-003 fix site (start_engine, lines ~150-340)
- `server/backend/database/job_repository.py` -- `mark_failed()` definition (already imported in websocket.py)

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/websocket.py` -- Add zombie-job guard after mark_delivered section: if `_result_persisted` is False and job_id exists, call `_mark_failed()` -- prevents jobs stuck in `processing` when DB write fails but delivery succeeds
- [x] `server/backend/api/routes/live.py` -- Add `_model_displaced` flag before try block; set True after detach/unload, clear on engine.start() success; move restore calls to finally block guarded by flag -- guarantees model restoration on CancelledError/BaseException

**Acceptance Criteria:**
- Given a job where `save_result()` throws, when WS delivery succeeds, then the job is marked `failed` (not stuck in `processing`)
- Given a WS disconnect during model swap in `start_engine()`, when CancelledError propagates, then `_restore_or_reload_main_model()` is called
- Given a successful `engine.start()`, when start_engine returns True, then no restoration is attempted (finally is no-op)
- Given existing tests, when `pytest tests/ -v` is run, then all previously-passing tests still pass

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: all previously-passing tests pass, no regressions

## Suggested Review Order

**R-001: Zombie-job guard (websocket.py)**

- Entry point: post-delivery guard marks job `failed` when DB persistence fails
  [`websocket.py:322`](../../server/backend/api/routes/websocket.py#L322)

**R-003: Model-swap safety net (live.py)**

- Flag declaration before try block — tracks whether model was displaced
  [`live.py:152`](../../server/backend/api/routes/live.py#L152)

- Early `self._shared_backend` assignment — prevents backend leak on CancelledError (review patch)
  [`live.py:292`](../../server/backend/api/routes/live.py#L292)

- Flag set after unload in non-share path
  [`live.py:316`](../../server/backend/api/routes/live.py#L316)

- Flag cleared on success — engine owns the model, finally becomes no-op
  [`live.py:339`](../../server/backend/api/routes/live.py#L339)

- Finally block — guarantees restoration on any exit including BaseException
  [`live.py:351`](../../server/backend/api/routes/live.py#L351)
