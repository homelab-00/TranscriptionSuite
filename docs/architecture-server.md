# TranscriptionSuite — Server Architecture

> Generated: 2026-06-11 | v1.3.6 | Part: server | Type: backend | Python 3.13 / FastAPI

## Executive Summary

The server is a Python 3.13 FastAPI application that provides speech-to-text transcription via 10 interchangeable STT backends, speaker diarization, a full-text searchable audio notebook, and LLM-powered summarization. It runs in Docker with CUDA/Vulkan/Metal GPU acceleration and communicates with the Electron dashboard over REST and WebSocket.

## Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| Language | Python | 3.13.x | Strict version pin (NeMo/lhotse compat) |
| Framework | FastAPI | 0.135.1 | Async HTTP + WebSocket API |
| Server | uvicorn | 0.41.0 | ASGI server |
| Validation | Pydantic | 2.12.5 | Request/response schemas |
| Database | SQLAlchemy + aiosqlite | 2.0.48 / 0.22.1 | Async SQLite with FTS5 |
| Migrations | Alembic | 1.18.4 | Schema versioning (17 versions) |
| ML Framework | PyTorch | 2.8.0 | GPU inference (CUDA 12.9) |
| Diarization | pyannote.audio | 4.0.4 | Speaker identification |
| Audio | soundfile, scipy, ffmpeg-python | Various | Audio I/O, resampling, conversion |
| VAD | webrtcvad + silero-vad | 2.0.10 / 6.2.1 | Voice activity detection |
| Logging | structlog | 25.5.0 | Structured logging |
| Package Mgr | uv | 0.10.8 | Fast Python deps (NEVER pip) |

### Optional STT Backend Extras

| Extra | Dependencies | GPU Target |
|-------|-------------|------------|
| `whisper` | faster-whisper 1.2.1, ctranslate2, WhisperX 3.8.1 | CUDA |
| `nemo` | nemo_toolkit[asr] 2.7.0 | CUDA |
| `vibevoice_asr` | VibeVoice (git pin) | CUDA |
| `mlx` | mlx-audio, parakeet-mlx, canary-mlx, faster-whisper | Apple Silicon (Metal) |

MLX and CUDA extras are mutually exclusive (enforced by `[tool.uv] conflicts`).

## Architecture Pattern

**Layered service architecture** with three tiers:

1. **API Layer** (`api/routes/`) — HTTP/WS request handling, auth, validation
2. **Core Layer** (`core/`) — Business logic, model management, STT engines
3. **Data Layer** (`database/`) — SQLite persistence, durability, cleanup

## API Layer

### Route Structure

Routes are organized by domain, each defining an `APIRouter()` included in `main.py`:

| Route File | Prefix | Purpose |
|-----------|--------|---------|
| `health.py` | `/health`, `/ready`, `/api/status` | Health probes, server status |
| `auth.py` | `/api/auth` | Token-based authentication |
| `transcription.py` | `/api/transcribe` | File upload transcription, cancel, languages |
| `notebook.py` | `/api/notebook` | Audio notebook CRUD, calendar, backup, aliases, diarization-review, auto-actions |
| `profiles.py` | `/api/profiles` | Transcription/recording profile CRUD (Issue #104) |
| `search.py` | `/api/search` | Full-text search (FTS5) |
| `llm.py` | `/api/llm` | Local LLM summarization, chat, and conversation CRUD |
| `admin.py` | `/api/admin` | Config management, model loading, logs, webhook test |
| `openai_audio.py` | `/v1/audio` | OpenAI-compatible transcription endpoint |
| `websocket.py` | `/ws` | Longform recording transcription (WebSocket) |
| `live.py` | `/ws/live` | Real-time live transcription (WebSocket) |

### Middleware Stack

1. **CORSMiddleware** — Permissive CORS headers
2. **OriginValidationMiddleware** — Strict origin policy (TLS: same-origin + localhost + Electron; Local: localhost only)
3. **AuthenticationMiddleware** (TLS only) — Require Bearer token for all non-public routes

### Authentication Model

- **SHA-256 hashed tokens** (plaintext never stored, shown once at creation)
- Admin and regular user roles (admin tokens never expire, user tokens: 30 days)
- Token sources checked in order: `Authorization` header → `auth_token` cookie → query param (notebook audio/export only)
- WebSocket auth via first JSON message (not headers)

## Core Layer

### Model Manager (`core/model_manager.py`)

Central hub for all ML model lifecycle management:

- **Single model at a time** — only one STT model loaded in GPU memory
- **Lazy imports** — torch, faster-whisper, NeMo imported inside methods (not at module level)
- **Background NeMo import** — if NeMo model selected, pre-import thread during init
- **Feature detection** — reads `bootstrap-status.json` for installed backend availability
- **TranscriptionJobTracker** — thread-safe slot manager (one transcription at a time)

### STT Backend Subsystem (`core/stt/`)

**10 backends**, all implementing abstract `STTBackend` base class:

| Backend | Class | Model Pattern | Translation | Platform |
|---------|-------|--------------|-------------|----------|
| WhisperX | `WhisperXBackend` | `Systran/*` (default) | Yes | CUDA |
| Faster-Whisper | `FasterWhisperBackend` | Systran/* (fallback) | Yes | CUDA/CPU |
| Parakeet | `ParakeetBackend` | `nvidia/parakeet*` | No | CUDA |
| Canary | `CanaryBackend` | `nvidia/canary*` | Yes (24 EU langs) | CUDA |
| VibeVoice-ASR | `VibeVoiceASRBackend` | `*/VibeVoice-ASR*` | No | CUDA |
| whisper.cpp | `WhisperCppBackend` | `*.gguf`/`ggml-*.bin` | Yes | Vulkan sidecar |
| MLX Whisper | `MLXWhisperBackend` | `mlx-community/whisper*` | Yes | Apple Silicon |
| MLX Parakeet | `MLXParakeetBackend` | `mlx-community/parakeet*` | No | Apple Silicon |
| MLX Canary | `MLXCanaryBackend` | `*/canary*-mlx` | Yes | Apple Silicon |
| MLX VibeVoice | `MLXVibeVoiceBackend` | `mlx-community/vibevoice*` | No | Apple Silicon |

**Factory routing** (`factory.py`): `detect_backend_type(model_name)` matches patterns in priority order
(first match wins). The `whisper` default resolves at runtime to `WhisperXBackend` (if `whisperx` is
importable) or `FasterWhisperBackend` (fallback). Notes: `CanaryBackend` subclasses `ParakeetBackend`
(not `STTBackend` directly); the four MLX backends mix in `MLXThreadAffinityMixin` (`mlx_thread_pin.py`,
GH #134) to pin GPU ops to one owning thread; `MLXCanaryBackend.supports_translation()` is `False` (the
`canary-mlx` port is ASR-only). `whisper_backend.py` (`WhisperBackend`) is **legacy/orphaned** — defined
but not wired into the factory; `FasterWhisperBackend` superseded it.

### Live Engine (`core/live_engine.py`)

Orchestrates real-time transcription:
- Model swap sequence (unload main → load live → on stop: unload live → reload main)
- VAD-based speech segmentation
- Partial and final result streaming via WebSocket

### Diarization (`core/diarization_engine.py`)

PyAnnote 4.x speaker diarization pipeline:
- Parallel mode (keep main model loaded) vs sequential (unload to save VRAM)
- Configurable speaker count hints (min/max or auto-detect)
- Sortformer engine as alternative for Apple Silicon (no HF token needed)

### Audio Processing (`core/ffmpeg_utils.py`, `core/audio_utils.py`)

- FFmpeg backend: SoX resampler, dynamic range normalization, format conversion
- CUDA health check: Detect unrecoverable GPU state at startup
- GPU memory management: `clear_gpu_cache()` after each job
- Audio hashing: raw + normalized SHA-256 for dedup; multi-channel handling in `core/multitrack.py`

### Issue #104 Subsystems (Audio Notebook QoL)

A cluster of business-logic modules added for the Audio Notebook QoL pack:

| Subsystem | Modules | Purpose |
|-----------|---------|---------|
| **Profiles** | `database/profile_repository.py` | Transcription/recording profiles; public/private field separation; snapshotted into jobs |
| **Speaker aliases** | `core/alias_substitution.py`, `database/alias_repository.py` | Read-time speaker display-name substitution (never mutates stored segments) |
| **Diarization review** | `core/diarization_confidence.py`, `diarization_review_filter.py`, `diarization_review_lifecycle.py`, `database/diarization_review_repository.py` | Per-turn confidence + ADR-009 `pending→in_review→completed→released` lifecycle |
| **Auto-actions** | `core/auto_action_coordinator.py`, `auto_action_sweeper.py`, `auto_summary_engine.py`, `database/auto_action_repository.py` | Fire auto-summary/auto-export/webhook per profile; deferred-export sweeper; retry/escalation ladder |
| **Webhooks (durable)** | `core/webhook_payload.py`, `webhook_url_validation.py`, `services/webhook_worker.py`, `database/webhook_deliveries_repository.py`, `webhook_cleanup.py` | Persist-Before-Deliver outgoing `transcription.completed` webhooks with SSRF allowlist + retry |
| **Webhooks (legacy)** | `core/webhook.py` | Fire-and-forget `live_sentence`/`longform_complete` (no persistence) |
| **Misc** | `core/filename_template.py`, `plaintext_export.py`, `hf_token_guard.py`, `multitrack.py` | Export filename templating, FR9 plaintext export, non-ASCII HF-token purge (GH #125), multi-channel transcription |

## Data Layer

### Database Schema

**SQLite + FTS5** with 17 migration versions. Full column-level reference in
[data-models-server.md](./data-models-server.md).

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `recordings` | Audio notebook entries | id, filename, filepath, title, duration_seconds, recorded_at, has_diarization, summary, transcription_backend, audio_hash, normalized_audio_hash, auto_*_status, transcript_corrected |
| `segments` | Transcription segments | id, recording_id, segment_index, speaker, text, start_time, end_time |
| `words` | Word-level timestamps | id, recording_id, segment_id, word, start_time, end_time, confidence |
| `words_fts` | Full-text search index | FTS5 virtual table over `words.word` (synced by triggers) |
| `conversations` | LLM chat sessions | id, recording_id, title, response_id, model |
| `messages` | LLM chat history | id, conversation_id, role, content, model, tokens_used |
| `transcription_jobs` | Durability ledger (TEXT UUID PK) | id, status, source, client_name, audio_path, result_text, result_json, delivered, audio_hash, normalized_audio_hash, job_profile_snapshot |
| `profiles` | Transcription/recording profiles | id, name, schema_version, public_fields_json, private_field_refs_json |
| `recording_diarization_review` | Review lifecycle (1:1) | recording_id, status, reviewed_turns_json |
| `recording_speaker_aliases` | Speaker aliases (1:N) | id, recording_id, speaker_id, alias_name |
| `webhook_deliveries` | Outgoing-webhook ledger (1:N) | id, recording_id, profile_id, status, attempt_count, payload_json |

#### Audio dedup scope (FR4 / R-EL23)

Issue #104: audio dedup operates **per-user-library**. Each upload row now
carries TWO complementary SHA-256 columns:

- **`audio_hash`** (migrations 011 + 012) — SHA-256 of the raw upload bytes,
  streamed in 1 MiB chunks. Cheapest signal; catches "same file imported
  twice".
- **`normalized_audio_hash`** (migration 013) — SHA-256 of the file rendered
  through ffmpeg as 16 kHz mono int16 PCM. Catches "same content, different
  encoding" (e.g. MP3 vs WAV vs M4A of the same source). NULL on rows where
  ffmpeg failed at upload time — those rows fall back to raw-only dedup.

Both columns exist on `transcription_jobs` (written by `/api/transcribe/audio`
+ `/api/transcribe/import`) and `recordings` (written by
`/api/notebook/transcribe/upload`). The dedup-check endpoint
(`POST /api/transcribe/import/dedup-check`) runs
`dedup_query.find_duplicates_anywhere`, which queries both tables and OR's
both columns, returning a merged list discriminated by a `source` field
(`"transcription_job"` vs `"recording"`). A row that matches on both columns
naturally appears once (SQLite predicate semantics).

All queries hit only the local SQLite database — no outbound network call,
no shared registry. Cross-user dedup is an explicit non-goal.

### Durability System (3 Waves)

1. **Wave 1 — Job persistence**: `create_job()` → `save_result()` → deliver → `mark_delivered()`
2. **Wave 2 — Audio preservation**: Raw audio saved to `/data/recordings/{job_id}.wav` before transcription
3. **Wave 3 — Orphan recovery**: On startup, `recover_orphaned_jobs()` marks stale processing jobs as failed

### Cleanup

- `audio_cleanup.py`: Deletes completed+delivered recordings older than `audio_retention_days`
- `backup.py`: Automatic SQLite backups with configurable retention

## Configuration System

**Source priority:** User config (`~/.config/TranscriptionSuite/`) → Docker mount (`/user-config/`) → Container default → Repo default

**Environment overrides:** `MAIN_TRANSCRIBER_MODEL`, `LIVE_TRANSCRIBER_MODEL`, `DIARIZATION_MODEL`, `LOG_LEVEL`, `INSTALL_WHISPER`, `INSTALL_NEMO`, `INSTALL_VIBEVOICE_ASR`, `HF_TOKEN`, `WHISPERCPP_SERVER_URL`

**Key config sections:** `longform_recording`, `static_transcription`, `main_transcriber`, `parakeet`,
`sortformer`, `mlx`, `vibevoice_asr`, `live_transcriber`, `diarization`, `audio_processing`, `storage`,
`backup`, `local_llm` (OpenAI-compatible LLM — note: not `lm_studio`), `remote_server` (TLS), `logging`,
`webhook` (legacy global), `stt`, `durability`, `auto_actions`, `webhook_deliveries` (durable per-profile)

> Profiles themselves live in the DB (`profiles` table); per-profile auto-summary/auto-export/webhook
> settings are profile columns, gated globally by the `auto_actions` and `webhook_deliveries` toggles.

## Startup Sequence

1. Load config from YAML
2. Setup structured logging
3. Initialize database + run Alembic migrations
4. Recover orphaned jobs from previous crashes
5. Schedule background backup check + audio cleanup
6. Initialize token store (generate admin token on first run)
7. CUDA health probe (detect unrecoverable GPU state)
8. Create ModelManager (lazy import torch)
9. Preload main transcriber model
10. Schedule periodic orphan sweep (every 30 min) + deferred-export sweeper + webhook retention cleanup
11. Start the durable WebhookWorker singleton (re-fires `in_flight` deliveries from prior run)
12. Emit startup events to event stream

**Shutdown:** Cancel cleanup/sweeper tasks → stop WebhookWorker (revert `in_flight` → `pending`) →
drain WebSocket sessions (120s timeout) → cleanup models → exit

## Deployment

- **Docker**: Ubuntu 24.04 base, 8 compose variants (base, linux-host, desktop-vm, GPU, GPU-CDI, Vulkan, Vulkan-WSL2, Podman)
- **Bootstrap**: Python deps installed at first container start into `/runtime/.venv` (not baked into image)
- **Volumes**: `transcription-data` (database, audio), `huggingface-models` (model cache), `runtime-deps` (venv)
- **Health check**: `GET /health` every 30s, 600s start period for model downloads
- **TLS**: Optional Tailscale integration with cert bind-mounts
