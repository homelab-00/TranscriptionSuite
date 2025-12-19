# TranscriptionSuite - Developer Notes

This document contains technical details, architecture decisions, and development notes for TranscriptionSuite.

## Table of Contents

- [Architecture Overview](#architecture-overview)
  - [Design Decisions](#design-decisions)
- [Project Structure](#project-structure)
  - [pyproject.toml Files](#pyprojecttoml-files)
- [API Reference](#api-reference)
  - [Endpoints](#endpoints)
  - [Swagger UI](#swagger-ui)
- [Development Setup](#development-setup)
  - [Local Python Development](#local-python-development)
  - [Docker Development](#docker-development)
    - [Local vs Remote Mode](#local-vs-remote-mode)
    - [Docker Build & Runtime Notes](#docker-build--runtime-notes)
      - [Config templates](#config-templates)
      - [Frontend build behavior](#frontend-build-behavior)
      - [Auditing the web frontends](#auditing-the-web-frontends)
  - [Client Development](#client-development)
  - [Dev & Build Tools](#dev--build-tools)
- [Building Executables](#building-executables)
  - [KDE AppImage](#kde-appimage)
  - [GNOME AppImage](#gnome-appimage)
  - [Windows Executable](#windows-executable)
- [Data Storage](#data-storage)
  - [Docker Volume Structure](#docker-volume-structure)
  - [Database Schema](#database-schema)
- [Architectural Refactoring History](#architectural-refactoring-history)
  - [Original Architecture (Pre-Docker)](#original-architecture-pre-docker)
  - [New Architecture (Docker-first)](#new-architecture-docker-first)
- [Configuration Reference](#configuration-reference)
  - [Server Configuration (Docker)](#server-configuration-docker)
  - [Client Configuration](#client-configuration)
  - [Native Development Configuration](#native-development-configuration)
- [Troubleshooting](#troubleshooting)
  - [Docker GPU Access](#docker-gpu-access)
  - [Docker Logs](#docker-logs)
  - [Model Loading](#model-loading)
  - [GNOME Tray Not Showing](#gnome-tray-not-showing)
  - [Permission Errors](#permission-errors)
- [Dependencies](#dependencies)
  - [Server (Docker)](#server-docker)
  - [Client](#client)

---

## Architecture Overview

TranscriptionSuite uses a **client-server architecture**:

```txt
┌─────────────────────────────────────────────────────────────┐
│                     Docker Container                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  TranscriptionSuite Server                          │    │
│  │  - FastAPI REST API                                 │    │
│  │  - faster-whisper transcription                     │    │
│  │  - PyAnnote diarization                             │    │
│  │  - Audio Notebook (React frontend)                  │    │
│  │  - SQLite + FTS5 search                             │    │
│  └─────────────────────────────────────────────────────┘    │
│                          ↕ HTTP/WebSocket                   │
└─────────────────────────────────────────────────────────────┘
                           ↕
┌─────────────────────────────────────────────────────────────┐
│                     Native Clients                          │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐                │
│  │ KDE Tray  │  │GNOME Tray │  │Windows Tray│               │
│  │ (PyQt6)   │  │(GTK+AppInd)│ │ (PyQt6)   │                │
│  └───────────┘  └───────────┘  └───────────┘                │
│  - Microphone recording                                     │
│  - Clipboard integration                                    │
│  - System notifications                                     │
└─────────────────────────────────────────────────────────────┘
```

### Design Decisions

- **Server in Docker**: All ML/GPU operations run in Docker for reproducibility and isolation
- **Native clients**: System tray, microphone, clipboard require native access (can't be containerized)
- **Single port**: Server exposes everything on port 8000 (API, WebSocket, static files)
- **SQLite + FTS5**: Lightweight full-text search without external dependencies

---

## Project Structure

```txt
TranscriptionSuite/
├── client/                       # Native client (runs locally)
│   ├── src/client/               # Python package source
│   │   ├── common/               # Shared client code
│   │   │   ├── api_client.py     # HTTP client for server communication
│   │   │   ├── audio_recorder.py # PyAudio recording wrapper
│   │   │   ├── orchestrator.py   # Main controller, state machine
│   │   │   ├── tray_base.py      # Abstract tray interface
│   │   │   ├── config.py         # Client configuration
│   │   │   └── models.py         # Shared data models
│   │   ├── kde/                  # KDE Plasma (PyQt6)
│   │   │   └── tray.py           # Qt6 system tray implementation
│   │   ├── gnome/                # GNOME (GTK + AppIndicator)
│   │   │   └── tray.py           # GTK/AppIndicator implementation
│   │   ├── windows/              # Windows (PyQt6)
│   │   │   └── tray.py           # Windows tray (same as KDE)
│   │   ├── build/                # Build configurations
│   │   │   ├── pyinstaller-kde.spec
│   │   │   └── pyinstaller-windows.spec
│   │   └── __main__.py           # CLI entry point
│   ├── scripts/                  # Build and setup scripts
│   │   ├── build-appimage-kde.sh     # Build KDE AppImage
│   │   ├── build-appimage-gnome.sh   # Build GNOME AppImage
│   │   ├── setup-client-kde.sh       # Setup KDE dev environment
│   │   ├── setup-client-gnome.sh     # Setup GNOME dev environment
│   │   ├── setup-client-windows.ps1  # Setup Windows dev environment
│   │   └── pyproject.toml            # Dev/build tools (separate venv)
│   └── pyproject.toml            # Client package + dependencies
│
├── docker/                       # Docker infrastructure
│   ├── Dockerfile                # Multi-stage build (frontend + Python)
│   ├── docker-compose.yml        # Unified local + remote deployment
│   ├── entrypoint.py             # Container entrypoint with setup wizard
│   └── .dockerignore             # Build context exclusions
│
├── native_src/                   # Python source for local development
│   ├── MAIN/                     # Legacy: Core transcription logic
│   ├── DIARIZATION/              # Legacy: Speaker diarization
│   ├── AUDIO_NOTEBOOK/           # Audio Notebook frontend (React)
│   ├── REMOTE_SERVER/            # Unified server components
│   │   ├── backend/              # Unified backend (runs in Docker + native)
│   │   │   ├── api/              # FastAPI application
│   │   │   │   ├── main.py       # App factory, lifespan, static mounting
│   │   │   │   └── routes/       # API endpoints
│   │   │   ├── core/             # ML engines
│   │   │   │   ├── transcription_engine.py  # Unified Whisper wrapper
│   │   │   │   ├── diarization_engine.py    # PyAnnote wrapper
│   │   │   │   ├── model_manager.py         # Model lifecycle management
│   │   │   │   └── audio_utils.py           # Audio processing utilities
│   │   │   ├── database/         # SQLite + FTS5
│   │   │   ├── logging/          # Centralized logging
│   │   │   ├── setup_wizard.py   # First-run configuration wizard
│   │   │   ├── config.py         # Server configuration loader
│   │   │   └── pyproject.toml    # Server dependencies
│   │   └── frontend/             # Remote UI frontend source (React)
│   ├── config.yaml               # Local configuration file (also serves as template)
│   ├── .env                      # Local environment variables
│   └── pyproject.toml            # Native dev environment (mirrors Docker)
```

### pyproject.toml Files

The project has multiple `pyproject.toml` files, each serving a different purpose:

| File | Purpose |
|------|------|
| `client/pyproject.toml` | Native client package definition. Defines runtime deps and platform extras (`kde`, `gnome`, `windows`). Provides the `transcription-client` entrypoint. |
| `client/scripts/pyproject.toml` | Dev/build tools environment (separate from client runtime). Contains `dev` extra with linting, testing, and packaging tools. |
| `native_src/REMOTE_SERVER/backend/pyproject.toml` | Server/backend package definition. Defines server deps (FastAPI, faster-whisper, torch, etc.) used by Docker builds. |
| `native_src/pyproject.toml` | Native development sandbox. Mirrors server deps + desktop extras for running legacy/native workflows without Docker. |

---

## API Reference

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (no auth) |
| `/api/status` | GET | Server status, GPU info |
| `/api/transcribe/audio` | POST | Transcribe uploaded audio file |
| `/api/notebook/recordings` | GET | List all recordings |
| `/api/notebook/recordings/{id}` | GET | Get recording details |
| `/api/notebook/recordings/{id}` | DELETE | Delete recording |
| `/api/notebook/calendar` | GET | Calendar view data |
| `/api/search` | GET | Full-text search |
| `/api/admin/tokens` | GET/POST | Token management (admin only) |

### Swagger UI

Full API documentation at `http://localhost:8000/docs`

---

## Development Setup

### Local Python Development

For working on the Python source (without Docker):

```bash
cd native_src
uv venv --python 3.11
uv sync --extra full      # All dependencies including diarization
```

**Running the native application:**

```bash
# Run with system tray (default mode - longform dictation + static transcription + web viewer)
uv run python MAIN/orchestrator.py

# Transcribe a single file and exit
uv run python MAIN/orchestrator.py --static /path/to/recording.wav

# Specify custom port for the web viewer backend (default: 8000)
uv run python MAIN/orchestrator.py --port 8080
```

### Docker Development

```bash
cd docker
docker compose build
docker compose up -d
```

**First-time startup**: The server takes ~30 seconds to initialize on first run (loading ML models into GPU memory). Wait before attempting client connections.

On first run, if the container is started without a TTY (common with `docker compose up -d`), the server will generate the minimum required configuration automatically (including an `ADMIN_TOKEN`) and persist it in the Docker volume at `/data/config/secrets.json`.

**Recommended workflow during development:**

```bash
# Stop container (preserves volumes and container state)
docker compose stop

# Restart existing container (fast - no model reloading)
docker compose start

# Rebuild after code changes
docker compose build
docker compose up -d

# Only use 'down' when you need to recreate the container
# (This removes containers but keeps volumes)
docker compose down
docker compose up -d
```

Use `docker compose stop`/`start` instead of `down`/`up` to avoid container recreation overhead—the server initialization and model loading takes significant time.

#### Local vs Remote Mode

The unified compose file supports both local and remote (Tailscale/HTTPS) deployment. Switch modes at runtime via environment variables—no rebuild or container recreation needed.

**Local mode (default):**

```bash
docker compose up -d
```

**Remote mode with HTTPS (Tailscale):**

##### Step 1: Set up Tailscale (one-time)

1. Install Tailscale on your host machine: [tailscale.com/download](https://tailscale.com/download)
2. Authenticate: `sudo tailscale up`
   Tailscale will open a browser window to authenticate. Follow the instructions.
   Verify with `tailscale status` - you should see your machine's Tailscale IP address, device name, username, OS and activity status (e.g. `100.78.16.89 desktop github-account@ linux -`).
3. Go to [https://login.tailscale.com/admin](https://login.tailscale.com/admin) and log in with the same account you used to authenticate Tailscale.
4. Look for the 'DNS' tab at the top and switch to it. Note the Tailnet DNS name at the top. You can change it to something more memorable but only once. Let's call it `tail1234.ts.net`.
5. Go all the way to the bottom of the 'DNS' tab and enable 'HTTPS Certificates'. 

##### Step 2: Generate and store certificates

Generate a certificate for your machine:

```bash
tailscale cert <YOUR_DEVICE_NAME>.<YOUR_TAILNET_DNS_NAME>
```

So continuing with the example this would be:
```bash
tailscale cert desktop.tail1234.ts.net
```

This creates two files in the current directory:
- `desktop.tail1234.ts.net.crt`
- `desktop.tail1234.ts.net.key`

**Move and rename** these files to a standard location:

| Platform | Certificate directory | Files |
|----------|----------------------|-------|
| **Linux** | `~/.config/.tailscale/` | `my-machine.crt`, `my-machine.key` |
| **Windows** | `Documents\Tailscale\` | `my-machine.crt`, `my-machine.key` |

**Linux example:**

```bash
mkdir -p ~/.config/.tailscale
mv desktop.tail1234.ts.net.crt ~/.config/.tailscale/my-machine.crt
mv desktop.tail1234.ts.net.key ~/.config/.tailscale/my-machine.key
chmod 600 ~/.config/.tailscale/my-machine.key
```

**Windows example (PowerShell):**

```powershell
mkdir "$env:USERPROFILE\Documents\Tailscale" -Force
mv desktop.tail1234.ts.net.crt "$env:USERPROFILE\Documents\Tailscale\my-machine.crt"
mv desktop.tail1234.ts.net.key "$env:USERPROFILE\Documents\Tailscale\my-machine.key"
```

> **Note:** Renaming the certificate files doesn't affect their validity—the certificate content is what matters, not the filename.

##### Step 3: Start with TLS enabled

**Linux:**

```bash
cd /path/to/TranscriptionSuite/docker
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/.tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/.tailscale/my-machine.key \
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

**Switching modes at runtime:**

```bash
# Switch to remote mode (Linux)
docker compose stop
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/.tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/.tailscale/my-machine.key \
docker compose start

# Switch back to local mode
docker compose stop
docker compose start  # TLS_ENABLED defaults to false
```

**Ports:**
- `8000` — HTTP API (always available)
- `8443` — HTTPS (only serves when `TLS_ENABLED=true`)

#### Docker Build & Runtime Notes

##### Config templates

- **Docker image template**: the Docker build copies `native_src/config.yaml` into the image as `config/config.yaml.example`.

##### Frontend build behavior

- The Docker image **builds both web frontends during `docker compose build`** in the `frontend-builder` stage.
- Steps used for each frontend:
  - `npm ci --omit=dev`
  - `npm run build`
- Docker layer caching may reuse these layers if `package*.json` and frontend sources are unchanged. Use `--no-cache` to force rebuilding.
- The Docker build **does not run `npm audit`**.

##### Auditing the web frontends

- Run audits in the source folders under `native_src/`:
  - `native_src/AUDIO_NOTEBOOK/`
  - `native_src/REMOTE_SERVER/frontend/`

Example:

```bash
npm ci
npm audit
```

### Client Development

```bash
cd client
uv venv --python 3.11
uv sync --extra kde  # or --extra gnome / --extra windows

# Run using the installed entry point script
.venv/bin/transcription-client --host localhost --port 8000

# Or with uv run (activates venv automatically)
uv run transcription-client --host localhost --port 8000
```

### Dev & Build Tools

A single environment for linting, type-checking, testing, and packaging:

```bash
cd client/scripts
uv venv --python 3.11
uv sync --extra dev  # ruff, pyright, pytest, pyinstaller, etc.

# Linting (run from project root, using the tools venv)
cd ../..
./client/scripts/.venv/bin/ruff check .
./client/scripts/.venv/bin/ruff format .

# Type checking (run from project root, using the tools venv)
./client/scripts/.venv/bin/pyright
```

This keeps dev/build tooling isolated from client runtime dependencies.
Note: running `uv sync` (without `--extra dev`) in `client/scripts` will remove these tools because the base dependencies for that project are empty.

---

## Building Executables

### KDE AppImage

```bash
./client/scripts/build-appimage-kde.sh
# Output: dist/TranscriptionSuite-KDE-x86_64.AppImage
```

### GNOME AppImage

```bash
# Requires system GTK3 and AppIndicator
sudo pacman -S gtk3 libappindicator-gtk3 python-gobject

./client/scripts/build-appimage-gnome.sh
# Output: dist/TranscriptionSuite-GNOME-x86_64.AppImage
```

### Windows Executable

```bash
# Run on Windows
pip install pyinstaller
pyinstaller client/build/pyinstaller-windows.spec
# Output: dist/TranscriptionSuite.exe
```

---

## Data Storage

### Docker Volume Structure

All persistent data in `/data/`:

| Path | Description |
|------|-------------|
| `/data/database/notebook.db` | SQLite database with FTS5 |
| `/data/audio/` | Stored audio recordings |
| `/data/config/secrets.json` | API keys, tokens, settings |
| `/data/logs/` | Server logs |
| `/data/certs/` | TLS certificates (remote mode) |

### Database Schema

**Tables:**

- `recordings` - Recording metadata (title, duration, date, summary)
- `segments` - Transcription segments with timestamps
- `words` - Word-level timestamps and confidence
- `conversations` - LLM chat conversations
- `messages` - Individual chat messages
- `recordings_fts` - FTS5 virtual table for search

---

## Architectural Refactoring History

### Original Architecture (Pre-Docker)

The application was originally a native Python application running directly on the host:

- `MAIN/` - Core orchestrator, transcription engine, system tray
- `AUDIO_NOTEBOOK/` - Separate FastAPI + React app
- `REMOTE_SERVER/` - Separate HTTPS server for remote access
- `DIARIZATION/` - Speaker diarization module

**Problems:**

- Service fragmentation (multiple ports, processes)
- Code duplication (transcription logic in multiple places)
- Complex installation (CUDA, Python deps, Node.js)
- Logging fragmentation (multiple log files)

### New Architecture (Docker-first)

**Phase 1: Server Consolidation**
- Created `server/` with unified API
- Merged transcription engines into `server/core/transcription_engine.py`
- Unified logging in `server/logging/`
- Single FastAPI app serving everything on port 8000

**Phase 2: Client Refactoring**
- Created `client/` with platform-specific tray implementations
- Shared code in `client/common/`
- Abstract tray interface for consistency

**Phase 2b: Client Executables**
- PyInstaller specs for Windows and KDE
- AppImage build scripts for Linux

**Phase 2c: First-Run Setup Wizard**
- Interactive configuration on first Docker run
- Non-interactive mode via environment variables
- Persistent storage in Docker volume

**Phase 3: Docker Optimization**
- Multi-stage Dockerfile (Node.js for frontends, Python for server)
- Non-root user for security
- Health checks
- Volume mounts for persistence

**Phase 4: Audio Notebook Integration**
- Verified API routes work with unified server
- Frontend served as static files from Docker build

**Phase 5: Documentation & Cleanup**
- Split README into user/developer docs
- Moved legacy source to `native_src/`
- Cleaned up duplicate files

---

## Configuration Reference

### Server Configuration (Docker)

Environment variables:

- `HF_TOKEN` - HuggingFace token for PyAnnote models
- `ADMIN_TOKEN` - Admin authentication token
- `LOG_LEVEL` - Logging verbosity (DEBUG, INFO, WARNING, ERROR)
- `LM_STUDIO_URL` - LM Studio API URL for chat features
- `TLS_ENABLED` - Enable HTTPS (remote mode)
- `TLS_CERT_PATH` - Path to TLS certificate
- `TLS_KEY_PATH` - Path to TLS private key

### Client Configuration

`~/.config/transcription-suite/client.yaml`:

```yaml
server:
  host: localhost
  port: 8000
  use_https: false
  token: ""

recording:
  sample_rate: 16000
  device_index: null

clipboard:
  auto_copy: true
```

### Native Development Configuration

`native_src/config.yaml` - Full configuration for running without Docker.

---

## Troubleshooting

### Docker GPU Access

GPU passthrough requirements depend on host OS:

- Linux: requires the NVIDIA driver + NVIDIA Container Toolkit on the host
- Windows: requires Docker Desktop (WSL2 backend) + NVIDIA driver with WSL support (the GPU is exposed to the Linux environment via WSL2)

```bash
# Verify GPU is accessible
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi

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

### Model Loading

**First container startup**: On initial boot, the server needs ~30 seconds to load ML models into GPU memory. The container may report as "healthy" before model loading completes. Wait before attempting transcriptions or client connections.

**First transcription of a new model**: Additional time may be needed if Whisper models are being downloaded from HuggingFace (varies by model size and network speed).

### GNOME Tray Not Showing

Install the AppIndicator extension:

- [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/)

### Permission Errors

```bash
# Fix Docker volume permissions
docker compose down
docker volume rm transcription-data
docker compose up -d
```

---

## Dependencies

### Server (Docker)

- Python 3.11
- FastAPI + Uvicorn
- faster-whisper (CTranslate2 backend)
- PyAnnote Audio (optional, for diarization)
- PyTorch + TorchAudio
- SQLite with FTS5

### Client

- Python 3.11
- aiohttp (async HTTP client)
- PyAudio (audio recording)
- PyQt6 (KDE/Windows) or GTK3+AppIndicator (GNOME)
- pyperclip (clipboard)
