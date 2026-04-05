# TranscriptionSuite — Data Models (Server)

> Generated: 2026-04-05 | Engine: SQLite + FTS5 (async via aiosqlite + SQLAlchemy)

## Database Location

- **Docker:** `/data/database/transcription_suite.db`
- **Local dev:** `<DATA_DIR>/database/transcription_suite.db`

## Schema

### `recordings` — Audio Notebook Entries

| Column | Type | Constraints | Purpose |
|--------|------|------------|---------|
| id | INTEGER | PK, autoincrement | Unique recording ID |
| filename | TEXT | NOT NULL | Original filename |
| filepath | TEXT | | Path to stored audio file |
| title | TEXT | | User-assigned title |
| duration_seconds | REAL | | Audio duration |
| recorded_at | TEXT | | Recording timestamp (ISO 8601) |
| imported_at | TEXT | DEFAULT CURRENT_TIMESTAMP | Import timestamp |
| word_count | INTEGER | DEFAULT 0 | Total word count |
| has_diarization | INTEGER | DEFAULT 0 | Has speaker labels (boolean) |
| summary | TEXT | | AI-generated or user summary |
| summary_model | TEXT | | LLM model used for summary |
| transcription_backend | TEXT | | STT backend used (e.g., "whisperx", "parakeet") |

### `segments` — Transcription Segments

| Column | Type | Constraints | Purpose |
|--------|------|------------|---------|
| id | INTEGER | PK, autoincrement | Unique segment ID |
| recording_id | INTEGER | FK → recordings.id | Parent recording |
| text | TEXT | NOT NULL | Segment text content |
| start_time | REAL | | Start timestamp (seconds) |
| end_time | REAL | | End timestamp (seconds) |
| speaker | TEXT | | Speaker label (e.g., "SPEAKER_00") |

### `words` — Word-Level Timestamps

| Column | Type | Constraints | Purpose |
|--------|------|------------|---------|
| id | INTEGER | PK, autoincrement | Unique word ID |
| segment_id | INTEGER | FK → segments.id | Parent segment |
| word | TEXT | NOT NULL | Single word |
| start_time | REAL | | Word start (seconds) |
| end_time | REAL | | Word end (seconds) |
| confidence | REAL | | Recognition confidence (0.0-1.0) |

### `recordings_fts` — Full-Text Search Index

FTS5 virtual table for fast text search across recording titles and segment text.

### `transcription_jobs` — Durability Layer (Wave 1)

| Column | Type | Constraints | Purpose |
|--------|------|------------|---------|
| id | TEXT | PK | Job UUID |
| status | TEXT | NOT NULL | `processing`, `completed`, `failed` |
| source | TEXT | | Job source (e.g., "websocket", "upload", "import") |
| client_name | TEXT | | Client identifier |
| language | TEXT | | Source language code |
| task | TEXT | | Task type ("transcribe" or "translate") |
| translation_target | TEXT | | Translation target language |
| audio_path | TEXT | | Path to preserved audio (Wave 2) |
| result_text | TEXT | | Plain text result |
| result_json | TEXT | | Full JSON result (segments, words, etc.) |
| error_message | TEXT | | Error details (if failed) |
| created_at | TEXT | DEFAULT CURRENT_TIMESTAMP | Job creation time |
| completed_at | TEXT | | Completion timestamp |
| delivered | INTEGER | DEFAULT 0 | Client received result (boolean) |

### `chat_history` — LLM Conversations

Stores LLM chat sessions associated with recordings for summarization and Q&A.

## Entity Relationships

```
recordings (1) ──────► (N) segments (1) ──────► (N) words
    │
    └─── transcription_jobs (linked by source context, not FK)
    │
    └─── chat_history (linked by recording_id)
    │
    └─── recordings_fts (FTS5 shadow table)
```

## Migrations

Located in `server/backend/database/migrations/versions/`:

| Version | File | Changes |
|---------|------|---------|
| 001 | `001_initial_schema.py` | Base tables: recordings, segments, words, FTS5 index |
| 002 | `002_add_response_id.py` | Add response_id column |
| 003 | `003_add_message_model_and_summary_model.py` | Add summary_model to recordings |
| 004 | `004_schema_sanity_and_segment_backfill.py` | Schema cleanup, backfill segment data |
| 005 | `005_add_recordings_transcription_backend.py` | Add transcription_backend column |
| 006 | `006_add_transcription_jobs.py` | Add transcription_jobs table (durability) |

Migrations run automatically on server startup via Alembic.

## Durability System

### Job Lifecycle State Machine

```
create_job()        save_result()     mark_delivered()
    │                   │                  │
    ▼                   ▼                  ▼
┌──────────┐    ┌──────────────┐    ┌──────────────┐
│processing │───►│  completed   │───►│  delivered   │
└──────────┘    └──────────────┘    └──────────────┘
    │                                      
    │ mark_failed()                        
    ▼                                      
┌──────────┐    reset_for_retry()   ┌──────────┐
│  failed   │◄──────────────────────│  retry   │
└──────────┘                        └──────────┘
```

### Key Repository Functions (`database/job_repository.py`)

| Function | Purpose |
|----------|---------|
| `create_job()` | Insert new job before transcription starts |
| `save_result()` | Store result BEFORE delivering to client |
| `mark_delivered()` | Client confirmed receipt |
| `mark_failed()` | Transcription failed |
| `get_recent_undelivered()` | Client polls for missed results |
| `set_audio_path()` | Link to preserved audio file |
| `reset_for_retry()` | Re-queue failed job for another attempt |
| `get_orphaned_jobs()` | Find jobs stuck in "processing" after crash |
| `get_jobs_for_cleanup()` | Find old delivered jobs for audio cleanup |

### Audio Cleanup (`database/audio_cleanup.py`)

- Runs at startup, then on interval (default: 24 hours)
- Deletes completed+delivered recordings older than retention period (default: 7 days)
- Never deletes audio for failed or undelivered jobs

### Backup (`database/backup.py`)

- Automatic SQLite backups with configurable retention
- Location: `/data/database/backups/`
- Configurable: `backup.enabled`, `backup.max_age_hours`, `backup.max_backups`

## Connection Settings

- Timeout: 30 seconds (lock wait)
- Busy timeout: 5 seconds (SQLITE_BUSY retry)
- Multi-thread: `check_same_thread=False`
- Foreign keys: Enabled
- WAL mode: For concurrent read access
