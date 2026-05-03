---
title: 'Deferred: Narrow except in integrated diarization fallback blocks'
type: 'bugfix'
created: '2026-04-12'
status: 'done'
baseline_commit: 'ea33c9c'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** In `server/backend/api/routes/transcription.py`, both the `/audio` sync route (around line 336) and the `/import` async route (around line 818) wrap their integrated-backend diarization attempt (WhisperX single-pass) in a bare `except Exception:` that logs a warning and falls through to standard transcription. This mask is too broad: `TranscriptionCancelledError` and (for the `/audio` route) `ValueError` get silently converted to "diarization failed — falling back to standard transcription" instead of propagating to the existing outer handlers, which would translate them into HTTP 499 / HTTP 400 responses (or job-tracker cancellation for `/import`). The practical consequence: when a user cancels mid-WhisperX-diarization, the route silently retries the whole file via the standard (non-diarized) path — wasting GPU time and producing the wrong transcript shape. When input validation fails inside `backend.transcribe_with_diarization`, the `/audio` route silently downgrades to a non-diarized transcript instead of returning a clean 400.

**Approach:** Add specific `except TranscriptionCancelledError: raise` handlers BEFORE the existing fallback `except` clauses in both routes. For `/audio`, additionally add `except ValueError: raise` — the outer route handler already knows how to turn that into a 400. For `/import`, keep the existing `except ValueError` clause (it specifically maps HuggingFace-token errors into `diarization_outcome["reason"] = "token_missing"` and falls through — that's correct and intentional). The ordering is: cancellation first (always re-raise), then ValueError (route-specific), then general `except Exception` (log + fall through, as today).

## Boundaries & Constraints

**Always:** Preserve the existing "fall through to standard transcription" behavior for all OTHER exceptions — e.g. missing optional dependency, model-loading hiccup, CUDA OOM on the WhisperX code path. Those remain caught and logged, and the route continues with the standard transcription path. The fix is purely narrower cancellation/validation handling, not broader diarization-fallback removal.

**Ask First:** If the `/import` route should ALSO let `ValueError` propagate (matching `/audio`). Today it uses `ValueError` as the signal for "HF token missing → mark outcome token_missing, retry without diarization". Changing that would alter response semantics users depend on — not in this spec's scope.

**Never:** Do not add a catch for `ValueError` in `/import` — preserve its current HF-token handling. Do not change the outer exception handlers (`/audio` has TranscriptionCancelledError → 499, ValueError → 400, Exception → 500; `/import` propagates TranscriptionCancelledError to `_run_file_import`'s caller). Do not delete the fallback `except Exception` — other failures should still degrade gracefully.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| /audio: cancel mid-integrated-diarization | WhisperX transcribe raises TranscriptionCancelledError | Error propagates to outer handler → HTTP 499 (and `mark_failed` per prior durability fix) | Not silently converted to "fallback to standard" |
| /audio: bad input in integrated path | Diarization raises ValueError | Error propagates to outer handler → HTTP 400 + `mark_failed` | No silent downgrade |
| /audio: model-loading failure in integrated path | Diarization raises RuntimeError / ImportError / CUDA OOM | Existing fallback kicks in — warning logged, `diarization = False`, standard path runs | Unchanged |
| /import: cancel mid-integrated-diarization | WhisperX transcribe raises TranscriptionCancelledError | Error propagates to `_run_file_import` outer handler → job marked cancelled | Not silently retried via standard path |
| /import: HuggingFace token missing | Diarization raises ValueError | Existing handler sets `reason="token_missing"`, falls through to standard path | Unchanged — that's the designed signal |
| /import: model-loading failure | Diarization raises RuntimeError / ImportError / CUDA OOM | Existing fallback kicks in — error logged, `reason="unavailable"`, standard path runs | Unchanged |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/transcription.py:277-341` -- `/audio` integrated diarization branch; add TranscriptionCancelledError + ValueError re-raises before the bare except
- `server/backend/api/routes/transcription.py:761-824` -- `/import` integrated diarization branch; add TranscriptionCancelledError re-raise before the existing except-ladder
- `server/backend/api/routes/transcription.py:25` -- READ-ONLY: `TranscriptionCancelledError` already imported at module top
- `server/backend/tests/test_audio_route_durability.py` -- ADD tests: /audio cancellation in integrated path propagates; /audio ValueError in integrated path propagates; /audio other exception still falls through

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/api/routes/transcription.py` -- In the `/audio` route's integrated-diarization `try:` block (around line 277-336), insert two new except clauses BEFORE the existing `except Exception:` at line 336: `except TranscriptionCancelledError: raise` and `except ValueError: raise`. Keep the existing `except Exception:` body (warning log + `diarization = False` fallthrough) unchanged.
- [x] `server/backend/api/routes/transcription.py` -- In the `/import` route's integrated-diarization `try:` block (around line 761-824), insert ONE new except clause BEFORE the existing `except ValueError as e:` at line 812: `except TranscriptionCancelledError: raise`. The existing ValueError handler (HF-token fall-through) and general Exception handler (reason="unavailable" fall-through) remain unchanged.
- [x] `server/backend/tests/test_audio_route_durability.py` -- Add 4 tests in a new `TestIntegratedDiarizationFallback` class: (a) TranscriptionCancelledError in `backend.transcribe_with_diarization` propagates to HTTP 499 with `mark_failed("Transcription cancelled by user")`; (b) ValueError in `backend.transcribe_with_diarization` propagates to HTTP 400 with `mark_failed(str(e))`; (c) a generic RuntimeError in `backend.transcribe_with_diarization` still triggers the fallback to standard path — i.e. `engine.transcribe_file` is called afterwards and the client receives a 200 result (verifies the general fallback still works); (d) symmetric coverage for /import — cancellation propagates to `_run_file_import`'s outer handler, end_job is called with the cancel message, and `engine.transcribe_file` is NEVER invoked (no silent fallthrough to standard path).

## Spec Change Log

- **Review iteration 1 (2026-04-12):** Consolidated review confirmed all ACs PASS and no bugs. One LOW/defer finding: AC4 (/import cancellation) was listed in the acceptance criteria but had no automated test — the reviewer called it out as a coverage gap. Patched by adding `test_import_route_cancellation_propagates_to_outer_handler` that exercises `_run_file_import` end-to-end with a cancelling integrated backend and asserts: (1) `end_job` is called with the cancel message, (2) `engine.transcribe_file` is NEVER invoked (which would signal a silent fallthrough to standard path). Test task count updated from 3 → 4.

**Acceptance Criteria:**
- Given the `/audio` route and a WhisperX-style backend whose `transcribe_with_diarization` raises `TranscriptionCancelledError`, when `transcribe_audio` runs, then the outer `except TranscriptionCancelledError` handler fires, `mark_failed` is called with "Transcription cancelled by user", and a 499 HTTPException is raised — no call to the standard `engine.transcribe_file` occurs.
- Given the `/audio` route and a WhisperX backend whose `transcribe_with_diarization` raises `ValueError("bad audio")`, when `transcribe_audio` runs, then the outer `except ValueError` handler fires, `mark_failed` is called with `"bad audio"`, and a 400 HTTPException is raised — no fallback to standard transcription.
- Given the `/audio` route and a WhisperX backend whose `transcribe_with_diarization` raises `RuntimeError("CUDA OOM")`, when `transcribe_audio` runs, then the fallback kicks in (warning logged), `engine.transcribe_file` is called, and the route returns the standard transcript.
- Given the `/import` route and a WhisperX backend whose `transcribe_with_diarization` raises `TranscriptionCancelledError`, when `_run_file_import` runs, then the error propagates out of the integrated block (verified by catching `TranscriptionCancelledError` at the call site in test).

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_audio_route_durability.py -v --tb=short` -- expected: existing 12 tests pass plus 4 new fallback tests

## Suggested Review Order

**/audio route (the route the deferred note was about)**

- Two new re-raise clauses before the bare Exception catch — cancellation first, validation second, fallthrough third.
  [`transcription.py:336`](../../server/backend/api/routes/transcription.py#L336)

**/import route (symmetric fix)**

- One new re-raise — cancellation propagates to `_run_file_import`'s outer handler; the intentional HF-token ValueError fallthrough is preserved.
  [`transcription.py:822`](../../server/backend/api/routes/transcription.py#L822)

**Tests**

- Four tests — 3 /audio (cancel→499, value→400, runtime→fallthrough) + 1 /import end-to-end (cancel→end_job with cancel message, transcribe_file never invoked).
  [`test_audio_route_durability.py:556`](../../server/backend/tests/test_audio_route_durability.py#L556)
