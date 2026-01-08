# TranscriptionSuite - Developer Guide

Technical documentation for developing and building TranscriptionSuite.

## Table of Contents

- [1. Quick Reference](#1-quick-reference)
  - [1.1 Development Commands](#11-development-commands)
  - [1.2 Running from Source (Development)](#12-running-from-source-development)
  - [1.3 Build Commands](#13-build-commands)
  - [1.4 Common Tasks](#14-common-tasks)
- [2. Architecture Overview](#2-architecture-overview)
  - [2.1 Design Principles](#21-design-principles)
  - [2.2 Platform Architectures](#22-platform-architectures)
  - [2.3 Security Model](#23-security-model)
- [3. Project Structure](#3-project-structure)
  - [3.1 pyproject.toml Files](#31-pyprojecttoml-files)
  - [3.2 Version Management](#32-version-management)
- [4. Development Workflow](#4-development-workflow)
  - [4.1 Step 1: Environment Setup](#41-step-1-environment-setup)
  - [4.2 Step 2: Build Docker Image](#42-step-2-build-docker-image)
  - [4.3 Step 3: Run Dashboard Locally](#43-step-3-run-dashboard-locally)
  - [4.4 Step 4: Run Dashboard Remotely (Tailscale)](#44-step-4-run-dashboard-remotely-tailscale)
  - [4.5 Publishing Docker Images](#45-publishing-docker-images)
- [5. Build Workflow](#5-build-workflow)
  - [5.1 Prerequisites](#51-prerequisites)
  - [5.2 Build Matrix](#52-build-matrix)
  - [5.3 KDE AppImage (Linux)](#53-kde-appimage-linux)
  - [5.4 GNOME AppImage (Linux)](#54-gnome-appimage-linux)
  - [5.5 Windows Executable](#55-windows-executable)
  - [5.6 Build Assets](#56-build-assets)
- [6. Docker Reference](#6-docker-reference)
  - [6.1 Local vs Remote Mode](#61-local-vs-remote-mode)
  - [6.2 Tailscale HTTPS Setup](#62-tailscale-https-setup)
  - [6.3 Docker Volume Structure](#63-docker-volume-structure)
- [7. API Reference](#7-api-reference)
  - [7.1 Web UI Routes](#71-web-ui-routes)
  - [7.2 API Endpoints](#72-api-endpoints)
  - [7.3 WebSocket Protocol](#73-websocket-protocol)
- [8. Backend Development](#8-backend-development)
  - [8.1 Backend Structure](#81-backend-structure)
  - [8.2 Running the Server Locally](#82-running-the-server-locally)
  - [8.3 Configuration System](#83-configuration-system)
  - [8.4 Frontend Development](#84-frontend-development)
  - [8.5 Testing](#85-testing)
- [9. Dashboard Development](#9-dashboard-development)
  - [9.1 Running from Source](#91-running-from-source)
  - [9.2 Verbose Logging](#92-verbose-logging)
  - [9.3 Key Modules](#93-key-modules)
  - [9.4 Server Busy Handling](#94-server-busy-handling)
  - [9.5 Model Management](#95-model-management)
- [10. Configuration Reference](#10-configuration-reference)
  - [10.1 Server Configuration](#101-server-configuration)
  - [10.2 Dashboard Configuration](#102-dashboard-configuration)
- [11. Data Storage](#11-data-storage)
  - [11.1 Database Schema](#111-database-schema)
  - [11.2 Database Migrations](#112-database-migrations)
  - [11.3 Automatic Backups](#113-automatic-backups)
- [12. Troubleshooting](#12-troubleshooting)
  - [12.1 Docker GPU Access](#121-docker-gpu-access)
  - [12.2 Health Check Issues](#122-health-check-issues)
  - [12.3 Tailscale DNS Resolution](#123-tailscale-dns-resolution)
  - [12.4 GNOME Tray Not Showing](#124-gnome-tray-not-showing)
  - [12.5 AppImage Startup Failures](#125-appimage-startup-failures)
- [13. Dependencies](#13-dependencies)
  - [13.1 Server (Docker)](#131-server-docker)
  - [13.2 Dashboard](#132-dashboard)

---

## 1. Quick Reference

### 1.1 Development Commands

```bash
# 1. Setup virtual environments
cd dashboard && uv venv --python 3.12 && uv sync --extra kde && cd ..
cd build && uv venv --python 3.12 && uv sync && cd ..

# 2. Audit frontend packages
cd server/frontend && npm ci && npm audit && cd ../..

# 3. Build and run Docker server
cd server/docker && docker compose build && docker compose up -d

# 4. Run dashboard locally
cd dashboard && uv run transcription-dashboard --host localhost --port 8000
```

### 1.2 Running from Source (Development)

```bash
# 1. Run backend server (native Python)
cd server/backend
uv venv --python 3.12 && uv sync
uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 8000

# 2. Run frontend dev server (in a separate terminal)
cd server/frontend
npm install
npm run dev  # Starts on http://localhost:1420

# 3. Run dashboard (in a separate terminal)
cd dashboard
uv venv --python 3.12 && uv sync --extra kde  # or --extra gnome / --extra windows
uv run transcription-dashboard --host localhost --port 8000
```

**Notes:**
- Backend runs on port 8000, frontend dev server on port 1420
- Frontend auto-detects dev mode and proxies API calls to backend
- Dashboard connects directly to backend API on port 8000
- Backend must be running for dashboard to function
- This setup enables hot-reload for both backend and frontend

### 1.3 Build Commands

```bash
# KDE AppImage (Linux)
./build/build-appimage-kde.sh
# Output: build/dist/TranscriptionSuite-KDE-x86_64.AppImage

# GNOME AppImage (Linux)
./build/build-appimage-gnome.sh
# Output: build/dist/TranscriptionSuite-GNOME-x86_64.AppImage

# Windows (on Windows machine)
.\build\.venv\Scripts\pyinstaller.exe --clean --distpath build\dist .\dashboard\src\dashboard\build\pyinstaller-windows.spec
# Output: build\dist\TranscriptionSuite.exe
```

### 1.4 Common Tasks

| Task | Command |
|------|---------|
| Start server (local) | `cd server/docker && ./start-local.sh` |
| Start server (HTTPS) | `cd server/docker && ./start-remote.sh` |
| Stop server | `cd server/docker && ./stop.sh` |
| Build Docker image | `cd server/docker && docker compose build` |
| View server logs | `docker compose logs -f` |
| Build & publish image | `./build/docker-build-push.sh` |
| Run dashboard (local) | `cd dashboard && uv run transcription-dashboard --host localhost --port 8000` |
| Run dashboard (remote) | `cd dashboard && uv run transcription-dashboard --host <tailscale-hostname> --port 8443 --https` |
| Lint code | `./build/.venv/bin/ruff check .` |
| Format code | `./build/.venv/bin/ruff format .` |
| Type check | `./build/.venv/bin/pyright` |

---

## 2. Architecture Overview

TranscriptionSuite uses a **client-server architecture**:

```
┌─────────────────────────────────────────────────────────┐
│                     Docker Container                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │  TranscriptionSuite Server                        │  │
│  │  - FastAPI REST API + WebSocket                   │  │
│  │  - faster-whisper transcription                   │  │
│  │  - Real-time STT with VAD (Silero + WebRTC)       │  │
│  │  - PyAnnote diarization                           │  │
│  │  - React frontend (Web UI)                        │  │
│  │  - SQLite + FTS5 search                           │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                           ↕
┌─────────────────────────────────────────────────────────┐
│                   Native Dashboards                     │
│     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐     │
│     │   KDE Tray  │ │ GNOME Tray  │ │Windows Tray │     │
│     │   (PyQt6)   │ │(GTK3+D-Bus) │ │  (PyQt6)    │     │
│     └─────────────┘ └──────┬──────┘ └─────────────┘     │
│                            │ D-Bus IPC                  │
│                      ┌─────┴──────┐                     │
│                      │ Dashboard  │                     │
│                      │   (GTK4)   │                     │
│                      └────────────┘                     │
└─────────────────────────────────────────────────────────┘
```

### 2.1 Design Principles

- **Server in Docker**: All ML/GPU operations run in Docker for reproducibility
- **Dashboard as command center**: Native application manages server control, client control, and configuration
- **Single port**: Server exposes everything on port 8000 (API, WebSocket, static files)
- **SQLite + FTS5**: Lightweight full-text search without external dependencies
- **Dual VAD**: Real-time engine uses both Silero (neural) and WebRTC (algorithmic) VAD
- **Multi-device support**: Multiple clients can connect, but only one transcription runs at a time

### 2.2 Platform Architectures

| Platform | Architecture | UI Toolkit | Notes |
|----------|--------------|------------|-------|
| **KDE Plasma** | Single-process | PyQt6 | Tray and Dashboard share one process |
| **Windows** | Single-process | PyQt6 | Same as KDE |
| **GNOME** | Dual-process | GTK3 + GTK4 | Tray (GTK3) and Dashboard (GTK4) via D-Bus |

**GNOME Dual-Process Design**: GTK3 and GTK4 cannot coexist in the same Python process (GObject Introspection limitation). The tray uses GTK3 + AppIndicator3, while the Dashboard uses GTK4 + libadwaita. They communicate via D-Bus (`com.transcriptionsuite.Dashboard`).

### 2.3 Security Model

TranscriptionSuite uses layered security for remote access:

1. **Tailscale Network**: Only devices on your Tailnet can reach the server
2. **TLS/HTTPS**: Encrypted connection with Tailscale certificates
3. **Token Authentication**: Required for all API endpoints in TLS mode

| Access Method | Authentication | Trust Level |
|---------------|----------------|-------------|
| `localhost:8000` (HTTP) | None | Full trust (user's own machine) |
| Tailscale + TLS | Token required | High trust (your Tailnet) |
| Public internet | Not supported | N/A (blocked by design) |

---

## 3. Project Structure

```
TranscriptionSuite/
├── dashboard/                    # Native dashboard application
│   ├── src/dashboard/            # Python package source
│   │   ├── common/               # Shared code (API client, orchestrator, config)
│   │   ├── kde/                  # KDE Plasma (PyQt6)
│   │   ├── gnome/                # GNOME (GTK3 tray + GTK4 Dashboard via D-Bus)
│   │   ├── windows/              # Windows (PyQt6)
│   │   └── build/                # PyInstaller spec files
│   └── pyproject.toml            # Dashboard package + dependencies
│
├── build/                        # Build and development tools
│   ├── build-appimage-kde.sh     # Build KDE AppImage
│   ├── build-appimage-gnome.sh   # Build GNOME AppImage
│   ├── docker-build-push.sh      # Build and push Docker image
│   ├── assets/                   # Logo, icons, profile picture
│   └── pyproject.toml            # Dev/build tools (ruff, pyright, pytest)
│
├── server/                       # Server source code
│   ├── docker/                   # Docker infrastructure
│   │   ├── Dockerfile            # Multi-stage build
│   │   ├── docker-compose.yml    # Container orchestration
│   │   └── entrypoint.py         # Container entrypoint
│   ├── backend/                  # FastAPI backend
│   │   ├── api/                  # FastAPI routes
│   │   ├── core/                 # ML engines (transcription, diarization, VAD)
│   │   ├── database/             # SQLite + FTS5 + migrations
│   │   └── pyproject.toml        # Server dependencies (pinned versions)
│   ├── frontend/                 # React web UI
│   └── config.yaml               # Server configuration template
```

### 3.1 pyproject.toml Files

| File | Purpose |
|------|---------|
| `dashboard/pyproject.toml` | Dashboard runtime deps with platform extras (`kde`, `gnome`, `windows`) |
| `build/pyproject.toml` | All dev/build tools (ruff, pyright, pytest, pyinstaller) |
| `server/backend/pyproject.toml` | Server deps with pinned versions for reproducible Docker builds |

### 3.2 Version Management

Each `pyproject.toml` defines its component's version. All version strings are dynamically sourced from these files - update the version in one place.

*Note: The tags and releases version numbers always refer to the Dashboard toml's version.*

---

## 4. Development Workflow

### 4.1 Step 1: Environment Setup

```bash
# Dashboard virtual environment
cd dashboard
uv venv --python 3.12
uv sync --extra kde    # or --extra gnome / --extra windows
cd ..

# Build tools virtual environment
cd build
uv venv --python 3.12
uv sync
cd ..

# Audit frontend packages
cd server/frontend && npm ci && npm audit && cd ../..
```

### 4.2 Step 2: Build Docker Image

```bash
cd server/docker
docker compose build
```

**What happens:**
1. Frontend builder stage: Builds React frontend
2. Python runtime stage: Installs server dependencies
3. Static files: Copies built frontend to `/app/static/frontend`

**Force rebuild:**
```bash
docker compose build --no-cache
```

### 4.3 Step 3: Run Dashboard Locally

```bash
# Start the server
cd server/docker && docker compose up -d

# Run the dashboard
cd dashboard && uv run transcription-dashboard --host localhost --port 8000
```

### 4.4 Step 4: Run Dashboard Remotely (Tailscale)

```bash
# Server side: Enable HTTPS
cd server/docker
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d

# Dashboard side: Connect via HTTPS
cd dashboard
uv run transcription-dashboard --host <your-machine>.tail1234.ts.net --port 8443 --https
```

### 4.5 Publishing Docker Images

```bash
# Build and push as 'latest'
./build/docker-build-push.sh

# Build and push a release version
./build/docker-build-push.sh v0.3.0

# Build and push a custom tag
./build/docker-build-push.sh dev
```

**Prerequisites:**
- Docker installed and running
- GHCR authentication: `gh auth login && gh auth token | docker login ghcr.io -u YOUR_USERNAME --password-stdin`

---

## 5. Build Workflow

### 5.1 Prerequisites

```bash
cd build
uv venv --python 3.12
uv sync    # Installs PyInstaller, build, ruff, pytest
```

### 5.2 Build Matrix

| Platform | Method | Output | Target Requirements |
|----------|--------|--------|---------------------|
| **KDE (Linux)** | PyInstaller + AppImage | Fully standalone | None |
| **GNOME (Linux)** | Source bundle + AppImage | Semi-portable | Python 3.12+, GTK3, AppIndicator3 |
| **Windows** | PyInstaller | Fully standalone | None |

### 5.3 KDE AppImage (Linux)

```bash
./build/build-appimage-kde.sh
# Output: build/dist/TranscriptionSuite-KDE-x86_64.AppImage
```

### 5.4 GNOME AppImage (Linux)

```bash
./build/build-appimage-gnome.sh
# Output: build/dist/TranscriptionSuite-GNOME-x86_64.AppImage
```

**Target system dependencies:**
```bash
# Arch Linux
sudo pacman -S --needed python gtk3 libappindicator-gtk3 python-gobject python-numpy python-aiohttp gtksourceview5 wl-clipboard

# Ubuntu/Debian
sudo apt install python3 python3-gi gir1.2-appindicator3-0.1 python3-pyaudio python3-numpy python3-aiohttp gir1.2-gtksource-5 wl-clipboard
```

### 5.5 Windows Executable

**Prerequisites (on Windows):**
```powershell
# Install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install ImageMagick for icon generation
winget install ImageMagick.ImageMagick
```

**Build steps:**
```powershell
cd build
uv venv --python 3.12
uv sync
cd ..

# Generate Windows icon
magick build\assets\logo.png -background transparent -define icon:auto-resize=256,48,32,16 build\assets\logo.ico

# Build executable
.\build\.venv\Scripts\pyinstaller.exe --clean --distpath build\dist .\dashboard\src\dashboard\build\pyinstaller-windows.spec
# Output: build\dist\TranscriptionSuite.exe
```

### 5.6 Build Assets

**Source files (manually maintained in `build/assets/`):**
- `logo.svg` (1024×1024) - Master vector logo
- `logo.png` (1024×1024) - High-resolution raster export
- `profile.png` - Author profile picture for About dialog

**Generated automatically during builds:**
- `logo.ico` - Multi-resolution Windows icon
- 256×256 PNG - Rescaled for AppImage

---

## 6. Docker Reference

### 6.1 Local vs Remote Mode

```bash
# Local mode (default)
docker compose up -d

# Remote mode with HTTPS
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d
```

**Ports:**
- `8000` — HTTP API (always available)
- `8443` — HTTPS (only when `TLS_ENABLED=true`)

### 6.2 Tailscale HTTPS Setup

1. **Install and authenticate Tailscale:**
   ```bash
   sudo tailscale up
   tailscale status
   ```

2. **Enable HTTPS certificates** in [Tailscale Admin DNS settings](https://login.tailscale.com/admin/dns)

3. **Generate certificates:**
   ```bash
   sudo tailscale cert <YOUR_DEVICE_NAME>.<YOUR_TAILNET_DNS_NAME>
   mkdir -p ~/.config/Tailscale
   mv <hostname>.crt ~/.config/Tailscale/my-machine.crt
   mv <hostname>.key ~/.config/Tailscale/my-machine.key
   sudo chown $USER:$USER ~/.config/Tailscale/my-machine.*
   chmod 640 ~/.config/Tailscale/my-machine.key
   ```

4. **Start with TLS:**
   ```bash
   TLS_ENABLED=true \
   TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
   TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
   docker compose up -d
   ```

### 6.3 Docker Volume Structure

**`transcription-suite-data`** (mounted to `/data`):

| Path | Description |
|------|-------------|
| `/data/database/` | SQLite database and backups |
| `/data/audio/` | Recorded audio files |
| `/data/logs/` | Server logs |
| `/data/tokens/` | Authentication tokens |

**`transcription-suite-models`** (mounted to `/models`):

| Path | Description |
|------|-------------|
| `/models/hub/` | HuggingFace models cache (Whisper, PyAnnote) |

**Optional user config** (bind mount to `/user-config`):

When `USER_CONFIG_DIR` is set, mounts custom config and logs.

---

## 7. API Reference

### 7.1 Web UI Routes

| URL Path | Description |
|----------|-------------|
| `/` | Redirects to `/record` |
| `/auth` | Authentication page (TLS mode) |
| `/record` | File upload, recording, admin panel |
| `/notebook` | Calendar view, search, audio playback |

### 7.2 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (no auth) |
| `/api/status` | GET | Server status, GPU info |
| `/api/auth/login` | POST | Authenticate with token |
| `/api/auth/tokens` | GET/POST | Token management (admin only) |
| `/api/admin/models/load` | POST | Load transcription models (admin only) |
| `/api/admin/models/unload` | POST | Unload models to free GPU memory (admin only) |
| `/api/transcribe/audio` | POST | Transcribe uploaded audio |
| `/api/transcribe/cancel` | POST | Cancel running transcription |
| `/ws` | WebSocket | Real-time audio streaming |
| `/api/notebook/recordings` | GET | List all recordings |
| `/api/notebook/recordings/{id}` | GET/DELETE | Get or delete recording |
| `/api/notebook/transcribe/upload` | POST | Upload and transcribe with diarization |
| `/api/search` | GET | Full-text search |
| `/api/llm/chat` | POST | LLM chat integration |

### 7.3 WebSocket Protocol

**Connection flow:**
1. Connect to `/ws`
2. Send auth: `{"type": "auth", "data": {"token": "<token>"}}`
3. Receive: `{"type": "auth_ok", "data": {...}}`
4. Send start: `{"type": "start", "data": {"language": "en"}}`
5. Stream binary audio (16kHz PCM Int16)
6. Send stop: `{"type": "stop"}`
7. Receive final: `{"type": "final", "data": {"text": "...", "words": [...]}}`

**Audio format:**
- Binary messages: `[4 bytes metadata length][metadata JSON][PCM Int16 data]`
- Sample rate: 16kHz, Format: Int16 PCM (little-endian)

---

## 8. Backend Development

### 8.1 Backend Structure

```
server/backend/
├── api/
│   ├── main.py                   # App factory, lifespan, routing
│   └── routes/                   # API endpoint modules
├── core/
│   ├── transcription_engine.py   # faster-whisper wrapper
│   ├── diarization_engine.py     # PyAnnote wrapper
│   ├── model_manager.py          # Model lifecycle, job tracking
│   ├── realtime_engine.py        # Async wrapper for real-time STT
│   ├── preview_engine.py         # Preview transcription
│   └── stt/                      # Real-time speech-to-text engine
│       ├── engine.py             # AudioToTextRecorder with VAD
│       └── vad.py                # Dual VAD (Silero + WebRTC)
├── database/
│   └── database.py               # SQLite + FTS5 operations
└── config.py                     # Configuration management
```

### 8.2 Running the Server Locally

```bash
cd server/backend
uv venv --python 3.12
uv sync

# Development mode with auto-reload
uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 8.3 Configuration System

All modules use `get_config()` from `server.config`. Configuration is loaded with priority:

1. `/user-config/config.yaml` (Docker with mounted user config)
2. `~/.config/TranscriptionSuite/config.yaml` (Linux user config)
3. `/app/config.yaml` (Docker default)
4. `server/config.yaml` (native development)

### 8.4 Frontend Development

```bash
cd server/frontend
npm install
npm run dev  # Starts dev server on http://localhost:1420
```

The frontend uses `import.meta.env.DEV` to detect development mode:
- HTTP API requests: `http://localhost:8000/api`
- WebSocket connections: `ws://localhost:8000/ws`

### 8.5 Testing

```bash
./build/.venv/bin/pytest server/backend/tests
```

---

## 9. Dashboard Development

### 9.1 Running from Source

```bash
cd dashboard
uv venv --python 3.12
uv sync --extra kde    # or --extra gnome / --extra windows

uv run transcription-dashboard
```

### 9.2 Verbose Logging

```bash
uv run transcription-dashboard --verbose
```

**Log locations:**
| Platform | Log File |
|----------|----------|
| Linux | `~/.config/TranscriptionSuite/dashboard.log` |
| Windows | `%APPDATA%\TranscriptionSuite\dashboard.log` |
| macOS | `~/Library/Application Support/TranscriptionSuite/dashboard.log` |

### 9.3 Key Modules

| Module | Purpose |
|--------|---------|
| `common/api_client.py` | HTTP client, WebSocket, error handling |
| `common/orchestrator.py` | Main controller, state machine |
| `common/docker_manager.py` | Docker server control |
| `common/setup_wizard.py` | First-time setup |
| `common/tailscale_resolver.py` | Tailscale IP fallback when DNS fails |

### 9.4 Server Busy Handling

The dashboard handles server busy conditions automatically:
- HTTP transcription: Server returns 409, dashboard shows "Server Busy" notification
- WebSocket recording: Server sends `session_busy` message, dashboard shows error

### 9.5 Model Management

The dashboard provides a convenient way to manage GPU memory via the system tray and client view:
- Automatically disabled when server is stopped or becomes unhealthy
- Checks server for active transcriptions before unloading
- Returns HTTP 409 if server is busy

---

## 10. Configuration Reference

### 10.1 Server Configuration

Config file: `~/.config/TranscriptionSuite/config.yaml` (Linux) or `$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml` (Windows)

**Key sections:**
- `main_transcriber` - Primary Whisper model, device, batch settings
- `preview_transcriber` - Optional preview model for live transcription
- `diarization` - PyAnnote model and speaker detection
- `remote_server` - Host, port, TLS settings
- `storage` - Database path, audio storage
- `local_llm` - LM Studio integration
- `backup` - Automatic database backup settings

**Environment variables:**
| Variable | Purpose |
|----------|---------|
| `HF_TOKEN` | HuggingFace token for PyAnnote models |
| `USER_CONFIG_DIR` | Path to user config directory |
| `LOG_LEVEL` | Logging verbosity (DEBUG, INFO, WARNING) |
| `TLS_ENABLED` | Enable HTTPS |
| `TLS_CERT_PATH` | Path to TLS certificate |
| `TLS_KEY_PATH` | Path to TLS private key |

### 10.2 Dashboard Configuration

Config file: `~/.config/TranscriptionSuite/dashboard.yaml`

```yaml
server:
  host: localhost              # Local server hostname
  port: 8000                   # Server port
  use_https: false             # Enable HTTPS
  token: ""                    # Authentication token
  use_remote: false            # Use remote_host instead of host
  remote_host: ""              # Remote server hostname (no protocol/port)
  auto_reconnect: true         # Auto-reconnect on disconnect
  reconnect_interval: 10       # Seconds between attempts
  tls_verify: true             # Verify TLS certificates

recording:
  sample_rate: 16000           # Audio sample rate (fixed for Whisper)
  device_index: null           # Audio input device (null = default)

clipboard:
  auto_copy: true              # Copy transcription to clipboard

ui:
  notifications: true          # Show desktop notifications
  start_minimized: false       # Start with tray icon only
```

---

## 11. Data Storage

### 11.1 Database Schema

| Table | Description |
|-------|-------------|
| `recordings` | Recording metadata (title, duration, date, summary) |
| `segments` | Transcription segments with timestamps |
| `words` | Word-level timestamps and confidence |
| `conversations` | LLM chat conversations |
| `messages` | Individual chat messages |
| `words_fts` | FTS5 virtual table for full-text search |

### 11.2 Database Migrations

TranscriptionSuite uses Alembic for schema versioning. Migrations run automatically on server startup via the `run_migrations()` function in `database.py`.

**Migration files:** `server/backend/database/migrations/versions/`

**Creating new migrations:**
1. Add a new file in `migrations/versions/` (e.g., `002_add_column.py`)
2. Follow the pattern in `001_initial_schema.py`
3. Use `op.batch_alter_table()` for SQLite compatibility

### 11.3 Automatic Backups

Backups are created on server startup using SQLite's backup API.

**Configuration:**
```yaml
backup:
    enabled: true        # Enable automatic backups
    max_age_hours: 1     # Backup if latest is older than this
    max_backups: 3       # Number of backups to keep
```

**Backup location:** `/data/database/backups/` (Docker)

---

## 12. Troubleshooting

### 12.1 Docker GPU Access

```bash
# Verify GPU is accessible
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi

# Check container logs
docker compose logs -f
```

### 12.2 Health Check Issues

```bash
# Check health status
docker compose ps
docker inspect transcription-suite | grep Health -A 10

# Test health endpoint
docker compose exec transcription-suite curl -f http://localhost:8000/health
```

### 12.3 Tailscale DNS Resolution

If DNS fails for `.ts.net` hostnames, the dashboard automatically falls back to Tailscale IP addresses.

**To diagnose:**
```bash
tailscale status
getent hosts <your-machine>.tail1234.ts.net
```

**Quick fix:**
```bash
sudo systemctl restart tailscaled
```

### 12.4 GNOME Tray Not Showing

Install the [AppIndicator Support extension](https://extensions.gnome.org/extension/615/appindicator-support/).

### 12.5 AppImage Startup Failures

```bash
# Run from terminal to see errors
./TranscriptionSuite-KDE-x86_64.AppImage

# Check for missing libraries
./TranscriptionSuite-KDE-x86_64.AppImage --appimage-extract
ldd squashfs-root/usr/bin/TranscriptionSuite-KDE
```

---

## 13. Dependencies

### 13.1 Server (Docker)

- Python 3.12
- FastAPI + Uvicorn
- faster-whisper (CTranslate2 backend)
- PyAnnote Audio 4.0.3+ (speaker diarization)
- PyTorch 2.8.0 + TorchAudio 2.8.0
- SQLite with FTS5
- NVIDIA GPU with CUDA support

### 13.2 Dashboard

- Python 3.12
- aiohttp (async HTTP client)
- PyAudio (audio recording)
- PyQt6 (KDE/Windows) or GTK3+AppIndicator (GNOME)
