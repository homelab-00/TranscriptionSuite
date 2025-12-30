# TranscriptionSuite - Developer Notes

This document contains technical details, architecture decisions, and development notes for TranscriptionSuite.

## Table of Contents

- [Quick Reference](#quick-reference)
- [Architecture Overview](#architecture-overview)
  - [Design Decisions](#design-decisions)
  - [Deployment Philosophy](#deployment-philosophy)
  - [Security Model](#security-model)
  - [Known Technical Debt](#known-technical-debt)
- [End User Workflow](#end-user-workflow)
  - [First-Time Setup](#first-time-setup)
  - [Configuration](#configuration)
  - [Daily Usage](#daily-usage)
- [Project Structure](#project-structure)
  - [Directory Layout](#directory-layout)
  - [pyproject.toml Files](#pyprojecttoml-files)
- [Development Workflow](#development-workflow)
  - [Step 1: Environment Setup](#step-1-environment-setup)
  - [Step 2: Build Docker Image](#step-2-build-docker-image)
  - [Step 2.1: Publishing to GitHub Container Registry](#step-21-publishing-to-github-container-registry)
  - [Step 3: Run Client Locally](#step-3-run-client-locally)
  - [Step 4: Run Client Remotely (Tailscale)](#step-4-run-client-remotely-tailscale)
- [Build Workflow](#build-workflow)
  - [Prerequisites](#prerequisites)
  - [KDE AppImage (Linux)](#kde-appimage-linux)
  - [GNOME AppImage (Linux)](#gnome-appimage-linux)
  - [Windows Executable](#windows-executable)
  - [Build Artifacts](#build-artifacts)
  - [Troubleshooting Builds](#troubleshooting-builds)
- [Docker Reference](#docker-reference)
  - [Docker Build & Runtime Notes](#docker-build--runtime-notes)
  - [Local vs Remote Mode](#local-vs-remote-mode)
  - [Tailscale HTTPS Setup](#tailscale-https-setup)
  - [Docker Volume Structure](#docker-volume-structure)
- [API Reference](#api-reference)
  - [Endpoints](#endpoints)
  - [Swagger UI](#swagger-ui)
- [Backend Development](#backend-development)
  - [Architecture](#backend-architecture)
  - [Setting Up Native Development](#setting-up-native-development)
  - [Running the Server Locally](#running-the-server-locally)
  - [Configuration System](#configuration-system)
  - [Key Modules Explained](#key-modules-explained)
  - [Frontend Development (React UI)](#frontend-development-react-ui)
  - [Testing](#testing)
  - [Common Development Tasks](#common-development-tasks)
  - [Development Tips](#development-tips)
- [Client Development](#client-development)
  - [Running from Source](#running-from-source)
  - [Verbose Logging](#verbose-logging)
  - [Troubleshooting Tailscale HTTPS](#troubleshooting-tailscale-https)
- [Configuration Reference](#configuration-reference)
  - [Voice Activity Detection (VAD) Configuration](#voice-activity-detection-vad-configuration)
  - [Static File Transcription Configuration](#static-file-transcription-configuration)
  - [Server Configuration (Docker)](#server-configuration-docker)
  - [Client Configuration](#client-configuration)
  - [Native Development Configuration](#native-development-configuration)
- [Data Storage](#data-storage)
  - [Database Schema](#database-schema)
  - [Database Migrations (Alembic)](#database-migrations-alembic)
  - [Database Backups](#database-backups)
  - [Sensitive Data Storage & Lifecycle](#sensitive-data-storage--lifecycle)
- [Troubleshooting](#troubleshooting)
  - [Docker GPU Access](#docker-gpu-access)
  - [Docker Logs](#docker-logs)
  - [Health Check Issues](#health-check-issues)
  - [Tailscale DNS Resolution Issues](#tailscale-dns-resolution-issues)
  - [Model Loading](#model-loading)
  - [cuDNN Library Errors](#cudnn-library-errors)
  - [GNOME Tray Not Showing](#gnome-tray-not-showing)
  - [Permission Errors](#permission-errors)
  - [AppImage Startup Failures](#appimage-startup-failures)
- [Dependencies](#dependencies)
  - [Server (Docker)](#server-docker)
  - [Client](#client-1)

---

## Quick Reference

This section provides a streamlined overview of the most common development tasks. For detailed explanations, see the full sections below.

### Development Workflow (TL;DR)

```bash
# 1. Setup all Python virtual environments
cd client && uv venv --python 3.11 && uv sync --extra kde && cd ..
cd build && uv venv --python 3.11 && uv sync && cd ..

# 2. Audit NPM packages (frontend)
cd server/frontend && npm ci && npm audit && cd ../..

# 3. Build and run Docker server
cd server/docker
docker compose build
docker compose up -d

# 4. Run client locally
cd client
uv run transcription-client --host localhost --port 8000
```

### Build Workflow (TL;DR)

Note: All three scripts are meant to be run from the project root.

```bash
# KDE AppImage (Linux)
./build/build-appimage-kde.sh
# Output: build/dist/TranscriptionSuite-KDE-x86_64.AppImage

# GNOME AppImage (Linux)
./build/build-appimage-gnome.sh
# Output: build/dist/TranscriptionSuite-GNOME-x86_64.AppImage

# Windows (on Windows machine)
.\build\.venv\Scripts\pyinstaller.exe --clean --distpath build\dist .\client\src\client\build\pyinstaller-windows.spec
# Output: build\dist\TranscriptionSuite.exe
```

### Key Commands

| Task | Command |
|------|---------|
| **First-time setup** | `cd build/user-setup && ./setup.sh` (Linux) or `.\setup.ps1` (Windows) |
| **Start server (local)** | `cd ~/.config/TranscriptionSuite && ./start-local.sh` |
| **Start server (HTTPS)** | `cd ~/.config/TranscriptionSuite && ./start-remote.sh` |
| **Stop server** | `cd ~/.config/TranscriptionSuite && ./stop.sh` |
| **Build Docker image** | `cd server/docker && docker compose build` |
| **Rebuild after code changes** | `docker compose build && docker compose up -d` |
| **View server logs** | `docker compose logs -f` |
| **Publish Docker image (release)** | `git tag v0.3.0 -m "Release" && git push origin v0.3.0` |
| **Publish Docker image (manual)** | `gh workflow run docker-publish.yml --field tag=test` |
| **Monitor GitHub Actions build** | `gh run watch` |
| **Run client (local)** | `cd client && uv run transcription-client --host localhost --port 8000` |
| **Run client (remote)** | `cd client && uv run transcription-client --host <tailscale-hostname> --port 8443 --https` |
| **Lint code** | `./build/.venv/bin/ruff check .` |
| **Format code** | `./build/.venv/bin/ruff format .` |
| **Type check** | `./build/.venv/bin/pyright` |

---

## Architecture Overview

TranscriptionSuite uses a **client-server architecture**:

```txt
┌─────────────────────────────────────────────────────────┐
│                     Docker Container                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │  TranscriptionSuite Server                        │  │
│  │  - FastAPI REST API + WebSocket                   │  │
│  │  - faster-whisper transcription                   │  │
│  │  - Real-time STT with VAD (Silero + WebRTC)       │  │
│  │  - PyAnnote diarization                           │  │
│  │  - Web UI (React frontend)                        │  │
│  │  - SQLite + FTS5 search                           │  │
│  └───────────────────────────────────────────────────┘  │
│           HTTP/WebSocket ↕                              │
└─────────────────────────────────────────────────────────┘
                           ↕
┌─────────────────────────────────────────────────────────┐
│                     Native Clients                      │
│     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐     │
│     │   KDE Tray  │ │ GNOME Tray  │ │Windows Tray │     │
│     │   (PyQt6)   │ │(GTK+AppInd) │ │  (PyQt6)    │     │
│     └─────────────┘ └─────────────┘ └─────────────┘     │
│     - Microphone recording                              │
│     - Clipboard integration                             │
│     - System notifications                              │
│     - Preview transcription (optional)                  │
└─────────────────────────────────────────────────────────┘
```

### Design Decisions

- **Server in Docker**: All ML/GPU operations run in Docker for reproducibility and isolation
- **Native clients**: System tray, microphone, clipboard require native access (can't be containerized)
- **Single port**: Server exposes everything on port 8000 (API, WebSocket, static files)
- **SQLite + FTS5**: Lightweight full-text search without external dependencies
- **Client detection**: Server detects client type (standalone vs web) to enable features like preview transcription only for standalone clients, saving GPU memory for web users
- **Dual VAD**: Real-time engine uses both Silero (neural) and WebRTC (algorithmic) VAD for robust speech detection
- **Multi-device support with job protection**: Multiple clients can connect simultaneously, but only one transcription job runs at a time. The `TranscriptionJobTracker` ensures exclusive access across all methods (HTTP uploads, WebSocket streaming) and returns clear 409 Conflict errors when busy.

### Deployment Philosophy

TranscriptionSuite is designed for **easy deployment by end users**, not just developers:

- **Docker abstracts complexity**: All ML dependencies, GPU configuration, and model management are handled inside the container. Users don't need Python, CUDA, or any development tools installed.
- **Binary clients**: End users download a single AppImage (Linux) or .exe (Windows) - no Python environment needed.
- **One-time setup**: Run `setup.sh` (or `setup.ps1` on Windows) once to pull the Docker image and create the config directory.
- **Simple scripts**: Use `start-local.sh` or `start-remote.sh` for daily usage instead of remembering Docker commands.
- **Config file customization**: All settings are in `~/.config/TranscriptionSuite/config.yaml` - edit once, use forever.

**Target user flow:**
1. Install Docker
2. Run setup script
3. Edit config file (HuggingFace token, TLS paths if needed)
4. Run start script
5. Download and use the native client

### Security Model

TranscriptionSuite uses a **"belt and suspenders"** layered security approach for remote access:

```txt
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Tailscale Network (Network Access Control)        │
│  - Only devices on your Tailnet can reach the server        │
│  - Zero-trust mesh VPN with identity-based access           │
│  - No open ports on public internet                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: TLS/HTTPS Encryption (Transport Security)         │
│  - Tailscale-issued certificates (trusted CA)               │
│  - All traffic encrypted in transit                         │
│  - Certificate validation prevents MITM attacks             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Token Authentication (Application Security)       │
│  - Admin token auto-generated on first run                  │
│  - Tokens hashed with SHA-256 before storage                │
│  - Required for all API endpoints in TLS mode               │
└─────────────────────────────────────────────────────────────┘
```

**Key Design Decisions:**

1. **Local users are not authenticated**: When running locally (`localhost:8000` or `127.0.0.1:8000`), no authentication is required. The `/record` view is specifically accessible without authentication from localhost to enable seamless local usage. This is a single-user server under the user's direct control.

2. **CORS allows all origins**: The `allow_origins=["*"]` configuration is acceptable because:
   - Local mode: Only accessible from localhost
   - Remote mode: Only accessible via Tailscale network (Layer 1 provides access control)

3. **Admin endpoints don't require role checks**: All users who can reach the server (via Tailscale) are implicitly trusted. The token system exists for:
   - Multi-device identification (knowing which device is making requests)
   - Session management (ability to revoke access)
   - Audit logging (tracking who did what)

4. **Host network mode**: The Docker container uses `network_mode: "host"` because:
   - Required for LM Studio access (localhost:1234 from within container)
   - Simplifies GPU passthrough and networking
   - Acceptable because access control is at the Tailscale layer

**Trust Boundaries:**

| Access Method | Authentication | Trust Level |
|---------------|----------------|-------------|
| `localhost:8000` (HTTP) | None | Full trust (user's own machine) |
| Tailscale + TLS | Token required | High trust (your Tailnet) |
| Public internet | Not supported | N/A (blocked by design) |

### Known Technical Debt

The following items are documented for future improvement but are not critical issues:

1. **Client Code Duplication (~655 lines)**
   - KDE and GNOME clients share similar logic but have separate implementations
   - Settings dialogs have nearly identical structure in different UI frameworks
   - `_get_client_name()` is duplicated in 3 route files (`transcription.py`, `notebook.py`, `websocket.py`)
   - *Recommendation:* Extract shared logic to base classes or utility modules

2. **Database N+1 Query Pattern**
   - `get_transcription()` in `database.py` executes one query per segment to fetch words
   - *Impact:* 51 queries for a recording with 50 segments instead of 1-2 JOINs
   - *Recommendation:* Refactor to use JOINs or batch word fetching

3. **Enhanced Search Performance**
   - `search_words_enhanced()` executes extra queries for context per match
   - No pagination - loads all results into memory
   - *Recommendation:* Use JOINs and add LIMIT/OFFSET pagination

---

## End User Workflow

This section describes how **end users** (not developers) should set up and run TranscriptionSuite.

### First-Time Setup

Run the setup script once to initialize your environment:

**Linux:**
```bash
cd build/user-setup
./setup.sh
```

**Windows (PowerShell):**
```powershell
cd build\user-setup
.\setup.ps1
```

The setup script will:
1. Check that Docker is installed and running
2. Create the config directory with all necessary files:
   - Linux: `~/.config/TranscriptionSuite/`
   - Windows: `Documents\TranscriptionSuite\`
3. Pull the Docker image from GitHub Container Registry

**Files created in your config directory:**
- `config.yaml` - Server settings
- `.env` - HuggingFace token (and log printouts) - **not tracked in git**
- `docker-compose.yml` - Docker configuration
- `start-local.sh/ps1` - Start server in HTTP mode
- `start-remote.sh/ps1` - Start server in HTTPS mode
- `stop.sh/ps1` - Stop the server

### Configuration

After setup, configure your HuggingFace Token and log settings:

**1. Edit the `.env` file for HuggingFace Token (required for speaker diarization):**

```bash
# Linux
nano ~/.config/TranscriptionSuite/.env

# Windows
notepad "$env:USERPROFILE\Documents\TranscriptionSuite\.env"
```

Set your HuggingFace token:
```
HUGGINGFACE_TOKEN=hf_your_token_here
```

Get a token from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) and accept the [PyAnnote model license](https://huggingface.co/pyannote/speaker-diarization-community-1).

**2. (Optional) For remote/HTTPS access, edit `config.yaml`:**

```yaml
remote_server:
  tls:
    host_cert_path: "~/.config/Tailscale/my-machine.crt"
    host_key_path: "~/.config/Tailscale/my-machine.key"
```

See [Tailscale HTTPS Setup](#tailscale-https-setup) for certificate generation.

### Daily Usage

All scripts are in your config directory. Navigate there first:

```bash
# Linux
cd ~/.config/TranscriptionSuite

# Windows
cd "$env:USERPROFILE\Documents\TranscriptionSuite"
```

**Start the server:**

```bash
# Linux - Local mode (HTTP on port 8000)
./start-local.sh

# Linux - Remote mode (HTTPS on port 8443)
./start-remote.sh

# Windows
.\start-local.ps1
.\start-remote.ps1
```

**Stop the server:**

```bash
# Linux
./stop.sh

# Windows
.\stop.ps1
```

**View logs:**

```bash
docker compose logs -f
```

### Script Reference

| Script | Purpose |
|--------|---------|
| `setup.sh` / `setup.ps1` | First-time setup (run once from build/user-setup/ folder) |
| `start-local.sh` / `start-local.ps1` | Start server in HTTP mode (port 8000) |
| `start-remote.sh` / `start-remote.ps1` | Start server in HTTPS mode (port 8443) |
| `stop.sh` / `stop.ps1` | Stop the server |

---

## Project Structure

### Directory Layout

```txt
TranscriptionSuite/
├── client/                       # Native client (runs locally)
│   ├── src/client/               # Python package source
│   │   ├── common/               # Shared client code
│   │   │   ├── api_client.py     # HTTP client, WebSocket, ServerBusyError handling
│   │   │   ├── audio_recorder.py # PyAudio recording wrapper
│   │   │   ├── orchestrator.py   # Main controller, state machine, error notifications
│   │   │   ├── tailscale_resolver.py # Tailscale IP fallback when DNS fails
│   │   │   ├── tray_base.py      # Abstract tray interface
│   │   │   ├── config.py         # Client configuration
│   │   │   └── models.py         # Shared data models
│   │   ├── kde/                  # KDE Plasma (PyQt6)
│   │   │   └── tray.py           # Qt6 system tray implementation
│   │   ├── gnome/                # GNOME (GTK + AppIndicator)
│   │   │   ├── tray.py           # GTK/AppIndicator implementation
│   │   │   └── settings_dialog.py # GTK3 settings dialog
│   │   ├── windows/              # Windows (PyQt6)
│   │   │   └── tray.py           # Windows tray (same as KDE)
│   │   ├── build/                # Build configurations
│   │   │   ├── pyinstaller-kde.spec
│   │   │   └── pyinstaller-windows.spec
│   │   └── __main__.py           # CLI entry point
│   └── pyproject.toml            # Client package + dependencies
│
├── build/                        # Build and development tools
│   ├── build-appimage-kde.sh     # Build KDE AppImage
│   ├── build-appimage-gnome.sh   # Build GNOME AppImage
│   └── pyproject.toml            # Dev/build tools (separate venv)
│
├── server/                       # Server source code
│   ├── docker/                   # Docker infrastructure
│   │   ├── Dockerfile            # Multi-stage build (frontend + Python)
│   │   ├── docker-compose.yml    # Unified local + remote deployment
│   │   └── entrypoint.py         # Container entrypoint
│   ├── backend/                  # Unified backend (runs in Docker + native)
│   │   ├── api/                  # FastAPI application
│   │   │   ├── main.py           # App factory, lifespan, static mounting
│   │   │   └── routes/           # API endpoints
│   │   ├── core/                 # ML engines
│   │   │   ├── transcription_engine.py  # Unified Whisper wrapper
│   │   │   ├── diarization_engine.py    # PyAnnote wrapper
│   │   │   ├── model_manager.py         # Model lifecycle management
│   │   │   ├── stt/              # Real-time speech-to-text engine
│   │   │   │   ├── engine.py     # AudioToTextRecorder (VAD-based)
│   │   │   │   ├── vad.py        # Dual VAD (Silero + WebRTC)
│   │   │   │   └── constants.py  # STT configuration constants
│   │   │   ├── realtime_engine.py       # Async wrapper for real-time STT
│   │   │   ├── preview_engine.py        # Preview transcription for clients
│   │   │   ├── client_detector.py       # Client type detection
│   │   │   └── audio_utils.py           # Audio processing utilities
│   │   ├── database/             # SQLite + FTS5
│   │   ├── logging/              # Centralized logging
│   │   ├── config.py             # Server configuration loader
│   │   └── pyproject.toml        # Server dependencies
│   ├── frontend/                 # Web UI frontend (React)
│   └── config.yaml               # Configuration file (also serves as template)
```

### pyproject.toml Files

The project has ***three*** `pyproject.toml` files, each serving a different purpose:

| File | Purpose |
|------|------|
| `client/pyproject.toml` | Native client package definition. Defines runtime deps and platform extras (`kde`, `gnome`, `windows`). Provides the `transcription-client` entrypoint. **No dev dependencies** - use `build/.venv` for development tools. |
| `build/pyproject.toml` | **All dev/build tools** (ruff, pyright, pytest, pyinstaller, httpx for testing). Use `build/.venv` for linting, type-checking, testing, and packaging. This is the single source of truth for all development tooling. |
| `server/backend/pyproject.toml` | Server/backend package definition. Defines server deps (FastAPI, faster-whisper, torch, pyannote.audio, etc.) with **pinned versions** for reproducible Docker builds. **No dev dependencies** - use `build/.venv` for development tools. |

**Dependency Management Philosophy:**
- Runtime dependencies are pinned to exact versions in `server/backend/pyproject.toml` (e.g., `fastapi==0.128.0`, `torch==2.8.0`)
- This ensures reproducible Docker builds and prevents version drift
- Dev tools are consolidated in `build/pyproject.toml` to avoid duplication
- Client runtime dependencies use minimum version constraints for flexibility across platforms

---

## API Reference

### Web UI

The server serves a unified web frontend with multiple views:

| URL Path | View | Description |
|----------|------|-------------|
| `/` | Redirect | Redirects to `/record` |
| `/auth` | Auth Page | Authentication page (required in TLS mode) |
| `/record` | Record | Web client for file upload, recording, admin panel |
| `/notebook` | Notebook | Personal transcription archive with calendar view and search |

**Security Model (Belt and Suspenders):**

The server uses a layered security approach:
1. **Tailscale Network**: Only users on your Tailscale network can reach the server
2. **TLS/HTTPS**: Encrypted connection with Tailscale certificates
3. **Token Authentication**: In TLS mode, all routes require valid token authentication

**TLS Mode Authentication:**

When `TLS_ENABLED=true`, the server enforces authentication for most routes **except localhost**:
- **Localhost access** (`127.0.0.1`, `::1`, `localhost`): `/record` and `/api/` endpoints accessible without authentication
- **Remote access via Tailscale**: Unauthenticated browser requests are redirected to `/auth`
- **Remote API requests**: Requests without valid token receive 401 Unauthorized
- **Tokens can be provided via:**
  - `Authorization: Bearer <token>` header (API clients)
  - `auth_token` cookie (web browsers)

**Record View Features:**
- File upload transcription (with optional diarization and word timestamps)
- Real-time microphone recording via WebSocket
- Admin panel for token management (requires login in TLS mode; accessible without login on localhost)
- Token-based authentication (login with admin or user token when using remote Tailscale access)
- Works on Android browsers (no app needed)

**Notebook View Features:**
- Calendar view of all recordings by date
- Day view with timeline of recordings
- Full-text search across all transcriptions
- Inline title editing (click to edit)
- Speaker diarization visualization (when enabled)
- Word-level timestamps (clickable words to jump to audio position)
- LLM chat integration for summarization and Q&A
- Audio playback with waveform visualization

**Authentication:** On first run, an admin token is automatically generated and printed to the console logs.
- **Localhost users**: No token needed - access `/record` directly
- **Remote users (via Tailscale)**: Save this token to login at `/auth` (or visit `/record` which will redirect to `/auth`) and access the admin panel for token management

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (no auth) |
| `/api/status` | GET | Server status, GPU info |
| `/api/auth/login` | POST | Authenticate with token |
| `/api/auth/tokens` | GET/POST | Token management (admin only) |
| `/api/auth/tokens/{id}` | DELETE | Revoke token (admin only) |
| `/api/transcribe/audio` | POST | Transcribe uploaded audio file (returns 409 if busy) |
| `/api/transcribe/quick` | POST | Quick transcription without word timestamps (returns 409 if busy) |
| `/api/transcribe/file` | POST | Alias for /audio (Remote UI compatibility) |
| `/ws` | WebSocket | Real-time audio streaming and transcription |
| `/api/notebook/recordings` | GET | List all recordings |
| `/api/notebook/recordings/{id}` | GET | Get recording details |
| `/api/notebook/recordings/{id}` | DELETE | Delete recording |
| `/api/notebook/recordings/{id}/title` | PATCH | Update recording title |
| `/api/notebook/recordings/{id}/summary` | PATCH | Update recording summary |
| `/api/notebook/recordings/{id}/transcription` | GET | Get full transcription with segments |
| `/api/notebook/recordings/{id}/audio` | GET | Download audio file |
| `/api/notebook/transcribe/upload` | POST | Upload and transcribe audio file (with diarization support, returns 409 if busy) |
| `/api/notebook/calendar` | GET | Calendar view data |
| `/api/search` | GET | Full-text search |
| `/api/admin/status` | GET | Admin status info |
| `/api/llm/status` | GET | LM Studio connection status |
| `/api/llm/chat` | POST | Send chat message to LLM |

### WebSocket Protocol

The `/ws` endpoint supports real-time audio streaming for long-form transcription:

**Connection Flow:**
1. Client connects to WebSocket (with `X-Client-Type` header for standalone clients)
2. Client sends auth message: `{"type": "auth", "data": {"token": "<token>"}, "timestamp": <unix_time>}`
3. Server responds with `{"type": "auth_ok", "data": {"client_type": "standalone|web", "capabilities": {...}}}`
4. Client sends start message: `{"type": "start", "data": {"language": "en", "use_vad": true}, "timestamp": <unix_time>}`
5. Client streams binary audio data (16kHz PCM Int16 with metadata header)
6. Client sends stop message: `{"type": "stop", "data": {}, "timestamp": <unix_time>}`
7. Server processes and returns: `{"type": "final", "data": {"text": "...", "words": [...], "duration": 10.5}}`

**Client Type Detection:**
- Server detects client type via `X-Client-Type` header or User-Agent
- Standalone clients get additional features (VAD events, preview transcription)
- Web clients use simplified mode to save GPU memory

**Audio Format:**
- Binary messages: `[4 bytes metadata length][metadata JSON][PCM Int16 data]`
- Sample rate: 16kHz
- Format: Int16 PCM (little-endian)
- Metadata: `{"sample_rate": 16000, "timestamp_ns": <nanoseconds>, "sequence": <number>}`

**VAD Events (Standalone Clients):**
- `{"type": "vad_start"}` - Voice activity detected
- `{"type": "vad_stop"}` - Voice activity ended
- `{"type": "vad_recording_start"}` - Recording started after VAD trigger
- `{"type": "vad_recording_stop"}` - Recording stopped after silence

**Session Management:**
- Multiple WebSocket connections allowed simultaneously
- Only one transcription job can run at a time (across all methods)
- When client sends `start` message, server checks job tracker
- Server sends `{"type": "session_busy", "data": {"active_user": "<client_name>"}}` if another job is running
- Connection remains open after `session_busy` - client can retry later

### Swagger UI

Full API documentation at `http://localhost:8000/docs`

---

## Development Workflow

This section describes the complete development workflow from initial setup to running the client. Development uses Docker for the server (no native server development) and runs the client natively.

### Step 1: Environment Setup

Set up all required Python virtual environments and audit NPM packages.

#### 1.1 Client Virtual Environment

```bash
cd client
uv venv --python 3.11
uv sync --extra kde    # For KDE/Plasma (PyQt6)
# OR: uv sync --extra gnome   # For GNOME (GTK + AppIndicator)
# OR: uv sync --extra windows # For Windows (PyQt6)
cd ..
```

#### 1.2 Build Tools Virtual Environment

```bash
cd build
uv venv --python 3.11
uv sync    # Installs ruff, pyright, pytest, pyinstaller, etc.
cd ..
```

#### 1.3 NPM Package Audit

Audit the web frontend for security vulnerabilities:

```bash
cd server/frontend
npm ci
npm audit
cd ../..
```

> **Note:** The Docker build runs `npm ci` but does **not** run `npm audit`. Always audit locally before building.

### Step 1.4: Development Configuration Files

For development, the startup scripts (`start-local.sh`, `start-remote.sh`) automatically search for configuration files in the following priority order:

**config.yaml:**
1. `server/config.yaml` (development - highest priority)
2. `~/.config/TranscriptionSuite/config.yaml` (user config)
3. `server/docker/config.yaml` (fallback)

**.env:**
1. `server/.env` (development - alongside dev config, highest priority)
2. `~/.config/TranscriptionSuite/.env` (user config)
3. `server/docker/.env` (fallback)

**For development**, you should:
- Keep config in `server/config.yaml` (recommended - already exists)
- Create `.env` at `server/.env` for secrets (HuggingFace token) - keeps dev config together

The startup scripts work seamlessly for both:
- **Development**: Run from `server/docker/` directory (finds config at `../`)
- **End users**: Run from `~/.config/TranscriptionSuite/` (finds config in same directory)

### Step 2: Build Docker Image

Build the Docker image containing the server, ML models support, and the web frontend:

```bash
cd server/docker
docker compose build
```

**What happens during build:**
1. **Frontend builder stage**: Builds the React frontend (`server/frontend`)
2. **Python runtime stage**: Installs all server dependencies from `server/backend/pyproject.toml`
3. **Static files**: Copies built frontend to `/app/static/frontend`
4. **Config template**: Copies `server/config.yaml` as `config/config.yaml.example`

**Development vs. Production Images:**
When you run `docker compose build`, Docker uses the `build:` section in `docker-compose.yml` to create a local image tagged as `ghcr.io/homelab-00/transcriptionsuite-server:latest`. This local image will **always** take priority over the one from GitHub Container Registry when you run `docker compose up`. Docker only attempts to pull from the registry if the image does not exist locally.

**Startup Script Behavior:**
The same priority applies when using the startup scripts (`start-local.sh`, `start-remote.sh`, etc.). These scripts run `docker compose up -d`, which follows the same logic:
- If a local image with the tag `ghcr.io/homelab-00/transcriptionsuite-server:latest` exists (from a previous `docker compose build`), it will be used.
- If no local image exists, Docker Compose will attempt to pull it from GitHub Container Registry.
- The scripts check if the image exists locally and inform you, but they do **not** force a pull if a local image is present.

This means for development, you can freely build and test local changes without worrying about the registry overwriting your work.

**Force rebuild** (if layer caching causes issues):

```bash
docker compose build --no-cache
```

### Step 2.1: Publishing to GitHub Container Registry

TranscriptionSuite uses **GitHub Actions** to automate Docker image builds and publishing to GitHub Container Registry (GHCR). This is the recommended approach for releases and sharing images.

#### Option 1: Automated Publishing with GitHub Actions (Recommended)

The repository includes a GitHub Actions workflow (`.github/workflows/docker-publish.yml`) that automatically builds and publishes Docker images to GHCR.

**Triggering Automated Builds:**

1. **Release Tags (Automatic)** - Creates both versioned and `latest` tags:
   ```bash
   # Create and push a release tag (e.g., v0.3.0)
   git tag v0.3.0 -m "Release v0.3.0: Description of changes"
   git push origin v0.3.0

   # This creates TWO images on GHCR:
   #   - ghcr.io/homelab-00/transcriptionsuite-server:v0.3.0
   #   - ghcr.io/homelab-00/transcriptionsuite-server:latest (updated)
   ```

2. **Manual Dispatch** - For ad-hoc builds with custom tags:
   ```bash
   # Install GitHub CLI (if not already installed)
   # Arch Linux: sudo pacman -S github-cli
   # Other distros: see https://github.com/cli/cli#installation

   # Authenticate (first time only)
   gh auth login

   # Trigger a build with custom tag
   gh workflow run docker-publish.yml --field tag=test

   # Monitor the build progress
   gh run watch

   # View build logs
   gh run list --workflow=docker-publish.yml
   gh run view <run-id> --log
   ```

**Workflow Features:**
- **Zero-config authentication**: Uses GitHub's auto-generated `GITHUB_TOKEN` (no manual PAT needed)
- **Build caching**: First build takes ~15-20 minutes, subsequent builds ~5 minutes (70% faster)
- **Multi-platform support**: Currently builds for `linux/amd64`, ready for `arm64` when needed
- **Automatic tagging**: Release tags create both versioned (e.g., `v1.0.0`) and `latest` tags
- **Build summary**: Each workflow run provides a detailed summary with pull commands

**Monitoring Builds:**

- **Web UI**: Check build status at https://github.com/homelab-00/TranscriptionSuite/actions
- **Terminal**: Use `gh run watch` for real-time progress
- **Notifications**: GitHub sends email notifications on build failures

**First-Time Setup:**

After your first automated build, make the package public so anyone can pull without authentication:
1. Visit: https://github.com/homelab-00/TranscriptionSuite/pkgs/container/transcriptionsuite-server
2. Click "Package settings" → Change visibility to "Public"

#### Option 2: Manual Publishing (For Local Testing)

For quick local builds or testing before pushing to production, you can manually push images:

1. **Install GitHub CLI** (if using manual dispatch):
   ```bash
   # Arch Linux
   sudo pacman -S github-cli

   # Authenticate
   gh auth login
   ```

2. **Build Locally**:
   ```bash
   cd server/docker
   docker compose build
   ```

3. **Login to GHCR** (first time only):
   ```bash
   # Using GitHub CLI (recommended - uses your gh auth)
   gh auth token | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin

   # OR using a Personal Access Token:
   echo "YOUR_GITHUB_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
   ```

   **Security Tip**: To avoid storing credentials in plaintext (`~/.docker/config.json`), use a credential helper:
   - **Linux (KDE/GNOME)**: Install `docker-credential-secretservice` and set `"credsStore": "secretservice"` in `~/.docker/config.json`
   - **Windows/macOS**: Docker Desktop uses built-in helpers by default

4. **Tag and Push**:
   ```bash
   # Push with custom tag for testing
   docker tag ghcr.io/homelab-00/transcriptionsuite-server:latest ghcr.io/homelab-00/transcriptionsuite-server:test
   docker push ghcr.io/homelab-00/transcriptionsuite-server:test

   # Push as latest (use with caution - prefer GitHub Actions for this)
   docker push ghcr.io/homelab-00/transcriptionsuite-server:latest
   ```

**Note**: Manual pushes should be used for testing only. For production releases, use the automated GitHub Actions workflow to ensure consistent builds and proper versioning.

### Step 3: Run Client Locally

Start the Docker server and connect with a local client.

#### 3.1 Start the Server

```bash
cd server/docker
docker compose up -d
```

**First-time startup notes:**
- Server startup takes ~9 seconds total:
  - ~0.9s: Module loading (FastAPI, routes, etc.)
  - ~2.3s: PyTorch import for GPU detection
  - ~6s: Whisper model loading into GPU memory (~3GB VRAM)
- On first run, an admin token is auto-generated and printed to the console logs - **save this token!** (as noted elsewhere on this file, you should wait ~10s and then run `docker compose logs | grep "Admin Token:"` to see this token)
- Check logs: `docker compose logs -f` (or just use `lazydocker`)
- Monitor GPU VRAM with `nvidia-smi` to see model loading progress

#### 3.2 Run the Client

```bash
cd client
uv run transcription-client --host localhost --port 8000
```

The client connects via HTTP to the local Docker server.

#### 3.3 Managing the Server

```bash
# Stop server
docker compose down

# Restart with same config
docker compose up -d

# Rebuild after code changes
docker compose build
docker compose up -d
```

**Note:** Models are cached in a persistent volume (`transcription-suite-models`), so they don't need to be re-downloaded on container recreation. Use `docker compose up -d` to ensure environment variables and volume mounts are applied correctly.

### Step 4: Run Client Remotely (Tailscale)

For connecting to the server from another machine over a secure connection.

#### 4.1 Server-Side: Enable HTTPS

```bash
cd server/docker
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d
```

See [Tailscale HTTPS Setup](#tailscale-https-setup) for certificate generation instructions.

#### 4.2 Client-Side: Connect via HTTPS

```bash
cd client
uv run transcription-client --host <your-machine>.tail1234.ts.net --port 8443 --https
```

Or with the AppImage:

```bash
./TranscriptionSuite-KDE-x86_64.AppImage --host <your-machine>.tail1234.ts.net --port 8443 --https
```

**Notes:**
- Replace `<your-machine>.tail1234.ts.net` with your actual Tailscale hostname
- Client persists CLI overrides to config, so you only need to pass flags once
- Port `8443` is for HTTPS; port `8000` is HTTP only

### Dev & Build Tools

A single environment for linting, type-checking, testing, and packaging:

```bash
cd build
uv venv --python 3.11
uv sync    # Installs ruff, pyright, pytest, pyinstaller, etc.
```

**Usage (from project root):**

```bash
# Linting
./build/.venv/bin/ruff check .
./build/.venv/bin/ruff format .

# Type checking
./build/.venv/bin/pyright
```

This keeps dev/build tooling isolated from client runtime dependencies.

---

## Build Workflow

This section covers building standalone executables for distribution. These are **not** needed for development—use the [Development Workflow](#development-workflow) to run from source.

### Prerequisites

All builds require the build tools environment:

```bash
cd build
uv venv --python 3.11
uv sync    # Installs PyInstaller, build, ruff, pytest, etc.
```

This creates `build/.venv` containing packaging tools isolated from runtime dependencies.

### Build Process Overview

| Platform | Method | Output | Target System Requirements |
|----------|--------|--------|---------------------------|
| **KDE (Linux)** | PyInstaller + AppImage | Fully standalone | None |
| **GNOME (Linux)** | Source bundle + AppImage | Semi-portable | Python 3.11+, GTK3, AppIndicator3 |
| **Windows** | PyInstaller | Fully standalone | None |

### KDE AppImage (Linux)

**What it does:**
1. Runs PyInstaller with `client/build/pyinstaller-kde.spec` to create a standalone binary
2. Bundles PyQt6, PyAudio, and all Python dependencies
3. Automatically rescales `build/assets/logo.png` (1024×1024 → 256×256) for AppImage icon
4. Creates an AppImage with `.desktop` file, icon, and launcher using `appimagetool`

**Requirements:**
- Linux system (tested on Arch, should work on any distro)
- `appimagetool` (auto-downloaded if not installed)
- ImageMagick (`magick` or `convert` command)
- Build tools venv set up (see Prerequisites)
- `build/assets/logo.png` (1024×1024) must exist

**Build:**

```bash
./build/build-appimage-kde.sh
```

**Output:** `build/dist/TranscriptionSuite-KDE-x86_64.AppImage`

**Usage on target system:**

```bash
chmod +x TranscriptionSuite-KDE-x86_64.AppImage
./TranscriptionSuite-KDE-x86_64.AppImage
```

### GNOME AppImage (Linux)

**What it does:**
1. Copies client source code into AppImage structure (no PyInstaller)
2. Creates a launcher script that validates system dependencies at runtime
3. Sets `PYTHONPATH` to include bundled source
4. Automatically rescales `build/assets/logo.png` (1024×1024 → 256×256) for AppImage icon
5. Packages into `.AppImage` for easier distribution

**Features:**
- GTK3-based settings dialog (Connection, Audio, Behavior tabs)
- System clipboard integration
- AppIndicator3 tray integration
- Desktop notifications

**Why not PyInstaller?**

GTK and GObject Introspection rely heavily on:
- Dynamic library loading at runtime
- GIR (GObject Introspection Repository) files
- Typelib files that must match system GTK version
- System-installed schemas and themes

PyInstaller cannot reliably bundle these, and attempts usually result in broken or unstable executables.

**Requirements:**
- Build system: Linux with `appimagetool` and ImageMagick (`magick` or `convert`)
- `build/assets/logo.png` (1024×1024) must exist
- Target system: Python 3.11+, GTK3, libappindicator-gtk3, python-gobject, python-numpy, python-aiohttp

**Build:**

```bash
./build/build-appimage-gnome.sh
```

**Output:** `build/dist/TranscriptionSuite-GNOME-x86_64.AppImage`

**Target system dependencies:**

```bash
# Arch Linux
sudo pacman -S python gtk3 libappindicator-gtk3 python-gobject python-numpy python-aiohttp

# Ubuntu/Debian
sudo apt install python3 python3-gi gir1.2-appindicator3-0.1 python3-pyaudio python3-numpy python3-aiohttp

# Fedora
sudo dnf install python3 gtk3 libappindicator-gtk3 python3-gobject python3-numpy python3-aiohttp
```

### Windows Executable

**What it does:**
- Uses build/assets/logo.ico (generated from build/assets/logo.svg) as the executable icon
- Uses PyInstaller to bundle Python interpreter, PyQt6, PyAudio, and dependencies
- Creates a standalone `.exe` file with embedded icon
- No Python installation required on target system

**Why Windows is required:**
- `.exe` files use Windows PE format (Windows-specific)
- PyQt6 and dependencies require Windows DLLs
- PyInstaller needs Windows linker tools
- Cross-compilation not supported due to platform-specific binaries

**Prerequisites:**

1. **Install uv** (Python package manager):

   Open PowerShell as Administrator and run:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Close and reopen PowerShell to refresh PATH.

2. **Install ImageMagick** (for icon generation):

   Download and install ImageMagick from [imagemagick.org](https://imagemagick.org/script/download.php#windows) or using winget:
   ```powershell
   winget install ImageMagick.ImageMagick
   ```

   Close and reopen PowerShell to refresh PATH.

**Build steps:**

1. **Clone the repository** (if not already done):
   ```powershell
   git clone <repository-url> TranscriptionSuite
   cd TranscriptionSuite
   ```

2. **Set up the build environment:**
   ```powershell
   cd build
   uv venv --python 3.11
   uv sync
   cd ..
   ```

3. **Generate Windows icon** (multi-resolution .ico from logo.png):
   ```powershell
   magick build\assets\logo.png -background transparent -define icon:auto-resize=256,48,32,16 build\assets\logo.ico
   ```
   *Note: you may need to restart the terminal after installing `magick` for it to be detected in your PATH (or you must run the windows `source .zshrc` equivalent).*

4. **Build the executable:**
   ```powershell
   .\build\.venv\Scripts\pyinstaller.exe --clean --distpath build\dist .\client\src\client\build\pyinstaller-windows.spec
   ```

**Output:** `build\dist\TranscriptionSuite.exe`

**Notes:**
- No need to install Python separately - `uv` handles Python installation automatically
- The executable is ~50-100 MB due to bundled Python interpreter and Qt libraries
- The build process takes 1-2 minutes on modern hardware
- Ensure `build/assets/logo.svg` and `build/assets/logo.png` (both 1024×1024) exist before building
- Icon sizes are automatically generated during builds - no manual resizing needed
- Requires ImageMagick installed for icon processing

### Icon Management

TranscriptionSuite uses a streamlined icon workflow:

**Source Files (manually maintained in `build/assets/`):**
- **logo.svg** (1024×1024) - Master vector logo, canonical source
- **logo.png** (1024×1024) - High-resolution raster export from logo.svg

**Generated Files (created automatically during builds):**
- **logo.ico** (multi-resolution: 16, 32, 48, 256) - Generated from logo.png for Windows builds
- **256×256 PNG** - Rescaled from logo.png for AppImage packaging

#### Creating Source Files

Export both files from Inkscape or GIMP at 1024×1024:

**Using Inkscape:**
1. Open your logo design
2. **File → Export As** → Save as `build/assets/logo.svg` (SVG format)
3. **File → Export As** → Set size to `1024` × `1024` → Save as `build/assets/logo.png`

**Using GIMP:**
1. Open your logo design
2. **Image → Scale Image** → Set to `1024` × `1024`
3. **File → Export As** → Save as `build/assets/logo.png`
4. For SVG: Use Inkscape or another vector editor

#### Automatic Icon Generation

**Linux AppImage Builds:**
- Automatically rescale `logo.png` (1024×1024 → 256×256) during build
- Requires: ImageMagick (`magick` or `convert` command)

**Windows Builds:**
- Run `build/generate-ico.sh` before building to create multi-resolution `logo.ico`
- Alternatively, run manually:
  ```bash
  # Linux/macOS
  ./build/generate-ico.sh

  # Windows (PowerShell)
  magick build\assets\logo.png -background transparent -define icon:auto-resize=256,48,32,16 build\assets\logo.ico
  ```

**Verify Generated Files:**
```bash
# Check multi-resolution .ico
identify build/assets/logo.ico  # Should show 4 sizes: 16, 32, 48, 256
```

### Build Artifacts

All builds output to the `build/dist/` directory:

```
build/dist/
├── TranscriptionSuite-KDE-x86_64.AppImage      # Linux KDE (standalone)
├── TranscriptionSuite-GNOME-x86_64.AppImage    # Linux GNOME (requires system GTK)
└── TranscriptionSuite.exe                       # Windows (standalone)
```

Intermediate build files are created in `build/appimage-kde/`, `build/appimage-gnome/`, etc. These can be deleted after successful builds.

### Troubleshooting Builds

**"PyInstaller not found"**

```bash
cd build && uv sync
```

**"appimagetool not found" (Linux)**
- The script auto-downloads it to `/tmp/appimagetool`
- Or install manually: Download from [AppImageKit releases](https://github.com/AppImage/AppImageKit/releases)

**"ImportError" when running built executable**
- Check the `.spec` file's `hiddenimports` list
- Add missing modules to the spec file
- Rebuild after spec changes

**GNOME AppImage fails on target system**
- Verify GTK3, AppIndicator3, numpy, and aiohttp are installed
- Check Python version: `python3 --version` (must be 3.11+)
- Test imports: `python3 -c "import gi; gi.require_version('Gtk', '3.0')"`
- Test numpy: `python3 -c "import numpy"`
- Test aiohttp: `python3 -c "import aiohttp"`

---

## Docker Reference

### Docker Build & Runtime Notes

#### Container Image Metadata

The Docker image includes an OCI (Open Container Initiative) label for source code attribution in the runtime stage:

```dockerfile
# In the runtime stage (Stage 3)
FROM ubuntu:22.04 AS runtime

# GitHub Container Registry label
LABEL org.opencontainers.image.source=https://github.com/homelab-00/TranscriptionSuite
```

This label:
- Links the container image to the source code repository
- Appears in GitHub Container Registry (GHCR) package metadata
- Helps users discover the source code for any image they pull
- Follows OCI image spec conventions for image attribution
- Required for GitHub Actions to properly link packages to the repository

**Note:** The label must be placed **after** a `FROM` statement (inside a build stage). It cannot be placed at the top of the Dockerfile outside of any stage.

#### Securing Docker Credentials

By default, Docker stores credentials in plaintext in `~/.docker/config.json`, which triggers a security warning during login. To secure your credentials:

1. **Install a credential helper**:
   - **Arch Linux (KDE/GNOME)**: `yay -S docker-credential-secretservice`
   - **Debian/Ubuntu**: `sudo apt install docker-credential-helpers`

2. **Configure Docker**:
   Edit `~/.docker/config.json` and add/update the `credsStore` field:
   ```json
   {
     "credsStore": "secretservice",
     "auths": { ... }
   }
   ```

3. **Re-login**:
   After configuring the helper, run `docker logout` and `docker login` again. The credentials will now be stored in your system keyring (KWallet or GNOME Keyring) instead of the config file.

#### Default Configuration

- **Docker image default config**: The Docker build copies `server/config.yaml` into the image as `/app/config.yaml`.
- This serves as the default configuration for the server.
- Users can override settings by mounting a custom `config.yaml` via `USER_CONFIG_DIR` (see [Customizing Server Configuration](#customizing-server-configuration)).

#### Frontend Build Behavior

- The Docker image **builds the web frontend during `docker compose build`** in the `frontend-builder` stage.
- Steps used:
  - `npm ci` (not `--omit=dev` to ensure build tools are available)
  - `npm run build`
- Docker layer caching may reuse these layers if `package*.json` and frontend sources are unchanged. Use `--no-cache` to force rebuilding.
- The Docker build **does not run `npm audit`** — run audits locally before building.

#### List all packages installed in running container

Helpful for diagnosing and pinning software versions prior to releases.

```bash
docker exec transcription-suite python -c "from importlib.metadata import distributions; print('\n'.join([f'{d.name}=={d.version}' for d in distributions()]))"
```

#### Docker Image Size Optimization

The Dockerfile uses `ubuntu:22.04` as the base image instead of `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04` to avoid CUDA library duplication:

- **Previous approach**: Used NVIDIA CUDA base image (~4.2 GB of CUDA/cuDNN libraries in base)
- **Current approach**: Uses minimal Ubuntu base image
- **Why it works**: PyTorch pip packages bundle their own CUDA libraries (~4.1 GB), which are prioritized via `LD_LIBRARY_PATH`
- **GPU access**: The nvidia-container-toolkit injects GPU drivers at runtime regardless of base image
- **Size savings**: ~4.2 GB reduction (from 19.9 GB to 15.5 GB)

The system CUDA libraries from the nvidia/cuda base image were unused since the Dockerfile already configured:
```dockerfile
ENV LD_LIBRARY_PATH=/app/.venv/lib/python3.11/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.11/site-packages/torch/lib:$LD_LIBRARY_PATH
```

This prioritizes PyTorch's bundled libraries, making the base image's CUDA installation redundant.

### Local vs Remote Mode

The unified compose file supports both local and remote (Tailscale/HTTPS) deployment. Switch modes via environment variables—no rebuild needed, but container recreation is required.

**Local mode (default):**

```bash
cd server/docker
docker compose up -d
```

**Remote mode with HTTPS:**

```bash
cd server/docker
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d
```

**Switching modes:**

> **Important:** Use `docker compose up -d`, NOT `docker compose start`. The `start` command only restarts a stopped container without re-reading environment variables or volume mounts. Certificate bind mounts are configured at container creation time.

```bash
# Switch to remote mode
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d

# Switch back to local mode
docker compose up -d    # TLS_ENABLED defaults to false
```

> **Note:** Switching modes recreates the container but preserves the Docker volume (`transcription-suite-data`). Your admin token, database, and all data persist across mode switches. The admin token is only regenerated if you delete the volume with `docker volume rm transcription-suite-data`.

**Ports:**
- `8000` — HTTP API (always available)
- `8443` — HTTPS (only serves when `TLS_ENABLED=true`)

### Tailscale HTTPS Setup

Complete instructions for setting up secure remote access via Tailscale.

#### Step 1: Set up Tailscale (One-Time)

1. Install Tailscale on your host machine: [tailscale.com/download](https://tailscale.com/download)
2. Authenticate: `sudo tailscale up`
   - Tailscale opens a browser window to authenticate
   - Verify with `tailscale status` — you should see your machine's Tailscale IP, device name, username, OS (e.g., `100.98.45.21 desktop github-account@ linux -`)
3. Go to [https://login.tailscale.com/admin](https://login.tailscale.com/admin) and log in
4. Go to the **DNS** tab. Note the Tailnet DNS name at the top (e.g., `tail1234.ts.net`). You can change it once to something more memorable.
5. Scroll to the bottom of the DNS tab and enable **HTTPS Certificates**

#### Step 2: Generate and Store Certificates

Generate a certificate for your machine:

```bash
sudo tailscale cert <YOUR_DEVICE_NAME>.<YOUR_TAILNET_DNS_NAME>
```

Example: `sudo tailscale cert desktop.tail1234.ts.net`

This creates two files in the current directory:
- `desktop.tail1234.ts.net.crt`
- `desktop.tail1234.ts.net.key`

**Move and rename** to a standard location:

| Platform | Certificate Directory | Files |
|----------|----------------------|-------|
| **Linux** | `~/.config/Tailscale/` | `my-machine.crt`, `my-machine.key` |
| **Windows** | `Documents\Tailscale\` | `my-machine.crt`, `my-machine.key` |
| **macOS** | `~/Library/Application Support/Tailscale/` | `my-machine.crt`, `my-machine.key` |

**Linux example:**

```bash
mkdir -p ~/.config/Tailscale
mv desktop.tail1234.ts.net.crt ~/.config/Tailscale/my-machine.crt
mv desktop.tail1234.ts.net.key ~/.config/Tailscale/my-machine.key
sudo chown $USER:$USER ~/.config/Tailscale/my-machine.*
sudo chmod 640 ~/.config/Tailscale/my-machine.key
```

> **Note:** Don't set `chmod 640` on the `.crt` file. The certificate (`.crt`) is public information. Only the private key (`.key`) needs strict permissions.

**Windows example (PowerShell):**

```powershell
mkdir "$env:USERPROFILE\Documents\Tailscale" -Force
mv desktop.tail1234.ts.net.crt "$env:USERPROFILE\Documents\Tailscale\my-machine.crt"
mv desktop.tail1234.ts.net.key "$env:USERPROFILE\Documents\Tailscale\my-machine.key"
```

> **Note:** Renaming the certificate files doesn't affect their validity—the certificate content is what matters, not the filename.

#### Step 3: Start with TLS Enabled

**Linux:**

```bash
cd server/docker
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d
```

**Windows (PowerShell):**

```powershell
cd C:\path\to\TranscriptionSuite\docker
$env:TLS_ENABLED="true"
$env:TLS_CERT_PATH="$env:USERPROFILE\Documents\Tailscale\my-machine.crt"
$env:TLS_KEY_PATH="$env:USERPROFILE\Documents\Tailscale\my-machine.key"
docker compose up -d
```

#### Step 4: Access the Remote Web UI

From any device on your Tailscale network, open a web browser and navigate to:

```
https://desktop.tail1234.ts.net:8443/record
```

Replace `desktop.tail1234.ts.net` with your actual Tailscale hostname (from `tailscale status`).

**Login:** Use the admin token printed in the server logs on first startup, or create additional tokens via the admin panel.

#### Tailscale Network Access (Remote and LAN)

Tailscale connections work in both scenarios:
- **Remotely**: When connected from a different network (e.g., accessing your home server from a coffee shop)
- **Locally (LAN)**: When on the same local network as the Docker server

This means you can use the Tailscale hostname even when on the same LAN, providing consistent addressing regardless of your location. The connection will automatically use the most efficient route (direct LAN connection when available, or relay through Tailscale when remote).

### Docker Volume Structure

Two named Docker volumes plus an optional user config bind mount:

**1. `transcription-suite-data`** - Application data (mounted to `/data`):

| Path | Description |
|------|-------------|
| `/data/database/` | SQLite database files for transcription records, metadata, and application state |
| `/data/audio/` | Audio files uploaded for transcription and processed audio data |
| `/data/logs/` | Application logs (fallback if user config not mounted) |
| `/data/tokens/` | Token store for authentication (`tokens.json`) |

**2. `transcription-suite-models`** - ML models cache (mounted to `/models`):

**3. User config directory** (optional bind mount to `/user-config`):

When `USER_CONFIG_DIR` is set, the specified host directory is mounted to `/user-config`:

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `~/.config/TranscriptionSuite/` (Linux) | `/user-config/` | Custom config and logs |
| `Documents\TranscriptionSuite\` (Windows) | `/user-config/` | Custom config and logs |

| File | Description |
|------|-------------|
| `/user-config/config.yaml` | Custom configuration (overrides `/app/config.yaml` defaults) |
| `/user-config/server.log` | Server logs (when user config is mounted) |

| Path | Description |
|------|-------------|
| `/models/hub/` | HuggingFace models cache (Whisper, PyAnnote diarization) |
| `/models/hub/models--Systran--faster-whisper-large-v3/` | Whisper model files (~3GB) |
| `/models/hub/models--pyannote--speaker-diarization-community-1/` | PyAnnote diarization model files (~1-2GB) |

**Model Download Behavior:**
- Models are downloaded on first use (not during Docker build)
- Whisper model: Downloads when first transcription is requested
- PyAnnote model: Downloads when first diarization is requested (requires `HUGGINGFACE_TOKEN`)
- Models persist across container rebuilds via the volume
- Total storage: ~4-5GB for both models

#### Volume Persistence

- **Data persistence**: Both volumes ensure data survives container restarts, updates, and recreation
- **Model cache**: Models are downloaded once and reused across rebuilds (~3GB saved per rebuild)
- **Primary storage**: Audio files, database, and ML models are the main storage consumers
- **Log retention**: Logs rotate automatically but remain in the volume

#### Host Access

Volumes are accessible from the host system:

```bash
/var/lib/docker/volumes/transcription-suite-data/_data
/var/lib/docker/volumes/transcription-suite-models/_data
```

#### Complete Volume Structure

```
/data/
├── database/
│   └── notebook.db           # SQLite database
├── audio/                    # Recorded audio files
├── logs/                     # Server logs
└── tokens/
    ├── tokens.json           # Authentication tokens
    └── tokens.lock           # Lock file for token store

/models/
└── hub/                      # HuggingFace models cache
    ├── models--Systran--faster-whisper-large-v3/
    ├── models--pyannote--speaker-diarization/
    └── ...                   # Other downloaded models
```

---

## Backend Development

The backend is the unified server component that powers TranscriptionSuite. It runs inside Docker for production but can be developed natively for faster iteration.

> **Note:** The primary development workflow uses Docker (see [Development Workflow](#development-workflow)). This section is for developers who need to work directly on the backend code with faster iteration cycles.

### Architecture

The backend is organized into focused modules:

```txt
server/backend/
├── api/                              # FastAPI application
│   ├── main.py                       # App factory, lifespan, routing
│   ├── routes/                       # API endpoint modules
│   │   ├── transcription.py          # POST /api/transcribe/audio
│   │   ├── notebook.py               # Audio Notebook CRUD
│   │   ├── search.py                 # Full-text search
│   │   ├── admin.py                  # Admin endpoints
│   │   ├── auth.py                   # Token authentication (login, token CRUD)
│   │   ├── health.py                 # Health checks
│   │   ├── websocket.py              # Real-time audio streaming transcription
│   │   └── llm.py                    # LLM chat endpoints
├── core/                             # ML and audio processing
│   ├── transcription_engine.py       # faster-whisper wrapper (file-based)
│   ├── diarization_engine.py         # PyAnnote wrapper
│   ├── model_manager.py              # Model lifecycle, GPU management & job tracking
│   ├── token_store.py                # Token authentication and management
│   ├── realtime_engine.py            # Async wrapper for real-time STT
│   ├── preview_engine.py             # Preview transcription for standalone clients
│   ├── client_detector.py            # Detect client type (standalone vs web)
│   ├── audio_utils.py                # Audio preprocessing utilities
│   └── stt/                          # Real-time speech-to-text engine
│       ├── engine.py                 # AudioToTextRecorder with VAD
│       ├── vad.py                    # Dual VAD (Silero + WebRTC)
│       └── constants.py              # STT configuration constants
├── database/                         # Data persistence
│   └── database.py                   # SQLite + FTS5 operations
├── logging/                          # Centralized logging
│   └── __init__.py                   # Structured logging configuration
├── config.py                         # Configuration management
└── pyproject.toml                    # Package definition & dependencies
```

#### Lazy Import Optimization

The backend uses **lazy imports** to minimize startup time by deferring heavy ML library loading until actually needed.

**Key principles:**

1. **Module-level imports are minimal**: Only import lightweight dependencies at module load time
2. **Heavy imports are deferred**: ML libraries (torch, faster-whisper, scipy, etc.) are imported inside methods where they're first used
3. **TYPE_CHECKING for type hints**: Use `typing.TYPE_CHECKING` to import types without runtime cost

**Example from `model_manager.py`:**

```python
from typing import TYPE_CHECKING, Any, Dict, Optional

# Type-only imports (no runtime cost)
if TYPE_CHECKING:
    from server.core.stt.engine import AudioToTextRecorder
    from server.core.diarization_engine import DiarizationEngine

class ModelManager:
    def __init__(self, config: Dict[str, Any]):
        # Lazy import - only loads when ModelManager is created
        from server.core.audio_utils import check_cuda_available, get_gpu_memory_info

        self.gpu_available = check_cuda_available()

    def _create_transcription_engine(self) -> "AudioToTextRecorder":
        # Lazy import - only loads when first transcription is requested
        from server.core.stt.engine import AudioToTextRecorder

        return AudioToTextRecorder(...)
```

**Affected files:**
- `api/main.py` - Lazy import of `model_manager` inside `lifespan()`
- `api/routes/websocket.py` - Lazy imports of `model_manager` in route handlers
- `api/routes/notebook.py` - Lazy import of `audio_utils` in upload handler
- `core/model_manager.py` - All heavy imports are lazy (torch, faster-whisper, etc.)

**Startup timing breakdown:**
```
[TIMING] 0.882s - main.py module load complete  ✓
[TIMING] 0.885s - lifespan() started            ✓ (3ms gap)
[TIMING] 3.143s - model manager created         (imports torch)
[TIMING] 9.002s - model preload complete        (loads Whisper model)
```

The ~9 second total startup is dominated by:
- **2.3s**: PyTorch import for GPU checking
- **5.9s**: Whisper model loading into GPU memory

Both are unavoidable when preloading models at startup. The key optimization was eliminating the 9.6s delay *before* lifespan starts.

**Timing instrumentation:**

The server includes optional timing instrumentation in `entrypoint.py` and `main.py` using `_log_time()` functions. These log timestamps to help diagnose startup performance. The overhead is negligible (<1ms per log).

#### Setting Up the Development Environment

**Prerequisites:**
- Python 3.11+
- CUDA 12.8 (for GPU acceleration)
- `uv` package manager

**Steps:**

```bash
cd server/backend
uv venv --python 3.11
uv sync                    # Install all dependencies including diarization
```

The backend uses the package name `server` internally (defined in `pyproject.toml`), so imports use `from server.api import ...`.

**Note:** Speaker diarization via PyAnnote is now included by default. You'll need a HuggingFace token to use diarization features - set it via the `HF_TOKEN` environment variable or in your configuration file.

#### Running the Server Locally

**Development mode with auto-reload:**

```bash
cd server/backend
uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 8000
```

**Production mode:**

```bash
uv run uvicorn server.api.main:app --host 0.0.0.0 --port 8000 --workers 1
```

**With custom configuration:**

```bash
# Point to a specific config file
export CONFIG_PATH=/path/to/config.yaml
uv run uvicorn server.api.main:app --reload
```

**Environment variables:**

The server respects these environment overrides:

| Variable | Purpose | Example |
|----------|---------|----------|
| `LOG_LEVEL` | Logging verbosity | `DEBUG`, `INFO`, `WARNING` |
| `HF_TOKEN` | HuggingFace token for PyAnnote models | `hf_...` |
| `SERVER_HOST` | Bind address | `0.0.0.0` |
| `SERVER_PORT` | HTTP port | `8000` |
| `DATA_DIR` | Base directory for all persistent data | `/data` (Docker), `./data` (local) |

#### Configuration System

The backend uses a **centralized configuration system** where all modules load settings via `get_config()` from `server.config`. This ensures consistent configuration across the entire application.

**Important:** All backend scripts (`engine.py`, `vad.py`, `diarization_engine.py`, `llm.py`, etc.) use `from server.config import get_config` to access configuration. No scripts directly load `config.yaml` with `yaml.safe_load()` - only `config.py` handles YAML loading.

The configuration file is loaded with the following search priority:

1. **User config** (highest priority):
   - Docker: `/user-config/config.yaml` (when `USER_CONFIG_DIR` is mounted)
   - Linux: `~/.config/TranscriptionSuite/config.yaml`
   - Windows: `Documents\TranscriptionSuite\config.yaml`
2. **Default config**:
   - `/app/config.yaml` (Docker container - baked into image)
   - `server/config.yaml` (native development)
   - `./config.yaml` (current directory fallback)

**Note:** A configuration file is required. The server will fail to start if no config file is found.

**Configuration structure:**

```python
from server.config import get_config

config = get_config()

# Access nested configuration
model = config.get("transcription", "model")  # Returns model name
gpu_device = config.transcription["device"]   # Direct dict access
log_level = config.logging["level"]            # Property accessor
```

**Main configuration sections:**

- `main_transcriber` - Primary Whisper model, device, batch settings
- `preview_transcriber` - Optional preview model for standalone clients (smaller, faster)
- `diarization` - PyAnnote model and speaker detection settings
- `remote_server` - Host, port, TLS settings
- `storage` - Database path, audio storage, format
- `local_llm` - LM Studio integration for chat features
- `logging` - Log level, directory, rotation settings

#### Key Modules Explained

##### `api/main.py` - Application Factory

The core FastAPI application:

- **`lifespan()`** - Async context manager for startup/shutdown
  - Initializes database, logging, model manager
  - Preloads transcription model into GPU
  - Cleans up resources on shutdown
- **`create_app()`** - Factory function for app creation
  - Configures CORS middleware
  - Registers all route modules
  - Sets up global exception handler
- **`mount_frontend()`** - Serves React frontend as static SPA

##### `core/model_manager.py` - ML Model Lifecycle

Manages GPU memory, model loading, and job concurrency control:

```python
from server.core.model_manager import get_model_manager

manager = get_model_manager(config)

# Job tracking - ensures only one transcription runs at a time
success, job_id, active_user = manager.job_tracker.try_start_job(client_name="Bill's Laptop")
if not success:
    print(f"Server busy - job running for {active_user}")
else:
    try:
        # Run transcription
        result = engine.transcribe_file(...)
    finally:
        # Always release the job slot
        manager.job_tracker.end_job(job_id)

# Load models (lazy loading)
transcription_model = manager.load_transcription_model()
diarization_pipeline = manager.load_diarization_pipeline()

# Preview engine (for standalone clients only)
manager.on_standalone_client_connected()  # Loads preview model if enabled
manager.on_standalone_client_disconnected()  # Unloads when no clients

# Real-time engine (per session)
realtime_engine = manager.get_realtime_engine(session_id, client_type, language)
manager.release_realtime_engine(session_id)

# Check GPU availability
if manager.gpu_available:
    print(f"GPU: {manager.gpu_info}")

# Cleanup (called automatically on shutdown)
manager.cleanup()
```

**TranscriptionJobTracker:**
- Ensures only one transcription job runs at a time across ALL methods (HTTP, WebSocket)
- Thread-safe with locking for concurrent access from multiple request handlers
- Tracks active job ID and client name for user-friendly error messages
- Returns 409 Conflict via HTTP or `session_busy` via WebSocket when busy

##### `core/transcription_engine.py` - Whisper Wrapper

Unified interface for faster-whisper:

```python
from server.core.transcription_engine import TranscriptionEngine

engine = TranscriptionEngine(config)
result = engine.transcribe(
    audio_path="/path/to/audio.wav",
    language="en",          # or None for auto-detect
    enable_diarization=True # Requires HF_TOKEN
)

# Returns structured output with segments, words, speakers
for segment in result["segments"]:
    print(f"{segment['start']:.2f}s: {segment['text']}")
```

##### `core/stt/` - Real-Time Speech-to-Text Engine

Server-side VAD-based audio processing for real-time transcription:

- **`engine.py`** - `AudioToTextRecorder` class with dual VAD (Silero + WebRTC)
- **`vad.py`** - `VoiceActivityDetector` for robust speech detection
- **`constants.py`** - Configuration constants (thresholds, timing, model defaults)

The STT engine handles silence trimming to prevent Whisper hallucinations and provides callbacks for VAD state changes.

##### `core/realtime_engine.py` - Async Real-Time Wrapper

Async wrapper around the STT engine for WebSocket integration:

- Session-based engine management
- Callbacks for VAD events (`on_vad_start`, `on_vad_stop`, etc.)
- Thread-safe audio buffer management

##### `core/preview_engine.py` - Preview Transcription

Secondary transcription engine for live preview (standalone clients only):

- Uses a smaller, faster model (e.g., `faster-whisper-medium`)
- Only loaded when `preview_transcriber.enabled = true` in config AND a standalone client connects
- Automatically unloaded when no standalone clients are connected
- Saves GPU memory for web-only usage

##### `core/client_detector.py` - Client Type Detection

Detects client type (standalone vs web) from request headers:

- Checks `X-Client-Type` header (set by native clients)
- Falls back to User-Agent pattern matching
- Returns `ClientCapabilities` with feature flags (VAD events, preview support)

##### `database/database.py` - SQLite + FTS5

Database operations for Audio Notebook:

- Full-text search across transcriptions
- Recording metadata storage
- Segment and word-level timestamps
- LLM conversation history

**Schema includes:**
- `recordings` - Recording metadata
- `segments` - Transcription segments with timestamps
- `words` - Word-level timing and confidence
- `recordings_fts` - FTS5 virtual table for search

**Notes:**

- Recordings now support an editable `title` field (stored in `recordings.title`).
  - Frontend allows inline editing by clicking the title in the DayView modal
  - Title updates are saved via `PATCH /api/notebook/recordings/{id}/title`
- For diarized recordings, word timestamps are assigned to speaker segments using overlap/nearest-segment matching to avoid dropping boundary words (e.g. the first word of an utterance).
  - **Bug Fix (Dec 2024)**: Fixed a critical issue where the first word of each speaker utterance was being dropped in diarized transcriptions. The root cause was in `_insert_diarization_segments_with_words()` which was using `word['start'] >= seg_start` instead of `word['start'] > seg_start`, causing boundary words to be skipped when their start time exactly matched the segment start time. Changed to use `>` for end boundary and `>=` for start boundary to ensure all words are captured.
- `conversations` + `messages` - Chat history

**Speaker Diarization:**

The server uses PyAnnote Audio for speaker diarization (identifying "who spoke when"):

- **Model**: `pyannote/speaker-diarization-community-1` (improved over 3.1)
- **Requirements**: HuggingFace token with accepted model license
- **Features**:
  - Automatic speaker detection (typically 2-3 speakers)
  - Segment-level speaker labels
  - Word-level speaker assignment via overlap matching
- **Configuration**: Enable via `enable_diarization=true` parameter in upload endpoint
- **Storage**: Diarization segments stored in `diarization_segments` table with speaker labels
- **Display**: DayView shows speaker chips for each segment when diarization data is available
- **Known Warnings** (Non-Critical): Several benign warnings occur during operation but do not affect functionality:
  - PyTorch Tensor Warning: `audio_utils.py:569` - Non-writable NumPy array converted to PyTorch tensor. PyTorch only reads the data, so undefined behavior is not triggered. Cosmetic issue; fix available by using `.copy()` on the array.
  - PyAnnote torchcodec Warning: Missing torchcodec for audio decoding, but PyAnnote falls back to preloaded in-memory audio. Acceptable because audio is preprocessed before PyAnnote receives it. Docker uses `ubuntu:22.04` base (not nvidia/cuda) to save ~4GB image size.
  - PyAnnote TensorFloat-32 (TF32) Warnings: Reproducibility warnings from PyTorch (see [pyannote/pyannote-audio#1370](https://github.com/pyannote/pyannote-audio/issues/1370)) and pooling `std()` degrees of freedom warnings during inference. TF32 is explicitly disabled before pipeline loading to prevent accuracy issues.
  - All benign warnings are filtered in `diarization_engine.py` using `warnings.catch_warnings()`

##### `token_store.py` - Authentication Management

Token-based authentication system:

- Generates secure admin token on first startup
- Hashes tokens with SHA-256 for secure storage
- Supports token creation, validation, revocation
- Thread-safe with file locking (`tokens.lock`)
- Persists tokens to `/data/tokens/tokens.json`

#### Frontend Development (React UI)

The server includes a React frontend for web access:

**Location:** `server/frontend/`

**Tech stack:**
- React 18 + TypeScript
- Vite (build tool)
- TailwindCSS (styling)
- Lucide React (icons)
- Howler.js (audio playback)

**UI Features:**
- **Inline Title Editing**: Click any recording title in DayView modal to edit it inline. Press Enter to save or Escape to cancel. Changes persist via `PATCH /api/notebook/recordings/{id}/title`.
- **Vertical Scrolling**: Layout component (`Layout.tsx`) uses `overflow-y-auto` on main content area to allow scrolling on long pages (e.g., Import view with many files).
- **Favicon Handling**: Uses relative path `vite.svg` in `index.html` to work correctly when served under `/notebook`, `/record`, or `/admin` base paths. The favicon is served from `/app/static/frontend/vite.svg` in Docker.

**Development workflow:**

```bash
cd server/frontend
npm install
npm run dev  # Starts dev server on http://localhost:1421
```

**API integration:**

The frontend expects the backend API at `http://localhost:8000` by default. During development:

1. Run the backend server on port 8000
2. Run frontend dev server on port 1421
3. Vite will proxy API requests to avoid CORS issues

**Building for production:**

```bash
npm run build  # Output: dist/
```

The Docker build process automatically builds the frontend and serves it as static files.

#### Testing

**Running tests:**

```bash
# All dev tools are in the build/ venv
cd build
uv sync  # Install all dev dependencies (if not already done)
cd ..

# Run tests from project root
./build/.venv/bin/pytest server/backend/tests
```

**Test structure:**

```txt
server/backend/tests/
└── test_ffmpeg_utils.py      # FFmpeg audio processing tests (load, resample, normalize)
```

**Note:** Currently only FFmpeg utilities have test coverage. The test suite validates:
- Audio loading with format conversion and resampling
- Normalization methods (peak, dynaudnorm, loudnorm)
- Resampling quality comparison against scipy reference
- Edge cases (empty audio, stereo-to-mono, invalid inputs)
- Performance benchmarks for real-time processing

Additional tests for API routes, transcription engine, and database operations can be added following the same pytest structure.

**Manual API testing:**

Use the built-in Swagger UI at `http://localhost:8000/docs` for interactive API exploration.

#### Common Development Tasks

**Adding a new API endpoint:**

1. Create route handler in `api/routes/`:

```python
# api/routes/my_feature.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/my-endpoint")
async def my_endpoint():
    return {"status": "ok"}
```

2. Register router in `api/main.py`:

```python
from server.api.routes import my_feature

app.include_router(my_feature.router, prefix="/api/my-feature", tags=["My Feature"])
```

**Modifying transcription behavior:**

Edit `core/transcription_engine.py` - the unified wrapper handles all transcription logic.

**Changing database schema:**

1. Modify `database/database.py`
2. Create migration SQL (manual for now)
3. Update `init_db()` function

**Adjusting logging:**

Edit `logging/setup.py` for custom formatters, handlers, or log levels.

#### Development Tips

1. **GPU Memory Management:**
   - Models are loaded lazily on first use
   - Use `model_manager.cleanup()` to free GPU memory
   - Monitor with `nvidia-smi` or `watch -n 1 nvidia-smi`

2. **Fast Iteration:**
   - Use `--reload` flag with uvicorn for auto-reload
   - Frontend hot-reload works automatically with Vite
   - Database is SQLite - easy to reset by deleting `data/database/notebook.db`

3. **Debugging:**
   - Set `LOG_LEVEL=DEBUG` for verbose output
   - Check `data/logs/server.log` for persistent logs
   - Use `/health` endpoint to verify server is responsive

4. **Docker vs Native:**
   - Docker for production-like testing
   - Native for faster development iteration
   - Keep `server/config.yaml` in sync with Docker config

5. **Code Quality:**
   - Use `ruff` for linting (installed in `build/` venv)
   - Run type checking with `pyright`
   - Follow existing code style (100-char line length)

6. **Testing Multi-Device Support:**
   - Start the Docker server once
   - Connect multiple clients simultaneously (different terminals, devices, or web browsers)
   - All clients authenticate successfully
   - First client to start transcription gets the job slot
   - Other clients receive clear busy notifications with the active user's name
   - Test scenarios:
     - Standalone client recording → another standalone client tries to record
     - Web UI recording → standalone client tries file upload
     - Standalone client recording → web UI tries notebook import
     - Multiple WebSocket connections → only one can record at a time
   - Verify job is released after completion or client disconnect
   - Check logs for job tracking messages: `Started transcription job...` and `Ended transcription job...`

---

## Client Development

### Running from Source

**Local mode (Docker server on the same machine):**

```bash
cd client
uv venv --python 3.11
uv sync --extra kde    # or --extra gnome / --extra windows

uv run transcription-client --host localhost --port 8000
```

**Remote mode (Docker server reachable via Tailscale):**

```bash
cd client
uv run transcription-client --host <your-machine>.tail1234.ts.net --port 8443 --https

# Or with the AppImage:
./TranscriptionSuite-KDE-x86_64.AppImage --host <your-machine>.tail1234.ts.net --port 8443 --https
```

**Notes:**
- Replace host values with your server's actual Tailscale IP or DNS name
- Use `--https` when the Docker server is started with `TLS_ENABLED=true`
- Port `8443` for HTTPS, port `8000` for HTTP
- Client persists CLI overrides to config file, so you only need to pass flags once

### Verbose Logging

Enable detailed diagnostic logging for troubleshooting:

```bash
uv run transcription-client --host <host> --port 8443 --https --verbose

# Or with AppImage:
./TranscriptionSuite-KDE-x86_64.AppImage --verbose
```

**Verbose mode features:**
- DNS resolution diagnostics
- SSL/TLS certificate validation details
- Detailed connection error messages with troubleshooting hints
- HTTP request/response logging
- File-based logs at `~/.config/TranscriptionSuite/logs/client.log`
- Log rotation (5MB per file, 3 backups retained)

**Log locations by platform:**

| Platform | Log Directory |
|----------|--------------|
| Linux | `~/.config/TranscriptionSuite/logs/` |
| macOS | `~/Library/Application Support/TranscriptionSuite/logs/` |
| Windows | `%APPDATA%\TranscriptionSuite\logs\` |

**Note:** Logs are written to files even in packaged versions (AppImage, .exe).

### Troubleshooting Tailscale HTTPS

If you encounter SSL/certificate errors:

1. **Verify certificate validity:**
   ```bash
   openssl s_client -connect <host>:8443 -servername <host>
   ```

2. **Check Tailscale cert status:**
   ```bash
   tailscale status
   curl -vk https://<host>:8443/health
   ```

3. **Common issues:**
   - Certificate hostname mismatch (use exact Tailscale hostname)
   - Server not started with `TLS_ENABLED=true`
   - Cert/key files not mounted correctly in Docker
   - Firewall blocking port 8443

#### DNS Resolution Issues

**Note:** As of December 2024, the client uses async DNS resolution to gracefully handle Tailscale MagicDNS timing issues.

If you see DNS errors like "DNS resolution failed for <your-machine>.tail1234.ts.net":

1. **This is usually a timing issue**, not a configuration problem
2. The client now logs this as WARNING (not ERROR) and continues with connection attempts
3. The actual aiohttp connection will retry DNS resolution with its own timeout
4. See [Tailscale DNS Resolution Issues](#tailscale-dns-resolution-issues) in the Troubleshooting section for detailed diagnosis and solutions

**Quick fix:** Restart Tailscale service:
```bash
sudo systemctl restart tailscaled
# Wait ~5 seconds, then retry connection
```

**Developer note:** The fix was implemented in `client/src/client/common/api_client.py` by replacing blocking `socket.getaddrinfo()` with async `asyncio.get_running_loop().getaddrinfo()` and adding graceful error handling.

### Server Busy Handling

The client automatically handles server busy conditions when another transcription is already running:

**HTTP Transcription (File Upload):**
- Server returns `409 Conflict` status code
- Client raises `ServerBusyError` exception with active user information
- Orchestrator shows user notification: "Server Busy - A transcription is already running for {active_user}"

**WebSocket Recording:**
- Multiple clients can connect and authenticate simultaneously
- When client sends `start` message, server checks if a job is already running
- Server sends `{"type": "session_busy", "data": {"active_user": "<client_name>"}}` message
- Client shows error notification and connection remains open for retry

**Example Error Messages:**
```
Server Busy
A transcription is already running for Bill's Laptop.
Please try again shortly.
```

**Implementation Details:**
- `api_client.py`: Defines `ServerBusyError` exception and handles 409 responses
- `orchestrator.py`: Catches `ServerBusyError` and displays notifications
- Connection remains open after `session_busy` - no need to reconnect

### Connection Management

**Automatic Reconnection:**
- The client automatically attempts to reconnect on connection loss
- Maximum reconnection attempts: **10** (defined by `MAX_RECONNECT_ATTEMPTS` in `orchestrator.py`)
- Reconnection interval: Configurable via `server.reconnect_interval` (default: 10 seconds)
- After max retries, user is notified: "Could not connect after 10 attempts. Use Settings to reconfigure."

**Initial Connection Handling:**
- On first connection failure, the settings dialog automatically opens
- This helps new users configure server details without manual config file editing
- Settings dialog does NOT open on reconnection attempts (only on initial failure)
- Implemented in `orchestrator.py` via `_is_initial_connection` flag

**Configuration:**
```yaml
server:
  auto_reconnect: true          # Enable automatic reconnection
  reconnect_interval: 10        # Seconds between attempts
```

### Platform-Specific Features

All client platforms (KDE, GNOME, Windows) provide the same core features:

**KDE & Windows (PyQt6):**
- Full-featured Qt6-based settings dialog
- System clipboard integration
- System tray with state icons
- Desktop notifications

**GNOME (GTK3 + AppIndicator):**
- GTK3-based settings dialog with tabs (Connection, Audio, Behavior)
- Settings dialog features:
  - Connection: Port, HTTPS toggle, token with show/hide, remote server config
  - Audio: Device selector with refresh button
  - Behavior: Auto-copy clipboard, notifications toggle
- GTK clipboard integration via `Gtk.Clipboard`
- AppIndicator3 tray integration
- Desktop notifications via `notify-send`
- Requires: `gtk3`, `libappindicator-gtk3`, AppIndicator GNOME extension

**Implementation Files:**
- `client/common/tray_base.py` - Base class defining `show_settings_dialog()` and `copy_to_clipboard()` methods
- `client/kde/tray.py` - Qt6 implementation (used by KDE and Windows)
- `client/gnome/tray.py` - GTK3 implementation
- `client/gnome/settings_dialog.py` - GTK3 settings dialog
- `client/common/orchestrator.py` - Connection management and retry logic

---

## Data Storage

### Database Schema

**Tables:**

- `recordings` - Recording metadata (title, duration, date, summary)
- `segments` - Transcription segments with timestamps
- `words` - Word-level timestamps and confidence
- `conversations` - LLM chat conversations
- `messages` - Individual chat messages
- `words_fts` - FTS5 virtual table for full-text search

**Database Features:**

- **WAL Mode**: Enabled for crash safety and concurrent access
- **Atomic Transactions**: Multi-step saves are wrapped in transactions with rollback on failure
- **Full-Text Search**: FTS5 virtual table with triggers for automatic sync
- **Cascade Deletes**: Deleting a recording removes all associated segments, words, and conversations

### Database Migrations (Alembic)

TranscriptionSuite uses [Alembic](https://alembic.sqlalchemy.org/) for database schema versioning.

**Migration files:** `server/backend/database/migrations/versions/`

**Key features:**
- `render_as_batch=True` for SQLite compatibility (required for ALTER TABLE)
- Migrations run automatically on server startup via `run_migrations()`
- Existing databases are upgraded seamlessly (IF NOT EXISTS checks)

**Migration commands (from project root):**

```bash
# Upgrade to latest version (runs automatically on startup)
./build/.venv/bin/alembic -c server/backend/database/migrations/env.py upgrade head

# View current version
./build/.venv/bin/alembic -c server/backend/database/migrations/env.py current

# Create a new migration
./build/.venv/bin/alembic -c server/backend/database/migrations/env.py revision -m "Add new_column to recordings"

# Generate SQL without applying (for review)
./build/.venv/bin/alembic -c server/backend/database/migrations/env.py upgrade head --sql
```

**Creating migrations:**

1. Modify the schema in `server/backend/database/migrations/versions/xxx_your_migration.py`
2. Use `op.add_column()`, `op.drop_column()`, etc. with `batch_alter_table()` for SQLite
3. Always implement both `upgrade()` and `downgrade()` functions

### Database Backups

Automatic backups are created on server startup using SQLite's built-in backup API.

**How it works:**
1. On startup, check age of latest backup
2. If backup is >1 hour old OR no backup exists → create backup async in background
3. Rotate old backups (keep max 3)
4. Never blocks server startup

**Configuration** (in `config.yaml`):

```yaml
backup:
    enabled: true        # Enable/disable automatic backups
    max_age_hours: 1     # Backup if latest is older than this
    max_backups: 3       # Number of backups to keep
```

**Backup location:** `/data/database/backups/` (Docker) or `<data_dir>/database/backups/` (local)

**Manual backup:**

```bash
# Using SQLite's built-in backup (preferred)
sqlite3 /path/to/notebook.db ".backup '/path/to/backup.db'"

# Docker: Copy from volume
docker run --rm -v transcription-suite-data:/data -v $(pwd):/backup \
    alpine cp /data/database/notebook.db /backup/notebook_backup.db
```

**Restore from backup:**

```bash
# Stop the server first
docker compose down

# Replace the database
docker run --rm -v transcription-suite-data:/data -v $(pwd):/backup \
    alpine cp /backup/notebook_backup.db /data/database/notebook.db

# Restart the server
docker compose up -d
```

**Backup files are named:** `notebook_backup_YYYYMMDD_HHMMSS.db`

### Sensitive Data Storage & Lifecycle

This section tracks when and where sensitive configuration data is collected, stored, and accessed across Docker and native/AppImage deployments.

#### 1. Tailscale TLS Certificates (.crt and .key files)

**When Collected:**
- User-initiated: User manually generates certificates using `tailscale cert <hostname>` on their host machine
- One-time setup: Certificates are generated once and reused

**Storage Locations:**

**Host Machine (User's filesystem):**
- Linux: `~/.config/Tailscale/my-machine.crt` and `my-machine.key`
- Windows: `Documents\Tailscale\my-machine.crt` and `my-machine.key`
- macOS: `~/Library/Application Support/Tailscale/my-machine.crt` and `my-machine.key`

**Docker Container:**
- **When mounted**: Only when `TLS_ENABLED=true` and `TLS_CERT_PATH`/`TLS_KEY_PATH` are set
- **How they get there**: Via Docker bind mounts (read-only) from host filesystem
- **Container path**: `/data/certs/my-machine.crt` and `/data/certs/my-machine.key`
- **Important**: These are **bind mounts**, NOT copies. Files remain on host and are mounted into container at runtime
- **Persistence**: NOT stored in the `transcription-suite-data` volume. Must be provided via environment variables on every `docker compose up`

**Native/AppImage:**
- Not applicable: Native clients don't handle TLS certificates
- Clients connect to the server using HTTPS but don't store server certificates

**Key Behavior:**
```bash
# Start with TLS and diarization support
HUGGINGFACE_TOKEN=hf_your_token_here \
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d

# Switch back to local mode (without diarization)
docker compose up -d    # TLS_ENABLED defaults to false

# Local mode with diarization
HUGGINGFACE_TOKEN=hf_your_token_here docker compose up -d
```

> **Important:** Always use `docker compose up -d` (not `docker compose start`) when switching modes. The `start` command only restarts a stopped container without re-reading environment variables or volume mounts. Certificate bind mounts are configured at container creation time.

#### 2. HuggingFace Token

**When Collected:**

**Docker Mode:**
1. Environment variable: Provided via `HUGGINGFACE_TOKEN` env var at startup
2. **Required for diarization**: PyAnnote models require authentication
3. Optional: If not provided, diarization will be disabled (transcription still works)

**Native Development:**
- Set via `HF_TOKEN` environment variable
- Or cached from `huggingface-cli login`

**How to Provide:**

**Docker:**
```bash
HUGGINGFACE_TOKEN=hf_your_token_here docker compose up -d
```

The token is passed to the container as `HF_TOKEN` environment variable and cached by the HuggingFace library in the `/models` volume.

**Getting a HuggingFace Token:**
1. Create a free account at [huggingface.co](https://huggingface.co)
2. Go to Settings → Access Tokens
3. Create a new token with "Read" permissions
4. Accept the PyAnnote model license at [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)

**Native Development:**
- Set via `HF_TOKEN` environment variable
- Or cached from `huggingface-cli login`

**Native/AppImage:**
- Not applicable: Clients don't use HuggingFace tokens
- Only the server (Docker or native backend) needs this token for diarization

#### 3. LM Studio Address

**When Configured:**

**Docker Mode (Host Network):**
- The Docker container runs with `network_mode: "host"`, sharing the host's network stack
- Environment variable: `LM_STUDIO_URL` env var
- Default: `http://127.0.0.1:1234` (localhost works directly with host network mode)
- LM Studio can stay bound to `127.0.0.1` (no need to expose to network)

**Native Development:**
- Configured in `server/config.yaml`
- Default: `http://127.0.0.1:1234`
- Section: `local_llm.base_url`

**Native/AppImage Client:**
- Not applicable: Clients don't connect to LM Studio
- Only the server backend uses LM Studio for chat features

**LM Studio Setup:**
1. Start LM Studio on the host machine
2. Enable server mode (default port 1234)
3. Load a model in LM Studio
4. The "Start LLM" button in the notebook will detect the running server

#### 4. Admin Token (TokenStore System)

The server uses a unified token-based authentication system managed by `TokenStore`. An admin token is automatically generated on first startup and printed to the console logs.

**When Generated:**
- On first server startup, when `/data/tokens/tokens.json` doesn't exist
- The token is printed to stdout with clear formatting for easy copying
- **Important**: Save this token immediately - it's only printed once!

**If you miss the token:**
```bash
# Check the Docker logs for the admin token
docker logs transcription-suite 2>&1 | grep -A 5 "Admin Token:"

# Or view the token store directly (tokens are hashed, but you can see metadata)
docker compose exec transcription-suite cat /data/tokens/tokens.json
```

**Note:** The tokens in `tokens.json` are hashed (SHA-256) for security. You cannot recover the plaintext token from this file - you must use the token printed at first startup.

**Storage Location:**
- File: `/data/tokens/tokens.json` inside the container
- Docker volume: `transcription-suite-data`
- Format: JSON with hashed tokens, client names, expiration, admin flag
- Lock file: `/data/tokens/tokens.lock` (for thread-safe access)

**Token Management:**
- Create new tokens via the Admin Panel at `/record` (requires admin login)
- Or via API: `POST /api/auth/tokens` with admin token in header
- Revoke tokens: `DELETE /api/auth/tokens/{id}`

**Token Storage Locations:**

**Web Browser:**
- Storage: `auth_token` HTTP cookie
- Scope: Path `/`, expires in 30 days
- Set automatically after successful login at `/auth`
- Sent with every request for server-side authentication

**Native/AppImage Client:**
- File: Platform-specific config file
  - Linux: `~/.config/TranscriptionSuite/client.yaml`
  - Windows: `%APPDATA%\TranscriptionSuite\client.yaml`
  - macOS: `~/Library/Application Support/TranscriptionSuite/client.yaml`
- Key: `server.token`
- When stored: After first successful connection or when provided via CLI flag
- Used in `Authorization: Bearer <token>` header for API requests

Structure:
```yaml
server:
  host: localhost
  port: 8000
  use_https: false
  token: "<admin_token_here>"
```

#### Understanding Docker Volume Paths

**Why `/data` inside the container but `_data` on the host?**

These are the same files accessed from different perspectives:

| Path | Where | Description |
|------|-------|-------------|
| `/data/` | **Inside container** | Mount point specified in docker-compose.yml |
| `_data/` | **On host filesystem** | Docker's internal storage directory for volumes |

Docker named volumes are stored at `/var/lib/docker/volumes/<volume-name>/_data/`. The `_data` directory is Docker's convention for the actual data storage location. When you mount a volume to `/data` in the container, Docker maps the contents of the `_data` directory to that mount point.

```
Host filesystem:                                    Container filesystem:
/var/lib/docker/volumes/                           /
└── transcription-suite-data/                      ├── data/          <- Volume mounted here
    └── _data/              ════════════════════>  │   ├── database/
        ├── database/                              │   ├── audio/
        ├── audio/                                 │   ├── logs/
        ├── logs/                                  │   └── tokens/
        └── tokens/                                └── ...
```

---

## Configuration Reference

### Configuration System Overview

TranscriptionSuite uses a YAML configuration file with the following search priority:

| Priority | Location | Purpose |
|----------|----------|---------|
| 1 (highest) | User config directory (see below) | Custom user settings |
| 2 | `/app/config.yaml` | Docker container defaults (baked into image) |
| 3 | `server/config.yaml` | Local development |
| 4 | `./config.yaml` | Current directory fallback |

**User Config Directory by Platform:**

| Platform | Config Directory | Config File |
|----------|-----------------|-------------|
| **Linux** | `~/.config/TranscriptionSuite/` | `config.yaml` |
| **Windows** | `Documents\TranscriptionSuite\` | `config.yaml` |
| **Docker** | Mounted via `USER_CONFIG_DIR` env var | `/user-config/config.yaml` |

### Customizing Server Configuration

To customize the server configuration:

1. **Create the config directory:**

   **Linux:**
   ```bash
   mkdir -p ~/.config/TranscriptionSuite
   ```

   **Windows (PowerShell):**
   ```powershell
   mkdir "$env:USERPROFILE\Documents\TranscriptionSuite" -Force
   ```

2. **Download the default config file:**

   Copy `server/config.yaml` from the repository to your config directory:

   **Linux:**
   ```bash
   curl -o ~/.config/TranscriptionSuite/config.yaml \
     https://raw.githubusercontent.com/your-repo/TranscriptionSuite/main/server/config.yaml
   ```

   Or manually copy from the repo if you have it cloned.

3. **Edit the settings you want to change:**

   ```bash
   # Linux
   nano ~/.config/TranscriptionSuite/config.yaml

   # Windows - open in your preferred editor
   notepad "$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml"
   ```

4. **Start Docker with the user config directory mounted:**

   **Linux:**
   ```bash
   USER_CONFIG_DIR=~/.config/TranscriptionSuite docker compose up -d
   ```

   **Windows (PowerShell):**
   ```powershell
   $env:USER_CONFIG_DIR="$env:USERPROFILE\Documents\TranscriptionSuite"
   docker compose up -d
   ```

**What happens:**
- The server looks for `config.yaml` in your mounted user config directory first
- If found, it uses your custom settings instead of the defaults baked into the Docker image
- Server logs are also written to the user config directory as `server.log`
- Your custom config persists across Docker container updates

**Important Notes:**
- The config file uses Docker container paths (e.g., `/data/audio`, `/data/logs`)
- You typically only need to change settings like model names, transcription options, or LLM settings
- Don't change storage paths unless you understand the Docker volume structure
- Changes require a container restart: `docker compose restart`

### Voice Activity Detection (VAD) Configuration

TranscriptionSuite uses Voice Activity Detection to remove silence and improve transcription quality. The VAD approach differs based on the transcription method.

#### VAD by Transcription Method

| Method | VAD Stage 1 | VAD Stage 2 | Purpose |
|--------|-------------|-------------|---------|
| **Static file transcription** | Silero preprocessing | faster_whisper VAD filter (Silero) | Remove silence from existing audio files while maintaining timestamp consistency |
| **Longform recording** | Dual VAD (WebRTC + Silero) | faster_whisper VAD filter (Silero) | Control when to record based on voice activity |
| **Real-time preview** | Dual VAD (WebRTC + Silero) | faster_whisper VAD filter (Silero) | Control when to record based on voice activity |

#### Static File Transcription VAD

**Two-stage approach:**
1. **Stage 1 - Silero preprocessing**: Processes the entire audio file upfront, intelligently removes silence while preserving natural pauses, maintains timestamp consistency with playback
2. **Stage 2 - faster_whisper VAD filter**: Silero VAD during Whisper transcription as additional safety net

**Configuration:**

```yaml
static_transcription:
  # Stage 1: Silero preprocessing removes silence before transcription
  # Silero VAD is used for static transcription to ensure timestamps align
  # with the original audio during playback
  silero_vad_preprocessing: true
  silero_vad_sensitivity: 0.5  # 0.0-1.0, higher = more sensitive to speech (lower silence removal)
```

**How it works:**
- Silero VAD processes 512ms audio chunks (optimal for accurate speech detection)
- Uses neural-network-based probability scoring for robust speech vs silence detection
- Sensitivity threshold: speech detected when probability > (1 - sensitivity)
  - 0.5 = balanced: removes most silence while preserving important pauses
  - 0.3 = aggressive: removes more silence (use if audio has many gaps)
  - 0.7 = conservative: keeps more audio including pauses (use for natural speech)
- Logs duration removed (e.g., "Silero VAD preprocessing: removed 5.2s of silence (60.0s -> 54.8s)")
- Whisper receives shorter audio with silence already removed
- **Critical for diarization**: Ensures word timestamps match with diarization segment boundaries

#### Longform & Real-Time Preview VAD

**Two-stage approach:**
1. **Stage 1 - Dual VAD for recording control**: WebRTC + Silero work together to decide when to start/stop recording
2. **Stage 2 - faster_whisper VAD filter**: Silero VAD during Whisper transcription

**Configuration:**

```yaml
stt:
  # WebRTC VAD for fast initial screening
  webrtc_sensitivity: 3  # 0-3, higher = less sensitive to noise

  # Use Silero for end-of-speech detection (more accurate but uses more GPU)
  silero_deactivity_detection: false

  # Recording timing
  post_speech_silence_duration: 0.6  # Silence duration before stopping recording
  min_length_of_recording: 0.5       # Minimum recording length
  pre_recording_buffer_duration: 1.0 # Pre-roll buffer to capture speech onset

preview_transcriber:
  # Silero sensitivity for preview (different from main transcriber)
  silero_sensitivity: 0.4  # 0.0-1.0, higher = more sensitive
```

**How it works:**
- WebRTC VAD performs fast initial screening of live audio
- Silero VAD confirms with higher accuracy (both must agree for voice to be "active")
- When voice detected: start recording
- When silence detected for `post_speech_silence_duration`: stop recording
- Silence is never recorded in the first place, so the final audio naturally contains only voiced segments

#### Functional Equivalence

While the implementation differs, **all methods achieve the same goal: transcribing audio with silence removed**.

- **Static files**: Silence is removed from existing audio before transcription (preprocessing)
- **Live recording**: Silence is prevented from being recorded in the first place (recording control)

Both then use **Stage 2** (faster_whisper VAD filter with Silero) during transcription as an additional safety net.

**Why this matters:**
- Reduces transcription time (less audio to process)
- Improves accuracy (Whisper performs better without long silence)
- Prevents hallucinations (long silence can cause Whisper to generate phantom text)

#### Technical Note: Two Audio Processing Paradigms

The `AudioToTextRecorder` class serves two distinct use cases with different VAD workflows:

**1. Streaming/Live Recording Workflow:**
- Audio arrives in real-time via WebSocket (`feed_audio()`)
- VAD controls the recording state machine: `inactive → listening → recording → transcribing`
- Dual VAD (WebRTC + Silero) decides **when to start/stop recording**
- Silence is never recorded in the first place
- Entry points: `feed_audio()` → `listen()` → `wait_audio()` → `transcribe()`

**2. Static File Transcription Workflow:**
- Audio already exists as a complete file
- No recording state machine needed (audio is already captured)
- VAD removes silence from existing audio via preprocessing
- Entry points: `transcribe_file()` → `transcribe_audio()`

Both workflows apply VAD, but differently:
- **Streaming**: VAD controls recording (preventive - silence never recorded)
- **Static files**: VAD removes silence (corrective - silence removed from existing audio)

The methods `transcribe_file()` and `transcribe_audio()` "bypass the streaming recording workflow" (not VAD itself). They skip the real-time state machine and directly transcribe audio data, applying WebRTC preprocessing (Stage 1) and faster_whisper VAD filter (Stage 2) as appropriate.

### Static File Transcription Configuration

There are four methods of static file transcription, each with different configuration behavior:

| Method | Endpoint | Config Source | word_timestamps | diarization |
|--------|----------|---------------|-----------------|-------------|
| **Standalone client** | `/api/transcribe/audio` | `static_transcription` section | From config | From config |
| **Recorder web UI** | `/api/transcribe/audio` | Main transcriber defaults | Always `false` | Always `false` |
| **Notebook import** | `/api/notebook/transcribe/upload` | UI form parameters | From UI toggle | From UI toggle |
| **Notebook day view** | `/api/notebook/transcribe/upload` | UI form parameters | From UI toggle | From UI toggle |

**Client Detection:**
- The server detects standalone clients via the `X-Client-Type: standalone` header
- Standalone clients use defaults from `config.yaml` → `static_transcription` section
- Web UI clients (Recorder page) always disable word_timestamps and diarization for speed
- Audio Notebook UI provides toggles that override any defaults

### Server Configuration (Docker)

Environment variables:

- `HF_TOKEN` - HuggingFace token for PyAnnote models
- `USER_CONFIG_DIR` - Path to user config directory (for custom config.yaml and logs)
- `LOG_LEVEL` - Logging verbosity (DEBUG, INFO, WARNING, ERROR)
- `LM_STUDIO_URL` - LM Studio API URL for chat features
- `TLS_ENABLED` - Enable HTTPS (remote mode)
- `TLS_CERT_PATH` - Path to TLS certificate
- `TLS_KEY_PATH` - Path to TLS private key

### Client Configuration

Client config location: `~/.config/TranscriptionSuite/client.yaml` (Linux), `Documents\TranscriptionSuite\client.yaml` (Windows)

**Full configuration with comments:**

```yaml
server:
  # Local server settings (used when use_remote is false)
  host: localhost              # Hostname for local connections
  port: 8000                   # Server port (8000 for HTTP, 8443 for HTTPS)
  use_https: false             # Enable HTTPS/TLS encryption
  token: ""                    # Authentication token from server

  # Remote server settings (Tailscale/VPN connections)
  use_remote: false            # Enable remote server mode
  remote_host: ""              # ONLY the hostname - no http://, no port
                               # Examples:
                               #   - desktop.tail1234.ts.net
                               #   - 100.101.102.103
                               # Configure port and HTTPS separately above

  # Connection behavior
  auto_reconnect: true         # Automatically reconnect on disconnect
  reconnect_interval: 10       # Seconds between reconnection attempts
  timeout: 30                  # General request timeout (seconds)
  transcription_timeout: 300   # Transcription request timeout (seconds)

recording:
  sample_rate: 16000           # Audio sample rate (fixed for Whisper)
  device_index: null           # Audio input device (null = default)

clipboard:
  auto_copy: true              # Copy transcription to clipboard automatically

ui:
  notifications: true          # Show desktop notifications
  start_minimized: false       # Start with tray icon only (no window)
  left_click: start_recording  # Left-click action: start_recording | show_menu
  middle_click: stop_transcribe # Middle-click: stop_transcribe | cancel_recording | none
```

**Key Configuration Concepts:**

**1. Local vs Remote Connection:**

The client supports two modes controlled by `use_remote`:

- **Local mode** (`use_remote: false`): Connects to `host:port` (usually `localhost:8000`)
- **Remote mode** (`use_remote: true`): Connects to `remote_host:port` (e.g., Tailscale server)

**2. Understanding `host` vs `remote_host`:**

| Setting | Purpose | Valid Values |
|---------|---------|--------------|
| `host` | Local server hostname | `localhost`, `127.0.0.1`, or any local hostname |
| `remote_host` | Remote server hostname | ONLY hostname - no protocol, no port |

**Common Mistakes:**

```yaml
# WRONG - includes protocol and port
remote_host: "https://desktop.tail1234.ts.net:8443/"

# CORRECT - hostname only
remote_host: "desktop.tail1234.ts.net"
```

The client will automatically strip protocols and ports from `remote_host` if accidentally included.

**3. Port and HTTPS Settings:**

The `port` and `use_https` settings apply to **both** local and remote connections:

```yaml
# Example: Local HTTP connection
use_remote: false
host: localhost
port: 8000
use_https: false

# Example: Remote HTTPS connection via Tailscale
use_remote: true
remote_host: desktop.tail1234.ts.net
port: 8443
use_https: true
```

**4. Authentication Token:**

The token is automatically saved after first successful connection or when provided via CLI:

```bash
# Token is saved to config after this command
uv run transcription-client --token "your_admin_token_here"
```

Tokens are used in `Authorization: Bearer <token>` headers for API authentication.

### Native Development Configuration

`server/config.yaml` - Full configuration for running without Docker.

---

## Troubleshooting

### Docker GPU Access

GPU passthrough requirements depend on host OS:

- Linux: requires the NVIDIA driver + NVIDIA Container Toolkit on the host
- Windows: requires Docker Desktop (WSL2 backend) + NVIDIA driver with WSL support (the GPU is exposed to the Linux environment via WSL2)

```bash
# Verify GPU is accessible
docker run --rm --gpus all nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04 nvidia-smi

# Check container logs
docker compose logs -f
```

### Docker Logs

There are two primary places to read server logs:

- **Container stdout/stderr** (Uvicorn + app console logs)
  - `docker compose logs -f transcription-suite`
  - `docker logs -f transcription-suite`
- **Persistent log files** (rotating)
  - Stored in the Docker volume under `/data/logs/`
  - Main file: `/data/logs/server.log`
  - View from host:

```bash
docker compose exec transcription-suite ls -la /data/logs
docker compose exec transcription-suite tail -n 200 -f /data/logs/server.log
```

### Health Check Issues

The container health check automatically adapts to your TLS configuration:

- **HTTP mode** (`TLS_ENABLED=false`): Checks `http://localhost:8000/health`
- **HTTPS mode** (`TLS_ENABLED=true`): Checks `https://localhost:8443/health` (with `-k` to skip cert validation)

**If the container becomes unhealthy:**

1. **Check current health status:**
   ```bash
   docker compose ps
   docker inspect transcription-suite | grep Health -A 10
   ```

2. **Test health endpoints manually:**
   ```bash
   # HTTP mode
   docker compose exec transcription-suite curl -f http://localhost:8000/health
   
   # HTTPS mode
   docker compose exec transcription-suite curl -f -k https://localhost:8443/health
   ```

3. **Common causes:**
   - Server startup failure (check logs above)
   - Port mismatch (server listening on wrong port)
   - TLS certificate issues (in HTTPS mode)
   - Resource exhaustion (GPU memory, disk space)

4. **Manual health check restart:**
   ```bash
   docker compose restart transcription-suite
   # Wait 60 seconds for start_period, then check:
   docker compose ps
   ```

### Tailscale DNS Resolution Issues

If the client fails to connect with DNS resolution errors like:

```
DNS resolution failed for <your-machine>.tail1234.ts.net: [Errno -2] Name or service not known
```

**The client now automatically falls back to using Tailscale IP addresses** when DNS resolution fails for `.ts.net` hostnames. This handles both timing issues and permanent DNS misconfigurations.

#### Root Cause

The error typically occurs when:
- **Timing issue:** Client starts before Tailscale MagicDNS is fully initialized
- **DNS fight:** `/etc/resolv.conf` has been overwritten (common on mobile networks)
- **systemd-resolved not running:** The system DNS resolver doesn't forward `.ts.net` queries to Tailscale

**To diagnose**, run `tailscale status` on the client machine. If you see:
```
# Health check:
#     - System DNS config not ideal. /etc/resolv.conf overwritten.
```

This indicates a "DNS fight" where NetworkManager (or another tool) has overwritten DNS configuration, preventing Tailscale's MagicDNS from working.

#### Automatic IP Fallback (December 2024)

When DNS resolution fails for a `.ts.net` hostname, the client automatically:
1. Queries `tailscale status --json` to find the device's IP
2. Switches to using the IP address directly
3. Preserves the original hostname for SSL certificate validation

**Files:**
- `client/src/client/common/tailscale_resolver.py` - Tailscale CLI helper
- `client/src/client/common/api_client.py` - Fallback logic in `_diagnose_connection()`

**Log output when fallback activates:**
```
WARNING - DNS pre-check failed for <your-machine>.tail1234.ts.net: [Errno -2] Name or service not known
INFO - Attempting Tailscale IP fallback for <your-machine>.tail1234.ts.net
INFO - Tailscale IP fallback: <your-machine>.tail1234.ts.net -> 100.98.45.21
```

**Why this works:**
- Tailscale connectivity works even when DNS doesn't (the VPN tunnel is independent of DNS)
- The `tailscale` CLI can resolve device IPs locally without DNS
- SSL certificates are validated using `server_hostname` parameter, so HTTPS still works

#### Verification Steps

**1. Check Tailscale is connected:**

```bash
tailscale status
# Should show your machine's IP, name, and "active; direct" connection
```

**2. Verify DNS resolution works:**

```bash
# Resolve the Tailscale hostname
getent hosts <your-machine>.tail1234.ts.net

# Or use dig/nslookup
dig <your-machine>.tail1234.ts.net
```

**3. Check systemd-resolved configuration:**

```bash
resolvectl status
# Look for:
# - DNS Servers: 100.100.100.100 (on tailscale0 interface)
# - DNS Domain: ~<your-tailnet>.ts.net
```

**4. Test direct IP connection:**

```bash
# If DNS fails, try using Tailscale IP directly
uv run transcription-client --host 100.98.45.21 --port 8443 --https
```

#### Restarting/Resetting Tailscale MagicDNS

If you suspect MagicDNS is stuck, try these methods (from least to most aggressive):

**Method 1: Restart Tailscale service** (least intrusive)

```bash
sudo systemctl restart tailscaled
# Wait ~5 seconds for initialization
tailscale status
```

**Method 2: Disconnect and reconnect**

```bash
sudo tailscale down
sudo tailscale up --accept-dns=true
# Wait ~10 seconds for full DNS propagation
```

**Method 3: Force DNS configuration refresh**

```bash
# Restart both Tailscale and systemd-resolved
sudo systemctl restart tailscaled
sudo systemctl restart systemd-resolved
# Wait ~10 seconds
resolvectl status  # Verify DNS is configured
```

**Method 4: Verify Tailscale admin settings**

1. Go to [https://login.tailscale.com/admin/dns](https://login.tailscale.com/admin/dns)
2. Verify MagicDNS is enabled
3. Check your Tailnet name/suffix (e.g., `tail1234.ts.net`)
4. Confirm HTTPS certificates are enabled (if using TLS)
5. Force a configuration sync:
   ```bash
   sudo tailscale down && sudo tailscale up --accept-dns=true --accept-routes
   ```

**Method 5: Full reset** (nuclear option - only if above methods fail)

```bash
# This will remove all Tailscale state and require re-authentication
sudo systemctl stop tailscaled
sudo rm -rf /var/lib/tailscale/
sudo systemctl start tailscaled
sudo tailscale up
# Re-authenticate via browser
```

#### Fixing DNS Fight Permanently (Optional)

If you want DNS to work natively (instead of relying on IP fallback), fix the DNS configuration on the client machine:

**Option A: Enable systemd-resolved (Recommended for Linux)**

```bash
# 1. Enable and start systemd-resolved
sudo systemctl enable systemd-resolved
sudo systemctl start systemd-resolved

# 2. Link /etc/resolv.conf to systemd-resolved's stub
sudo ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

# 3. Restart Tailscale to pick up the change
sudo systemctl restart tailscaled

# 4. Verify - tailscale status should no longer show DNS warning
tailscale status
```

**Option B: Force Tailscale DNS override**

```bash
sudo tailscale down
sudo tailscale up --accept-dns=true --reset
```

#### Resilience Summary

The client is now resilient to DNS issues through multiple mechanisms:
- **Async DNS resolution:** Non-blocking, won't hang the event loop
- **Automatic IP fallback:** Uses `tailscale status --json` when DNS fails
- **SSL hostname preservation:** HTTPS works even when connecting via IP
- **Graceful degradation:** Warnings instead of errors for diagnostic checks

**For developers:** The `TailscaleResolver` class in `client/common/tailscale_resolver.py` can be reused for other Tailscale-aware applications.

### Model Loading

**First container startup**: On initial boot, the server takes ~9 seconds total to start:
- **0.9s**: FastAPI module loading and route registration
- **2.3s**: PyTorch import for GPU detection
- **6s**: Whisper model loading into GPU memory (~3GB VRAM)

The container health check may report "healthy" before model loading completes. Use `docker compose logs -f` to monitor startup progress and watch for the "Server startup complete" message.

**First transcription of a new model**: Additional time (2-5 minutes) is needed if Whisper models are being downloaded from HuggingFace on first use. Monitor with `docker compose logs -f` to see download progress. Models are cached in the `transcription-suite-models` volume and don't need to be re-downloaded on container recreation.

### FastAPI Startup Errors

**Server Bootloop with FastAPIError:**

If the server crashes on startup with an error like:

```
fastapi.exceptions.FastAPIError: Invalid args for response field! 
Hint: check that starlette.responses.FileResponse | starlette.responses.JSONResponse is a valid Pydantic field type.
```

**Cause**: FastAPI inspects route handler return type annotations to generate response models. Union types like `FileResponse | JSONResponse` are not valid Pydantic field types and cause import-time crashes.

**Solution**: Remove the return type annotation from the problematic route handler:

```python
# Bad - causes bootloop
@app.get("/favicon.ico")
async def favicon() -> FileResponse | JSONResponse:
    ...

# Good - no type annotation
@app.get("/favicon.ico")
async def favicon():
    ...
```

Alternatively, use `response_model=None` in the decorator to disable response model generation.

### cuDNN Library Errors

> **Note:** The current Dockerfile uses `ubuntu:22.04` as the base image (not nvidia/cuda) and relies on PyTorch's bundled CUDA/cuDNN libraries. The `LD_LIBRARY_PATH` is pre-configured to prioritize PyTorch's bundled cuDNN. You should not encounter these errors with the standard build.

If you see errors like:

```
Unable to load any of {libcudnn_ops.so.9.1.0, libcudnn_ops.so.9.1, libcudnn_ops.so.9, libcudnn_ops.so}
Invalid handle. Cannot load symbol cudnnCreateTensorDescriptor
```

This means the cuDNN libraries cannot be found. The `faster-whisper` library uses CTranslate2 which requires cuDNN libraries.

**Current Architecture:** The Dockerfile uses a minimal `ubuntu:22.04` base image and PyTorch pip packages that bundle their own CUDA/cuDNN libraries (~4.1 GB). These are prioritized via `LD_LIBRARY_PATH`:

```dockerfile
ENV LD_LIBRARY_PATH=/app/.venv/lib/python3.11/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.11/site-packages/torch/lib:$LD_LIBRARY_PATH
```

**If you encounter this error**, rebuild the container to ensure the environment is correctly configured:

```bash
cd server/docker
docker compose build --no-cache
docker compose up -d
```

#### cuDNN Version Mismatch (Historical)

> **Note:** This issue is pre-emptively fixed in the current Dockerfile via `LD_LIBRARY_PATH` configuration. This section is kept for reference if you're customizing the Docker build.

If you see errors like:

```
cuDNN version incompatibility: PyTorch was compiled against (9, 8, 0) but found runtime version (9, 7, 0)
```

This occurs when PyTorch expects a different cuDNN version than what's being loaded. The `LD_LIBRARY_PATH` environment variable determines library search order.

**Solution**: Ensure `LD_LIBRARY_PATH` prioritizes PyTorch's bundled cuDNN (already configured in the standard Dockerfile):

```dockerfile
# Prioritize PyTorch's bundled cuDNN
ENV LD_LIBRARY_PATH=/app/.venv/lib/python3.11/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.11/site-packages/torch/lib:$LD_LIBRARY_PATH
```

**Key Points**:
- PyTorch 2.8.0 bundles cuDNN 9.8.0
- The path must match your virtual environment location (check `UV_PROJECT_ENVIRONMENT` in Dockerfile)
- Both `nvidia/cudnn/lib` and `torch/lib` should be included

### Favicon 404 Errors

**Problem**: Browser requests `/vite.svg` or `/favicon.ico` resulting in 404 errors or auth redirects in TLS mode.

**Root Cause**: 
- Absolute favicon path (`href="/vite.svg"`) doesn't work when frontend is served under base paths like `/notebook`
- Missing `/favicon.ico` route causes browsers to hit auth middleware in TLS mode

**Solution**:
1. **Frontend**: Change `index.html` favicon to relative path:
   ```html
   <link rel="icon" type="image/svg+xml" href="vite.svg" />
   ```

2. **Backend**: Add `/favicon.ico` route and mark as public:
   ```python
   PUBLIC_ROUTES = {
       "/health",
       "/api/auth/login",
       "/auth",
       "/auth/",
       "/favicon.ico",  # Add this
   }
   
   @app.get("/favicon.ico", include_in_schema=False)
   async def favicon():
       icon_path = Path("/app/static/frontend/vite.svg")
       if icon_path.exists():
           return FileResponse(icon_path)
       return JSONResponse(status_code=204, content=None)
   ```

3. **Static Asset**: Ensure `vite.svg` exists in `frontend/public/` directory so Vite copies it to build output.

### GNOME Tray Not Showing

Install the AppIndicator extension:

- [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/)

### GNOME Tray Behavior (Left-Click)

**Platform Limitation**: On GNOME with AppIndicator, left-clicking the tray icon opens the menu instead of starting recording. This is a technical limitation of the AppIndicator API.

**Why this happens:**
- AppIndicator (used by GNOME) only supports menu-based interactions
- Unlike KDE/Windows (which use Qt's QSystemTrayIcon), AppIndicator doesn't provide click event handlers
- The library only exposes a `menu` property, not `activate` signals for direct clicks

**Workaround:**
- Use the menu to start recording: Click tray icon → "Start Recording"
- Or use keyboard shortcuts if configured in your system

**Technical Details:**
- KDE and Windows clients use `QSystemTrayIcon.activated` signal for click detection
- GNOME client uses `AppIndicator3.Indicator` which only supports menu attachment
- This is an upstream limitation of the AppIndicator specification, not a TranscriptionSuite bug

### Permission Errors

```bash
# Fix Docker volume permissions
docker compose down
docker volume rm transcription-data
docker compose up -d
```

### AppImage Startup Failures

If the AppImage fails to start without any visible error:

**Development Note**: Avoid using GUI tools like Gear Lever to launch AppImages during development. They suppress stderr output, making it impossible to diagnose startup failures. Always run from terminal to see error messages.

**1. Run from terminal to see errors:**

```bash
./TranscriptionSuite-KDE-x86_64.AppImage
```

**2. Check if logs were created:**

```bash
# Linux
ls -la ~/.config/TranscriptionSuite/logs/

# If no logs exist, the app crashed before logging initialized
```

**3. Common causes:**

- **Missing PyQt6**: The AppImage build must include PyQt6. Rebuild with updated dependencies:
  ```bash
  cd build
  rm -rf .venv
  uv venv && uv sync
  cd ..
  ./build/build-appimage-kde.sh
  ```

- **Missing system libraries**: Check for missing shared libraries:
  ```bash
  ./TranscriptionSuite-KDE-x86_64.AppImage --appimage-extract
  ldd squashfs-root/usr/bin/TranscriptionSuite-KDE
  ```

- **Wayland/X11 issues**: Try forcing X11 backend:
  ```bash
  QT_QPA_PLATFORM=xcb ./TranscriptionSuite-KDE-x86_64.AppImage
  ```

---

## Dependencies

### Server (Docker)

- Python 3.11
- FastAPI + Uvicorn
- faster-whisper (CTranslate2 backend)
- PyAnnote Audio 4.0.3+ (for speaker diarization)
- PyTorch 2.8.0 + TorchAudio 2.8.0
- SQLite with FTS5
- NVIDIA GPU with CUDA support (PyTorch bundles CUDA/cuDNN libraries)

**Key Version Constraints:**
- PyTorch 2.8.0 is pinned for compatibility with PyAnnote Audio 4.0.3
- PyTorch bundles cuDNN 9.8.0 (prioritized via `LD_LIBRARY_PATH`)
- TorchAudio is being deprecated but still required by PyAnnote and Silero VAD
- Docker base image is `ubuntu:22.04` (minimal, no system CUDA)

> **Note:** The current Dockerfile uses `ubuntu:22.04` as the base image (not nvidia/cuda) and relies on PyTorch's bundled CUDA/cuDNN libraries. The `LD_LIBRARY_PATH` is pre-configured to prioritize PyTorch's bundled cuDNN.

### Client

- Python 3.11
- aiohttp (async HTTP client)
- PyAudio (audio recording)
- PyQt6 (KDE/Windows) or GTK3+AppIndicator (GNOME)
- pyperclip (clipboard)
