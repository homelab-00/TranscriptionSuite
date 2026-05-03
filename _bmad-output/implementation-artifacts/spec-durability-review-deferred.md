---
title: 'Durability review deferred fixes (W3, W1, W2)'
type: 'bugfix'
created: '2026-04-05'
status: 'done'
baseline_commit: '757cbb6'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The durability code review (commits 9d07247..9fffc01) flagged five findings. W4 (cleanup not awaited on shutdown) is already correctly handled and W5 (stale job dict) uses only immutable fields — both need no fix. Three remain: orphaned jobs persist in `processing` state indefinitely if the server runs without restarting (W3, Medium); a TOCTOU window lets periodic cleanup delete audio between the retry endpoint's `exists()` check and `_run_retry`'s `transcribe_file` call (W1, Low); the 410 response on retry uses a generic message instead of distinguishing "never preserved" vs "file deleted" (W2, Low).

**Approach:** Add a periodic orphan sweep task reusing `recover_orphaned_jobs()` on a configurable interval. Harden `_run_retry` with a `FileNotFoundError` catch that marks the job failed with a clear message. Split the 410 detail into two distinct messages.

## Boundaries & Constraints

**Always:** Preserve existing startup orphan recovery unchanged. Never mark genuinely in-progress jobs as failed — the existing `timeout_minutes` threshold must apply. Sweep interval configurable via `config.yaml`.

**Ask First:** If the default sweep interval should differ from 30 minutes.

**Never:** Change the retry endpoint's HTTP status codes or response contract. Add database schema changes. Modify `recover_orphaned_jobs()` logic — only wrap it in a periodic loop.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sweep finds orphan | Job in `processing` > timeout_minutes | Job marked `failed`, reason mentions orphan sweep | Logged; sweep continues |
| Sweep finds active job | Job in `processing` < timeout_minutes | Job untouched | N/A |
| Sweep disabled | `orphan_sweep_interval_minutes: 0` | Single startup recovery only, no periodic task | N/A |
| TOCTOU file gone | `_run_retry` starts, file deleted by cleanup | Job marked `failed`: "Audio file was removed" | FileNotFoundError caught |
| Retry 410 — never saved | `audio_path` is NULL | 410: "Audio was not preserved for this job" | N/A |
| Retry 410 — file deleted | `audio_path` set but file missing on disk | 410: "Audio file has been deleted" | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/api/main.py:86-111` -- `recover_orphaned_jobs()`: startup-only sweep (not reused for periodic — uses "Server restarted" reason and doesn't account for retries)
- `server/backend/api/main.py:408-421` -- periodic cleanup task pattern to replicate
- `server/backend/api/main.py:542-553` -- shutdown cancellation pattern to replicate
- `server/backend/api/routes/transcription.py:912-914` -- retry 410 check (split message here)
- `server/backend/api/routes/transcription.py:954-1001` -- `_run_retry` try/except (add FileNotFoundError guard)
- `server/backend/database/audio_cleanup.py:20-55` -- `periodic_cleanup()` reference pattern
- `server/backend/database/job_repository.py:172-192` -- `reset_for_retry()`: needs `created_at = CURRENT_TIMESTAMP` to prevent false orphan detection
- `server/backend/database/job_repository.py:195-219` -- `get_orphaned_jobs()`: called directly by periodic sweep (not via `recover_orphaned_jobs`)
- `server/config.yaml:600-603` -- durability config section (add sweep interval)

## Tasks & Acceptance

**Execution:**
- [x] `server/config.yaml` -- Add `orphan_sweep_interval_minutes: 30` with comment, under the existing `orphan_job_timeout_minutes` entry
- [x] `server/backend/database/job_repository.py` -- In `reset_for_retry`, add `created_at = CURRENT_TIMESTAMP` to the UPDATE statement. This ensures the orphan query's `created_at < cutoff` doesn't match jobs that were just retried.
- [x] `server/backend/api/main.py` -- Add `periodic_orphan_sweep(timeout_minutes, interval_minutes)` async function following the `periodic_cleanup` pattern (no immediate run — startup already calls `recover_orphaned_jobs`). The sweep loop must call `get_orphaned_jobs(timeout_minutes)` and `mark_failed` directly (NOT via `recover_orphaned_jobs`) using reason prefix "Orphan sweep" instead of "Server restarted". Preserve the audio-exists check from `recover_orphaned_jobs` (audio exists → "use retry to re-transcribe"; audio missing → "audio not preserved"). Initialize `_orphan_sweep_task = None` before any code that could fail. Schedule as `_orphan_sweep_task` after existing cleanup task. Cancel and await on shutdown alongside `_cleanup_task`.
- [x] `server/backend/api/routes/transcription.py` -- In retry endpoint (~line 913), split the 410 into two messages: `audio_path` falsy → "Audio was not preserved for this job — cannot retry" vs path set but file missing → "Audio file has been deleted — cannot retry"
- [x] `server/backend/api/routes/transcription.py` -- In `_run_retry` (~line 954), wrap `transcribe_file` call in a `try/except FileNotFoundError` that calls `mark_failed(job_id, "Audio file was removed before retry could complete")` and returns early
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- Mark W4 and W5 as resolved in item 9

**Acceptance Criteria:**
- Given a server running continuously with a job stuck in `processing` beyond `orphan_job_timeout_minutes`, when the sweep interval elapses, then the job is marked `failed` with a reason containing "Orphan sweep"
- Given a retried job (via retry endpoint) currently being transcribed by `_run_retry`, when the orphan sweep runs, then the job is NOT marked failed (because `reset_for_retry` updated `created_at` to now, which is within the timeout window)
- Given `orphan_sweep_interval_minutes: 0` in config, when the server starts, then no periodic sweep task is created (startup recovery still runs)
- Given a retry request where `audio_path` is NULL, when the endpoint responds, then 410 detail says "not preserved"
- Given a retry where the file is deleted after the exists() check, when `_run_retry` runs, then the job is marked `failed` (no unhandled exception)

## Spec Change Log

- **Review iteration 1 (2026-04-05):** Edge-case review found that `reset_for_retry` does not update `created_at`, so the orphan query (`created_at < cutoff`) would immediately sweep any retried job older than `timeout_minutes`. Fix: (a) add `created_at = CURRENT_TIMESTAMP` to `reset_for_retry`, (b) have periodic sweep call `get_orphaned_jobs` + `mark_failed` directly with "Orphan sweep" reason instead of wrapping `recover_orphaned_jobs`. Also: acceptance auditor found AC1 fail (reason said "Server restarted" not "orphan") — fixed by the same direct-call approach. Patch: initialize `_orphan_sweep_task = None` before potential failure point. KEEP: config entry naming/placement, periodic_cleanup asyncio pattern, shutdown cancel+await, 410 split, FileNotFoundError catch, W4/W5 resolution.

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: all existing tests pass

## Suggested Review Order

**W3 — Periodic orphan sweep**

- Entry point: cancel-safe async loop calling `get_orphaned_jobs` directly with "Orphan sweep" prefix
  [`main.py:113`](../../server/backend/api/main.py#L113)

- Prevents false orphan detection on retried jobs by resetting the timestamp the sweep queries
  [`job_repository.py:188`](../../server/backend/database/job_repository.py#L188)

- Early `None` init prevents `UnboundLocalError` if lifespan fails before task creation
  [`main.py:410`](../../server/backend/api/main.py#L410)

- Task scheduling in lifespan, reads `orphan_sweep_interval_minutes` from durability config
  [`main.py:479`](../../server/backend/api/main.py#L479)

- Graceful shutdown: cancel + await matches existing `_cleanup_task` pattern
  [`main.py:615`](../../server/backend/api/main.py#L615)

**W1 — TOCTOU hardening**

- Catches file deletion between retry endpoint's `exists()` check and actual transcription
  [`transcription.py:992`](../../server/backend/api/routes/transcription.py#L992)

**W2 — 410 message improvement**

- Split: "not preserved" (NULL path) vs "has been deleted" (path set, file missing)
  [`transcription.py:913`](../../server/backend/api/routes/transcription.py#L913)

**Config**

- New `orphan_sweep_interval_minutes` setting with comment matching surrounding style
  [`config.yaml:608`](../../server/config.yaml#L608)
