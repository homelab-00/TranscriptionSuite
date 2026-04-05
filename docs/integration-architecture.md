# TranscriptionSuite — Integration Architecture

> Generated: 2026-04-05 | Multi-part: server (backend) + dashboard (desktop)

## Part Communication Overview

TranscriptionSuite is a client-server application where the **dashboard** (Electron desktop app) communicates with the **server** (FastAPI in Docker) over HTTP and WebSocket. The dashboard also manages the server's Docker container lifecycle directly.

```
┌─────────────────────────────────────────────────────────┐
│  Electron App (Dashboard)                                │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │  Renderer     │  │  Main Process │  │  Preload      │ │
│  │  (React)      │◄─┤  (Node.js)   │──┤  (IPC Bridge) │ │
│  │               │  │              │  │               │ │
│  │  Views        │  │  Docker Mgr  │  │  contextBridge│ │
│  │  Hooks        │  │  Tray Mgr    │  │               │ │
│  │  Services     │  │  Shortcuts   │  │               │ │
│  └──────┬────────┘  └──────┬───────┘  └───────────────┘ │
│         │                  │                             │
└─────────┼──────────────────┼─────────────────────────────┘
          │                  │
          │ REST/WebSocket   │ docker compose CLI
          │ (port 9786)      │ + fs.watch (startup events)
          ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│  Docker Container (Server)                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │  FastAPI      │  │  Core Engine  │  │  Database     │ │
│  │  REST + WS    │──┤  Model Mgr   │──┤  SQLite+FTS5  │ │
│  │  Middleware   │  │  STT Backends │  │  Job Repos    │ │
│  │  Auth         │  │  Diarization  │  │  Migrations   │ │
│  └──────┬────────┘  └──────┬───────┘  └───────────────┘ │
│         │                  │                             │
└─────────┼──────────────────┼─────────────────────────────┘
          │                  │
          ▼                  ▼
    ┌───────────┐     ┌───────────┐     ┌───────────┐
    │ HuggingFace│     │ GPU       │     │ LM Studio │
    │ Hub        │     │ CUDA/MPS  │     │ (optional)│
    └───────────┘     └───────────┘     └───────────┘
```

## Integration Points

### 1. REST API (Dashboard → Server)

**Protocol:** HTTP/HTTPS (port 9786)
**Client:** `dashboard/src/api/client.ts` (fetch-based)
**Auth:** Bearer token in `Authorization` header (TLS mode) or no auth (local mode)

| Category | Endpoints | Purpose |
|----------|-----------|---------|
| Health | `GET /health`, `/ready`, `/api/status` | Server health, readiness, detailed status |
| Auth | `POST /api/auth/login`, `GET/POST/DELETE /api/auth/tokens` | Token auth, token CRUD |
| Transcription | `POST /api/transcribe/audio`, `/quick`, `/cancel` | File upload transcription |
| Notebook | `GET/POST/PATCH/DELETE /api/notebook/recordings/*` | Recording CRUD, calendar, backup |
| Search | `GET /api/search`, `/search/words`, `/search/recordings` | Full-text search (FTS5) |
| LLM | `POST /api/llm/process`, `/summarize/{id}` | LM Studio integration |
| Admin | `GET/PATCH /api/admin/*`, `POST /api/admin/models/load` | Config, model management |
| OpenAI | `POST /v1/audio/transcriptions` | OpenAI-compatible API |

### 2. WebSocket — Longform Transcription (Dashboard → Server)

**Endpoint:** `ws(s)://host:9786/ws`
**Client:** `dashboard/src/services/websocket.ts`
**Auth:** Token sent as first JSON message (not header-based)

**Flow:**
```
Client                          Server
  │── WS Connect ──────────────►│
  │── {authenticate: token} ───►│
  │◄── {authenticated: true} ──│
  │── {start: {language, ...}} ►│
  │                              │
  │── PCM Int16 binary chunks ─►│  (loop: audio streaming)
  │                              │
  │── {stop: true} ───────────►│
  │                              │── STT transcribe()
  │                              │── save_result() to DB
  │◄── {result: segments} ─────│
  │── WS Close ────────────────►│
```

**Key detail:** Results are persisted to the database BEFORE delivery to the client (durability invariant).

### 3. WebSocket — Live Mode (Dashboard → Server)

**Endpoint:** `ws(s)://host:9786/ws/live`
**Client:** `dashboard/src/hooks/useLiveMode.ts` → `websocket.ts`

**Flow:**
```
Client                          Server
  │── WS Connect ──────────────►│
  │── {authenticate: token} ───►│
  │── {start: {language, ...}} ►│── Unload main model
  │                              │── Load live model
  │                              │
  │── PCM Int16 binary chunks ─►│  (continuous streaming)
  │                              │── VAD detects speech
  │◄── {type: "partial", ...} ─│  (interim results)
  │◄── {type: "sentence", ...} │  (final segments)
  │                              │
  │── {stop: true} ───────────►│── Unload live model
  │                              │── Reload main model
  │◄── {result: transcript} ───│
  │── WS Close ────────────────►│
```

**Key detail:** Model swap sequence — main model unloaded before live model loads to conserve GPU memory.

### 4. Docker Container Lifecycle (Dashboard → Docker CLI)

**Manager:** `dashboard/electron/dockerManager.ts`
**Protocol:** Child process execution of `docker compose` commands via Electron main process

**Operations:**
| Operation | Command Pattern | Triggered By |
|-----------|----------------|-------------|
| Start | `docker compose -f base.yml -f platform.yml [-f gpu.yml] up -d` | ServerView "Start" button |
| Stop | `docker compose ... down` | ServerView "Stop" button |
| Restart | `docker compose ... down && up -d` | ServerView "Restart" button |
| Update | `docker compose ... pull && down && up -d` | ServerView "Update" button |
| Logs | `docker compose ... logs -f --tail 200` | LogsView |
| Status | `docker ps --filter name=transcriptionsuite-container` | Periodic polling |

**Compose file selection** (by `containerRuntime.ts`):
- Linux: `docker-compose.yml` + `docker-compose.linux-host.yml` + GPU overlay
- macOS/Windows: `docker-compose.yml` + `docker-compose.desktop-vm.yml` + optional GPU
- Vulkan: `docker-compose.vulkan.yml` added when whisper.cpp model selected

### 5. Startup Event Stream (Server → Dashboard)

**File:** `/startup-events/startup-events.jsonl` (bind-mounted)
**Writer:** `server/backend/core/startup_events.py`
**Reader:** `dashboard/electron/startupEventWatcher.ts` (fs.watch)

**Purpose:** Server emits JSON events during bootstrap (dependency install, model loading, GPU check). Dashboard reads them in real-time to show progress to the user.

**Event types:** `lifespan-start`, `lifespan-gpu`, `info-gpu`, `warn-gpu`, `warn-gpu-fatal`, `server-ready`

### 6. Server → HuggingFace Hub

**Protocol:** HTTPS
**Client:** `huggingface_hub` Python library (via STT backend `load()`)
**Auth:** `HF_TOKEN` env var (optional, required for gated models like PyAnnote)
**Cache:** `HF_HOME=/models` (persistent Docker volume)

### 7. Server → GPU (CUDA/Vulkan/Metal)

**Interface:** PyTorch CUDA API, MLX framework (Apple Silicon), or HTTP to whisper.cpp sidecar
**Management:** `ModelManager` handles load/unload, single model at a time
**Memory:** `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,garbage_collection_threshold:0.8`

### 8. Server → whisper.cpp Sidecar (Optional)

**Protocol:** HTTP multipart POST
**Endpoint:** `http://whisper-server:8080` (Docker DNS) or `WHISPERCPP_SERVER_URL` env
**Purpose:** Vulkan-accelerated Whisper inference for AMD/Intel GPUs
**Backend:** `WhisperCppBackend` in `stt/backends/whispercpp_backend.py`

### 9. Server → LM Studio (Optional)

**Protocol:** HTTP (OpenAI-compatible API)
**Endpoint:** `http://127.0.0.1:1234` (default) or `LM_STUDIO_URL` env
**Purpose:** Local LLM for transcription summarization and chat
**Route:** `api/routes/llm.py`

## Shared Data

| Resource | Owner | Consumer | Mechanism |
|----------|-------|----------|-----------|
| Auth tokens | Server (TokenStore) | Dashboard (useAuthTokenSync) | File + API |
| Server config | `config.yaml` | Both | YAML file (server reads, dashboard edits via admin API) |
| Model cache | HuggingFace Hub | Server (STT backends) | `HF_HOME` volume |
| SQLite database | Server | Server only | `/data/database/` volume |
| Audio recordings | Server | Server + Dashboard (playback) | `/data/audio/` volume + REST API |
| Startup events | Server | Dashboard (fs.watch) | Bind-mounted JSONL file |

## Error Recovery Integration

| Failure Scenario | Detection | Recovery |
|-----------------|-----------|----------|
| WebSocket disconnect during transcription | Client: WS close event | Client polls `GET /api/transcribe/result/{job_id}` |
| Server crash during transcription | Server: orphan job sweep on startup | Marks stale jobs as `failed`, client shows recovery banner |
| GPU crash (CUDA error 999) | Server: `cuda_health_check()` at startup | Sets `_cuda_probe_failed` flag, server runs in degraded mode |
| Docker container crash | Dashboard: crash-safe sentinel (Linux) | Sentinel process (setsid) stops container on Electron PID exit |
| Large result (>1MB) | Server: payload size check | Sends `result_ready` reference, client fetches via HTTP |
