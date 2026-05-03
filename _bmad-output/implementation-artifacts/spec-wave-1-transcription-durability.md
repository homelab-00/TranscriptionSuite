---
title: 'Wave 1 — Never Lose a Completed Transcription Result'
type: 'feature'
created: '2026-03-29'
status: 'done'
baseline_commit: '7f3ed82940d654344abc029cb170c121215bb5ed'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The WebSocket transcription path has zero persistence — results live only in memory and are delivered via a single `send_message()` call. If that call fails (disconnect, crash, timeout), the result is silently gone. The HTTP upload path already saves to the database; the WebSocket path does not.

**Approach:** Before delivering any result via WebSocket, persist it to a new `transcription_jobs` SQLite table. Add an HTTP retrieval endpoint so the client can recover the result after an unexpected disconnect. Add a JSON sanitization utility to prevent serialization crashes from corrupting the persist step.

## Boundaries & Constraints

**Always:**
- Persist to DB BEFORE calling `send_message("final", ...)` — no exceptions
- Use parameterized queries; no string formatting in SQL
- Import path for new modules: `server.backend.database.*`, `server.backend.core.*`
- Follow existing migration pattern: `op.get_bind()` + `text()`, revision string `"006"`, `down_revision = "005"`
- Add attribution comments at implementation sites for logic borrowed from external sources (see Design Notes)

**Ask First:**
- If `_current_job_id` is None when `save_result()` would be called (should not happen, but ask before adding a silent skip)
- If the HTTP result endpoint should require auth (current WebSocket auth pattern uses token query param)

**Never:**
- Do not implement Wave 2 (audio preservation) or Wave 3 (startup recovery) in this spec
- Do not use an ORM — keep raw sqlite3 like the rest of the database layer
- Do not change the `recordings` table or existing `save_longform_to_database()` logic

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal completion | WS connected, transcription finishes | `save_result()` writes to DB, then `send_message("final")` fires, `mark_delivered()` set | If send fails, result stays in DB with `delivered=0` |
| Client disconnects mid-processing | WS drops while `transcribe_future` is pending | `mark_failed()` called with "Cancelled: client disconnected" | Job row shows `status='failed'` |
| Server exception during transcription | Exception in `process_transcription()` | `mark_failed()` called with `str(e)` | Job row shows `status='failed'`, error text stored |
| Client polls after disconnect | `GET /api/transcribe/result/{job_id}`, job completed | 200 with result JSON, `mark_delivered()` called | 404 if not found; 202 if still processing; 410 if failed (with error) |
| NaN/Inf in whisper word probabilities | `result.words` contains `float('nan')` | Sanitized to `None` before both DB write and WS send | No crash; result still persisted |
| Duplicate `create_job()` call | Same `job_id` inserted twice | Second insert ignored (INSERT OR IGNORE) | No crash; log warning |

</frozen-after-approval>

## Code Map

- `server/backend/database/migrations/versions/006_add_transcription_jobs.py` -- new Alembic migration; creates `transcription_jobs` table + 2 indexes
- `server/backend/database/job_repository.py` -- new file; CRUD layer for `transcription_jobs`; uses `get_connection()` context manager
- `server/backend/core/json_utils.py` -- new file; `sanitize_for_json()` — handles NaN/Inf, numpy types, bad UTF-8
- `server/backend/api/routes/websocket.py` -- `TranscriptionSession`: add `create_job()` in `handle_client_message()` after `try_start_job()` succeeds; add `save_result()` + `mark_delivered()` in `process_transcription()`; add `mark_failed()` in both exception handlers; add `job_id` to `session_started` payload
- `server/backend/api/routes/transcription.py` -- add `GET /result/{job_id}` endpoint; calls `get_job()` + `mark_delivered()` on retrieval
- `dashboard/src/hooks/useTranscription.ts` -- store `jobId` from `session_started`; add HTTP polling fallback in `onClose` when status is `'processing'`

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/database/migrations/versions/006_add_transcription_jobs.py` -- CREATE migration with `transcription_jobs` table (id TEXT PK, status, source, client_name, language, task, translation_target, result_text, result_json, result_language, duration_seconds, error_message, delivered INTEGER DEFAULT 0, created_at, completed_at) + indexes on (status) and (client_name, created_at) -- establishes durable store before any code changes
- [x] `server/backend/database/job_repository.py` -- IMPLEMENT `create_job`, `save_result`, `mark_delivered`, `mark_failed`, `get_job`, `get_recent_undelivered`, `set_audio_path` (stub for Wave 2) -- all using `get_connection()` + parameterized queries
- [x] `server/backend/core/json_utils.py` -- IMPLEMENT `sanitize_for_json(obj)` that replaces float NaN/Inf with None, converts numpy scalars to Python natives, ensures string UTF-8 validity
- [x] `server/backend/api/routes/websocket.py` -- MODIFY as follows. All new imports must be added at the TOP of the file, not inline. (1) In `handle_client_message()`: after `session._current_job_id = job_id` is set, extract `language`, `translation_enabled`, and `translation_target_language` from `message["data"]` FIRST, then call `create_job()` using those extracted values — do NOT use session attributes which are not yet set at this point; on `create_job()` failure, set `session._current_job_id = None` and log warning. (2) In `process_transcription()`: call `sanitize_for_json()` on the result payload, then call `save_result()` BEFORE `send_message("final")` — if `save_result()` raises, log CRITICAL but do NOT re-raise; attempt `send_message("final")` regardless (delivery must not be sacrificed for DB consistency); after successful send, call `mark_delivered()` with warning-only on failure. (3) Add `mark_failed()` to both exception handlers (TranscriptionCancelledError and general), wrapped in try/except that only logs on failure. (4) Add `"job_id": self._current_job_id` to `session_started` data dict.
- [x] `server/backend/api/routes/transcription.py` -- ADD `GET /result/{job_id}` route: returns 200+result if completed, 202 if processing, 410+error if failed, 404 if not found; calls `mark_delivered()` on 200 response -- enables HTTP recovery path
- [x] `dashboard/src/hooks/useTranscription.ts` -- ADD `jobId: string | null` to `TranscriptionState`; store `jobId` from `session_started` message; in `onClose`, if `status === 'processing'` and `jobId` is set, poll `GET /api/transcribe/result/{jobId}` every 3s up to 10 retries; on success treat as `"final"` message -- closes the client-side recovery loop

**Acceptance Criteria:**
- Given a completed transcription, when the result is persisted, then the DB write occurs before `send_message("final")` fires (verified by log ordering and DB state)
- Given a WebSocket disconnect during processing, when the client reconnects and polls `GET /api/transcribe/result/{job_id}`, then the completed result is returned with 200
- Given a server exception during `process_transcription()`, when the exception is caught, then the job row has `status='failed'` with a non-empty `error_message`
- Given `result.words` contains `float('nan')`, when `sanitize_for_json()` is called, then the serialized JSON contains `null` instead and no `ValueError` is raised
- Given a new WebSocket session starts, when `session_started` is sent, then the payload includes `job_id`
- Given all of the above, when existing test suite runs, then all previously-passing tests still pass

## Design Notes

`save_result()` DB failure must NOT abort delivery. "Persist before deliver" means ordering, not coupling. If the DB write fails: log a CRITICAL-level error (so ops can see it in logs), then attempt `send_message("final")` anyway. The user already has the transcription in memory — sacrificing client delivery to protect DB consistency violates the AVOID DATA LOSS invariant. Do NOT re-raise. Do NOT call `mark_failed`.

`mark_delivered()` should NOT re-raise on failure — if it fails, log a warning and move on. Delivery already happened; `delivered=0` just means the recovery path may offer a duplicate later.

The HTTP `GET /result/{job_id}` endpoint should call `mark_delivered()` only on 200 responses — not on 202 or 410.

`create_job()` must be called with data extracted directly from the message dict (`message["data"]`), not from session attributes (`self.language` etc.). Session attributes are set in `start_recording()` which is called AFTER `handle_client_message()` returns. Reading them before `start_recording()` will always give `None`/`False`. If `create_job()` itself fails, immediately set `session._current_job_id = None` and log a warning — this prevents downstream DB calls from failing against a non-existent row.

**Required attribution comments** (per CLAUDE.md `CREDIT CODE SOURCES` invariant). Add at the implementation site, not in docs:

| Where | Credit |
|-------|--------|
| `job_repository.py` — top of file or near `create_job()` | `# Adapted from Scriberr (https://github.com/rishikanthc/Scriberr) — job model structure: id, status, audio_path, result, error_message, timestamps` |
| `job_repository.py` — state machine transitions (`processing→completed\|failed`) | `# Adapted from Scriberr (https://github.com/rishikanthc/Scriberr) — job state machine pattern` |

No attribution needed for the JSON sanitization utility, polling logic, or the persist-before-deliver pattern (general architectural pattern, not borrowed from a specific codebase).

## Verification

**Commands:**
- `cd server && python -m pytest backend/tests/ -x -q` -- expected: same pass count as baseline (285), no new failures
- `cd server && python -m alembic upgrade head` -- expected: migration applies cleanly, no errors

**Manual checks (if no CLI):**
- After a WebSocket transcription: verify row exists in `transcription_jobs` with `status='completed'` and `delivered=1`
- After killing the WebSocket mid-processing: verify row exists with `status='failed'`
- Disconnect during processing then poll `GET /api/transcribe/result/{job_id}`: verify 200 with result text

## Suggested Review Order

**Core invariant — persist before deliver**

- Entry point: `save_result()` called, then `send_message("final")` — never the other way
  [`websocket.py:211`](../../server/backend/api/routes/websocket.py#L211)

- On DB failure: logs CRITICAL, falls through to delivery — result is not silently dropped
  [`websocket.py:221`](../../server/backend/api/routes/websocket.py#L221)

- `mark_delivered` and `mark_failed` calls — terminal state bookkeeping
  [`websocket.py:237`](../../server/backend/api/routes/websocket.py#L237)

**Job lifecycle — creation and metadata**

- `create_job()` reads from message dict before session attrs are set by `start_recording()`
  [`websocket.py:485`](../../server/backend/api/routes/websocket.py#L485)

- On create failure: `_current_job_id = None` prevents downstream noise, not silent loss
  [`websocket.py:493`](../../server/backend/api/routes/websocket.py#L493)

- `job_id` included in `session_started` — gives client a recovery token from the start
  [`websocket.py:369`](../../server/backend/api/routes/websocket.py#L369)

- `mark_failed` in both cancellation and error paths
  [`websocket.py:270`](../../server/backend/api/routes/websocket.py#L270)

**Database layer**

- Alembic migration: table schema, indexes, revision chain `005→006`
  [`006_add_transcription_jobs.py:36`](../../server/backend/database/migrations/versions/006_add_transcription_jobs.py#L36)

- `save_result()` — sets completed_at and stores full JSON payload; re-raises on failure
  [`job_repository.py:45`](../../server/backend/database/job_repository.py#L45)

- `create_job()` — INSERT OR IGNORE; Scriberr attribution; state machine pattern
  [`job_repository.py:21`](../../server/backend/database/job_repository.py#L21)

**HTTP recovery path**

- `GET /result/{job_id}` — 200/202/404/410; ownership check; safe JSON decode
  [`transcription.py:788`](../../server/backend/api/routes/transcription.py#L788)

**Client-side recovery**

- Dual `jobId` state + `jobIdRef`: reactive for render, stable for closure
  [`useTranscription.ts:75`](../../dashboard/src/hooks/useTranscription.ts#L75)

- `session_started` handler stores job_id into both state and ref
  [`useTranscription.ts:116`](../../dashboard/src/hooks/useTranscription.ts#L116)

- `onClose` polling loop with cancellation guard and 404 fallthrough
  [`useTranscription.ts:234`](../../dashboard/src/hooks/useTranscription.ts#L234)

**Utilities**

- `sanitize_for_json()` — NaN/Inf→None, numpy types, UTF-8; called before both DB write and WS send
  [`json_utils.py:9`](../../server/backend/core/json_utils.py#L9)

## Spec Change Log

### Loop 1 (2026-03-30) — websocket.py reverted and re-derived

**Finding A (bad_spec):** Design Notes said `save_result()` should re-raise on DB failure. This caused the outer `except` to call `mark_failed`, marking a *successful* transcription as failed and aborting client delivery.
**Amendment:** Changed to "log CRITICAL + attempt delivery regardless." Ordering invariant preserved; coupling removed.
**Known-bad state avoided:** `save_result` DB error → `mark_failed` → client sees error → transcription lost despite successful STT.
**KEEP:** `mark_delivered()` warning-only semantics; `mark_failed()` in both exception handlers; `session_started` includes `job_id`.

**Finding B (bad_spec):** Task said to use `self.language`, `self.translation_enabled` etc. but those are set by `start_recording()` which runs *after* `handle_client_message()`. Every insert had `language=NULL, task='transcribe'`.
**Amendment:** Task now requires extracting values from `message["data"]` dict *before* calling `create_job()`. On failure: set `session._current_job_id = None`.
**Known-bad state avoided:** All jobs stored with wrong language/task metadata.
**KEEP:** `create_job()` placed in `handle_client_message()` after `try_start_job()` succeeds.

**Patches applied to other files after re-derivation:**
- `transcription.py` — remove unreachable dead-code guard
- `useTranscription.ts` — unmount cancel flag; `jobId` as useState; `404` poll fallback
- Removed `AssemblyAI/Deepgram` attribution from websocket.py (general pattern, not a specific source)
