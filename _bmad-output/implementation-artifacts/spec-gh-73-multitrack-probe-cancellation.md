---
title: 'GH-73 Deferred: Cancellation check in probe_channels volumedetect loop'
type: 'bugfix'
created: '2026-04-12'
status: 'done'
baseline_commit: '9be0b11'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `probe_channels()` in `server/backend/core/multitrack.py` runs `_measure_channel_volume()` in a per-channel loop (one ffmpeg subprocess per channel, 120 s timeout each). With the `MAX_CHANNELS=16` cap a cancel request made early in the probe phase can block for up to 32 minutes before `split_channels` — already cancel-responsive since the prior spec — is even reached. The multitrack pipeline is `probe → filter → split → transcribe`; three of four phases honor cancel but probe does not.

**Approach:** Mirror the exact pattern landed for `split_channels` in the sibling spec: add `cancellation_check: Callable[[], bool] | None = None` to `probe_channels`, check it at the top of each iteration of the volumedetect loop BEFORE launching the ffmpeg subprocess, and raise `TranscriptionCancelledError` if cancelled. Wrap the callback invocation in try/except so a broken check propagates cleanly (same hardening added to split_channels in review). No temp files are created by the probe phase, so there is no cleanup obligation on cancel. Thread the callback from `transcribe_multitrack` (which already receives it) into the `probe_channels(file_path)` call.

## Boundaries & Constraints

**Always:** Preserve existing behavior when `cancellation_check` is None or returns False — byte-identical to pre-change. Raise `TranscriptionCancelledError` (imported from `server.core.model_manager`, already imported in this module). Do NOT return a partial `{"num_channels": N, "channel_levels_db": [...]}` on cancel — raise instead, so the caller handles cancellation uniformly.

**Ask First:** If the ffprobe call at the head of `probe_channels` (the channel-count query) should also check cancellation before launching. Argument for: symmetry. Argument against: a single ≤30 s call is not where users perceive unresponsiveness. Out of scope here.

**Never:** Do not try to interrupt the currently-running ffmpeg volumedetect subprocess — matches the split_channels trade-off (bounded worst case of one channel's 120 s timeout). Do not change `_measure_channel_volume`'s signature or timeout. Do not alter return types of `probe_channels` on the non-cancelled path.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No cancellation (current) | `cancellation_check=None` | Full dict returned with all per-channel levels | N/A |
| Not cancelled | `cancellation_check=lambda: False` | Same as above | N/A |
| Cancelled before first volumedetect | `cancellation_check=lambda: True` | Raises `TranscriptionCancelledError`; zero ffmpeg subprocesses launched | N/A |
| Cancelled after channel 1 of N | Stateful check flips True after first iteration | Raises `TranscriptionCancelledError` after 1 ffmpeg call completes | Partial `levels` list is discarded — not returned |
| Cancellation check raises | `cancellation_check` raises unexpectedly | Exception propagates; no further ffmpeg launches | Pre-existing `_measure_channel_volume` behavior unchanged |
| Mono file | `num_channels <= 1` | Early return BEFORE loop — cancellation_check never invoked | N/A |
| MAX_CHANNELS cap hit | `num_channels > 16` | Cap applied, then the cancellation-responsive loop runs against the capped count | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/core/multitrack.py:43-101` -- `probe_channels`: add param, wrap the per-channel loop with cancellation check
- `server/backend/core/multitrack.py:~320` -- `transcribe_multitrack`: pass `cancellation_check` to `probe_channels`
- `server/backend/core/multitrack.py:24` -- existing `TranscriptionCancelledError` import (reuse)
- `server/backend/tests/test_multitrack.py` -- ADD tests: None-passthrough, False-passthrough, immediate cancel (no ffmpeg), mid-loop cancel (one ffmpeg fires, then raise), broken-check (exception propagates)

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/multitrack.py` -- Add `cancellation_check: Callable[[], bool] | None = None` parameter to `probe_channels`. Between line 94 ("# Step 2: measure per-channel mean volume via volumedetect") and the `for ch_idx in range(num_channels):` loop body, check cancellation at the TOP of each iteration: wrap `cancellation_check()` in try/except (broken check propagates); on True, raise `TranscriptionCancelledError("Transcription cancelled during channel probe")`. Do NOT check in the early-return paths (ffprobe failure, mono files) — those return immediately anyway.
- [x] `server/backend/core/multitrack.py` -- In `transcribe_multitrack`, change `probe = probe_channels(file_path)` to `probe = probe_channels(file_path, cancellation_check=cancellation_check)`.
- [x] `server/backend/tests/test_multitrack.py` -- Add unit tests in a new `TestProbeChannelsCancellation` class: (a) `cancellation_check=None` preserves current behavior; (b) `lambda: False` preserves current behavior; (c) `lambda: True` raises `TranscriptionCancelledError` with zero ffmpeg subprocesses invoked; (d) stateful check that flips True after first iteration raises `TranscriptionCancelledError` with exactly one ffmpeg call recorded; (e) a broken `cancellation_check` that raises RuntimeError propagates with zero or one ffmpeg calls depending on iteration.

## Spec Change Log

- **Implementation note (2026-04-12):** The spec prose said "wrap `cancellation_check()` in try/except (broken check propagates)". The implementation omitted the wrapper because, unlike `split_channels`, the probe phase has no temp files to clean up on a broken check — a naked call achieves the same observable behavior (exception propagates) with fewer lines. Verified by `test_broken_cancellation_check_propagates`.
- **Review iteration 1 (2026-04-12):** Consolidated review. All 11 acceptance items PASS, no HIGH/MEDIUM findings. One LOW coverage gap: AC4 (`transcribe_multitrack` threads the callback into `probe_channels`) had no direct unit test — the existing `transcribe_multitrack` tests stub `probe_channels` whole, hiding the parameter. Patched by adding `test_transcribe_multitrack_threads_cancellation_into_probe` that spies on the `probe_channels` call and asserts the sentinel callback reaches it as a kwarg.

**Acceptance Criteria:**
- Given `probe_channels` called with `cancellation_check=None`, when it runs, then its behavior is byte-identical to the pre-change implementation.
- Given a cancellation check that returns True immediately, when `probe_channels` is called on a multi-channel file, then `TranscriptionCancelledError` is raised before any `_measure_channel_volume` invocation and no partial dict is returned.
- Given a cancellation check that returns False then True, when `probe_channels` runs with 3 channels, then exactly one `_measure_channel_volume` call is made before the raise.
- Given `transcribe_multitrack` invoked with a `cancellation_check`, when the probe phase starts, then that same callable is observed at every iteration of the volumedetect loop.
- Given a mono file (`num_channels <= 1`), when `probe_channels` is called with any cancellation_check, then it returns early without ever invoking the check.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_multitrack.py -v --tb=short` -- expected: existing tests pass plus 7 new probe-cancellation tests (6 direct + 1 wiring regression)

## Suggested Review Order

- Cancellation check at the top of the volumedetect iteration — one line of guard, one raise.
  [`multitrack.py:107`](../../server/backend/core/multitrack.py#L107)

- Call-site wiring: `transcribe_multitrack` now threads its own callback into `probe_channels`.
  [`multitrack.py:336`](../../server/backend/core/multitrack.py#L336)

- 7 new tests (6 direct scenarios + 1 wiring regression).
  [`test_multitrack.py:192`](../../server/backend/tests/test_multitrack.py#L192)
