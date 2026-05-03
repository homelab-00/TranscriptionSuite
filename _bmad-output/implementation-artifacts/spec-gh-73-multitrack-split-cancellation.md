---
title: 'GH-73 Deferred: Cancellation check between channels in split_channels'
type: 'bugfix'
created: '2026-04-12'
status: 'done'
baseline_commit: '7e960e6'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `split_channels()` in `server/backend/core/multitrack.py` runs `ffmpeg` synchronously once per channel (`subprocess.run(..., timeout=300)`). For a file with many active channels the loop can block cancellation for minutes — the user's cancel request is observed by the transcription engine on the NEXT call but cannot interrupt the split phase that precedes it. With the MAX_CHANNELS cap of 16 this is a worst case of 16 × 300 s = 80 minutes of unresponsive state.

**Approach:** Add an optional `cancellation_check: Callable[[], bool] | None` parameter to `split_channels`. Call it at the top of each loop iteration BEFORE starting the next ffmpeg subprocess. If cancelled, clean up any already-created temp files (reuse the existing failure-path cleanup block) and raise `TranscriptionCancelledError` — the same exception `engine.transcribe_file` uses — so the route handler's existing `except TranscriptionCancelledError` catches it and returns 499. Propagate the `cancellation_check` from `transcribe_multitrack` (already receives it from the route) into the `split_channels` call.

## Boundaries & Constraints

**Always:** Preserve current behavior when `cancellation_check` is None or returns False — no behavior change for existing callers. Keep the existing temp-file cleanup on failure; add the same cleanup on cancellation. Raise `TranscriptionCancelledError` (imported from `server.core.model_manager`) — the rest of the system already distinguishes this from generic exceptions.

**Ask First:** If the probe phase (`_measure_channel_volume` loop inside `probe_channels`) should also become cancellation-responsive. Out of scope here; the deferred-work note was explicit about the split phase only.

**Never:** Do not try to terminate the currently-running ffmpeg subprocess — that requires `Popen` + `terminate()` and can leave zombie processes. Checking between iterations is enough to bound the worst case to one channel's work. Do not change the `subprocess.run` timeout. Do not alter the function's return type or success-path behavior.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No cancellation (current behavior) | `cancellation_check=None` | All N channels extracted and returned | N/A |
| Not cancelled | `cancellation_check=lambda: False` | Same as above | N/A |
| Cancelled before first channel | `cancellation_check=lambda: True` | Raises `TranscriptionCancelledError` immediately; no temp files left on disk | Clean up any partial files |
| Cancelled after channel 1 of N | `cancellation_check` flips to True after first iteration | Raises `TranscriptionCancelledError`; channel-0 temp file is unlinked; remaining channels not extracted | Clean up all partial files |
| Cancellation check raises | `cancellation_check` raises unexpectedly | Propagate the exception; clean up partial files via the generic except handler | Existing cleanup path covers it |
| ffmpeg subprocess still in-flight when cancelled | User cancels mid-ffmpeg | Current ffmpeg finishes (up to 300 s); cancellation observed on next loop iteration | Acknowledged trade-off — see Never clause |

</frozen-after-approval>

## Code Map

- `server/backend/core/multitrack.py:158-205` -- `split_channels`: add `cancellation_check` param; check between iterations; unify cleanup between failure and cancellation paths
- `server/backend/core/multitrack.py:274-356` -- `transcribe_multitrack`: pass `cancellation_check` to `split_channels`
- `server/backend/core/model_manager.py` -- READ-ONLY: `TranscriptionCancelledError` import site
- `server/backend/tests/test_multitrack.py` -- ADD tests: early cancellation (no files written), mid-loop cancellation (partial files cleaned up), no-op when check is None or returns False

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/multitrack.py` -- Import `TranscriptionCancelledError` at top-level. Add `cancellation_check: Callable[[], bool] | None = None` parameter to `split_channels`. Inside the channel loop, at the top of each iteration, call `if cancellation_check is not None and cancellation_check():` and, if True, unlink any accumulated temp files (mirror the existing failure-path cleanup) before raising `TranscriptionCancelledError("Transcription cancelled during channel split")`.
- [x] `server/backend/core/multitrack.py` -- In `transcribe_multitrack`, pass `cancellation_check=cancellation_check` to the `split_channels(file_path, active)` call.
- [x] `server/backend/tests/test_multitrack.py` -- Add unit tests: (a) `cancellation_check=None` preserves current behavior; (b) `cancellation_check=lambda: False` preserves current behavior; (c) `cancellation_check=lambda: True` raises `TranscriptionCancelledError` with NO temp files remaining; (d) stateful `cancellation_check` that flips True after first iteration raises `TranscriptionCancelledError` and ensures the first temp file has been unlinked.

## Spec Change Log

- **Review iteration 1 (2026-04-12):** Blind hunter and edge-case hunter independently flagged two error-masking hazards. Applied patches (no intent or spec changes):
  - `_cleanup_partials` now wraps each `Path.unlink(missing_ok=True)` in `try/except OSError` with a warning log. `missing_ok=True` only swallows `FileNotFoundError`; permission errors or I/O errors on cleanup would otherwise escape and mask the real `TranscriptionCancelledError` (or `RuntimeError` on failure path) the caller needs to see.
  - The `cancellation_check()` call is now wrapped in `try/except Exception` that runs `_cleanup_partials()` before re-raising. A broken check (lock corruption, etc.) must not leak already-extracted channel temp files.
  - Added 2 tests: `test_cancellation_check_raising_still_cleans_up_partials` (broken check → partial files cleaned), `test_cleanup_unlink_failure_does_not_mask_original_error` (PermissionError during cleanup → `TranscriptionCancelledError` still reaches caller).
  - **Deferred** (not this spec's scope): `probe_channels` has an identical per-channel ffmpeg loop (`_measure_channel_volume`) with no cancellation check — worst case ~32 min (16 × 120 s) of unresponsive volumedetect before `split_channels` is even reached. Appended to `deferred-work.md`.

**Acceptance Criteria:**
- Given `split_channels` called with `cancellation_check=None`, when the function runs, then its behavior is byte-identical to the pre-change implementation.
- Given `cancellation_check` that returns True immediately, when `split_channels` is called, then `TranscriptionCancelledError` is raised before any ffmpeg invocation and no temp files are created.
- Given `cancellation_check` that returns False for the first iteration then True for the second, when `split_channels` is called with 3 channels, then channel-0 is extracted, the loop breaks on iteration 2, and the channel-0 temp file is unlinked before the raise — no partial output remains.
- Given `transcribe_multitrack` is invoked with a `cancellation_check`, when the split phase starts, then that same callable is observed at every iteration of the channel loop.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_multitrack.py -v --tb=short` -- expected: existing 28 tests plus 6 new cancellation tests all pass

## Suggested Review Order

**Cancellation-responsiveness**

- `cancellation_check` parameter added; called at the TOP of each iteration before any ffmpeg work.
  [`multitrack.py:190`](../../server/backend/core/multitrack.py#L190)

- `TranscriptionCancelledError` (not a new custom exception) is raised so the route's existing 499 handler fires unchanged.
  [`multitrack.py:199`](../../server/backend/core/multitrack.py#L199)

- `transcribe_multitrack` forwards its own cancellation callable into `split_channels`.
  [`multitrack.py:355`](../../server/backend/core/multitrack.py#L355)

**Error-masking hardening (review iteration 1)**

- `_cleanup_partials` wraps each unlink in try/except — permission / I/O errors during cleanup never mask the real `TranscriptionCancelledError` or `RuntimeError`.
  [`multitrack.py:179`](../../server/backend/core/multitrack.py#L179)

- `cancellation_check()` itself is wrapped — a broken check cleans up partial files before re-raising.
  [`multitrack.py:192`](../../server/backend/core/multitrack.py#L192)

- The shared cleanup closure also replaces the inlined loop in the existing ffmpeg-failure path.
  [`multitrack.py:233`](../../server/backend/core/multitrack.py#L233)

**Tests**

- 6 new tests in `TestSplitChannels`: two no-op baselines (None + returns-False), immediate-cancel, mid-loop-cancel, broken-check, and permission-error-during-cleanup.
  [`test_multitrack.py:226`](../../server/backend/tests/test_multitrack.py#L226)
