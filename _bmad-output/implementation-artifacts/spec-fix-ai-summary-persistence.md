---
title: 'Persist AI summary across app restarts'
type: 'bugfix'
created: '2026-04-15'
status: 'done'
baseline_commit: '984602ee1e9541252210198941b3622499c27047'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/docs/api-contracts-server.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** AI summaries generated in the notebook disappear after restarting the application. The streaming endpoint `POST /api/llm/summarize/{id}/stream` (and its blocking twin `POST /api/llm/summarize/{id}`) forward LLM output to the client but never write the result to the `recordings` table. Only summaries the user manually edits go through `update_recording_summary`, so a freshly generated summary lives exclusively in React state in `AudioNoteModal.tsx` and is lost on reload.

**Approach:** Persist the summary server-side at the moment generation completes. Accumulate streamed content inside `process_with_llm_stream`, expose an optional `on_complete(text, model)` hook, and have `summarize_recording_stream` + `summarize_recording` call `update_recording_summary(recording_id, text, model)` before the response finishes. Client code is unchanged.

## Boundaries & Constraints

**Always:**
- Persist the summary BEFORE the SSE stream yields its final `{'done': True}` event (delivery completes AFTER durability, per CLAUDE.md "persist first, deliver second").
- On a successful generation, store both `summary` text and `summary_model` string (captured from SSE `model` field or `LLMResponse.model`).
- Never overwrite an existing persisted summary with an empty string on generation error — skip the save when accumulated content is empty or when the stream yielded an `error` event.
- If `update_recording_summary` raises or returns `False`, log at ERROR level but do not break the stream; still emit the `done` event so the UI stays responsive. The client already has the text in hand.
- Keep the generic `POST /api/llm/process/stream` endpoint's behavior identical (no recording_id, no save). Persistence is only wired in the recording-scoped `summarize_*` handlers.

**Ask First:**
- None — scope is mechanical.

**Never:**
- Do not move persistence to the client. A tab close / reload / network blip mid-stream must not cause data loss.
- Do not change the SSE wire format (event shape, field names) — the Electron client and any external consumers rely on it.
- Do not touch migrations, the `recordings` schema, or the `update_recording_summary` DB helper signature.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Happy path — streaming | Existing recording, LLM up, stream completes with content | Content streamed to client; after `[DONE]`, `update_recording_summary(id, full_text, model)` called; `{'done': True}` yielded; row has `summary` + `summary_model`. | N/A |
| Happy path — blocking | Existing recording, LLM up, 200 response with content | `LLMResponse` returned; `update_recording_summary(id, response, model)` called before returning to the caller. | N/A |
| LLM returns error mid-stream | Stream yields `{'error': ...}` event or no content | Client receives error event; **no DB write**. Existing persisted summary (if any) is preserved. | Log WARNING with recording_id + sanitized error. |
| DB save fails after successful stream | `update_recording_summary` raises / returns `False` | Client still gets the full content and `{'done': True}`; DB unchanged. | Log ERROR with recording_id + exception; do not raise. |
| Empty LLM response | Stream ends with `total_content_length == 0` | No DB write. `{'done': True}` still yielded. | Log INFO "empty LLM response, skipping persistence". |
| Generic `/process/stream` (no recording) | `on_complete=None` | Behaves exactly as today — no persistence, no new logging. | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/llm.py` -- streaming + blocking summarize handlers and `process_with_llm_stream`; primary edit site.
- `server/backend/database/database.py:372` -- `update_recording_summary(recording_id, summary, summary_model)` — persistence entry point (unchanged).
- `dashboard/components/views/AudioNoteModal.tsx:681-735` -- client-side stream consumer; already re-reads `recording.summary` on modal open, so no client change required.
- `dashboard/src/api/client.ts:853-876` -- `summarizeRecording` / `summarizeRecordingStream`; wire format consumers.
- `server/backend/tests/test_p2_llm_routes.py` -- existing direct-call test harness to extend.
- `server/backend/tests/conftest.py` -- shared fixtures (test clients, mocks) used below.

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/llm.py` -- Extracted the SSE generator into `_build_llm_stream_response(request, *, on_complete=None)` so `process_with_llm_stream` stays a plain route handler (adding a Callable parameter would have confused FastAPI's request parser). Generator now accumulates `full_text_parts`, captures `captured_model` from the first chunk with a `model` field, tracks `saw_error`, and — on clean completion — awaits `on_complete(full_text, captured_model)` inside try/except, then yields `{'done': True}` exactly once AFTER persistence.
- [x] `server/backend/api/routes/llm.py` -- `summarize_recording_stream` now lazy-imports `update_recording_summary`, defines an `async def _persist(text, model)` closure, and calls `_build_llm_stream_response(..., on_complete=_persist)` instead of re-entering `process_with_llm_stream`.
- [x] `server/backend/api/routes/llm.py` -- `summarize_recording` (blocking) now calls `update_recording_summary(recording_id, llm_response.response, llm_response.model)` after `process_with_llm` returns, guarded by `if llm_response.response:` and a try/except that logs ERROR on failure.
- [x] `server/backend/tests/test_llm_summarize_persistence.py` -- New file with 5 direct-call tests: streaming happy path (verifies text + model + ordering of persist-before-done), streaming 500-error path (no save, no done event), streaming save-failure path (stream still completes), blocking happy path (verifies save), blocking empty-response path (no save). Uses a custom `_FakeStreamResponse` / `_FakeStreamingClient` pair that mimics `httpx.AsyncClient.stream()`'s async-context-manager contract; monkeypatches `server.database.database.update_recording_summary` with spies/raisers.

**Acceptance Criteria:**
- Given a recording with no prior summary, when the user clicks "Generate AI Summary" and the stream completes, then the `recordings` row for that id has non-null `summary` and `summary_model` columns before the client receives `{'done': True}`.
- Given the same recording, when the app is restarted and the notebook modal is reopened, then the saved summary is shown immediately via the `recording?.summary` branch at `AudioNoteModal.tsx:686` (no regeneration, no LLM call).
- Given the LLM server is unreachable and the stream yields an `error` event, when the client receives the response, then `update_recording_summary` is NOT called and any previously persisted summary remains intact.
- Given `update_recording_summary` raises a `sqlite3.OperationalError`, when the stream generator handles the `[DONE]` event, then an ERROR is logged, the generator still yields `{'done': True}`, and the HTTP response completes with 200.
- Given a request to the generic `POST /api/llm/process/stream` (no recording), when the stream completes, then no DB write occurs and no new log lines are emitted beyond today's output.

## Spec Change Log

- **2026-04-15 — review patch (no loopback):** Three parallel reviewers flagged two real data-loss edges in the first implementation: (1) client disconnect mid-stream threw `GeneratorExit` and skipped persistence even though the text was already accumulated; (2) an unexpected httpx error after N chunks set `saw_error=True` and discarded salvageable content. Amendments (not touching `<frozen-after-approval>`): wrapped `generate_stream()` in a `try/finally` with an idempotent `_persist_once()` helper so persistence runs in finally as a safety net whenever `full_text_parts` is non-empty; removed `saw_error=True` from the generic `except Exception` path so the finally salvage can run. Also switched `captured_model` from first-wins to last-wins per OpenAI-compatible spec (final chunk is canonical) — tolerates router/proxy aliases. Added two tests: empty-stream-then-done (regression guard against blanking out an existing persisted summary) and last-wins model capture. One concern deferred to `deferred-work.md`: concurrent generations for the same recording race in SQLite. KEEP: the `_build_llm_stream_response` extraction is the right seam for injecting `on_complete` without breaking FastAPI routing.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_p2_llm_routes.py -v` -- expected: all new tests pass, existing LLM route tests unchanged.
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: no regressions beyond the two known pre-existing failures (db migration version, swr_linear resample).
- `cd server/backend && ../../build/.venv/bin/ruff check api/routes/llm.py` -- expected: clean.

**Manual checks (if no CLI):**
- Start the server + dashboard, open a synced recording, click "Generate AI Summary", wait for stream to finish, restart the Electron app, reopen the same recording → summary appears without re-streaming. Confirm `recordings.summary_model` is set to the actual model id (not `"unknown"` when the provider returns one).
