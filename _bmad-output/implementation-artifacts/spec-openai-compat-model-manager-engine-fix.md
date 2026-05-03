---
title: 'OpenAI-Compat Endpoints — model_manager.engine AttributeError Fix'
type: 'bugfix'
created: '2026-04-14'
status: 'done'
baseline_commit: '41d564c62ce0396e9c7aca6e0d9af8273fb2aedf'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-gh-76-fix-stt-not-loaded.md'
  - '{project-root}/server/backend/api/routes/transcription.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `server/backend/api/routes/openai_audio.py:138` and `:238` read `model_manager.engine` — **no such attribute exists** on `ModelManager` (it has `transcription_engine` as a property, and `ensure_transcription_loaded()` as a method). Both `POST /v1/audio/transcriptions` and `POST /v1/audio/translations` will raise `AttributeError: 'ModelManager' object has no attribute 'engine'` on the first request, hit the bare `except Exception` at `:175`/`:275`, and return a generic `500 Internal server error` to the client. The OpenAI-compatible API is documented as a drop-in for OpenWebUI, LM Studio, and other clients — any external integration using these endpoints sees a broken server. Also, the preexisting `_assert_model_loaded` check only tests config presence, not actual load state — it doesn't cover the Issue #76 silent-detach scenario.

**Approach:** Mirror the canonical pattern established in `server/backend/api/routes/transcription.py:128-134`: before `try_start_job()`, call `await asyncio.to_thread(model_manager.ensure_transcription_loaded)` and catch `BackendDependencyError` to return a structured OpenAI-shaped 503 with the remedy surfaced. Use the returned engine directly instead of the nonexistent `model_manager.engine`. Apply symmetrically to both the transcription and translation handlers.

## Boundaries & Constraints

**Always:**
- Replace `engine = model_manager.engine` at `openai_audio.py:138` and `:238` with either the return value of `ensure_transcription_loaded()` or `model_manager.transcription_engine` (post-ensure).
- Ensure-call runs BEFORE `try_start_job()` so a failed reload doesn't occupy the single-slot job tracker.
- `BackendDependencyError` is caught and returned as `_openai_error(503, detail_message, error_type='server_error')` with `detail_message = f"Backend dependency missing: {dep_err}{remedy_suffix}"` — same shape as `transcription.py:130-134`.
- Run inside `await asyncio.to_thread(...)` so the event loop stays responsive (ensure_transcription_loaded is sync + blocking).
- Preserve the OpenAI-shaped error response envelope for the 503; do not switch to `HTTPException`.

**Ask First:**
- Extending the fix to cover other callers of `model_manager.engine` elsewhere in the codebase (grep-confirmed: only `openai_audio.py` has the bug). If any surface during implementation, pause and ask.

**Never:**
- Do not modify `ModelManager` to add a legacy `engine` property alias — would mask the typo and prevent callers from getting the self-heal benefit.
- Do not remove or change `_assert_model_loaded` — it's a valid config-presence pre-check; keep it AS-IS even though `ensure_transcription_loaded` is now the stronger load-state check.
- Do not touch the `_openai_error` helper shape — external clients depend on the envelope.
- Do not touch the dashboard — this is a pure backend bugfix; the dashboard doesn't call `/v1/audio/*`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Backend loaded, valid audio POST | 200 with transcribed text in requested format | N/A |
| Backend silently detached (Issue #76) | `_backend is None` post-live-mode | `ensure_transcription_loaded` self-heals; 200 with transcribed text | Recovered transparently |
| Missing NeMo for Parakeet | Parakeet configured, nemo-toolkit absent | 503 with OpenAI-shaped body: `{"error":{"message":"Backend dependency missing: ... . Install nemo-toolkit...", "type":"server_error", ...}}` | `BackendDependencyError` caught |
| Generic reload failure (CUDA OOM, corrupt weights) | Transient infra failure | 500 `Internal server error` (unchanged — existing bare-except path) | Existing `except Exception` |
| Cancelled mid-request | Client cancelled | 500 `Transcription was cancelled` (existing path, unchanged) | Existing `TranscriptionCancelledError` |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/openai_audio.py` — replace `engine = model_manager.engine` at lines 138 + 238 with `ensure_transcription_loaded()` call pattern; add `BackendDependencyError` import + catch before `try_start_job`.
- `server/backend/api/routes/transcription.py:128-134` — REFERENCE ONLY (canonical pattern to mirror).
- `server/backend/core/model_manager.py:714` — REFERENCE ONLY (`ensure_transcription_loaded` implementation).
- `server/backend/tests/test_openai_audio.py` — NEW; targeted tests for (a) AttributeError no longer raised, (b) BackendDependencyError → 503 with OpenAI envelope + remedy text, (c) ensure-call placement before try_start_job.

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/openai_audio.py` — add `import asyncio` + `from server.core.stt.backends.base import BackendDependencyError`. Insert `ensure_transcription_loaded` + `BackendDependencyError` catch block BEFORE `try_start_job` in BOTH `create_transcription` and `create_translation` (mirror of `transcription.py:128-134`, but returning `_openai_error(503, ..., error_type='server_error')` instead of `HTTPException`).
- [x] `server/backend/api/routes/openai_audio.py` — replace `engine = model_manager.engine` at both sites with `engine = model_manager.transcription_engine` (post-ensure the engine is attached and the property is safe).
- [x] `server/backend/tests/test_openai_audio.py` — NEW; using the direct-call route-handler test pattern per CLAUDE.md, cover: success path calls ensure_transcription_loaded; BackendDependencyError → 503 with OpenAI envelope and remedy text; ensure is awaited before try_start_job (job slot not occupied on failure).

**Acceptance Criteria:**
- Given a healthy server (backend loaded), when `POST /v1/audio/transcriptions` is called, then the response is 200 and no `AttributeError: 'ModelManager' object has no attribute 'engine'` is raised anywhere in the handler path.
- Given `ensure_transcription_loaded` raises `BackendDependencyError(reason, remedy)`, when `POST /v1/audio/transcriptions` (or `/translations`) is called, then the response is 503 with body shape `{"error":{"message":<str>,"type":"server_error",...}}` AND the message contains both the `str(dep_err)` and the `remedy` text.
- Given `ensure_transcription_loaded` raises `BackendDependencyError`, when the handler returns, then `job_tracker` has NOT acquired a slot (the ensure-call preceded `try_start_job`).
- Existing tests in `server/backend/tests/` continue to pass; no new pytest warnings.

## Spec Change Log

### Review iteration 1 (2026-04-14)

Adversarial review verdict: ship as-is. All findings LOW-severity test-rigor nits or explicitly per-spec decisions. No PATCH-class changes applied. No DEFER-class findings (the ones flagged were either GOOD observations or items already scoped out by the spec's `Never` list — e.g. "consolidate `_assert_model_loaded` with `ensure_transcription_loaded`" is deliberately out of scope per `Never:` clause on preserving `_assert_model_loaded`).

KEEP: symmetric pattern across both handlers; tight exception scope (try/except wraps only the `ensure_transcription_loaded` call, not `try_start_job` or `transcribe_file`); `asyncio.to_thread` offload to prevent event-loop blocking; call-order lock test that asserts `ensure` runs before `try_start_job`; structured-error message format `"Backend dependency missing: {err}{remedy}"` matching `transcription.py`'s canonical string.

## Design Notes

The spec for Issue #76 (`spec-gh-76-fix-stt-not-loaded.md`) landed the self-heal helper + the pattern in `transcription.py`, `notebook.py`, `websocket.py`, and `live.py`. `openai_audio.py` was flagged in the deferred ledger as the one caller that was missed because the dashboard doesn't exercise the OpenAI-compat routes, so CI never saw the bug.

Golden fix shape (≤10 lines per handler, from canonical transcription.py):

```python
model_manager = request.app.state.model_manager
try:
    await asyncio.to_thread(model_manager.ensure_transcription_loaded)
except BackendDependencyError as dep_err:
    remedy_suffix = f". {dep_err.remedy}" if dep_err.remedy else ""
    return _openai_error(
        503,
        f"Backend dependency missing: {dep_err}{remedy_suffix}",
        error_type="server_error",
    )
# Then proceed with try_start_job + transcribe using transcription_engine
```

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_openai_audio.py -v` — expected: new tests pass.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v` — expected: full backend suite unchanged (excluding the 2 pre-existing known failures).

## Suggested Review Order

**Design intent — the canonical pattern mirror**

- Import of `asyncio` + `BackendDependencyError` at the top of the module.
  [`openai_audio.py:11`](../../server/backend/api/routes/openai_audio.py#L11)

- Transcription handler: ensure-call BEFORE `try_start_job` + OpenAI-shaped 503 on `BackendDependencyError`.
  [`openai_audio.py:122`](../../server/backend/api/routes/openai_audio.py#L122)

- Translation handler: symmetric pattern.
  [`openai_audio.py:235`](../../server/backend/api/routes/openai_audio.py#L235)

- Engine-read replaced with `transcription_engine` property (post-ensure, guaranteed attached).
  [`openai_audio.py:153`](../../server/backend/api/routes/openai_audio.py#L153)

**Behavioral contracts — tests**

- Fixture drift: stub now exposes `ensure_transcription_loaded` + `transcription_engine` (no more phantom `engine`).
  [`test_openai_audio_routes.py:63`](../../server/backend/tests/test_openai_audio_routes.py#L63)

- Call-order lock: ensure runs BEFORE `try_start_job` so failed reload doesn't occupy the single slot.
  [`test_openai_audio_routes.py:609`](../../server/backend/tests/test_openai_audio_routes.py#L609)

- `BackendDependencyError` → 503 with OpenAI envelope + remedy in message.
  [`test_openai_audio_routes.py:531`](../../server/backend/tests/test_openai_audio_routes.py#L531)

- Symmetric coverage for translation.
  [`test_openai_audio_routes.py:574`](../../server/backend/tests/test_openai_audio_routes.py#L574)
