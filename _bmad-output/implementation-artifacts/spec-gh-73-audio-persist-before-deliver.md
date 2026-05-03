---
title: 'GH-73 Deferred: Persist-before-deliver on /audio sync route'
type: 'bugfix'
created: '2026-04-12'
status: 'done'
baseline_commit: '32b566f'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The synchronous `/api/transcribe/audio` route (and its `/api/transcribe/file` alias) runs transcription and returns the result dict directly to the client without ever calling `create_job()` or `save_result()`. If the HTTP response fails mid-flight (connection reset, client crash, serialization error, reverse-proxy timeout), the completed transcription is silently lost. This violates the CLAUDE.md invariant: "Every code path that produces a transcription result MUST persist it to durable storage BEFORE attempting to deliver it to the client." The gap is pre-existing — not introduced by multitrack — and applies to all four code paths in the route (multitrack, integrated diarization, parallel/sequential diarization, standard).

**Approach:** Adopt the WebSocket durability pattern already used in `websocket.py::handle_client_message` / `process_transcription`. After `try_start_job()` succeeds, immediately call `create_job()` with source `"audio_upload"` using the Form params. Before each of the three `return result_dict` sites, call `sanitize_for_json()` + `save_result()` (save failure is CRITICAL-logged but non-blocking — delivery must still proceed). After the existing webhook dispatch, call `mark_delivered()` (warning-only on failure). In the `TranscriptionCancelledError` and general `Exception` handlers, call `mark_failed()` wrapped in try/except. The existing `/result/{job_id}` endpoint then becomes the recovery path — clients that drop connections can poll and re-retrieve the persisted result.

## Boundaries & Constraints

**Always:** Preserve the existing response shape — the client still receives the same `result_dict` it does today. Persist-before-deliver ordering is the invariant: `save_result()` runs before `return`; `mark_delivered()` runs on the success path only. DB failures log but never abort delivery. Scope limited to `/audio` (and its `/file` alias on the same decorator); `/quick` is out of scope for this spec.

**Ask First:** If `create_job()` should be skipped when `client_name` is empty/unknown (WebSocket precedent keeps it; we follow suit).

**Never:** Do not change `job_repository.py` — reuse the existing functions. Do not alter HTTP status codes or response payload shape. Do not touch `/quick`, `/import`, or the WebSocket path. Do not introduce a new job-tracker source string outside `"audio_upload"` without updating existing sources.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Multi-channel WAV, multitrack=true | DB row: status=completed, result_json populated, delivered=1; client receives result_dict | N/A |
| Standard transcription | Mono WAV, diarization=false | Same: row saved before return, delivered marked after webhook | N/A |
| Integrated diarization | WhisperX backend, diarization=true | Row saved before return from integrated path | N/A |
| Parallel diarization | Mono WAV, diarization=true | Row saved before return from diarize path | N/A |
| `create_job()` DB failure | SQLite locked at job start | Log warning, set `db_job_id=None`, continue transcription (no persistence, but no 500 to client) | Warning logged |
| `save_result()` DB failure | SQLite locked at result persist | CRITICAL log, continue to webhook+return (client still receives result) | CRITICAL logged |
| `mark_delivered()` DB failure | SQLite locked after delivery | Warning log, return result anyway | Warning logged |
| TranscriptionCancelledError | User cancels mid-job | `mark_failed(job_id, "Cancelled by user")`, then existing 499 raise | Failure captured in DB |
| General Exception | Backend crashes during transcribe | `mark_failed(job_id, str(e))`, then existing 500 raise | Failure captured in DB |
| ValueError (bad input) | Invalid audio file | `mark_failed(job_id, str(e))`, then existing 400 raise | Failure captured in DB |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/transcription.py:65-381` -- MODIFY: add create_job after try_start_job; wrap each of 3 return paths with save_result + mark_delivered; wrap 3 exception handlers with mark_failed
- `server/backend/database/job_repository.py` -- READ-ONLY: existing create_job / save_result / mark_delivered / mark_failed API
- `server/backend/core/json_utils.py` -- READ-ONLY: existing `sanitize_for_json`
- `server/backend/api/routes/websocket.py:580-610` -- READ-ONLY: canonical persist-before-deliver pattern to mirror
- `server/backend/tests/test_transcription_durability_routes.py` -- READ-ONLY reference for durability test style
- `server/backend/tests/test_audio_route_durability.py` -- NEW: unit tests covering persist ordering on all 4 paths and 3 error handlers

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/transcription.py` -- Add top-level imports for `sanitize_for_json`, `create_job`, `save_result`, `mark_delivered`, `mark_failed`, `json as _json`. Inside `transcribe_audio`, immediately after `try_start_job()` succeeds, call `create_job(job_id, source="audio_upload", client_name=client_name, language=language, task="translate" if translation_enabled else "transcribe", translation_target=translation_target_language if translation_enabled else None)` wrapped in try/except that logs a warning and sets a local `db_job_id = None` on failure (else `db_job_id = job_id`).
- [x] `server/backend/api/routes/transcription.py` -- Introduce a tiny local helper `_persist_result(db_job_id, result_dict)` inside `transcribe_audio` that: (a) builds a sanitized copy via `sanitize_for_json(result_dict)`, (b) if `db_job_id` is truthy, calls `save_result(job_id=db_job_id, result_text=result_dict.get("text",""), result_json=_json.dumps(sanitized, ensure_ascii=False), result_language=result_dict.get("language"), duration_seconds=result_dict.get("duration"))` inside try/except that logs CRITICAL on failure but never raises. Call this helper before each of the 3 return sites (multitrack, integrated diarization, standard). After the existing `dispatch_webhook` call, add `if db_job_id: try: mark_delivered(db_job_id) except Exception as _e: logger.warning(...)` before the return.
- [x] `server/backend/api/routes/transcription.py` -- In the `except ValueError`, `except TranscriptionCancelledError`, and general `except Exception` handlers (lines ~362-371), add `if db_job_id:` guarded `mark_failed(db_job_id, <message>)` calls, each wrapped in try/except that logs warning only. Cancellation uses "Transcription cancelled by user"; ValueError uses `str(e)`; general uses `str(e)`. Re-raise the existing HTTPException unchanged.
- [x] `server/backend/tests/test_audio_route_durability.py` -- CREATE unit tests using the direct-call pattern (see CLAUDE.md Backend Testing section). Patch `job_repository.create_job/save_result/mark_delivered/mark_failed`, engine.transcribe_file, and related helpers. Verify: (a) happy path calls create_job → save_result → dispatch_webhook → mark_delivered in order for the standard path; (b) multitrack path persists before return; (c) integrated diarization path persists before return; (d) `save_result` DB failure does NOT abort delivery (client still gets dict); (e) `create_job` DB failure leaves `db_job_id=None` and suppresses later persist calls; (f) cancellation triggers `mark_failed` with cancel message; (g) general exception triggers `mark_failed` with exception string.

**Acceptance Criteria:**
- Given a multi-channel audio upload with multitrack=true, when transcription completes, then `save_result` is called before the HTTP response is constructed (verified by call-order assertion in the test) and the DB row has `status='completed'`, `delivered=1`.
- Given a standard mono upload, when transcription completes, then the same save_result→webhook→mark_delivered ordering applies.
- Given `save_result()` raises, when the route continues, then the client still receives the 200 result_dict AND a CRITICAL log entry is recorded.
- Given a `TranscriptionCancelledError`, when the handler runs, then `mark_failed(job_id, "Transcription cancelled by user")` is called and a 499 is raised.
- Given an unhandled exception in the transcription engine, when the handler runs, then `mark_failed(job_id, str(exc))` is called and a 500 is raised.
- Given `create_job()` raises at route start, when transcription proceeds, then no `save_result`/`mark_delivered`/`mark_failed` calls are made (db_job_id is None) and the route still returns the result to the client.

## Spec Change Log

- **Review iteration 1 (2026-04-12):** Three review subagents (blind hunter, edge case hunter, acceptance auditor) raised overlapping findings that required patches (no intent or spec changes). Applied:
  - Added a `_persisted` nonlocal flag set by `_persist_result` on success. Gated `mark_delivered` on `_persisted` (never deliver an unpersisted row → prevents `delivered=1` + `status='processing'` dead state) and gated `mark_failed` in all 3 exception handlers on `not _persisted` (a post-persist exception — e.g. webhook failure — must not overwrite `status='completed'` to `status='failed'`).
  - Moved the tempfile block inside the main `try:` so `file.read()` / `tmp.write()` failures (client disconnect mid-body, disk full) route through `mark_failed` + `end_job` via the shared exception handler instead of leaking a busy tracker slot and an orphaned processing row. `tmp_path` is initialized to `None` so the `finally` cleanup is tolerant of the tempfile step failing.
  - Applied `sanitize_for_json` consistently — now `result_text`, `result_language`, and `duration_seconds` all read from the sanitized dict (previously only `result_json` was sanitized; scalar numpy floats could leak to SQLite).
  - Added 4 tests to `test_audio_route_durability.py`: `test_webhook_failure_after_persist_does_not_overwrite_to_failed`, `test_mark_delivered_failure_does_not_abort_delivery`, `test_tempfile_read_failure_triggers_mark_failed`, `test_save_result_failure_on_multitrack_suppresses_mark_delivered`.
  - **Deferred** (not this spec's problem): the pre-existing `except Exception:` at the integrated diarization path silently swallows `TranscriptionCancelledError` and `ValueError`, falling through to the standard path. Appended to `deferred-work.md`.

## Design Notes

The `_persist_result` helper is intentionally tiny and defined inside `transcribe_audio` to avoid a module-level abstraction that would over-generalize one endpoint's needs. Three return sites calling the same 8 lines of save+log justify a local helper; `/quick` and future endpoints can copy the pattern if/when they adopt durability (out of scope here).

Persist-before-deliver means ordering, not coupling — DB failures must never prevent the client from receiving a completed transcription. See `docs/project-context.md` and the Wave 1 spec for the canonical statement of this invariant.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_audio_route_durability.py -v --tb=short` -- expected: all new tests pass
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: existing passing suite still passes (no regressions)

## Suggested Review Order

**Persist-before-deliver state machine**

- The `_persisted` flag is the fulcrum — set only on successful `save_result`, gates every downstream DB write.
  [`transcription.py:157`](../../server/backend/api/routes/transcription.py#L157)

- `_persist_result` closure: mirrors the WebSocket pattern — CRITICAL log on DB failure, never raises. Scalar fields now read from the sanitized dict.
  [`transcription.py:159`](../../server/backend/api/routes/transcription.py#L159)

- `create_job` at route start with warning-on-failure fallback to `db_job_id = None`.
  [`transcription.py:136`](../../server/backend/api/routes/transcription.py#L136)

**Success-path persist ordering (three entry points, identical shape)**

- Multitrack path: `save_result` → webhook → `mark_delivered` (gated on `_persisted`).
  [`transcription.py:258`](../../server/backend/api/routes/transcription.py#L258)

- Integrated diarization path: same ordering; note this path does not dispatch a webhook today.
  [`transcription.py:326`](../../server/backend/api/routes/transcription.py#L326)

- Standard / parallel-diarization path: same ordering.
  [`transcription.py:461`](../../server/backend/api/routes/transcription.py#L461)

**Failure-path guarantees**

- `except ValueError` — `mark_failed` gated on `not _persisted` so post-persist exceptions cannot clobber `status='completed'`.
  [`transcription.py:476`](../../server/backend/api/routes/transcription.py#L476)

- `except TranscriptionCancelledError` — mark_failed uses the spec-mandated "Transcription cancelled by user" message.
  [`transcription.py:489`](../../server/backend/api/routes/transcription.py#L489)

- `except Exception` — catch-all; this is the branch that now fires when e.g. the tempfile write fails.
  [`transcription.py:502`](../../server/backend/api/routes/transcription.py#L502)

**Lifecycle hardening**

- Tempfile write moved inside the main `try` block; `tmp_path = None` initializer makes the `finally` cleanup tolerant of upstream failure.
  [`transcription.py:203`](../../server/backend/api/routes/transcription.py#L203)

**Tests**

- 12 tests covering happy path on 3 routes, DB failure modes for create_job/save_result/mark_delivered, webhook-after-persist guarantee, tempfile I/O failure, and three exception handlers.
  [`test_audio_route_durability.py:1`](../../server/backend/tests/test_audio_route_durability.py#L1)
