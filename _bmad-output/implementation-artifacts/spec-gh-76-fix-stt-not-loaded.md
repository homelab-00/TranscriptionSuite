---
title: 'GH-76: Auto-recover transcription engine when backend is silently unloaded'
type: 'bugfix'
created: '2026-04-14'
status: 'done'
baseline_commit: '5f5b9cc23d8758073509ed22532922203a0eaca2'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every Notebook → Import job fails with `STT model is not loaded` whenever the main `AudioToTextRecorder._backend` is `None` at the time the upload background task runs. The most common trigger is the live-mode restore path (`live.py:_reload_main_model` at lines 385–405) silently swallowing exceptions on its `model_manager.load_transcription_model()` call after Live Mode ends, so the engine stays unloaded forever with no user-visible signal. None of the file-transcription routes proactively re-load the model before calling `engine.transcribe_file(...)`, so the user sees the cryptic error on every retry until they manually click "Reload Model" in Settings.

**Approach:** Introduce a single `ModelManager.ensure_transcription_loaded()` helper that returns the engine when its backend is attached, and otherwise calls `load_transcription_model()` on demand to re-attach. Wire every file-transcription entry point — Notebook upload, `/api/transcribe/audio|file|quick|import|retry`, and the realtime WS file path — through that helper so a transient unload self-heals on the next request. Surface a clear actionable HTTP error (with `BackendDependencyError.remedy` text where applicable) instead of the bare runtime string when the on-demand reload also fails.

## Boundaries & Constraints

**Always:**
- Persist-before-deliver ordering in routes that touch the durability tables MUST remain unchanged — auto-reload runs BEFORE `try_start_job`/`create_job` so a failed reload aborts the job slot acquisition cleanly.
- The reload helper MUST be idempotent and a no-op when `_backend` is already attached (do not unload-then-reload working backends).
- The helper MUST hold the model-manager's existing lock semantics (no new locks introduced) — rely on `load_transcription_model()`'s current single-call contract; concurrent callers serialize on the same in-engine model load.
- `BackendDependencyError` propagation MUST surface the `remedy` field in the user-facing error so the dashboard can render an actionable hint (matches the existing `/api/admin/models/load` 503 contract at `admin.py:233-236`).

**Ask First:**
- If `engine.transcribe_file()` would benefit from an `is_loaded()` re-check between auto-reload and call (i.e., a paranoia second guard against same-loop concurrent unloads).
- If we should also harden `live.py:_reload_main_model` to emit a user-visible `emit_event` toast on non-`BackendDependencyError` failures (out-of-scope for this spec unless asked).

**Never:**
- Do not introduce any new public-facing endpoints or change existing route paths/response shapes outside of error payloads.
- Do not change the live-mode backend sharing path (`detach_transcription_backend` / `attach_transcription_backend`) — those work correctly and are not the bug.
- Do not auto-reload from inside `engine.transcribe_audio()` itself (the leaf function) — keep model lifecycle decisions in `ModelManager`, not the engine.
- Do not alter the OpenAI compat endpoints' `model_manager.engine` (sic) bug — that's a separate latent bug to be filed as deferred work.
- Do not silently swallow non-`BackendDependencyError` reload failures inside `ensure_transcription_loaded()` — they MUST raise so the route returns a meaningful 5xx.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Healthy steady state | `_backend` attached, no concurrent unload | `ensure_transcription_loaded()` returns the existing engine; no reload attempted | N/A |
| Backend silently unloaded after live-mode restore failure | `_transcription_engine` is set but `_backend is None` | `ensure_transcription_loaded()` calls `load_transcription_model()`, returns engine with backend re-attached; transcription proceeds | N/A — recovery succeeded |
| Engine never created (preload failed at startup) | `_transcription_engine is None` | `ensure_transcription_loaded()` triggers `_create_transcription_engine()` via `load_transcription_model()` | If creation raises `BackendDependencyError`, propagate up. Routes return HTTP 503 with `BackendDependencyError.remedy` in detail. |
| Reload fails with `BackendDependencyError` (e.g., NeMo missing for Parakeet) | `_backend is None`, dependency missing | `ensure_transcription_loaded()` re-raises `BackendDependencyError` | Routes catch and return HTTP 503 with actionable detail (matches `admin.py:233-236` shape). Notebook background job stores `{"error": "<message>", "remedy": "<remedy>"}` in `job_tracker.result`. |
| Reload fails with non-dependency error (e.g., transient CUDA OOM) | `_backend is None`, model load raises generic `RuntimeError` | `ensure_transcription_loaded()` re-raises | Routes return HTTP 500 with sanitized error message. Background job stores the error. The next request retries (no permanent break). |
| No main model selected (disabled slot) | `resolve_main_transcriber_model(config) == ""` | `ensure_transcription_loaded()` raises a typed `MainModelDisabledError` (or reuses `RuntimeError` from `_create_transcription_engine`) | Routes return HTTP 409 mirroring the existing `_assert_main_model_selected` contract. |
| Concurrent uploads race the reload | Two uploads arrive while `_backend is None` | First call's `load_transcription_model()` completes; second observes `is_loaded()` true and short-circuits | The internal `engine.load_model()` already guards via `if self._model_loaded: return` (engine.py:1142-1144). Acceptable; document the assumption. |

</frozen-after-approval>

## Code Map

- `server/backend/core/model_manager.py` — add `ensure_transcription_loaded()` method (~10 lines) below the `transcription_engine` property; reuses existing `load_transcription_model()` plumbing.
- `server/backend/core/stt/engine.py:903-904` — leaf-level `_backend is None` guard stays as a defense-in-depth fallback; no change.
- `server/backend/api/routes/notebook.py:437` — primary bug site; replace `engine = model_manager.transcription_engine` in `_run_transcription`.
- `server/backend/api/routes/transcription.py:216,574,706,1220` — four call sites in `transcribe_audio`, `transcribe_quick`, `_run_file_import`, `_run_retry`; same swap.
- `server/backend/api/routes/websocket.py:210` — realtime WS file-transcription path; same swap.
- `server/backend/api/routes/live.py:385-405` — `_reload_main_model`: leave the `BackendDependencyError` warning-and-continue branch, but **let non-dependency errors propagate** (delete the bare `else: logger.error(...)` swallow) so the caller's `try/except` at line 379 logs them with the original traceback. This is the critical structural fix to surface the unload trigger.
- `server/backend/tests/test_model_manager.py` (or new `test_ensure_loaded.py`) — new unit tests for the helper.
- `server/backend/tests/test_transcription_durability_routes.py` and/or new `test_notebook_upload_recovery.py` — route-level test that an unloaded backend triggers reload.
- `_bmad-output/implementation-artifacts/deferred-work.md` — file the `openai_audio.py` `model_manager.engine` AttributeError bug as deferred follow-up.

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/model_manager.py` — add `ensure_transcription_loaded()` method that returns `self.transcription_engine` if `_backend` is attached, else calls `self.load_transcription_model()` and returns the engine. Document that `BackendDependencyError` propagates for caller HTTP-mapping.
- [x] `server/backend/api/routes/notebook.py` — in `_run_transcription`, replace `engine = model_manager.transcription_engine` with `engine = model_manager.ensure_transcription_loaded()`. Catch `BackendDependencyError` in the outer except and store both `error` and `remedy` in `job_tracker.result`.
- [x] `server/backend/api/routes/transcription.py` — at all four call sites (`transcribe_audio`, `transcribe_quick`, `_run_file_import`, `_run_retry`), swap to `ensure_transcription_loaded()`. For sync routes, surface `BackendDependencyError` as HTTP 503 with `detail = f"{error}. {remedy}"`.
- [x] `server/backend/api/routes/websocket.py` — same swap in the realtime file-transcription path; on `BackendDependencyError`, send a structured WS error message (mirror the existing error-message protocol).
- [x] `server/backend/api/routes/live.py:_reload_main_model` — keep the `BackendDependencyError` graceful warning. Remove the silent `else: logger.error(...)` swallow for non-dep errors; add `raise` so the caller's `try/except` at line 379 records the actual failure with traceback. Add an `emit_event("warn-stt", "warning", "Main model unavailable — click Reload Model in Settings", persistent=True)` next to the warning log so the user sees a banner instead of a healthy-looking server.
- [x] `server/backend/tests/test_model_manager.py` — add 4 unit tests covering the I/O matrix scenarios for `ensure_transcription_loaded` (healthy, unloaded, never-created, dep-error).
- [x] `server/backend/tests/test_notebook_upload_recovery.py` (new) — direct-call test against `_run_transcription` proving auto-reload occurs and the original error message is replaced when reload fails with `BackendDependencyError`.
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` — append entry: "openai_audio.py uses `model_manager.engine` (no such attr) at lines 138, 238 — must be `model_manager.transcription_engine`. Both POST /v1/audio/transcriptions and /v1/audio/translations endpoints currently throw AttributeError on first use. Filed as separate deferred fix."

**Acceptance Criteria:**
- Given the main backend is unloaded after a Live Mode session, when the user uploads a file via Notebook → Import, then the upload route auto-reloads the model and transcription proceeds without manual intervention.
- Given the main backend cannot be loaded due to a missing dependency (e.g., NeMo for Parakeet), when the user uploads via Notebook → Import, then the job_tracker result contains `error` AND `remedy` fields, and the dashboard can surface them.
- Given the main backend was never loaded (preload failed silently at startup), when any file transcription route is hit, then it triggers a load attempt and either succeeds or returns HTTP 503 with the dependency remedy text — never the bare "STT model is not loaded".
- Given Live Mode reload fails for a non-dependency reason, when the live-mode session ends, then the failure is logged with full traceback (not silently swallowed) AND a persistent warning event is emitted so the dashboard can show a banner.
- Given two upload jobs arrive concurrently while the backend is unloaded, when both call `ensure_transcription_loaded()`, then exactly one full reload happens and both jobs proceed (no double-load, no race-induced failure).
- All existing tests in `server/backend/tests/` continue to pass.

## Spec Change Log

### 2026-04-14 — step-04 review, iteration 1

PATCH-class findings applied during review (no loopback — no intent_gap or bad_spec). Scoped to the already-frozen Boundaries & I/O matrix; no frozen-section content changed.

- **Thread safety for `ensure_transcription_loaded`** — added `threading.Lock` in `ModelManager.__init__` and wrapped the helper body, so two concurrent HTTP uploads racing into a detached state can't both trigger `load_transcription_model()` and double-allocate GPU memory. Matches the Row 6 "concurrent uploads" scenario already listed in the I/O matrix. *Known bad state avoided: OOM on sub-16 GB GPUs when two requests overlap after a Live Mode reload.*
- **Post-reload state-desync guard** — added a `_backend is None` re-check after `load_transcription_model()` returns; if the engine is still detached, raise `RuntimeError("… still detached after reload …")`. *Known bad state avoided: silently returning a still-broken engine that would crash at the leaf guard with a generic message.*
- **Sync-route ordering — `ensure_transcription_loaded` now runs BEFORE `try_start_job`** in both `transcribe_audio` and `transcribe_quick`, matching the frozen Always rule verbatim. A failed reload short-circuits to HTTP 503 without ever acquiring a slot, creating an orphan DB row, or writing a tmp file. *Known bad state avoided: job-slot pollution + orphan rows on every failed reload.*
- **`stop_engine` catches `CancelledError`** — the try/except around `_restore_or_reload_main_model()` now catches `(Exception, asyncio.CancelledError)` so a WS cancel mid-reload doesn't skip the `STOPPED` state notification. Mirrors the existing `start_engine.finally` block's tuple. *Known bad state avoided: client UI stuck showing "stopping".*
- **`_run_retry` gained a `BackendDependencyError` handler** — previously routed BDE to the generic `except Exception` which wrote the bare error string to `mark_failed`. Now surfaces `f"{dep_err}. {dep_err.remedy}"`.
- **HTTP 503 detail prefix + empty-remedy guard** — detail now formats as `f"Backend dependency missing: {dep_err}{remedy_suffix}"` matching the existing `admin.py:233-236` 503 contract; `remedy_suffix` is empty when `dep_err.remedy` is falsy, avoiding a trailing ". " artefact.
- **Dropped pointless `lambda` wrapper** around `model_manager.ensure_transcription_loaded` in `websocket.py`.
- **`emit_event` failure log level** — raised from `debug` to `warning` in `live.py:_reload_main_model`.
- **Removed duplicate inline `BackendDependencyError` import** in `_run_file_import`.
- **Two new tests** — `test_raises_when_reload_lies_and_backend_still_none` locks in the post-reload guard; `test_concurrent_callers_trigger_exactly_one_reload` exercises the threading lock.

**KEEP instructions** (preserve across any future re-derivation):
- The single `ensure_transcription_loaded()` helper pattern — do NOT split into per-route helpers.
- `BackendDependencyError` propagation with `remedy` surfaced as HTTP 503 — matches existing admin.py contract.
- Live-mode reload failure emits `warn-stt-main` event BEFORE any `raise`, so dashboard visibility is preserved even when the caller catches.
- `stop_engine` must always send the final `STOPPED` state message — catch exceptions AND CancelledError around the restore call.

Defer-class findings appended to `deferred-work.md` under "Surfaced during step-04 adversarial review of this same spec": payload DRY extraction, nested `__cause__` walker, repeated-failure cost amortization, sync-disk writes from async, and `STOPPED`-state UX polish.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_model_manager.py -v --tb=short` -- expected: all tests pass including the 4 new `ensure_transcription_loaded` cases
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_notebook_upload_recovery.py -v --tb=short` -- expected: new recovery test passes
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short -x` -- expected: no regressions in the broader suite (285+ existing passing tests)
- `cd server/backend && ../../build/.venv/bin/ruff check server/core/model_manager.py server/api/routes/notebook.py server/api/routes/transcription.py server/api/routes/websocket.py server/api/routes/live.py` -- expected: no lint errors

## Suggested Review Order

**The helper (design intent)**

- New method + threading lock — returns the engine if backend is attached, otherwise triggers an on-demand reload; post-reload guard raises if state is still desynced.
  [`model_manager.py:714`](../../server/backend/core/model_manager.py#L714)

- Lock initialization in `ModelManager.__init__` — serialises concurrent uploads racing into a detached state.
  [`model_manager.py:211`](../../server/backend/core/model_manager.py#L211)

**Sync-route pre-check (frozen Always rule)**

- Ensure runs BEFORE `try_start_job` so a failed reload never acquires a slot or creates an orphan DB row. Maps `BackendDependencyError` → HTTP 503 with admin.py-shaped detail.
  [`transcription.py:129`](../../server/backend/api/routes/transcription.py#L129)

- Same pattern for the Record-view "quick" path.
  [`transcription.py:591`](../../server/backend/api/routes/transcription.py#L591)

**Background-task recovery (Notebook → Import — the bug-affected path)**

- Primary #76 fix: notebook upload background task auto-reloads and surfaces `remedy` + `backend_type` on dependency failure.
  [`notebook.py:440`](../../server/backend/api/routes/notebook.py#L440)

- Mirror pattern for session Import Queue background task.
  [`transcription.py:758`](../../server/backend/api/routes/transcription.py#L758)

- New `BackendDependencyError` handler on retry so retried jobs get the same remedy text.
  [`transcription.py:1286`](../../server/backend/api/routes/transcription.py#L1286)

**WebSocket realtime file transcription**

- Same ensure + BDE-aware error message; dropped the pointless `lambda` wrapper that was masking tracebacks.
  [`websocket.py:212`](../../server/backend/api/routes/websocket.py#L212)

**Live-mode visibility (secondary #76 fix — surfaces the next failure trigger)**

- `_reload_main_model` now emits `warn-stt-main` event on both branches and re-raises non-dependency errors so the caller sees the full traceback.
  [`live.py:385`](../../server/backend/api/routes/live.py#L385)

- `stop_engine` wraps the restore call to catch both `Exception` and `CancelledError`, guaranteeing the final `STOPPED` state reaches the client.
  [`live.py:454`](../../server/backend/api/routes/live.py#L454)

**Tests**

- Helper scenarios — healthy path, detached reload, never-created, BDE propagation, state-desync guard, and two-thread concurrency race.
  [`test_ensure_transcription_loaded.py:1`](../../server/backend/tests/test_ensure_transcription_loaded.py#L1)

- Route-level recovery — notebook + import-queue + live-mode emit-event visibility.
  [`test_notebook_upload_recovery.py:1`](../../server/backend/tests/test_notebook_upload_recovery.py#L1)

- Fixture updates so pre-#76 tests continue to pass with the new helper shape.
  [`test_audio_route_durability.py:49`](../../server/backend/tests/test_audio_route_durability.py#L49)

- Same fixture update in the P0 durability suite.
  [`test_p0_durability.py:89`](../../server/backend/tests/test_p0_durability.py#L89)
