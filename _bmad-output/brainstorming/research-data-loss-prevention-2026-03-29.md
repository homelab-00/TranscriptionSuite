# Research: Data Loss Prevention in Long-Running Transcription Systems

**Date:** 2026-03-29
**Purpose:** Inform brainstorming session on preventing data loss when WebSocket connections drop during transcription processing.

---

## 1. WebSocket Durability Patterns

### The Core Problem

WebSocket provides a bidirectional byte pipe with no built-in reliability guarantees beyond ordered delivery. After the HTTP upgrade handshake, there are no status codes, no request-response pairing, no per-message headers, and no built-in acknowledgment. Connection drops are a certainty: mobile users walk into elevators, laptops sleep, Docker containers restart, and load balancers time out idle connections.

The current TranscriptionSuite architecture (`websocket.py`) has a critical vulnerability: transcription results exist only in memory during processing, and delivery depends on the WebSocket connection surviving the entire GPU processing duration. If the connection drops after `transcribe_file()` completes but before `send_message("final", ...)` succeeds, the result is lost permanently.

### Pattern 1: Server-Side Result Caching (Outbox Pattern)

**How it works:** Before attempting to deliver a result over WebSocket, write it to a durable store (database, file). The WebSocket delivery becomes a "best effort" notification. If delivery fails, the client can retrieve the result later via a separate HTTP endpoint or upon reconnection.

**Production examples:**
- AWS Transactional Outbox Pattern: Write the business data and the "event to send" in the same database transaction. A separate poller/CDC process reads the outbox and delivers notifications. If delivery fails, the outbox retains the record.
- Collaborative editors (Google Docs, Figma): Server persists all operations to a log before acknowledging to clients. Reconnecting clients replay from their last known sequence number.

**Key implementation detail:** The result must be persisted *before* attempting WebSocket delivery. The WebSocket send is a side effect of the durable write, not the other way around.

### Pattern 2: Sequence Numbers + Replay on Reconnect

**How it works:** Every server-to-client message gets a monotonically increasing sequence number (or event ID). The client tracks the last received sequence number. On reconnection, the client sends `lastEventId` and the server replays missed messages.

**Production examples:**
- Server-Sent Events (SSE) has this built in via `Last-Event-ID` header
- Ably, Pusher, and other realtime platforms implement message history with sequence-based replay
- CRDTs in collaborative editors use vector clocks / sequence counters

**Relevance to TranscriptionSuite:** For longform transcription, the "event stream" is simple (progress updates, then one final result). A single job_id-based lookup is sufficient; full sequence replay is overkill.

### Pattern 3: Heartbeat + Dead Connection Detection

**How it works:** Application-level ping/pong at 30s intervals with 10s timeout. If no pong arrives, force-close and trigger reconnection. TCP keepalive alone is insufficient because it operates at the OS level with much longer timeouts (typically 2+ hours).

**Current state in TranscriptionSuite:** The WebSocket handler already sends `processing_progress` keepalives every 5 seconds during transcription. This is good for preventing idle timeout but does not detect dead connections (a dead TCP connection will not raise an error on `send_json` until the OS TCP timeout fires).

### Pattern 4: Message Queuing During Disconnection

**How it works:** When the server detects a disconnection, outbound messages are buffered in a queue (in-memory or persistent). On reconnection, the queue is flushed. Messages have TTL and max-retry limits.

**Relevance:** Less applicable to TranscriptionSuite since there is typically one large result, not a stream of messages. The "outbox" pattern (persist result, let client fetch) is simpler and more robust for this use case.

---

## 2. Transcription-Specific Approaches

### AssemblyAI Architecture (Industry Standard Pattern)

AssemblyAI uses a fully asynchronous job model for pre-recorded audio:

1. **Submit:** `POST /v2/transcript` with `audio_url` -- returns immediately with `transcript_id` and status `queued`
2. **Poll:** `GET /v2/transcript/{transcript_id}` -- returns current status (`queued` -> `processing` -> `completed` | `error`)
3. **Webhook alternative:** Optionally provide a `webhook_url` at submission time; server POSTs the completed transcript to the webhook when done

**Status lifecycle:** `queued` -> `processing` -> `completed` | `error`

**Key design properties:**
- Results are persisted server-side indefinitely (retrievable by `transcript_id` at any time)
- Client connection is fully decoupled from processing -- disconnection is irrelevant
- Client can poll, use webhooks, or both
- Failed transcriptions are recorded with error details, not silently lost

### Deepgram Architecture

Deepgram offers two modes:

1. **Synchronous:** `POST /v1/listen` -- blocks until transcription completes, returns result. Simple but vulnerable to HTTP timeout.
2. **Callback (async):** `POST /v1/listen?callback=URL` -- returns `request_id` immediately, POSTs result to callback URL when done. Retries callback delivery up to 10 times with 30-second delays.

**Key insight:** Even Deepgram's "synchronous" mode persists results internally -- the callback mode proves results exist independently of the client connection.

### OpenAI Whisper API

Uses synchronous HTTP: `POST /v1/audio/transcriptions` blocks until done. Maximum file size 25MB, timeout ~10 minutes. No async job model. This is the simplest approach but only works because OpenAI limits file size to keep processing time bounded.

### Common Pattern Across All Services

Every production transcription service that handles long audio uses the same core pattern:

```
Client                    Server                    Storage
  |                         |                         |
  |--- POST /transcribe --->|                         |
  |<-- 202 { job_id } -----|                         |
  |                         |--- process audio ------>|
  |                         |--- store result ------->|
  |                         |<-- result stored -------|
  |--- GET /job/{id} ------>|                         |
  |<-- { status, result } --|                         |
```

The WebSocket connection, if used at all, is a *notification channel* for progress -- never the sole delivery mechanism for results.

---

## 3. Task Queue Patterns (Celery / Dramatiq / Huey)

### Celery + Redis (Heavy-Weight)

**Architecture:** Celery workers consume tasks from a Redis/RabbitMQ broker. Results are stored in a configurable "result backend" (Redis, database, filesystem). FastAPI submits tasks and returns task IDs; clients poll for results.

**Durability guarantees:**
- Redis broker: Messages survive Redis restarts only if AOF persistence is enabled
- RabbitMQ broker: Messages are durable by default (written to disk)
- Result backend: Configurable TTL (default 24h in Redis)
- `task.get()` or `AsyncResult(task_id).state` for polling

**Overkill for TranscriptionSuite because:** Single server, single GPU, one transcription job at a time. Celery adds Redis dependency, worker process management, serialization overhead, and significant operational complexity.

### Dramatiq (Medium-Weight)

**Architecture:** Similar to Celery but cleaner API, fewer footguns. Uses Redis or RabbitMQ as broker. Built-in result storage, retries, rate limiting.

**Same problem as Celery:** Requires external broker (Redis/RabbitMQ).

### Huey (Light-Weight) -- Most Relevant

**Architecture:** Minimal task queue with built-in support for Redis, SQLite, filesystem, or in-memory storage. Single consumer process model. Clean decorator-based API.

**SQLite backend:** Huey can use SQLite as both broker and result store -- no external dependencies. This is directly relevant to TranscriptionSuite.

```python
from huey import SqliteHuey

huey = SqliteHuey(filename='/data/jobs.db')

@huey.task()
def transcribe_audio(file_path, language=None):
    # ... GPU transcription work ...
    return {"text": result.text, "words": result.words}

# Submit:
result_handle = transcribe_audio(file_path)

# Poll:
result_handle.get(blocking=False)  # Returns None if not ready
```

**Key features:**
- Task result storage with configurable TTL
- Automatic retries with delay
- Task locking (prevent duplicate execution)
- SQLite storage avoids adding Redis dependency

### FastAPI BackgroundTasks (Ultra-Light, Current Adjacent Pattern)

**Architecture:** FastAPI's built-in `BackgroundTasks` runs work in the same process after returning the HTTP response. No external dependencies.

**Limitation:** No durability. If the process crashes, the task and its result are lost. No built-in result storage or polling.

**Enhancement pattern:** Combine with a database job table for persistence:

```python
@router.post("/transcribe", status_code=202)
async def start_transcription(file: UploadFile, background_tasks: BackgroundTasks):
    job_id = create_job_record(status="queued")  # Write to SQLite
    background_tasks.add_task(run_transcription, job_id, file_path)
    return {"job_id": job_id}

@router.get("/transcribe/{job_id}")
async def get_result(job_id: str):
    return get_job_record(job_id)  # Read from SQLite
```

### The "SQLite Job Store" Pattern (No External Dependencies)

A lightweight pattern seen across multiple projects that avoids external task queues entirely:

```sql
CREATE TABLE transcription_jobs (
    id TEXT PRIMARY KEY,           -- UUID
    status TEXT DEFAULT 'pending', -- pending -> processing -> completed | failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    client_name TEXT,
    audio_path TEXT,               -- Path to saved audio file
    config_json TEXT,              -- Language, translation settings, etc.
    result_json TEXT,              -- Full transcription result (NULL until completed)
    error_message TEXT,            -- Error details (NULL unless failed)
    progress_current INTEGER,
    progress_total INTEGER
);

CREATE INDEX idx_jobs_status ON transcription_jobs(status, created_at);
```

**Worker pattern:**
1. `BEGIN IMMEDIATE TRANSACTION` (avoids SQLite deadlock -- critical for WAL mode)
2. `SELECT` oldest pending job
3. `UPDATE` status to `processing`
4. `COMMIT`
5. Process (GPU transcription)
6. `UPDATE` status to `completed`, store `result_json`

**Why this works for TranscriptionSuite:**
- Already has SQLite with WAL mode configured
- Already uses `busy_timeout=5000`
- Single-GPU, single-job-at-a-time (the `TranscriptionJobTracker` already enforces this)
- No new dependencies needed

---

## 4. SQLite WAL + Crash Recovery Patterns

### Current TranscriptionSuite Database Configuration

The project already has solid SQLite configuration:
- `PRAGMA journal_mode=WAL` -- enabled at init
- `PRAGMA synchronous=NORMAL` -- good balance for WAL (fsync on checkpoint, not every commit)
- `PRAGMA busy_timeout=5000` -- 5s retry on lock contention
- `PRAGMA foreign_keys=ON`
- Alembic migrations for schema management
- Built-in backup system using SQLite's backup() API

### WAL Mode Durability Guarantees

**What WAL guarantees:**
- Committed transactions survive process crashes (the WAL file is replayed on next open)
- Readers never block writers, writers never block readers
- `PRAGMA synchronous=NORMAL` in WAL mode: data survives process crashes but theoretically could lose the last transaction on a power failure (OS-level crash). `FULL` mode survives power failures but is ~2x slower.

**What WAL does NOT guarantee:**
- Data in uncommitted transactions is lost on crash
- In-memory state (like `TranscriptionJobTracker._result`) is lost on process restart

### SQLite as a Durability Layer

**Pattern: Write-Before-Deliver**

The key insight is that `TranscriptionJobTracker` currently stores results only in `self._result` (in-memory dict). If the process crashes or the WebSocket disconnects at the wrong moment, the result is lost.

The fix is conceptually simple: write the result to SQLite *before* attempting WebSocket delivery.

```python
# Current (vulnerable):
result = engine.transcribe_file(...)      # GPU work
await self.send_message("final", result)  # WebSocket delivery (may fail)
# Result is GONE if send_message fails

# Fixed (durable):
result = engine.transcribe_file(...)              # GPU work
save_job_result(job_id, result)                   # SQLite write (durable)
await self.send_message("final", result)          # WebSocket delivery (best effort)
# Result is SAFE in SQLite regardless of WebSocket outcome
```

**Pattern: SAVEPOINT for Partial Progress**

For very long transcriptions (chunked processing), SQLite SAVEPOINTs allow checkpointing partial progress within a transaction:

```sql
BEGIN;
SAVEPOINT chunk_1;
INSERT INTO partial_results VALUES (...);  -- First 5 minutes
RELEASE SAVEPOINT chunk_1;

SAVEPOINT chunk_2;
INSERT INTO partial_results VALUES (...);  -- Next 5 minutes
RELEASE SAVEPOINT chunk_2;
-- If crash occurs here, chunk_1 and chunk_2 are committed
COMMIT;
```

**Relevance:** TranscriptionSuite backends already chunk long audio (20-minute chunks for NeMo, configurable for Whisper). Each chunk's result could be checkpointed to SQLite, making the transcription resumable after crashes.

### SQLite-Specific Gotchas for Job Tables

1. **Use `BEGIN IMMEDIATE`** for job claim transactions (prevents deadlock when multiple threads compete)
2. **Separate database file** for jobs vs. notebook data (avoids lock contention between job polling and notebook queries). Jason Gorman's pattern uses a separate `jobs.db` file.
3. **Index on `(status, created_at)`** for efficient job polling
4. **JSON1 extension** for storing structured results -- SQLite's `json()` and `json_extract()` functions work with TEXT columns storing JSON

---

## 5. Synthesis: Recommended Architecture Patterns for TranscriptionSuite

### Pattern A: "Persist-Before-Deliver" (Minimal Change)

**Effort:** Low
**Concept:** Add a `transcription_results` table (or extend the existing job tracker). Write the transcription result to SQLite immediately after GPU processing completes, before attempting WebSocket delivery. Add a `GET /api/transcription/result/{job_id}` endpoint for clients to retrieve results if WebSocket delivery failed.

**What changes:**
- New SQLite table for job results (via Alembic migration)
- `TranscriptionJobTracker.end_job()` writes result to SQLite
- New HTTP endpoint to fetch results by job_id
- Client reconnection logic to poll for result if WebSocket died mid-transcription

### Pattern B: "Async Job Model" (Medium Change)

**Effort:** Medium
**Concept:** Shift from "WebSocket-centric" to "job-centric" architecture, matching the AssemblyAI / Deepgram pattern. Audio is saved to disk, a job record is created in SQLite, processing happens in a background thread, results are stored in SQLite. WebSocket becomes a notification/progress channel only.

**What changes:**
- New `transcription_jobs` table with full lifecycle
- Audio saved to temp file *before* processing starts (already partially done)
- Job processing decoupled from WebSocket session lifetime
- Progress updates still sent via WebSocket when connected
- Result always retrievable via `GET /api/transcription/jobs/{id}`
- Client can survive disconnection and pick up result on reconnect

### Pattern C: "Checkpoint + Resume" (Higher Effort, Maximum Durability)

**Effort:** Higher
**Concept:** Chunk-level checkpointing. Each chunk's partial result is committed to SQLite as it completes. If the server crashes mid-transcription, it can resume from the last completed chunk rather than restarting from scratch.

**What changes:**
- Everything in Pattern B, plus:
- `transcription_chunks` table for partial results
- Modified transcription loop to checkpoint after each chunk
- Resume logic that loads partial results and skips completed chunks
- Particularly valuable for NeMo backends with 20-minute chunking on long audio

### Key Libraries / Tools Referenced

| Tool | Purpose | Dependency Impact |
|------|---------|-------------------|
| SQLite (existing) | Job store, result persistence | None (already in use) |
| Huey + SqliteHuey | Formal task queue with SQLite backend | Light (pure Python) |
| FastAPI BackgroundTasks | Background processing (already available) | None |
| Alembic (existing) | Schema migrations for new tables | None (already in use) |

### What NOT to Adopt

- **Celery + Redis:** Overkill for single-server, single-GPU. Adds operational complexity and a Redis dependency with no corresponding benefit.
- **Full CRDT / OT replication:** Designed for collaborative editing with concurrent writers. TranscriptionSuite has one writer (the server) and one reader (the client).
- **External message brokers (RabbitMQ, Kafka):** Same rationale as Redis -- unnecessary for single-server architecture.

---

## Sources

- WebSocket.org: "Best Practices for Production Applications" (2026-03-13)
- WebSocket.org: "Reconnection: State Sync and Recovery Guide" (2026-03-13)
- Zylos Research: "WebSocket Reliability Patterns for Multi-Agent Systems" (2026-02-23)
- OneUptime: "How to Implement Reconnection Logic for WebSockets" (2026-01-27)
- AssemblyAI API Documentation: Transcript Status, Webhooks
- Deepgram API Documentation: STT Callback, Pre-Recorded Audio
- Jason Gorman: "A SQLite Background Job System" (2024-07-06)
- AWS Prescriptive Guidance: "Transactional Outbox Pattern"
- Zylos Research: "SQLite WAL Mode: Patterns and Pitfalls for AI Agent Systems" (2026-02-20)
- TheLinuxCode: "SQLite Transactions: Autocommit, WAL, SAVEPOINT, Production Patterns" (2026-02-08)
- MarkAICode: "Handling Long-Running AI Jobs with Redis and Celery" (2026-03-02)
- Mujtaba Almas: "Background Tasks & Workers: Celery vs. Dramatiq vs. Huey" (2025-03-15)
- Huey documentation: https://huey.readthedocs.io/ (SQLite storage backend)
- DEV Community: "Designing Asynchronous APIs with Pending, Processing, Done Workflow" (2026-03-12)
- NVIDIA NeMo Curator: "Resumable Processing: Infrastructure References"
