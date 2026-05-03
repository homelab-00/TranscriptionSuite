---
title: 'Audio cleanup periodic scheduling'
type: 'feature'
created: '2026-04-04'
status: 'done'
baseline_commit: 'e9350fb'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Audio cleanup only runs at startup. On long-running deployments, files whose retention window expires while the server is running are not deleted until the next restart, causing unbounded disk growth.

**Approach:** Wrap the existing one-shot `cleanup_old_recordings` call in a periodic `asyncio` loop that repeats at a configurable interval (default: 24 hours). Cancel the loop task on shutdown.

## Boundaries & Constraints

**Always:**
- Reuse the existing `cleanup_old_recordings` function unchanged
- Default interval must be 24 hours (sensible for `audio_retention_days` granularity)
- The periodic task must be cancelled cleanly on server shutdown (no orphan coroutines)
- First run executes immediately (preserving current startup cleanup behavior)

**Ask First:**
- If adding a new config key (`cleanup_interval_hours`) seems unnecessary

**Never:**
- Do not change `cleanup_old_recordings` itself or `get_jobs_for_cleanup`
- Do not add external scheduling dependencies (APScheduler, etc.) — use stdlib `asyncio`
- Do not block the event loop

</frozen-after-approval>

## Code Map

- `server/backend/database/audio_cleanup.py` -- Add periodic wrapper function
- `server/backend/api/main.py:408-423` -- Replace one-shot task with periodic task, cancel on shutdown
- `server/config.yaml:589-593` -- Add `cleanup_interval_hours` config key

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/database/audio_cleanup.py` -- Add `periodic_cleanup(recordings_dir, max_age_days, interval_hours)` async function that loops with `asyncio.sleep`
- [x] `server/backend/api/main.py` -- Replace `asyncio.create_task(cleanup_old_recordings(...))` with `asyncio.create_task(periodic_cleanup(...))`, store task reference, cancel it in shutdown section
- [x] `server/config.yaml` -- Add `cleanup_interval_hours: 24` under `durability` with doc comment

**Acceptance Criteria:**
- Given a running server, when `cleanup_interval_hours` elapses, then `cleanup_old_recordings` runs again automatically
- Given server shutdown, when the periodic task is running, then it is cancelled without errors
- Given `cleanup_interval_hours: 0`, when the server starts, then cleanup runs once at startup and does not repeat (backwards-compatible)

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short -k cleanup` -- expected: existing tests still pass
- `cd server/backend && ../../build/.venv/bin/python -c "from server.database.audio_cleanup import periodic_cleanup; print('import ok')"` -- expected: no import errors

## Suggested Review Order

- Periodic loop function — async sleep + exception-guarded cleanup calls
  [`audio_cleanup.py:18`](../../server/backend/database/audio_cleanup.py#L18)

- Lifespan wiring — create_task with stored reference, new config read
  [`main.py:408`](../../server/backend/api/main.py#L408)

- Shutdown cancellation — cancel + await pattern
  [`main.py:547`](../../server/backend/api/main.py#L547)

- Config entry — cleanup_interval_hours under durability
  [`config.yaml:595`](../../server/config.yaml#L595)
