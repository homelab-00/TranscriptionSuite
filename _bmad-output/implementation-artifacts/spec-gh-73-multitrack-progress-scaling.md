---
title: 'GH-73 Deferred: Scale progress callback across multitrack tracks'
type: 'feature'
created: '2026-04-12'
status: 'done'
baseline_commit: '2abd0b4'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `transcribe_multitrack()` in `server/backend/core/multitrack.py` forwards the caller-provided `progress_callback` unmodified to `engine.transcribe_file()` for each of N channel tracks. Because each track is an independent transcription call, the callback reports `(0, track_total)` at the start of every track — progress visibly resets to 0% at the start of track 2, track 3, etc. The `/import` route relays this to `job_tracker.update_progress`, which clients poll. UX is janky: a 4-track file shows 0→100% four times instead of a monotonic 0→100%.

**Approach:** When a `progress_callback` is supplied and we know we're about to process `N` tracks, wrap it into a per-track adapter before calling `engine.transcribe_file`. The wrapper rescales `(current, total)` from the single-track domain into `(track_idx * total + current, N * total)` so the overall value walks monotonically from `0/N → 1/N → ... → N/N`. Semantics-agnostic: works whether backends emit samples, seconds, or chunk counts, because only the ratio matters. Pass a FRESH wrapper per track (capturing `track_idx`) — not a single shared wrapper.

## Boundaries & Constraints

**Always:** When `progress_callback is None` or we fall through to the mono/standard path, behavior is byte-identical to pre-change. The wrapper must be robust to `total <= 0` (don't divide by zero if a backend reports garbage — pass through unchanged). The wrapper never raises; a user callback that raises propagates to the caller exactly as today.

**Ask First:** If the /audio sync route should also wire `progress_callback=on_progress` so that sync uploads benefit from scaled progress. Currently only `/import` wires it — keeping the wiring identical to pre-change is the safest choice.

**Never:** Don't change the `progress_callback` signature or any backend's progress-emit semantics. Don't alter `_run_file_import` or the route layer. Don't try to normalize units across backends. Don't rescale inside `engine.transcribe_file` or further down.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 4 tracks, progress reported as samples | Backend emits `(half_samples, total_samples)` on track 2 | Outer callback receives `(1*total + half, 4*total)` i.e. ~37.5% overall | N/A |
| 4 tracks, progress reported as chunk counts | Backend emits `(3, 10)` on track 0 | Outer receives `(0*10 + 3, 4*10) = (3, 40)` i.e. 7.5% overall | N/A |
| Single active channel | multitrack=true, 1 active channel after filter | 1 track, wrapper scales `(c, t) → (c, 1*t)` i.e. no visible rescale | N/A |
| `progress_callback=None` | caller did not provide | No wrapping, no call — identical to pre-change | N/A |
| Mono file falls through | num_channels ≤ 1 | engine.transcribe_file called directly with raw callback — unchanged | N/A |
| Backend reports `total <= 0` | e.g. `(0, 0)` on first heartbeat | Wrapper passes through `(current, total)` unchanged | Avoid divide-by-zero in any derived math (there is none today) |
| User callback raises | `progress_callback` raises RuntimeError inside engine | Propagates via engine; no multitrack-level catch | Pre-existing behavior |

</frozen-after-approval>

## Code Map

- `server/backend/core/multitrack.py:274-365` -- `transcribe_multitrack`: wrap `progress_callback` per-iteration inside the transcribe loop
- `server/backend/api/routes/transcription.py:692-712` -- READ-ONLY: `/import` route's `on_progress` wiring; reference for integration testing
- `server/backend/tests/test_multitrack.py` -- ADD tests: scaling math, None passthrough, single-active-channel no-op, total≤0 passthrough

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/core/multitrack.py` -- Inside `transcribe_multitrack`'s `for track_idx, ch_file in enumerate(channel_files)` loop, compute a per-track callback wrapper when `progress_callback is not None`: `def _scaled(current: int, total: int) -> None: if total <= 0: progress_callback(current, total); return; progress_callback(track_idx * total + current, total_tracks * total)`. Pass `_scaled` (or `progress_callback` when None) to `engine.transcribe_file(..., progress_callback=...)`. Capture `track_idx` via default argument (`def _scaled(current, total, _i=track_idx): ...`) to avoid late-binding of the loop variable — standard Python closure gotcha.
- [x] `server/backend/tests/test_multitrack.py` -- Add tests: (a) with N=3 tracks each reporting `(0, 100)` then `(100, 100)`, captured outer calls are `(0, 300)`, `(100, 300)`, `(100, 300)`, `(200, 300)`, `(200, 300)`, `(300, 300)` in order; (b) `progress_callback=None` means the inner `engine.transcribe_file` is called with `progress_callback=None` for every track; (c) single active channel after filter — the wrapper still scales correctly as 1-of-1; (d) backend reporting `total=0` passes `(current, 0)` through unchanged (no divide); (e) late-binding regression — three concurrent captured callbacks each report their own `track_idx` when all are called after the loop completes.

## Spec Change Log

- **Review iteration 1 (2026-04-12):** All 3 reviewers (blind, edge-case, acceptance auditor) — no patches required. All 4 ACs, all execution items, and all boundary constraints verified PASS. Reviewer concerns (non-uniform per-track totals, `(0,0)` passthrough semantics, user-callback exceptions, engine returning None) were classified as either pre-existing behavior outside this spec's scope or theoretical concerns not exhibited by current backends (`mlx_canary_backend` emits `(sample_index, total_samples)`; `vibevoice_asr_backend` emits `(chunk_index, num_chunks)` — both stable totals within a track).

**Acceptance Criteria:**
- Given 4 tracks and a backend that emits `(current, total)` in any units, when each track progresses from 0 to total, then the outer `progress_callback` observes a strictly monotone non-decreasing sequence of `current_overall` values that reach `N * total` exactly at the end of the last track.
- Given `progress_callback=None`, when `transcribe_multitrack` runs, then every call to `engine.transcribe_file` passes `progress_callback=None` (no adapter constructed).
- Given a mono file (num_channels ≤ 1), when `transcribe_multitrack` falls through to standard transcription, then the original callback is forwarded unchanged — no scaling applied.
- Given a backend call with `total=0`, when the wrapper fires, then the outer callback receives `(current, 0)` unchanged — no ZeroDivisionError, no scaling.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_multitrack.py -v --tb=short` -- expected: existing 33 tests plus 5 new scaling tests all pass

## Suggested Review Order

**Scaling math**

- Per-iteration wrapper built inside the track loop; `None` callback short-circuits with no wrapper.
  [`multitrack.py:372`](../../server/backend/core/multitrack.py#L372)

- The rescale formula: `(track_idx * total + current, N * total)` — semantics-agnostic; `total <= 0` passes through unscaled.
  [`multitrack.py:378`](../../server/backend/core/multitrack.py#L378)

- Wrapper handed to `engine.transcribe_file` via `progress_callback=track_progress_cb` (was raw `progress_callback` before).
  [`multitrack.py:399`](../../server/backend/core/multitrack.py#L399)

**Closure correctness**

- `_i=track_idx`, `_n=total_tracks`, `_cb=user_cb` defaults freeze the values at def-time — avoids the classic late-binding bug where all three wrappers would capture the final `track_idx`.
  [`multitrack.py:381`](../../server/backend/core/multitrack.py#L381)

**Tests**

- Full observed sequence for N=3: asserts exact `[(0,300),(100,300),(100,300),(200,300),(200,300),(300,300)]`.
  [`test_multitrack.py:601`](../../server/backend/tests/test_multitrack.py#L601)

- `None` passthrough: every per-track call gets `progress_callback=None`, not a wrapper.
  [`test_multitrack.py:644`](../../server/backend/tests/test_multitrack.py#L644)

- Late-binding regression: captured wrappers called AFTER the loop each report their own `track_idx`.
  [`test_multitrack.py:725`](../../server/backend/tests/test_multitrack.py#L725)
