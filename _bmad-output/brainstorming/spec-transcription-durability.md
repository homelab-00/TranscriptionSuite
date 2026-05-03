# Spec: Transcription Data Durability

**Status:** Ready for implementation
**Priority:** Critical — data loss is unacceptable
**Origin:** Brainstorming session 2026-03-29 (reverse brainstorming + cross-pollination + morphological analysis)

## Problem Statement

Transcription results can be silently lost when the WebSocket connection drops, the server
crashes, or the client navigates away during processing. The WebSocket path has zero
persistence — results exist only in memory and are delivered via a single `send_message()`
call. If that call fails, the result is gone.

The HTTP file upload path (`/api/transcribe/upload`) already saves to the database via
`save_longform_to_database()`. The WebSocket path does not. This asymmetry must be fixed.

## Guiding Principles

**PERSIST BEFORE DELIVER.** Every transcription result must be written to durable storage
(SQLite database) before any attempt to deliver it to the client. The WebSocket is a
notification channel, not the sole delivery path.

**CREDIT CODE SOURCES.** Per project rules (CLAUDE.md), add an attribution comment wherever
code is copied from or substantially inspired by an external source. The following credits
are known in advance — add them at the implementation site:

| Source | URL | What we borrow |
|--------|-----|----------------|
| Scriberr | https://github.com/rishikanthc/Scriberr | Job state machine (`processing→completed\|failed`), startup recovery pattern for orphaned jobs, per-track incremental save idea |
| Scriberr | https://github.com/rishikanthc/Scriberr | Job model structure: id, status, audio_path, result, error_message, timestamps |
| AssemblyAI / Deepgram (async job pattern) | https://www.assemblyai.com/docs | Persist-before-deliver: result hits DB before client notification; WebSocket as notification-only channel |

Use this format at the implementation site:

```python
# Adapted from Scriberr (https://github.com/rishikanthc/Scriberr) — startup recovery
# pattern: on boot, re-queue jobs stuck in 'processing' state from a prior crash.
async def recover_orphaned_jobs() -> None:
    ...
```

Only add attribution when the specific logic or structure came from an identifiable external
source. Standard patterns and original TranscriptionSuite-specific logic need no comment.

## Architecture Context

- **Server:** Python/FastAPI, runs in Docker, single instance, single GPU
- **Database:** SQLite with WAL mode, managed by Alembic migrations, located at `/data/database/notebook.db`
- **Storage:** Docker volume mounted at `/data/`
- **WebSocket handler:** `server/backend/api/routes/websocket.py`
- **HTTP transcription:** `server/backend/api/routes/transcription.py`
- **Model manager / job tracker:** `server/backend/core/model_manager.py`
- **STT engine:** `server/backend/core/stt/engine.py`
- **Database layer:** `server/backend/database/database.py` (init, migrations, Alembic)
- **Dashboard hooks:** `dashboard/src/hooks/useTranscription.ts`, `dashboard/src/hooks/useLiveMode.ts`
- **Dashboard views:** `dashboard/components/views/SessionView.tsx`

## Implementation Waves

Each wave is independently shippable and testable. Implement in order.

---

## Wave 1: Never Lose a Completed Result

### 1.1 Database Migration — `transcription_jobs` Table

**File:** New Alembic migration in `server/backend/database/migrations/versions/`

Follow the existing migration pattern (see other files in that directory for the Alembic
boilerplate). The table goes in the existing `notebook.db` database.

```sql
CREATE TABLE transcription_jobs (
    id TEXT PRIMARY KEY,                          -- UUID, same as job_id from job tracker
    status TEXT NOT NULL DEFAULT 'processing',    -- 'processing' | 'completed' | 'failed'
    source TEXT NOT NULL,                         -- 'websocket' | 'upload' | 'notebook'
    client_name TEXT,
    language TEXT,
    task TEXT DEFAULT 'transcribe',               -- 'transcribe' | 'translate'
    translation_target TEXT,
    audio_path TEXT,                              -- filled in Wave 2
    result_text TEXT,                             -- full transcription text
    result_json TEXT,                             -- full result payload (words, segments, etc.)
    result_language TEXT,                         -- detected language
    duration_seconds REAL,                        -- audio duration
    error_message TEXT,
    delivered INTEGER NOT NULL DEFAULT 0,         -- 0 = not yet delivered to client, 1 = delivered
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_transcription_jobs_status ON transcription_jobs(status);
CREATE INDEX idx_transcription_jobs_client ON transcription_jobs(client_name, created_at);
```

### 1.2 Job Repository

**File:** New file `server/backend/database/job_repository.py`

Simple data access layer. All methods operate on the `transcription_jobs` table using the
existing database connection from `server/backend/database/database.py`.

Required functions:

```python
def create_job(job_id: str, source: str, client_name: str, language: str | None,
               task: str, translation_target: str | None) -> None:
    """Insert a new job with status='processing'. Called at transcription start."""

def save_result(job_id: str, result_text: str, result_json: str,
                result_language: str | None, duration_seconds: float | None) -> None:
    """Set status='completed', write result fields, set completed_at. Called BEFORE delivery."""

def mark_delivered(job_id: str) -> None:
    """Set delivered=1. Called AFTER successful WebSocket/HTTP delivery."""

def mark_failed(job_id: str, error_message: str) -> None:
    """Set status='failed', write error_message."""

def get_job(job_id: str) -> dict | None:
    """Return job row as dict, or None."""

def get_recent_undelivered(client_name: str, limit: int = 5) -> list[dict]:
    """Return completed jobs where delivered=0 for this client, newest first."""

def set_audio_path(job_id: str, audio_path: str) -> None:
    """Set audio_path field. Used by Wave 2."""
```

Use parameterized queries for all SQL. No ORM — keep it simple like the existing database code.

### 1.3 WebSocket Handler Changes

**File:** `server/backend/api/routes/websocket.py`

**In `process_transcription()` method, after `result = transcribe_future.result()`:**

```python
# --- PERSIST BEFORE DELIVER ---
import json as _json
from server.database.job_repository import save_result, mark_delivered

result_payload = {
    "text": result.text,
    "words": result.words,
    "language": result.language,
    "duration": result.duration,
}
save_result(
    job_id=self._current_job_id,
    result_text=result.text,
    result_json=_json.dumps(result_payload, ensure_ascii=False, default=str),
    result_language=result.language,
    duration_seconds=result.duration,
)

# Now deliver (best-effort — result is safe in DB regardless)
await self.send_message("final", result_payload)
mark_delivered(self._current_job_id)
```

**In the `start_recording()` flow (where `try_start_job()` is called):**

After successfully acquiring a job slot, create the job record:

```python
from server.database.job_repository import create_job

create_job(
    job_id=self._current_job_id,
    source="websocket",
    client_name=self.client_name,
    language=self.language,
    task="translate" if self.translation_enabled else "transcribe",
    translation_target=getattr(self, "translation_target_language", None),
)
```

**In the error handler for `TranscriptionCancelledError` and general exceptions:**

```python
from server.database.job_repository import mark_failed

if isinstance(e, TranscriptionCancelledError):
    mark_failed(self._current_job_id, "Cancelled: client disconnected")
else:
    mark_failed(self._current_job_id, str(e))
```

**In the `session_started` message**, include the job_id so the client can use it for recovery:

```python
await self.send_message("session_started", {
    # ... existing fields ...
    "job_id": self._current_job_id,
})
```

### 1.4 HTTP Result Retrieval Endpoint

**File:** `server/backend/api/routes/transcription.py` (add to existing router)

```python
@router.get("/result/{job_id}")
async def get_transcription_result(job_id: str, ...):
    """Retrieve a transcription result by job ID.

    Returns the stored result for a completed job.
    Marks the job as delivered on successful retrieval.
    Returns 404 if job not found, 202 if still processing,
    410 if failed (with error message).
    """
```

### 1.5 JSON Sanitization Utility

**File:** New file `server/backend/core/json_utils.py`

```python
def sanitize_for_json(obj: Any) -> Any:
    """Recursively sanitize a data structure for JSON serialization.

    - Replace float NaN/Inf with None
    - Convert numpy types to Python natives
    - Ensure all strings are valid UTF-8
    """
```

Call this in `process_transcription()` before both `save_result()` and `send_message()`.

### 1.6 Client Changes — Store job_id and Add HTTP Fallback

**File:** `dashboard/src/hooks/useTranscription.ts`

- Store `jobId` from the `session_started` message data
- In the `onClose` callback: if `status === 'processing'` and we have a `jobId`, start polling
  `GET /api/transcribe/result/{jobId}` every 3 seconds (max 10 retries)
- On successful poll: set result and status as if `"final"` message was received
- Add `jobId` to `TranscriptionState` interface

### Wave 1 Acceptance Criteria

- [ ] New Alembic migration applies cleanly (`alembic upgrade head`)
- [ ] WebSocket transcription creates a job record in `transcription_jobs` on start
- [ ] Result is written to `transcription_jobs` BEFORE `send_message("final", ...)`
- [ ] If WebSocket dies mid-processing, result is still in the database
- [ ] `GET /api/transcribe/result/{job_id}` returns the saved result
- [ ] Client polls HTTP endpoint on unexpected disconnect and recovers the result
- [ ] NaN/Inf values in whisper output don't crash serialization
- [ ] All existing tests pass (`pytest server/backend/tests/`)
- [ ] Manual test: start long recording, navigate away during processing, navigate back,
  see "transcription ready" notification

---

## Wave 2: Never Lose Raw Audio

### 2.1 Audio Preservation

**File:** `server/backend/api/routes/websocket.py` — `process_transcription()`

**Before the current WAV-writing code**, save the audio to the persistent data directory:

```python
RECORDINGS_DIR = Path("/data/recordings")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

audio_path = RECORDINGS_DIR / f"{self._current_job_id}.wav"
sf.write(str(audio_path), audio_float, self.sample_rate)

# Update job record with audio path
from server.database.job_repository import set_audio_path
set_audio_path(self._current_job_id, str(audio_path))

# Use this file for transcription (no separate /tmp file needed)
self.temp_file = audio_path  # NOTE: do NOT delete this in the finally block
```

**Modify the `finally` block:** Only delete the temp file if it's in `/tmp`. Don't delete
files in `/data/recordings/`.

### 2.2 Retry Endpoint

**File:** `server/backend/api/routes/transcription.py`

```python
@router.post("/retry/{job_id}")
async def retry_transcription(job_id: str, ...):
    """Re-run transcription for a failed job using its saved audio file.

    Resets status to 'processing', re-runs engine.transcribe_file() on audio_path.
    Returns 404 if job not found, 409 if job is already processing,
    410 if audio file is missing/deleted.
    """
```

This endpoint should run the transcription in a background task (not block the HTTP response).
Return 202 Accepted with the job_id. Client polls `/result/{job_id}` for completion.

### 2.3 Audio Auto-Cleanup

**File:** New background task registered in the FastAPI lifespan or existing backup scheduler.

```python
async def cleanup_old_recordings(max_age_days: int = 7) -> None:
    """Delete audio files and associated job records older than max_age_days.

    Only delete audio for jobs with status='completed' AND delivered=1.
    Never delete audio for 'failed' or 'processing' jobs.
    Read max_age_days from config.yaml key: audio_retention_days (default: 7).
    """
```

Schedule this to run daily (or on server startup).

### 2.4 Disk Space Guard

Before writing audio to disk, check available space:

```python
import shutil
usage = shutil.disk_usage(str(RECORDINGS_DIR))
if usage.free < 500_000_000:  # 500MB minimum
    logger.warning("Low disk space (%dMB free) — audio may not be saved", usage.free // 1_000_000)
```

Don't hard-fail on low disk — still attempt the save. Log loudly so the user can see it in
the admin dashboard.

### Wave 2 Acceptance Criteria

- [ ] Audio saved to `/data/recordings/{job_id}.wav` BEFORE transcription starts
- [ ] `audio_path` column populated in job record
- [ ] `finally` block does NOT delete audio files in `/data/recordings/`
- [ ] `POST /api/transcribe/retry/{job_id}` successfully re-transcribes from saved audio
- [ ] Cleanup task removes old audio files for completed+delivered jobs
- [ ] Cleanup task does NOT remove audio for failed/undelivered jobs
- [ ] Low disk space produces a warning log, not a crash
- [ ] Manual test: kill the Docker container mid-transcription, restart, retry via endpoint

---

## Wave 3: Recover From Everything

### 3.1 Startup Recovery

**File:** Add to FastAPI lifespan startup in `server/backend/api/main.py`

```python
async def recover_orphaned_jobs() -> None:
    """On startup, find jobs stuck in 'processing' and handle them.

    - If audio_path exists on disk: reset status to 'failed' with message
      'Server restarted during processing — use retry to re-transcribe'
    - If no audio_path: mark 'failed' with 'Server restarted — audio not preserved'
    - Log each recovered job
    """
```

Call this after database initialization in the lifespan.

### 3.2 Client Recovery UX

**File:** `dashboard/src/hooks/useTranscription.ts` or new hook `useTranscriptionRecovery.ts`

On component mount (SessionView), call `GET /api/transcribe/recent?status=completed&undelivered=true`.
If results exist, show a non-intrusive notification:

"A transcription from [relative time] is available. [View] [Dismiss]"

Clicking "View" loads the result into the transcription panel. Clicking "Dismiss" calls
`mark_delivered` on the server.

**File:** `dashboard/components/views/SessionView.tsx` — render the recovery notification.

### 3.3 Graceful Shutdown Drain

**File:** `server/backend/api/main.py` — lifespan shutdown

```python
# In the shutdown phase of the lifespan:
active_sessions = list(_connected_sessions.values())
for session in active_sessions:
    if session.is_recording:
        logger.info("Draining active session for %s before shutdown", session.client_name)
        await session.stop_recording()

# Wait for in-progress transcriptions (they run in executor threads)
# Give them up to 120 seconds
```

**File:** `docker-compose.yml` (or equivalent) — set `stop_grace_period: 130s`

### 3.4 Large Result Handling

**File:** `server/backend/api/routes/websocket.py` — `process_transcription()`

After persisting to DB, before sending via WebSocket:

```python
result_size = len(_json.dumps(result_payload))
if result_size > 1_000_000:  # 1MB threshold
    # Too large for WebSocket — send reference instead
    await self.send_message("result_ready", {"job_id": self._current_job_id})
else:
    await self.send_message("final", result_payload)
```

**File:** `dashboard/src/hooks/useTranscription.ts` — handle `result_ready` message by
fetching from HTTP endpoint.

### Wave 3 Acceptance Criteria

- [ ] Server startup logs recovery of any orphaned `processing` jobs
- [ ] Orphaned jobs with audio can be retried
- [ ] Dashboard shows recovery notification for undelivered results
- [ ] `docker stop` with active transcription: transcription completes before container exits
- [ ] Results >1MB delivered via HTTP reference, not inline WebSocket
- [ ] Manual test: kill container mid-transcription, restart, see recovery prompt in dashboard

---

## Files Modified (All Waves)

| File | Wave | Change |
|------|------|--------|
| `server/backend/database/migrations/versions/xxx_add_transcription_jobs.py` | 1 | New migration |
| `server/backend/database/job_repository.py` | 1 | New file — job CRUD |
| `server/backend/core/json_utils.py` | 1 | New file — JSON sanitization |
| `server/backend/api/routes/websocket.py` | 1,2 | Persist before deliver, audio save |
| `server/backend/api/routes/transcription.py` | 1,2 | `/result/{job_id}`, `/retry/{job_id}` |
| `server/backend/api/main.py` | 3 | Startup recovery, graceful drain |
| `dashboard/src/hooks/useTranscription.ts` | 1,3 | Job ID tracking, HTTP fallback, recovery |
| `dashboard/components/views/SessionView.tsx` | 3 | Recovery notification UI |
| `docker-compose.yml` | 3 | `stop_grace_period: 130s` |

## Testing Strategy

### Unit Tests (per wave)
- `test_job_repository.py` — CRUD operations, edge cases (duplicate ID, missing job)
- `test_json_utils.py` — NaN, Inf, numpy types, Unicode edge cases
- Extend existing `test_websocket.py` (if it exists) with persistence assertions

### Integration Tests
- WebSocket session: start → record → stop → verify job in DB → verify result in DB
- WebSocket disconnect during processing → verify result still in DB → verify HTTP retrieval
- Retry endpoint: create failed job with audio → POST retry → verify new result

### Manual Smoke Tests
- Long recording (>2 min), navigate away during processing, navigate back → result available
- Kill Docker container during processing → restart → retry from saved audio
- Very long recording (>30 min) → verify result delivery (size handling)

## Config Additions

Add to `config.yaml`:

```yaml
durability:
  audio_retention_days: 7          # How long to keep raw audio files (0 = forever)
  recordings_dir: /data/recordings # Where to save audio files
  orphan_job_timeout_minutes: 10   # Jobs stuck in 'processing' longer than this are orphaned
```

---

## Review Findings

**Review date:** 2026-03-30
**Commits reviewed:** `9d07247..9fffc01` (6 commits, 27 files, 1405 insertions)
**Layers:** Blind Hunter · Edge Case Hunter · Acceptance Auditor
**Result:** 0 decision-needed · 13 patch · 5 defer · 5 dismissed

### Patch Items

- [x] [Review][Patch] P1 — `_run_retry` bypasses job tracker: concurrent retry + active session can cause GPU OOM (deferred-work item #10 confirmed HIGH) [`transcription.py:1065`]
- [x] [Review][Patch] P2 — `sanitize_for_json` has no tuple branch: NaN inside tuple structures crashes serialization [`json_utils.py:33`]
- [x] [Review][Patch] P3 — REST recovery endpoints send no auth headers: TLS mode silently broken (recovery banner + fallback poll + dismiss all affected) [`SessionView.tsx:83,136,157` / `useTranscription.ts:289`]
- [x] [Review][Patch] P4 — `cancelled` flag is dead code: poll loop cannot be stopped on component unmount, leaks state updates [`useTranscription.ts:283`]
- [x] [Review][Patch] P5 — `result_ready` path calls `mark_delivered` before client fetches: recovery banner will not appear for large-result client crashes [`websocket.py:304`]
- [x] [Review][Patch] P6 — `save_result` failure path: `mark_delivered` still called producing `processing/delivered=1` row with no result — no recovery path until restart [`websocket.py:282-311`]
- [x] [Review][Patch] P7 — `_run_retry` never calls `mark_delivered`: successfully retried jobs permanently appear in recovery banner [`transcription.py:1094`]
- [x] [Review][Patch] P8 — Graceful drain iterates `_connected_sessions` without `_sessions_lock`: potential `RuntimeError` on concurrent disconnect [`main.py:933`]
- [x] [Review][Patch] P9 — `get_recent_undelivered` orders by `created_at` not `completed_at`: retried jobs may never surface in limit=5 recovery list [`job_repository.py:138`]
- [x] [Review][Patch] P10 — `result_ready` path never calls `setProcessingProgress(null)`: stale progress bar remains visible after large-result delivery [`useTranscription.ts:461`]
- [x] [Review][Patch] P11 — Poll loop treats 500/503 as `idle`: user sees UI snap to idle with no error on server-side failure [`useTranscription.ts:314`]
- [x] [Review][Patch] P12 — Null `client_name` in DB bypasses auth guard: any caller can access jobs with `client_name=NULL` [`transcription.py:993`]
- [x] [Review][Patch] P13 — Timestamp format asymmetry: orphan uses `strftime`, cleanup uses `isoformat` — latent trap for future developers [`job_repository.py:203,227`]

### Deferred Items

- [x] [Review][Defer] W1 — TOCTOU: audio cleanup could delete file between `exists()` check and `_run_retry` start [`transcription.py:1056`] — deferred, low-probability edge case; job fails gracefully with mark_failed
- [x] [Review][Defer] W2 — `/tmp` fallback + restart → retry returns 410 with no actionable UX message — deferred, orphan recovery sets correct reason string; UX improvement only
- [x] [Review][Defer] W3 — Orphaned jobs can persist in `processing` indefinitely if server runs continuously without restart (no scheduled sweep) — deferred, by design for single-server use
- [x] [Review][Defer] W4 — `cleanup_old_recordings` task not awaited on shutdown: stale `audio_path` in DB if interrupted mid-run — deferred, no data loss; `unlink(missing_ok=True)` handles re-runs
- [x] [Review][Defer] W5 — `_run_retry` uses stale `job` dict snapshot from request time — deferred, not currently exploitable; refactor concern
