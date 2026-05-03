---
title: 'Wave 2 — Never Lose Raw Audio'
type: 'feature'
created: '2026-03-30'
status: 'done'
baseline_commit: '7eb7a65295d6018b3cf11c3d6587e76b64fa43c8'
context:
  - docs/project-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The WebSocket path writes audio to `/tmp` and deletes it on completion. If the server crashes mid-transcription, the raw audio is gone — the `audio_path` column in `transcription_jobs` is always null, and there is no way to retry a failed job from its original recording.

**Approach:** Save audio to `/data/recordings/{job_id}.wav` before transcription starts, populate `audio_path` immediately, skip `/tmp` entirely. Add `POST /retry/{job_id}` to re-transcribe from saved audio. Add a startup cleanup task to delete old audio files for completed+delivered jobs. Read retention config from `config.yaml`.

## Boundaries & Constraints

**Always:**
- Write audio to `recordings_dir` BEFORE calling `engine.transcribe_file()` — never after
- Call `set_audio_path()` immediately after the file is written — even if transcription subsequently fails
- In the `finally` block: only delete `self.temp_file` if its path starts with `/tmp`
- Check disk space before writing; if free < 500 MB, log a WARNING and continue — never hard-fail
- Retry endpoint: use same `get_client_name(request)` auth as `GET /result/{job_id}`
- Retry must return 202 immediately; transcription runs as a background task
- Use `asyncio.to_thread()` (not `run_in_executor`) for the CPU-bound retry transcription call
- Config reads: `config.get("durability", "recordings_dir", default="/data/recordings")` and `config.get("durability", "audio_retention_days", default=7)`

**Ask First:**
- (none — Wave 1 already established the auth pattern: `get_client_name(request)` + compare against stored `client_name`; retry uses the same check)

**Never:**
- Do not implement Wave 3 (startup recovery, graceful drain, recovery UI)
- Do not change the Alembic migration or `transcription_jobs` schema — `audio_path` column already exists
- Do not use ORM; raw sqlite3 only
- Do not delete audio files for jobs that are `failed` or not yet `delivered=1`

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Audio save — happy path | `audio_float` ndarray, `job_id` set | File at `recordings_dir/{job_id}.wav`; `audio_path` in DB set | — |
| Audio save — low disk | Free space < 500 MB | WARNING logged; write attempted | If write fails: log error, fall back to /tmp so transcription still runs |
| Audio save — write fails | `sf.write()` raises | Log error, fall back to /tmp | `set_audio_path()` still called with /tmp path (best-effort) |
| Retry — valid failed job | `job_id` with `status='failed'`, audio on disk | 202; background transcription; `save_result()` called on finish | Failure: `mark_failed()` again |
| Retry — not found | Unknown `job_id` | 404 Not Found | — |
| Retry — already processing | `status='processing'` | 409 Conflict | — |
| Retry — audio missing | `audio_path=None` or file not on disk | 410 Gone | — |
| Cleanup — old records | Completed+delivered jobs, `completed_at` > retention cutoff | Audio file deleted; DB row kept | Missing file: log warning, skip |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/websocket.py` — `process_transcription()`: replace /tmp write with persistent write; `finally` block guard
- `server/backend/database/job_repository.py` — add `get_jobs_for_cleanup()` and `reset_for_retry()`
- `server/backend/api/routes/transcription.py` — add `POST /retry/{job_id}` endpoint
- `server/backend/database/audio_cleanup.py` — new file: `cleanup_old_recordings()` async function (mirrors backup.py pattern)
- `server/backend/api/main.py` — schedule cleanup task in lifespan startup (same pattern as backup task)
- `server/backend/config.yaml` — add `durability:` section

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/database/job_repository.py` -- ADD `get_jobs_for_cleanup(max_age_days: int, limit: int = 100) -> list[dict]` returning rows where `status='completed' AND delivered=1 AND audio_path IS NOT NULL AND completed_at < cutoff`; ADD `reset_for_retry(job_id: str) -> None` setting `status='processing'`, clearing `error_message`, `completed_at`, `result_text`, `result_json` -- enables retry and cleanup workflows
- [x] `server/backend/database/audio_cleanup.py` -- NEW FILE: `async def cleanup_old_recordings(recordings_dir: str, max_age_days: int) -> None` — skips cleanup if `max_age_days == 0`; calls `get_jobs_for_cleanup()`; deletes each audio file with `Path(row["audio_path"]).unlink(missing_ok=True)`; logs each deletion -- prevents unbounded disk growth
- [x] `server/backend/config.yaml` -- ADD `durability:` section with `audio_retention_days: 7`, `recordings_dir: /data/recordings`, `orphan_job_timeout_minutes: 10` (last key reserved for Wave 3) -- single source of truth for durability config
- [x] `server/backend/api/routes/websocket.py` -- MODIFY `process_transcription()`: (1) read `recordings_dir` from `request.app.state.config`; create `Path(recordings_dir)` and call `.mkdir(parents=True, exist_ok=True)`; (2) check `shutil.disk_usage(recordings_dir).free < 500_000_000` → log WARNING; (3) write audio to `recordings_dir / f"{self._current_job_id}.wav"` via `sf.write()`; (4) call `set_audio_path(self._current_job_id, str(audio_path))` immediately after; (5) use `audio_path` (not a /tmp file) in the `transcribe_file()` call; (6) in `finally` block: `if self.temp_file and not str(self.temp_file).startswith("/tmp"): pass  # persistent file — do not delete` — keeps audio on disk for retry
- [x] `server/backend/api/routes/transcription.py` -- ADD `POST /retry/{job_id}`: call `get_client_name(request)`; validate job (404/409/410 as per matrix); call `reset_for_retry(job_id)`; `background_tasks.add_task(_run_retry, job_id, job["audio_path"], job, request.app.state)`; return 202 with `{"job_id": job_id}` -- enables user-initiated retry from saved audio
- [x] `server/backend/api/routes/transcription.py` -- ADD private `async def _run_retry(job_id, audio_path, job, app_state)` function: calls `engine.transcribe_file(audio_path, ...)` via `asyncio.to_thread()`; on success: calls `sanitize_for_json()` + `save_result()`; on failure: calls `mark_failed()` -- retry execution logic decoupled from HTTP handler
- [x] `server/backend/api/main.py` -- ADD cleanup startup task after the backup task block: read `durability` config; `asyncio.create_task(cleanup_old_recordings(recordings_dir, max_age_days))` -- schedules one cleanup pass on startup

**Acceptance Criteria:**
- Given a WebSocket transcription starts, when audio data arrives, then `recordings_dir/{job_id}.wav` exists on disk and `audio_path` is set in DB before `engine.transcribe_file()` runs
- Given the server crashes mid-transcription, when it restarts, then the `.wav` file persists at `audio_path` (Wave 3 will use this to offer retry to the user)
- Given a failed job with a valid audio file, when `POST /retry/{job_id}` is called, then 202 is returned and on background completion `status='completed'` with result in DB
- Given `POST /retry/{job_id}` on a job already `status='processing'`, then 409 is returned with no DB change
- Given `POST /retry/{job_id}` on a job with no audio file on disk, then 410 is returned
- Given disk free < 500 MB, when audio write is attempted, then a WARNING is logged and write proceeds
- Given jobs with `completed_at` older than `audio_retention_days` that are `status='completed' AND delivered=1`, when cleanup runs, then their audio files are deleted
- Given all of the above, when existing test suite runs, then all previously-passing tests still pass

## Design Notes

**Audio write fallback:** If `sf.write()` to `recordings_dir` fails, the code must fall back to `/tmp` so the transcription still runs. The `set_audio_path()` call in the fallback branch should use the `/tmp` path — it's better than null, and Wave 3 startup recovery will handle the "file in /tmp at restart" case gracefully.

**`finally` block guard:** The simplest gate is `str(self.temp_file).startswith("/tmp")`. Do not introduce a new `self._audio_persistent` flag — it adds state that can desync. The path prefix is the ground truth.

**Retry engine access:** `request.app.state.model_manager` has a `.get_engine()` method (or similar). Match the pattern used by the `/upload` endpoint in the same file — do not reach into the model manager differently.

**Cleanup idempotence:** `Path.unlink(missing_ok=True)` means running cleanup twice is safe. The DB row is kept even after the audio file is deleted — it records that a transcription happened.

## Verification

**Commands:**
- `cd server && python -m pytest backend/tests/ -x -q` -- expected: same pass count as baseline (285+), no new failures
- `cd server && python -m alembic upgrade head` -- expected: no new migration (schema unchanged from Wave 1)

**Manual checks:**
- After a WebSocket transcription: verify `/data/recordings/{job_id}.wav` exists and `audio_path` is set in the DB row
- Kill the container mid-transcription, restart: verify the `.wav` file persists in `/data/recordings/`
- POST `/api/transcribe/retry/{job_id}` on a completed job: verify 409 Conflict
- POST `/api/transcribe/retry/{job_id}` after deleting audio file: verify 410 Gone

## Suggested Review Order

**Persistent audio write — core invariant**

- Entry point: `_audio_written_persistently` flag + persistent write attempt before transcription
  [`websocket.py:149`](../../server/backend/api/routes/websocket.py#L149)

- `set_audio_path()` called immediately after write — DB records location even if transcription fails
  [`websocket.py:170`](../../server/backend/api/routes/websocket.py#L170)

- `finally` guard: only unlink files in `/tmp` — persistent audio is never deleted here
  [`websocket.py:344`](../../server/backend/api/routes/websocket.py#L344)

- `transcribe_file()` uses the persistent path — fallback /tmp path also supported
  [`websocket.py:226`](../../server/backend/api/routes/websocket.py#L226)

**Retry endpoint**

- Handler: validation gates (404/403/409/410), 202 response, background task dispatch
  [`transcription.py:833`](../../server/backend/api/routes/transcription.py#L833)

- Safety guard: only `status='failed'` jobs can be retried — prevents overwriting completed results
  [`transcription.py:864`](../../server/backend/api/routes/transcription.py#L864)

- Background task: `asyncio.to_thread()` for CPU-bound call; `save_result()` or `mark_failed()`
  [`transcription.py:879`](../../server/backend/api/routes/transcription.py#L879)

**Database layer**

- `reset_for_retry()`: clears result fields, resets status to 'processing'; preserves `audio_path`
  [`job_repository.py:157`](../../server/backend/database/job_repository.py#L157)

- `get_jobs_for_cleanup()`: age-cutoff query — only completed+delivered rows with audio_path
  [`job_repository.py:180`](../../server/backend/database/job_repository.py#L180)

**Audio cleanup**

- `cleanup_old_recordings()`: skips if `max_age_days <= 0`; `missing_ok=True` for idempotence
  [`audio_cleanup.py:17`](../../server/backend/database/audio_cleanup.py#L17)

- Scheduled once at startup via `asyncio.create_task()` — same pattern as backup task
  [`main.py:405`](../../server/backend/api/main.py#L405)

**Config**

- `durability:` section: `recordings_dir`, `audio_retention_days`, `orphan_job_timeout_minutes`
  [`config.yaml:579`](../../server/config.yaml#L579)
