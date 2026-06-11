# TranscriptionSuite — Data Models (Server)

> Generated: 2026-06-11 | v1.3.6 | Engine: SQLite + FTS5 (async via aiosqlite + SQLAlchemy; raw `sqlite3` for CRUD)

## Database Location

- **Docker:** `/data/database/transcription_suite.db`
- **Local dev:** `<DATA_DIR>/database/transcription_suite.db`

Schema ownership: Alembic migrations `001`–`017` own the schema. `database.py` holds connection
pragmas, runtime CRUD, and a `_assert_schema_sanity()` contract that fails startup hard if a
required table/column is missing.

## Schema Overview

The current schema (after migration 017) has **9 base tables** + **1 FTS5 virtual table** (`words_fts`,
with its SQLite-managed shadow tables) + **3 FTS sync triggers**.

| Table | Kind | Purpose |
|-------|------|---------|
| `recordings` | base | Central entity — one row per audio note / imported file |
| `segments` | base | Speaker turns / time blocks within a recording |
| `words` | base | Word-level timestamps (FTS source) |
| `words_fts` | FTS5 virtual | Full-text index over `words.word` |
| `conversations` | base | LLM chat sessions per recording |
| `messages` | base | Chat messages within a conversation |
| `transcription_jobs` | base | Durability ledger — one row per WS/HTTP job (TEXT UUID PK) |
| `profiles` | base | Transcription/recording profiles (Issue #104) |
| `recording_diarization_review` | base | Diarization-review lifecycle state (1:1 with recording) |
| `recording_speaker_aliases` | base | Speaker label → display name (1:N with recording) |
| `webhook_deliveries` | base | Per-attempt outgoing-webhook delivery ledger (1:N with recording) |

> **Corrections vs. earlier docs:** the FTS table is **`words_fts`** (not `recordings_fts`); there is
> **no `chat_history` table** — LLM history lives in `conversations` + `messages`.

## Core Tables

### `recordings` — Audio Notebook Entries

The central entity. Many columns were bolted on by later migrations (cited).

| Column | Type | Constraints | Purpose | Migr. |
|--------|------|------------|---------|-------|
| id | INTEGER | PK, autoincrement | Recording ID | 001 |
| filename | TEXT | NOT NULL | Audio file name | 001 |
| filepath | TEXT | NOT NULL, UNIQUE | Absolute path to stored audio (MP3) | 001 |
| title | TEXT | | Display title (defaults to filename) | 001 |
| duration_seconds | REAL | NOT NULL | Audio duration | 001 |
| recorded_at | TIMESTAMP | NOT NULL | When recording was made | 001 |
| imported_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | When ingested into DB | 001 |
| word_count | INTEGER | DEFAULT 0 | Cached count of `words` rows | 001 |
| has_diarization | INTEGER | DEFAULT 0 | Bool: speaker turns present | 001 |
| summary | TEXT | | AI-generated summary | 001 |
| summary_model | TEXT | | Model id that produced the summary | 003 |
| transcription_backend | TEXT | | Normalized backend family (whisper/parakeet/canary/vibevoice_asr) | 005 |
| audio_hash | TEXT | idx | SHA-256 of raw upload bytes (dedup) | 012 |
| normalized_audio_hash | TEXT | idx | SHA-256 of normalized 16 kHz mono int16 PCM (format-agnostic dedup) | 013 |
| auto_summary_status | TEXT | partial idx | Auto-summary lifecycle state | 015 |
| auto_summary_error | TEXT | | Last auto-summary error | 015 |
| auto_summary_attempts | INTEGER | NOT NULL DEFAULT 0 | Auto-summary retry count | 015 |
| auto_summary_completed_at | TIMESTAMP | | Auto-summary success time | 015 |
| auto_export_status | TEXT | partial idx | Auto-export lifecycle state | 015 |
| auto_export_error | TEXT | | Last auto-export error | 015 |
| auto_export_attempts | INTEGER | NOT NULL DEFAULT 0 | Auto-export retry count | 015 |
| auto_export_path | TEXT | | Path written by auto-export | 015 |
| auto_export_completed_at | TIMESTAMP | | Auto-export success time | 015 |
| auto_action_profile_snapshot | TEXT | | Frozen profile JSON used at auto-action time | 015 |
| transcript_corrected | TEXT | | Non-destructive hand-corrected/flattened transcript; NULL = use original segments | 017 |

Indexes: `idx_recordings_date(recorded_at)`, `idx_recordings_audio_hash`,
`idx_recordings_normalized_audio_hash`, partial `idx_recordings_auto_summary_status`,
partial `idx_recordings_auto_export_status`.

> Speaker aliases, diarization-review state, and webhook deliveries are **separate tables**.
> Auto-action status and `transcript_corrected` are **columns on `recordings`** (1:1 by design).

### `segments` — Transcription Segments

| Column | Type | Constraints | Purpose |
|--------|------|------------|---------|
| id | INTEGER | PK, autoincrement | Segment ID |
| recording_id | INTEGER | NOT NULL, FK → recordings.id ON DELETE CASCADE | Parent recording |
| segment_index | INTEGER | NOT NULL | Order within recording |
| speaker | TEXT | | Raw diarization label (e.g. `SPEAKER_00`) |
| text | TEXT | NOT NULL | Segment text |
| start_time | REAL | NOT NULL | Start (seconds) |
| end_time | REAL | NOT NULL | End (seconds) |

### `words` — Word-Level Timestamps

| Column | Type | Constraints | Purpose |
|--------|------|------------|---------|
| id | INTEGER | PK, autoincrement | Word ID (FTS rowid) |
| recording_id | INTEGER | NOT NULL, FK → recordings.id ON DELETE CASCADE | Parent recording |
| segment_id | INTEGER | NOT NULL, FK → segments.id ON DELETE CASCADE | Parent segment |
| word_index | INTEGER | NOT NULL | Order within segment |
| word | TEXT | NOT NULL | Token text |
| start_time | REAL | NOT NULL | Word start (seconds) |
| end_time | REAL | NOT NULL | Word end (seconds) |
| confidence | REAL | | ASR confidence (0.0–1.0) |

### `words_fts` — Full-Text Search Index

FTS5 external-content virtual table: `fts5(word, content='words', content_rowid='id', tokenize='unicode61')`.
Kept in sync by triggers `words_ai` (after insert), `words_ad` (after delete), `words_au` (after update).

### `conversations` / `messages` — LLM Chat

`conversations` (one per recording chat session): `id`, `recording_id` (FK CASCADE), `title`,
`created_at`, `updated_at`, `response_id` (LM Studio stateful chat, migr. 002), `model`
(per-conversation override, migr. 007).

`messages` (chat history): `id`, `conversation_id` (FK CASCADE), `role`
(CHECK in `user`/`assistant`/`system`), `content`, `created_at`, `model` (migr. 003), `tokens_used`.

### `transcription_jobs` — Durability Ledger

Created by migration 006. Adapted from Scriberr. **`id` is a TEXT job UUID**, not an integer.

| Column | Type | Constraints | Purpose | Migr. |
|--------|------|------------|---------|-------|
| id | TEXT | PK | Job UUID | 006 |
| status | TEXT | NOT NULL DEFAULT 'processing' | `processing` → `completed`/`failed` | 006 |
| source | TEXT | NOT NULL | Origin (websocket / audio / import) | 006 |
| client_name | TEXT | | Client identifier (undelivered redelivery) | 006 |
| language | TEXT | | Requested language | 006 |
| task | TEXT | DEFAULT 'transcribe' | transcribe / translate | 006 |
| translation_target | TEXT | | Translation target language | 006 |
| audio_path | TEXT | | Preserved audio path (retry / cleanup) | 006 |
| result_text | TEXT | | Plain-text result | 006 |
| result_json | TEXT | | Full structured result (segments/words) | 006 |
| result_language | TEXT | | Detected language | 006 |
| duration_seconds | REAL | | Audio duration | 006 |
| error_message | TEXT | | Failure detail | 006 |
| delivered | INTEGER | NOT NULL DEFAULT 0 | 1 after successful client delivery | 006 |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | Job start | 006 |
| completed_at | TIMESTAMP | | Completion (ISO format) | 006 |
| job_profile_snapshot | TEXT | | Frozen profile JSON at job start | 009 |
| snapshot_schema_version | TEXT | | Profile schema_version at start | 009 |
| audio_hash | TEXT | idx | SHA-256 raw upload bytes (dedup) | 011 |
| normalized_audio_hash | TEXT | idx | SHA-256 normalized PCM (dedup) | 013 |

> **Timestamp-format gotcha:** `created_at` uses SQLite `CURRENT_TIMESTAMP` (`"YYYY-MM-DD HH:MM:SS"`,
> space-separated); `completed_at` is written via `datetime.isoformat()` (`"T"`-separated). Cleanup/orphan
> queries must match the respective format for correct lexicographic comparison.

## Issue #104 Tables

### `profiles` — Transcription/Recording Profiles (migr. 008)

| Column | Type | Constraints | Purpose |
|--------|------|------------|---------|
| id | INTEGER | PK, autoincrement | Profile ID |
| name | TEXT | NOT NULL | Profile name |
| description | TEXT | | Free-text description |
| schema_version | TEXT | NOT NULL | Versioned schema (only `"1.0"` supported) |
| public_fields_json | TEXT | NOT NULL | Non-sensitive settings (template, destination, toggles, model, prompt, format) |
| private_field_refs_json | TEXT | | **Keychain reference IDs only** — never plaintext secrets (FR11) |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | Created |
| updated_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | Last write (last-write-wins) |

Profiles are **snapshotted** (frozen JSON, no live FK) into `transcription_jobs.job_profile_snapshot`
(009) and `recordings.auto_action_profile_snapshot` (015), so concurrent profile edits never affect
in-flight jobs.

### `recording_diarization_review` — Review Lifecycle (migr. 010, 1:1)

`recording_id` (PK, FK CASCADE), `status` (CHECK in `pending`/`in_review`/`completed`/`released`),
`reviewed_turns_json`, `created_at`, `updated_at`. Index `idx_diarization_review_status` powers the
persistent-banner query. Transition legality is enforced by the ADR-009 lifecycle state machine in
`core/diarization_review_lifecycle.py`, not by the DB.

### `recording_speaker_aliases` — Speaker Aliases (migr. 014, 1:N)

`id`, `recording_id` (FK CASCADE), `speaker_id` (raw label, e.g. `SPEAKER_00`), `alias_name`
(display name, stored **verbatim** — no normalize/truncate, R-EL3), `created_at`, `updated_at`,
**UNIQUE(recording_id, speaker_id)**. Cross-recording uniqueness intentionally not enforced.

### `webhook_deliveries` — Outgoing-Webhook Ledger (migr. 016, 1:N)

| Column | Type | Constraints | Purpose |
|--------|------|------------|---------|
| id | INTEGER | PK, autoincrement | Delivery-attempt ID |
| recording_id | INTEGER | NOT NULL, FK → recordings.id ON DELETE CASCADE | Recording whose event is delivered |
| profile_id | INTEGER | FK → profiles.id **ON DELETE SET NULL** | Profile config (kept queryable after delete) |
| status | TEXT | NOT NULL, CHECK | `pending`/`in_flight`/`success`/`failed`/`manual_intervention_required` |
| attempt_count | INTEGER | NOT NULL DEFAULT 0 | Number of attempts |
| last_error | TEXT | | Last failure reason |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | Row creation (retention age) |
| last_attempted_at | TIMESTAMP | | Last HTTP attempt |
| payload_json | TEXT | NOT NULL | Frozen POST body (no-drift across retries) |

Indexes: partial `idx_webhook_deliveries_status` (worker drain over `pending`/`in_flight`),
`idx_webhook_deliveries_recording`.

## Entity Relationships

```
recordings (1) ──< segments (N) ──< words (N)        [FK CASCADE]
words.word ──ext-content──> words_fts                 [synced by triggers ai/ad/au]
recordings (1) ──< conversations (N) ──< messages (N) [FK CASCADE]
recordings (1) ──1:1── recording_diarization_review   [FK CASCADE]
recordings (1) ──< recording_speaker_aliases (N)      [FK CASCADE, UNIQUE(recording_id, speaker_id)]
recordings (1) ──< webhook_deliveries (N)             [FK CASCADE]
profiles   (1) ──< webhook_deliveries (N)             [FK SET NULL]
recordings ⋯⋯ transcription_jobs   (NO FK — separate ledgers; jobs keyed by TEXT UUID)
profiles   ⋯⋯ snapshots into transcription_jobs + recordings (frozen JSON, no FK)
```

## Migrations

Located in `server/backend/database/migrations/versions/`. Run automatically on startup via
`run_migrations()` → Alembic `upgrade head`. **Forward-only from 008 onward** (`downgrade()` raises).

| Ver | File | Change |
|-----|------|--------|
| 001 | `001_initial_schema.py` | recordings, segments, words, words_fts (+3 triggers), conversations, messages |
| 002 | `002_add_response_id.py` | `conversations.response_id` (LM Studio stateful chat) |
| 003 | `003_add_message_model_and_summary_model.py` | `recordings.summary_model` + `messages.model` |
| 004 | `004_schema_sanity_and_segment_backfill.py` | Legacy compat; backfill empty `segments.text` from words |
| 005 | `005_add_recordings_transcription_backend.py` | `recordings.transcription_backend` |
| 006 | `006_add_transcription_jobs.py` | `transcription_jobs` table (durability Wave 1) |
| 007 | `007_add_conversation_model.py` | `conversations.model` (per-conversation override) |
| 008 | `008_add_profiles_table.py` | `profiles` table |
| 009 | `009_add_profile_snapshot_to_transcription_jobs.py` | `job_profile_snapshot` + `snapshot_schema_version` |
| 010 | `010_add_recording_diarization_review.py` | `recording_diarization_review` table |
| 011 | `011_add_audio_hash_to_transcription_jobs.py` | `transcription_jobs.audio_hash` (raw-byte dedup) |
| 012 | `012_add_audio_hash_to_recordings.py` | `recordings.audio_hash` (closes notebook-upload dedup gap) |
| 013 | `013_add_normalized_audio_hash.py` | `normalized_audio_hash` on BOTH jobs + recordings (format-agnostic dedup) |
| 014 | `014_add_recording_speaker_aliases.py` | `recording_speaker_aliases` table |
| 015 | `015_add_recording_auto_action_status.py` | 10 auto-action columns on `recordings` + 2 partial indexes |
| 016 | `016_add_webhook_deliveries.py` | `webhook_deliveries` table |
| 017 | `017_add_recording_transcript_corrected.py` | `recordings.transcript_corrected` (in-place editing) |

## Repository Layer (`database/`)

| Module | Purpose |
|--------|---------|
| `database.py` | Connection mgmt + pragmas, schema bootstrap, recordings/segments/words/conversations/messages CRUD, FTS search, longform save, recordings-side dedup lookup |
| `job_repository.py` | `transcription_jobs` CRUD (durability). `create_job` → `save_result` → `mark_delivered`/`mark_failed`; `reset_for_retry`, `get_orphaned_jobs`, `get_jobs_for_cleanup`, `find_by_audio_hash` |
| `profile_repository.py` | `profiles` CRUD; `to_public_dict` strips private refs; `snapshot_profile_at_job_start` |
| `alias_repository.py` | `recording_speaker_aliases` CRUD; `replace_aliases` (full-replace upsert), `alias_map` |
| `diarization_review_repository.py` | `recording_diarization_review` CRUD; `update_status`/`update_reviewed_turns` |
| `auto_action_repository.py` | Auto-action columns on `recordings`; status enums, profile snapshot, `list_pending_auto_actions` |
| `webhook_deliveries_repository.py` | `webhook_deliveries` CRUD; worker state transitions, `requeue_*`, `count_consecutive_recent_failures`, `cleanup_older_than` |
| `webhook_cleanup.py` | `periodic_webhook_cleanup` — retention sweep of success/manual rows |
| `dedup_query.py` | `find_duplicates_anywhere` — merges job + recording hash matches into one list |
| `audio_cleanup.py` | `periodic_cleanup` — deletes audio files for completed+delivered+old jobs (durability Wave 2) |
| `backup.py` | `DatabaseBackupManager` — WAL-safe SQLite `.backup()`, rotate (keep 3), verify, restore |

## Durability System (3 Waves)

1. **Wave 1 — Job persistence:** `create_job()` → `save_result()` (persist) → deliver → `mark_delivered()`.
2. **Wave 2 — Audio preservation:** raw audio saved to `/data/recordings/{job_id}.wav` before transcription;
   `audio_cleanup.periodic_cleanup()` deletes only completed+delivered audio older than `audio_retention_days`.
3. **Wave 3 — Orphan recovery:** on startup, `recover_orphaned_jobs()` marks stale `processing` jobs as
   `failed`; periodic orphan sweep re-checks (guarded by `job_tracker.is_busy()`).

### Job Lifecycle

```
create_job()       save_result()      mark_delivered()
    │                  │                   │
    ▼                  ▼                   ▼
processing ───────► completed ───────► delivered
    │
    │ mark_failed()        reset_for_retry()  (preserves created_at + audio_path)
    ▼                      ▲
  failed ──────────────────┘
```

## Key Data Lifecycles

### Audio Dedup (raw + normalized hash, per-user scope)

Each upload row carries **two SHA-256 columns**: `audio_hash` (raw upload bytes) and
`normalized_audio_hash` (16 kHz mono int16 PCM rendered via ffmpeg — catches same content in different
encodings, e.g. MP3 vs WAV). Both exist on `transcription_jobs` (written by `/api/transcribe/audio` +
`/import`) and `recordings` (written by `/api/notebook/transcribe/upload`). The dedup-check endpoint
(`POST /api/transcribe/import/dedup-check`) runs `dedup_query.find_duplicates_anywhere`, which queries
both tables and ORs both columns. NULL columns never match. Local-DB-only; cross-user dedup is a non-goal.

### Webhook Delivery (`webhook_deliveries`)

Producer `create_pending(recording_id, profile_id, payload)` freezes the POST body → worker
`mark_in_flight` (committed **before** HTTP fire) → `mark_success` (2xx) / `mark_failed` (else, increments
`attempt_count`). One 30 s auto-retry (`requeue_failed_row`); second consecutive failure →
`manual_intervention_required` (terminal, surfaced as dashboard badge). Shutdown reverts `in_flight` →
`pending`. Retention deletes only success/manual rows older than `retention_days`.

### Auto-Action Status (columns on `recordings`)

Coordinator persists `auto_action_profile_snapshot` → `set_auto_action_status(..., "in_progress")` →
per-attempt `increment_auto_action_attempts` → terminal `success` (stamps `*_completed_at`) or
`deferred`/`retry_pending`/`failed`/`held`/`manual_intervention_required`. Sweeper re-drives
`deferred`/`retry_pending` rows. Status strings validated in the repo (no DB CHECK).

### Diarization Review (`recording_diarization_review`)

`create_review(status="pending")` → user edits → `update_status("in_review")` +
`update_reviewed_turns(turns_json)` → `completed` → `released` (lifts the auto-summary HOLD). The
status index powers the persistent review banner.

### `transcript_corrected` (in-place edit / find-replace)

Default source of truth is the rich `segments`+`words` view (`transcript_corrected IS NULL`). On save,
`update_recording_corrected_transcript(recording_id, transcript)` stores the flattened corrected text;
the original `segments`/`words` are **never touched** (non-destructive, NFR21). Revert = store NULL.

## Connection Settings

- Timeout: 30 s (lock wait); busy timeout: 5 s (SQLITE_BUSY retry)
- `check_same_thread=False` (multi-thread); foreign keys enabled; WAL mode + `synchronous=NORMAL`
