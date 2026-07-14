# Remove the whisper.cpp inference time limit

**Date:** 2026-07-13
**Status:** Approved, ready for implementation planning
**Area:** `server/backend/core/stt/backends/whispercpp_backend.py`, cancellation wiring, partial-result surfacing

## Problem

`WhisperCppBackend` caps each `/inference` request at a read timeout of
`max(inference_timeout_s, ceil(chunk_seconds * timeout_seconds_per_audio_second))`
(`whispercpp_backend.py:124-140`). With the shipped defaults (600s chunks, 300s floor, 2.0x
factor) this permits roughly 2x real-time inference. A low-end machine that is slower than
that is failed, even though it is healthy and would have finished given time.

This is not merely an inconvenience. It silently truncates transcripts:

1. A chunk exceeds the budget, and httpx raises a read timeout (`whispercpp_backend.py:803`).
2. If at least one earlier chunk succeeded, the backend raises `PartialTranscriptionError`
   carrying the completed chunks (`:712`).
3. `engine.py:947` catches it, sets `partial=True` / `partial_reason`, and keeps only the
   chunks completed so far.
4. That flows into the ordinary result path, and `save_result()` writes
   **`status = 'completed'`** (`job_repository.py:163`).
5. The dashboard never reads `partial` or `partial_reason` (zero occurrences in the frontend).
6. `/retry` refuses the job, accepting only `status == 'failed'` (`transcription.py:1466`).

A user on a slow machine therefore records a 2-hour lecture, receives a transcript that stops
40 minutes in, sees it marked complete with no warning, and cannot retry it. This is the exact
failure class `CLAUDE.md` forbids: a completed transcription silently discarded.

The partial-salvage machinery (GH #168) was designed as a safety net for a genuinely dead
sidecar, where half a transcript beats none. Once a healthy-but-slow machine raises the same
exception, the net becomes a trap, because "we gave up early" and "the sidecar died" are
indistinguishable downstream.

## Why the timeout exists, and why it cannot simply be deleted

The read timeout is currently the **only** mechanism that terminates a stuck whisper.cpp job.
Two facts make a naive `read=None` actively dangerous, and both were verified empirically:

**Cancel is not wired up on the main path.** `websocket.py:459` binds
`cancellation_check=lambda: self._client_disconnected`, and that flag is only ever set on a
real socket disconnect (`websocket.py:220, 1065, 1083`). `POST /cancel`
(`transcription.py:770`) flips `job_tracker._cancelled`, which the WebSocket path never reads.
Every other caller polls `job_tracker.is_cancelled` (`transcription.py:313, 488, 543, 716, 890`;
`openai_audio.py:246`). Two further paths pass no `cancellation_check` at all
(`notebook.py:1031`, `transcription.py:1103`) - and `notebook.py:1345` calls `cancel_job()`
anyway, a flag with no reader.

**A blocked read cannot be interrupted by closing the client.** Driven against a fake sidecar
that accepts the POST, drains the body, and then sends nothing (the GPU-wedge shape):

| Abort mechanism | Result |
|---|---|
| `resp.close()` from another thread | request hung the full 30s, then **completed normally** |
| `client.close()` from another thread | same |
| httpcore `NetworkStream.close()` | same |
| `sock.shutdown(SHUT_RDWR)` | aborted in 2.0s |

`httpcore/_backends/sync.py:141` calls `self._sock.close()`, and on Linux closing an fd does not
wake a thread already blocked in `recv()` on it. The kernel keeps the file description alive for
the in-flight syscall.

Consequently, with a sync client and `read=None`, a wedged sidecar blocks forever in an
unkillable thread, holding both the single `job_tracker` slot and `engine.transcription_lock`,
which deadlocks the notebook, OpenAI-compat, and retry paths too. That is a server restart,
not a lost job. Measured: with `read=None`, warmup, live, and longform all remained blocked
past 20s **even with `cancellation_check` flipping to True**, because it is polled only between
chunks and never during the blocked read.

## Design principle

> **An unbounded read is permitted only where an abort path exists.**

The current code inverts this: it bounds the read (harming honest slow machines) while leaving
the abort path disconnected (so a wedge is unrecoverable anyway).

## The abort primitive

`httpx.AsyncClient` + `asyncio.Task.cancel()` aborts a request blocked before response headers,
using only public API. asyncio registers the socket with a selector rather than issuing a
blocking `recv()`, so cancellation is a first-class operation.

Verified against a stalling server, from a synchronous caller (the `STTBackend.transcribe()`
contract) that runs its own event loop inside the executor thread:

| Scenario | Result |
|---|---|
| Wedged sidecar, user cancels at t=2s | aborted in **2.04s** |
| Slow but healthy, 12s of work (old cap would have killed it) | **completed**, no limit |
| Dead sidecar host | failed in **0.01s** (connect still bounded) |
| fd hygiene after abort | no leak |

No httpcore internals, no socket surgery, no subprocess, no async rewrite of the backend.

## Changes

Shipped as **one PR, three commits**. Wave 1 must land first: it restores the escape hatch that
Wave 2 relies on.

### Commit 1 - fix cancellation wiring

Independent user-facing bug fix. Today, pressing Cancel on a whisper.cpp longform job does
nothing: the job transcribes to completion, persists, auto-adds to the notebook, fires the
webhook, and holds the job slot so no new recording can start.

- `websocket.py:459` - bind to both signals:
  `cancellation_check=lambda: self._client_disconnected or model_manager.job_tracker.is_cancelled()`
  (`model_manager` is already in scope). Flag hygiene is already safe: `try_start_job` and
  `end_job` reset `_cancelled` (`model_manager.py:90, 113`), and `_release_job()` runs in
  `stop_recording`'s `finally` (`websocket.py:786-788`), so no stale flag leaks into the next job.
- `notebook.py:1031` - pass `cancellation_check=model_manager.job_tracker.is_cancelled`.
- `transcription.py:1103` (`_run_file_import`) - same.

### Commit 2 - remove the time limit

- Rewrite `_transcribe_chunk` around the abortable POST: `httpx.Timeout(None, connect=10.0,
  write=120.0, pool=10.0)`, request issued as an asyncio task, `cancellation_check` polled every
  250ms, `task.cancel()` on request.
- `read=None` applies wherever a `cancellation_check` is available (every longform path, after
  Commit 1). Warmup, live, and preview keep a finite read via a module constant - their audio is
  seconds long, they have no abort path, and no legitimate slow machine needs 20 minutes for a
  3-second utterance.
- **Delete the knobs entirely**: `inference_timeout_s` and `timeout_seconds_per_audio_second`
  from `config.yaml:159-180` and `config.py:250-254`; `_INFERENCE_TIMEOUT`,
  `_TIMEOUT_SECONDS_PER_AUDIO_SECOND`, `_inference_timeout_for`, `_resolve_timeout_config` from
  the backend. Unbounded is the only behavior.
- **Fixes a latent bug**: line 775 passes a bare scalar, and httpx expands a scalar to all four
  timeout fields, so today a blackholed sidecar host hangs in the **connect** phase for 20-60
  minutes. Bounding connect at 10s fixes this.
- **Removes dead code**: the client-level default at line 514 never applies, because httpx
  replaces the client default wholesale when a per-request `timeout=` is passed
  (`_client.py:371-377`). It also reads the module constant rather than the config-resolved value.

Chunking (`_MAX_CHUNK_DURATION_S`, `_MAX_CHUNK_DURATION_CEILING_S`) is **retained unchanged**.
It bounds memory per forward pass and preserves per-chunk progress and cancellation. It was
never the time limit.

### Commit 3 - stop laundering partials into "completed"

Partials remain possible after the cap is gone (sidecar crash, connection reset mid-chunk), so
they must stop being silently truncated "completed" jobs.

Keep `status='completed'` and drive off the `partial` / `partial_reason` fields that
`engine.py:99-100` already persists. **No migration, no new status value.** A new status would
have to be retrofitted into `get_recent_undelivered` and `get_jobs_for_cleanup`, and the failure
mode of forgetting either is silent data loss. Staying inside `'completed'` means partial jobs
keep being re-delivered on reconnect and keep having their audio GC'd, for free.

- `GET /result` (`transcription.py:~1428`) - echo `partial` and `partial_reason`.
- `/retry` (`transcription.py:1466`) - accept a completed-but-partial job.
- Dashboard - banner on a partial result with a Retry action.

## Testing

- Backend suite from `server/backend/` using the build venv, per `CLAUDE.md`.
- `test_whispercpp_backend.py:1656-1693` asserts on the deleted knobs and must be rewritten.
- New tests, against a fake stalling sidecar: unbounded read completes slow-but-healthy work;
  cancel aborts a wedged request promptly; connect stays bounded against a dead host; a partial
  result is surfaced and is retryable.
- A regression test asserting the abort actually fires, so an upstream httpx change cannot
  silently degrade back into a hang.
- Frontend: Vitest for the partial banner. Node 22 required (`cd dashboard && nvm use`).

## Risks

- Abort verified on Linux/CPython 3.13 only. The sidecar also ships on Windows and macOS; the
  asyncio primitive is platform-independent by construction, but should be smoke-tested there.
- A wedged sidecar on a no-cancel path (warmup, live, preview) still relies on the finite read
  constant. This is intentional and is strictly better than today.
- `RemoteProtocolError` from a self-requested abort is indistinguishable from a genuine sidecar
  crash, so the caller must consult its own "I requested this" flag before labelling the job, and
  must persist any partial state first.
