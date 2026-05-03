---
title: 'Resolve 9 open CodeQL alerts (security + cleanup)'
type: 'bugfix'
created: '2026-04-18'
status: 'done'
baseline_commit: '09899d6076245ee995a14ef85f17dafc434ff97c'
context:
  - '{project-root}/server/backend/logging/setup.py'
  - '{project-root}/server/backend/api/routes/utils.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** GitHub's CodeQL scan reports 9 open alerts on `main` (3 errors, 1 warning, 5 notes) covering log injection, stack-trace exposure in HTTP responses, a TOCTOU file-system race in Electron, redundant imports, and one `BaseException` catch in a test. Nothing is actively exploitable today (FastAPI coerces `recording_id` to `int`; the Electron config path is user-local), but leaving the warnings open hides future regressions in the same places and inflates the alerts queue.

**Approach:** Fix all 8 code-level alerts in one hardening pass, and dismiss the remaining one (`py/catch-base-exception` in a race-condition test) via GitHub UI with a "used in tests" reason. Reuse the existing sanitization helpers (`sanitize_for_log`, `sanitize_log_value`) rather than inventing new patterns, and make the Electron file write atomic (`wx` flag) so the TOCTOU window disappears.

## Boundaries & Constraints

**Always:**
- Use existing helpers: `sanitize_for_log` (in `server.api.routes.utils`) for log format-string arguments; `sanitize_log_value` is available but the `%s`-with-`sanitize_for_log` pattern already used in `llm.py` is the project idiom — match it.
- Prefer lazy logging (`logger.warning("... %s", sanitize_for_log(...))`) over f-strings when the value is user-influenced; CodeQL's log-injection rule is satisfied by lazy formatting of a sanitized value.
- For HTTP error bodies: never echo raw exception `__str__` to the client. Log the detail server-side; return a generic message (keep the existing fallback phrases like "Backend dependency unavailable").
- For the Electron atomic write: the fallback stub write must fail cleanly (log + continue) if the file was created by another process between check and write — the caller already tolerates a pre-existing config.

**Ask First:**
- If fixing a log-injection line forces a message rewording that changes what operators search for in logs — keep the recognizable phrase ("update_recording_summary returned False ...") and only change the formatting mechanism.
- If CodeQL re-scan after the fix still reports any of these alerts (not counting #550 which will be dismissed) — HALT and show which one persists before iterating further.

**Never:**
- Do not introduce a new "sanitizer" utility — the two existing ones cover every case here.
- Do not change any public API shape (response schemas, status codes, error `type` strings) — alerts must be resolved without behaviour change visible to clients.
- Do not suppress alerts via `# nosec` / `// codeql[...]` comments; fix the code. The one exception is #550 (test worker), dismissed via GitHub UI.
- Do not touch `transcription.py` beyond removing the three redundant `import json as _json` lines — the module already imports `json as _json` at line 13.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Summary persist fails, `recording_id=42` | `update_recording_summary` returns `False` | `logger.warning` emits line with sanitized id; response still returns generated summary | N/A — persistence is best-effort |
| OpenAI transcribe: backend dep missing | `BackendDependencyError` with remedy | Client gets 503 `"Backend dependency unavailable"`; server log has full `dep_err` + remedy | Generic client message; operator detail in logs |
| Electron first-start: config file absent | `userConfigPath` does not exist | Template copy succeeds OR stub written via atomic `wx` | If `wx` EEXIST (raced): log + treat as success (file now exists) |
| Electron first-start: config file appears mid-call | Another proc writes file between check and write | Atomic write fails with EEXIST; caller logs "config already present" | No crash; server still starts using the existing file |
| `get_transcription_result` json decode | Stored `result_json` is valid | Parsed via module-level `_json` (no re-import) | `JSONDecodeError` path unchanged |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/llm.py` — lines 718–720, 722–725, 760: three `logger.warning`/`logger.error` f-strings interpolating `recording_id`. Module already imports `sanitize_for_log` from `server.api.routes.utils` (line 22).
- `server/backend/api/routes/openai_audio.py` — lines 126–130 and 236–240: `_openai_error(503, detail_message, ...)` where `detail_message` embeds the exception. `_openai_error` helper at line 42 builds the JSONResponse; stack-trace sink reported at line 52 (`status_code=status_code,` inside the helper).
- `server/backend/api/routes/transcription.py` — lines 1150, 1253, 1522: `import json as _json` inside function bodies; module-level `import json as _json` already exists at line 13. Removing the local imports makes `_json` resolve to the module-level alias, which is identical.
- `dashboard/electron/mlxServerManager.ts` — lines 132–148: `existsSync` → `copyFileSync`/`writeFileSync` TOCTOU. The caller already accepts "file already present" as a success state (line 132 short-circuits).
- `server/backend/tests/test_ensure_transcription_loaded.py` — line 240: `except BaseException as err` in a worker thread inside a race-condition test. Intentional pattern; will be dismissed on GitHub rather than changed.
- `server/backend/api/routes/utils.py` — `sanitize_for_log` at line 335 (existing helper — reuse, don't duplicate).
- `server/backend/logging/setup.py` — `sanitize_log_value` at line 143 (alternative helper; not needed here).

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/llm.py` — rewrite the three logger calls at lines 718–720, 722–725, 760 to use lazy `%s` formatting with `sanitize_for_log(str(recording_id))`. Preserve the existing log phrasing ("update_recording_summary returned False for recording %s", "Failed to persist summary for recording %s: %s") so operator grep patterns keep working. Do not change `exc_info=True` on the error log.
- [x] `server/backend/api/routes/openai_audio.py` — in both handlers (lines 126–130 and 236–240), split the current behavior: log the full `detail_message` server-side via `logger.warning` (already present) and return `_openai_error(503, "Backend dependency unavailable", error_type="server_error")` with the raw exception kept out of the response body. Remove the `detail_message` variable if it becomes log-only and is clearer inline.
- [x] `server/backend/api/routes/transcription.py` — delete the three local `import json as _json` statements (lines 1150, 1253, 1522). Verify all `_json.` references in the enclosing functions still resolve via the module-level import.
- [x] `dashboard/electron/mlxServerManager.ts` — collapse the `existsSync` check and both write paths into an atomic pattern. Attempt `copyFileSync(templatePath, userConfigPath, fs.constants.COPYFILE_EXCL)`; on `EEXIST` treat as success. On any other error (e.g. template missing), fall back to `writeFileSync(userConfigPath, stub, { flag: 'wx' })`; on `EEXIST` there, also treat as success. Keep the existing log messages for each branch.
- [x] `server/backend/tests/test_openai_audio_routes.py` — update the two `BackendDependencyError` tests to assert the new contract: generic `"Backend dependency unavailable"` in the response body; full error + remedy text captured via `caplog` from the server log. (Added as part of Execution because the tests were asserting the old exposed-exception behavior.)
- [ ] Dismiss CodeQL alert #550 (`py/catch-base-exception`) via GitHub UI with reason **"Used in tests"** and a comment linking to the race-test rationale. No code change. _Deferred to post-review (remote op)._
- [x] Self-verify: backend tests — 2 new-contract tests pass; remaining 29 failures + 13 errors are all pre-existing MLX/model_manager_init environment issues unrelated to this change (same set before edits). Dashboard typecheck clean.

**Acceptance Criteria:**
- Given a push to `main` with these changes, when CodeQL re-runs, then alerts #495, #547, #548, #549, #551, #552, #553, #554 transition to `fixed` and alert #550 shows `dismissed` with reason "used in tests".
- Given the `summarize_recording` endpoint is called with a valid `recording_id` and persistence fails, when the handler runs, then the logger emits a line containing the sanitized recording id and the response body still contains the generated summary text.
- Given an `OPTIONS`/`POST` to `/v1/audio/transcriptions` when the STT backend dependency is missing, when the handler raises `BackendDependencyError`, then the client receives a 503 with message `"Backend dependency unavailable"` and no exception string in the body, while the server log contains the full `dep_err` + remedy.
- Given the Electron app starts with no pre-existing `userData/config.yaml`, when another process writes that file between check and write, then no unhandled exception is raised, the server still starts, and a log line is emitted for whichever branch "won".
- Given `git grep "import json as _json" server/backend/api/routes/transcription.py`, when run after the change, then exactly one match remains (line 13).

## Spec Change Log

## Design Notes

**Why generic 503 body, not structured error:** The OpenAI API compatibility layer already returns OpenAI-shaped errors (`{error: {message, type, param, code}}`). The CodeQL finding is specifically about the `message` field being sourced from an exception's stringification. The fix is to stop sourcing it from the exception — not to rewrite the response shape. Operators debugging a failed backend look at server logs anyway; clients only need enough info to know it's a server-side issue (503 + "unavailable").

**Why lazy `%s` over sanitize + f-string:** Both satisfy CodeQL; the project already uses `logger.info("... %s", sanitize_for_log(x))` in `llm.py` (lines 876, 1011, etc.). Matching that pattern keeps the file consistent and silences the analyzer deterministically.

**Why `COPYFILE_EXCL` + `wx` flag:** Both Node APIs translate to `O_EXCL` at the syscall level, so the existence check and the write collapse into a single atomic operation. CodeQL's TOCTOU rule accepts this pattern. Treating `EEXIST` as success is safe here because the caller's intent is "there is a config file at this path" — who wrote it doesn't matter.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` — expected: all previously-passing tests still pass; no new failures.
- `cd server/backend && ../../build/.venv/bin/ruff check api/routes/llm.py api/routes/openai_audio.py api/routes/transcription.py` — expected: clean or no new warnings vs baseline.
- `cd dashboard && npm run typecheck` (or `tsc --noEmit`) — expected: clean.
- `cd dashboard && node --check electron/mlxServerManager.ts` is not applicable (TS); rely on typecheck.
- After push: `gh api "repos/homelab-00/TranscriptionSuite/code-scanning/alerts?state=open&per_page=20" --jq '.[] | .number'` — expected: only alerts unrelated to this spec, or empty.

**Manual checks:**
- Start the dashboard against an environment where the backend dependency is missing, trigger `/v1/audio/transcriptions`, confirm client receives generic 503 and server log contains the full `dep_err` message.
- Delete `~/.config/TranscriptionSuite/config.yaml` (or equivalent `userData` path), start the Electron app, confirm the server starts and a single "Copied config" or "wrote minimal config stub" log line appears.

## Suggested Review Order

**Response-body hardening (py/stack-trace-exposure #495)**

- Design intent: client gets a generic 503; full error + remedy stays in server log.
  [`openai_audio.py:126`](../../server/backend/api/routes/openai_audio.py#L126)

- Symmetric fix for the translation handler.
  [`openai_audio.py:238`](../../server/backend/api/routes/openai_audio.py#L238)

**Log-injection hardening (py/log-injection #551–#553)**

- Main fix pattern: lazy `%s` with `sanitize_for_log(str(recording_id))`, phrasing preserved.
  [`llm.py:718`](../../server/backend/api/routes/llm.py#L718)

- Same pattern for the error branch — `exc_info=True` retained.
  [`llm.py:723`](../../server/backend/api/routes/llm.py#L723)

- Streaming persist callback, same shape.
  [`llm.py:762`](../../server/backend/api/routes/llm.py#L762)

**Electron TOCTOU fix (js/file-system-race #554)**

- Atomic `copyFileSync(..., COPYFILE_EXCL)`; EEXIST treated as success.
  [`mlxServerManager.ts:138`](../../dashboard/electron/mlxServerManager.ts#L138)

- Nested stub write with `flag: 'wx'` covers the template-missing path.
  [`mlxServerManager.ts:155`](../../dashboard/electron/mlxServerManager.ts#L155)

**Dead-code cleanup (py/repeated-import #547–#549)**

- Three inline `import json as _json` removed; module-level alias at line 13 remains.
  [`transcription.py:13`](../../server/backend/api/routes/transcription.py#L13)

**Tests**

- Contract now asserts generic body + `caplog` for remedy.
  [`test_openai_audio_routes.py:560`](../../server/backend/tests/test_openai_audio_routes.py#L560)

- Symmetric translation-handler test.
  [`test_openai_audio_routes.py:609`](../../server/backend/tests/test_openai_audio_routes.py#L609)

**Not in diff — requires GitHub UI action**

- Dismiss alert #550 (`py/catch-base-exception`) with reason **"Used in tests"**; the test at `test_ensure_transcription_loaded.py:240` deliberately captures `BaseException` from worker threads for the race assertion.
