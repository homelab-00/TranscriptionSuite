# TranscriptionSuite - Developer Notes

This document contains technical details, architecture decisions, and development notes for TranscriptionSuite.

## Table of Contents

- [Quick Reference](#quick-reference)
- [Architecture Overview](#architecture-overview)
  - [Design Decisions](#design-decisions)
- [Project Structure](#project-structure)
  - [Directory Layout](#directory-layout)
  - [pyproject.toml Files](#pyprojecttoml-files)
- [Development Workflow](#development-workflow)
  - [Step 1: Environment Setup](#step-1-environment-setup)
  - [Step 2: Build Docker Image](#step-2-build-docker-image)
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
  - [Server Configuration (Docker)](#server-configuration-docker)
  - [Client Configuration](#client-configuration)
  - [Native Development Configuration](#native-development-configuration)
- [Data Storage](#data-storage)
  - [Database Schema](#database-schema)
  - [Sensitive Data Storage & Lifecycle](#sensitive-data-storage--lifecycle)
- [Troubleshooting](#troubleshooting)
  - [Docker GPU Access](#docker-gpu-access)
  - [Docker Logs](#docker-logs)
  - [Health Check Issues](#health-check-issues)
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

# 2. Audit NPM packages (both frontends)
cd native_src/AUDIO_NOTEBOOK && npm ci && npm audit && cd ../..
cd native_src/REMOTE_SERVER/frontend && npm ci && npm audit && cd ../../..

# 3. Build and run Docker server
cd docker
docker compose build
docker compose up -d

# 4. Run client locally
cd client
uv run transcription-client --host localhost --port 8000
```

### Build Workflow (TL;DR)

```bash
# KDE AppImage (Linux)
./build/build-appimage-kde.sh
# Output: dist/TranscriptionSuite-KDE-x86_64.AppImage

# GNOME AppImage (Linux)
./build/build-appimage-gnome.sh
# Output: dist/TranscriptionSuite-GNOME-x86_64.AppImage

# Windows (on Windows machine)
.\build\.venv\Scripts\pyinstaller.exe --clean client/build/pyinstaller-windows.spec
# Output: dist/TranscriptionSuite.exe
```

### Key Commands

| Task | Command |
|------|---------|
| **Build Docker image** | `cd docker && docker compose build` |
| **Start server (local)** | `cd docker && docker compose up -d` |
| **Start server (HTTPS)** | `TLS_ENABLED=true TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt TLS_KEY_PATH=~/.config/Tailscale/my-machine.key docker compose up -d` |
| **Stop server (keep state)** | `docker compose stop` |
| **Restart server (fast)** | `docker compose start` |
| **Rebuild after code changes** | `docker compose build && docker compose up -d` |
| **View server logs** | `docker compose logs -f` |
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
│  │  - FastAPI REST API                               │  │
│  │  - faster-whisper transcription                   │  │
│  │  - PyAnnote diarization                           │  │
│  │  - Audio Notebook (React frontend)                │  │
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
└─────────────────────────────────────────────────────────┘
```

### Design Decisions

- **Server in Docker**: All ML/GPU operations run in Docker for reproducibility and isolation
- **Native clients**: System tray, microphone, clipboard require native access (can't be containerized)
- **Single port**: Server exposes everything on port 8000 (API, WebSocket, static files)
- **SQLite + FTS5**: Lightweight full-text search without external dependencies

---

## Project Structure

### Directory Layout

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
│   └── pyproject.toml            # Client package + dependencies
│
├── build/                        # Build and development tools
│   ├── build-appimage-kde.sh     # Build KDE AppImage
│   ├── build-appimage-gnome.sh   # Build GNOME AppImage
│   └── pyproject.toml            # Dev/build tools (separate venv)
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
│   └── config.yaml               # Local configuration file (also serves as template)
```

### pyproject.toml Files

The project has ***three*** `pyproject.toml` files, each serving a different purpose:

| File | Purpose |
|------|------|
| `client/pyproject.toml` | Native client package definition. Defines runtime deps and platform extras (`kde`, `gnome`, `windows`). Provides the `transcription-client` entrypoint. |
| `build/pyproject.toml` | Dev/build tools environment (separate from client runtime). Contains linting, testing, and packaging tools. |
| `native_src/REMOTE_SERVER/backend/pyproject.toml` | Server/backend package definition. Defines server deps (FastAPI, faster-whisper, torch, pyannote.audio, etc.) used by Docker builds and native development. |

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

Audit both web frontends for security vulnerabilities:

```bash
# Audio Notebook frontend
cd native_src/AUDIO_NOTEBOOK
npm ci
npm audit
cd ../..

# Remote Server frontend
cd native_src/REMOTE_SERVER/frontend
npm ci
npm audit
cd ../../..
```

> **Note:** The Docker build runs `npm ci` but does **not** run `npm audit`. Always audit locally before building.

### Step 2: Build Docker Image

Build the Docker image containing the server, ML models support, and both web frontends:

```bash
cd docker
docker compose build
```

**What happens during build:**
1. **Frontend builder stage**: Builds both React frontends (`AUDIO_NOTEBOOK` and `REMOTE_SERVER/frontend`)
2. **Python runtime stage**: Installs all server dependencies from `native_src/REMOTE_SERVER/backend/pyproject.toml`
3. **Static files**: Copies built frontends to `/app/static/`
4. **Config template**: Copies `native_src/config.yaml` as `config/config.yaml.example`

**Force rebuild** (if layer caching causes issues):

```bash
docker compose build --no-cache
```

### Step 3: Run Client Locally

Start the Docker server and connect with a local client.

#### 3.1 Start the Server

```bash
cd docker
docker compose up -d
```

**First-time startup notes:**
- Server takes ~30 seconds to load ML models into GPU memory (you can verify by monitoring your GPU VRAM usage, you'll see a jump ~3GB)
- On first run without TTY, server auto-generates `ADMIN_TOKEN` and saves to `/data/config/secrets.json`
- Check logs: `docker compose logs -f` (or just use `lazydocker`)

#### 3.2 Run the Client

```bash
cd client
uv run transcription-client --host localhost --port 8000
```

The client connects via HTTP to the local Docker server.

#### 3.3 Managing the Server

```bash
# Stop (preserves state, fast restart)
docker compose stop

# Restart (fast - no model reloading)
docker compose start

# Rebuild after code changes
docker compose build
docker compose up -d

# Full recreate (only when needed)
docker compose down
docker compose up -d
```

**Tip:** Use `stop`/`start` instead of `down`/`up` to avoid model reloading overhead.

### Step 4: Run Client Remotely (Tailscale)

For connecting to the server from another machine over a secure connection.

#### 4.1 Server-Side: Enable HTTPS

```bash
cd docker
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
3. Creates an AppImage with `.desktop` file, icon, and launcher
4. Uses `appimagetool` to package everything into a single `.AppImage` file

**Requirements:**
- Linux system (tested on Arch, should work on any distro)
- `appimagetool` (auto-downloaded if not installed)
- Build tools venv set up (see Prerequisites)

**Build:**

```bash
./build/build-appimage-kde.sh
```

**Output:** `dist/TranscriptionSuite-KDE-x86_64.AppImage`

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
4. Packages into `.AppImage` for easier distribution

**Why not PyInstaller?**

GTK and GObject Introspection rely heavily on:
- Dynamic library loading at runtime
- GIR (GObject Introspection Repository) files
- Typelib files that must match system GTK version
- System-installed schemas and themes

PyInstaller cannot reliably bundle these, and attempts usually result in broken or unstable executables.

**Requirements:**
- Build system: Linux with `appimagetool`
- Target system: Python 3.11+, GTK3, libappindicator-gtk3, python-gobject, python-numpy, python-aiohttp

**Build:**

```bash
./build/build-appimage-gnome.sh
```

**Output:** `dist/TranscriptionSuite-GNOME-x86_64.AppImage`

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

**Status:** Build script not yet implemented. Manual PyInstaller workflow below.

**What it does:**
- Uses PyInstaller to bundle Python interpreter, PyQt6, PyAudio, and dependencies
- Creates a standalone `.exe` file
- No Python installation required on target system

**Why Windows is required:**
- `.exe` files use Windows PE format (Windows-specific)
- PyQt6 and dependencies require Windows DLLs
- PyInstaller needs Windows linker tools
- Cross-compilation not supported due to platform-specific binaries

**Build (manual, on Windows):**

```powershell
.\build\.venv\Scripts\pyinstaller.exe --clean client/build/pyinstaller-windows.spec
```

**Output:** `dist/TranscriptionSuite.exe`

**TODO:** Create `build/build-windows.ps1` script to automate this process.

### Build Artifacts

All builds output to the `dist/` directory:

```
dist/
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

#### Config Templates

- **Docker image template**: The Docker build copies `native_src/config.yaml` into the image as `config/config.yaml.example`.

#### Frontend Build Behavior

- The Docker image **builds both web frontends during `docker compose build`** in the `frontend-builder` stage.
- Steps used for each frontend:
  - `npm ci` (not `--omit=dev` to ensure build tools are available)
  - `npm run build`
- Docker layer caching may reuse these layers if `package*.json` and frontend sources are unchanged. Use `--no-cache` to force rebuilding.
- The Docker build **does not run `npm audit`** — run audits locally before building.

### Local vs Remote Mode

The unified compose file supports both local and remote (Tailscale/HTTPS) deployment. Switch modes at runtime via environment variables—no rebuild or container recreation needed.

**Local mode (default):**

```bash
cd docker
docker compose up -d
```

**Remote mode with HTTPS:**

```bash
cd docker
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d
```

**Switching modes at runtime:**

```bash
# Switch to remote mode (Linux)
docker compose stop
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose start

# Switch back to local mode
docker compose stop
docker compose start    # TLS_ENABLED defaults to false
```

**Ports:**
- `8000` — HTTP API (always available)
- `8443` — HTTPS (only serves when `TLS_ENABLED=true`)

### Tailscale HTTPS Setup

Complete instructions for setting up secure remote access via Tailscale.

#### Step 1: Set up Tailscale (One-Time)

1. Install Tailscale on your host machine: [tailscale.com/download](https://tailscale.com/download)
2. Authenticate: `sudo tailscale up`
   - Tailscale opens a browser window to authenticate
   - Verify with `tailscale status` — you should see your machine's Tailscale IP, device name, username, OS (e.g., `100.78.16.89 desktop github-account@ linux -`)
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
cd docker
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

### Docker Volume Structure

The `transcription-suite-data` Docker volume provides persistent storage. It's mounted to `/data` inside the container:

| Path | Description |
|------|-------------|
| `/data/database/` | SQLite database files for transcription records, metadata, and application state |
| `/data/audio/` | Audio files uploaded for transcription and processed audio data |
| `/data/logs/` | Application logs with automatic rotation |
| `/data/certs/` | TLS certificates (bind-mounted from host, NOT persisted in volume) |
| `/data/config/` | Runtime configuration files including `secrets.json` |

#### Volume Persistence

- **Data persistence**: The volume ensures all data survives container restarts, updates, and recreation
- **Configuration template**: `config.yaml.example` is copied from the image; actual runtime config lives in `/data/config`
- **Primary storage**: Audio files and database are the main storage consumers
- **Log retention**: Logs rotate automatically but remain in the volume

#### Host Access

The volume is accessible from the host system:

```bash
/var/lib/docker/volumes/transcription-suite-data/_data
```

#### Complete Volume Structure

```
/data/
├── config/
│   ├── secrets.json          # HuggingFace token, admin token, LM Studio URL
│   └── .setup_complete       # Marker file
├── database/
│   └── notebook.db           # SQLite database
├── audio/                    # Recorded audio files
├── logs/                     # Server logs
├── certs/                    # TLS certificates (bind-mounted, NOT in volume)
│   ├── my-machine.crt        # Only present when TLS_CERT_PATH is mounted
│   └── my-machine.key        # Only present when TLS_KEY_PATH is mounted
└── tokens/
    └── tokens.json           # API tokens (if using token management)
```

> **Critical:** The `certs/` directory exists in the volume structure, but the actual certificate files are **bind-mounted from the host** and are **not persisted in the volume**. They only appear when you start the container with `TLS_CERT_PATH` and `TLS_KEY_PATH` environment variables.

---

## Backend Development

The REMOTE_SERVER backend is the unified server component that powers TranscriptionSuite. It runs inside Docker for production but can be developed natively for faster iteration.

> **Note:** The primary development workflow uses Docker (see [Development Workflow](#development-workflow)). This section is for developers who need to work directly on the backend code with faster iteration cycles.

### Architecture

The backend is organized into focused modules:

```txt
REMOTE_SERVER/backend/
├── api/                              # FastAPI application
│   ├── main.py                       # App factory, lifespan, routing
│   ├── routes/                       # API endpoint modules
│   │   ├── transcription.py          # POST /api/transcribe/audio
│   │   ├── notebook.py               # Audio Notebook CRUD
│   │   ├── search.py                 # Full-text search
│   │   ├── admin.py                  # Token management
│   │   ├── health.py                 # Health checks
│   │   └── llm.py                    # LLM chat endpoints
│   └── websocket/                    # WebSocket handlers (future)
├── core/                             # ML and audio processing
│   ├── transcription_engine.py       # faster-whisper wrapper
│   ├── diarization_engine.py         # PyAnnote wrapper
│   ├── model_manager.py              # Model lifecycle & GPU management
│   └── audio_utils.py                # Audio preprocessing utilities
├── database/                         # Data persistence
│   └── database.py                   # SQLite + FTS5 operations
├── logging/                          # Centralized logging
│   └── setup.py                      # Structured logging configuration
├── config.py                         # Configuration management
├── setup_wizard.py                   # First-run interactive setup
└── pyproject.toml                    # Package definition & dependencies
```

#### Setting Up the Development Environment

**Prerequisites:**
- Python 3.11+
- CUDA 12.6+ (for GPU acceleration)
- `uv` package manager

**Steps:**

```bash
cd native_src/REMOTE_SERVER/backend
uv venv --python 3.11
uv sync                    # Install all dependencies including diarization
```

The backend uses the package name `server` internally (defined in `pyproject.toml`), so imports use `from server.api import ...`.

**Note:** Speaker diarization via PyAnnote is now included by default. You'll need a HuggingFace token to use diarization features - set it via the `HF_TOKEN` environment variable or in your configuration file.

#### Running the Server Locally

**Development mode with auto-reload:**

```bash
cd native_src/REMOTE_SERVER/backend
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

The backend uses a hierarchical configuration system:

1. **Default values** - Hardcoded in `config.py`
2. **YAML file** - Loaded from:
   - `/app/config.yaml` (Docker)
   - `native_src/config.yaml` (native development)
   - Path specified via `CONFIG_PATH` environment variable
3. **Environment variables** - Highest priority, override YAML settings

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

- `server` - Host, port, TLS settings, Tailscale config
- `transcription` - Whisper model, device, VAD, diarization
- `audio_notebook` - Database path, audio storage, format
- `llm` - LM Studio integration for chat features
- `logging` - Log level, directory, rotation settings
- `auth` - Token storage and expiry

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
- **`mount_frontend()`** - Serves React frontends as static SPAs

##### `core/model_manager.py` - ML Model Lifecycle

Manages GPU memory and model loading:

```python
from server.core.model_manager import get_model_manager

manager = get_model_manager(config)

# Load models (lazy loading)
transcription_model = manager.load_transcription_model()
diarization_pipeline = manager.load_diarization_pipeline()

# Check GPU availability
if manager.gpu_available:
    print(f"GPU: {manager.gpu_info}")

# Cleanup (called automatically on shutdown)
manager.cleanup()
```

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
- `conversations` + `messages` - Chat history

##### `setup_wizard.py` - Interactive Configuration

First-run wizard for Docker deployments:

- Detects TTY availability
- Interactive prompts for HuggingFace token, admin token, etc.
- Non-interactive mode generates secure defaults
- Persists configuration to `/data/config/secrets.json`

#### Frontend Development (React UI)

The REMOTE_SERVER includes a React frontend for remote web access:

**Location:** `native_src/REMOTE_SERVER/frontend/`

**Tech stack:**
- React 18 + TypeScript
- Vite (build tool)
- TailwindCSS (styling)

**Development workflow:**

```bash
cd native_src/REMOTE_SERVER/frontend
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

The Docker build process automatically builds both frontends (Audio Notebook + Remote UI) and serves them as static files.

#### Testing

**Running tests:**

```bash
cd native_src/REMOTE_SERVER/backend
uv sync --extra dev  # Install test dependencies
uv run pytest
```

**Test structure:**

```txt
tests/
├── test_api_routes.py        # API endpoint tests
├── test_transcription.py     # Transcription engine tests
├── test_database.py          # Database operations
└── conftest.py               # Pytest fixtures
```

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
   - Keep `native_src/config.yaml` in sync with Docker config

5. **Code Quality:**
   - Use `ruff` for linting (installed in `build/` venv)
   - Run type checking with `pyright`
   - Follow existing code style (100-char line length)

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

---

## Data Storage

### Database Schema

**Tables:**

- `recordings` - Recording metadata (title, duration, date, summary)
- `segments` - Transcription segments with timestamps
- `words` - Word-level timestamps and confidence
- `conversations` - LLM chat conversations
- `messages` - Individual chat messages
- `recordings_fts` - FTS5 virtual table for search

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
# First run with TLS - certificates are bind-mounted
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose up -d

# Subsequent runs - you MUST provide paths again
# This WON'T work (certificates not available):
docker compose start

# This WILL work:
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/my-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/my-machine.key \
docker compose start
```

The difference: `docker compose up` applies volume mounts from the compose file, while `docker compose start` uses existing container configuration. Since bind mounts are set at container creation, you need `up` (not `start`) to apply new mount paths.

#### 2. HuggingFace Token

**When Collected:**

**Docker Mode:**
1. Interactive setup: Prompted during first-run wizard (`docker compose run --rm transcription-suite --setup`)
2. Environment variable: Can be provided via `HUGGINGFACE_TOKEN` env var
3. Non-interactive: Skipped if not provided (diarization will be disabled)

**Native Development:**
- Set via `HF_TOKEN` environment variable
- Or cached from `huggingface-cli login`

**Storage Locations:**

**Docker:**
- File: `/data/config/secrets.json` inside the container
- Docker volume: `transcription-suite-data` volume at `/data/config/secrets.json`
- Permissions: `0o600` (read/write for owner only)
- Persistence: Survives container recreation, stored in named volume

Structure:
```json
{
  "huggingface_token": "hf_...",
  "admin_token": "...",
  "lm_studio_url": "..."
}
```

**Native/AppImage:**
- Not stored by the client: Clients don't use HuggingFace tokens
- Only the server (Docker or native backend) needs this token for diarization

#### 3. LM Studio Address

**When Collected:**

**Docker Mode:**
1. Interactive setup: Prompted during setup wizard
2. Environment variable: `LM_STUDIO_URL` env var
3. Default: `http://host.docker.internal:1234` (allows container to reach host's LM Studio)

**Native Development:**
- Configured in `native_src/config.yaml`
- Default: `http://127.0.0.1:1234`

**Storage Locations:**

**Docker:**
- File: `/data/config/secrets.json` inside the container (same file as HuggingFace token)
- Docker volume: `transcription-suite-data` volume
- Key: `"lm_studio_url"`

**Native Development:**
- File: `native_src/config.yaml` (not sensitive, just a URL)
- Section: `local_llm.base_url`

**Native/AppImage Client:**
- Not applicable: Clients don't connect to LM Studio
- Only the server backend uses LM Studio for chat features

#### 4. Admin Token (Generated at Server Creation)

**When Collected:**

**Docker Mode:**
1. Interactive setup: Auto-generated or user-provided during setup wizard
2. Non-interactive first run: Auto-generated using `secrets.token_urlsafe(32)`
3. Environment variable: Can be provided via `ADMIN_TOKEN` env var
4. **Important**: When auto-generated, it's shown **only once** during first run

**If you miss the token:**
```bash
# View the generated token
docker compose exec transcription-suite cat /data/config/secrets.json

# Or re-run setup
docker compose run --rm transcription-suite --force-setup
```

**Storage Locations:**

**Docker:**
- File: `/data/config/secrets.json` inside the container
- Docker volume: `transcription-suite-data` volume at `/data/config/secrets.json`
- Permissions: `0o600` (read/write for owner only)
- Key: `"admin_token"`
- Persistence: Survives container recreation

**Native/AppImage Client:**
- File: Platform-specific config file
  - Linux: `~/.config/TranscriptionSuite/client.yaml`
  - Windows: `%APPDATA%\TranscriptionSuite\client.yaml`
  - macOS: `~/Library/Application Support/TranscriptionSuite/client.yaml`
- Key: `server.token`
- When stored: After first successful connection or when provided via CLI flag

Structure:
```yaml
server:
  host: localhost
  port: 8000
  use_https: false
  token: "<admin_token_here>"
```

#### Complete Docker Volume Structure

The `transcription-suite-data` volume contains:

```
/data/
├── config/
│   ├── secrets.json          # HuggingFace token, admin token, LM Studio URL
│   └── .setup_complete       # Marker file
├── database/
│   └── notebook.db           # SQLite database
├── audio/                    # Recorded audio files
├── logs/                     # Server logs
├── certs/                    # TLS certificates (bind-mounted, NOT in volume)
│   ├── my-machine.crt        # Only present when TLS_CERT_PATH is mounted
│   └── my-machine.key        # Only present when TLS_KEY_PATH is mounted
└── tokens/
    └── tokens.json           # API tokens (if using token management)
```

**Critical Note**: The `certs/` directory exists in the volume structure, but the actual certificate files are **bind-mounted from the host** and are **not persisted in the volume**. They only appear when you start the container with `TLS_CERT_PATH` and `TLS_KEY_PATH` environment variables.

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

`~/.config/TranscriptionSuite/client.yaml`:

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

### Model Loading

**First container startup**: On initial boot, the server needs ~30 seconds to load ML models into GPU memory. The container may report as "healthy" before model loading completes. Wait before attempting transcriptions or client connections.

**First transcription of a new model**: Additional time may be needed if Whisper models are being downloaded from HuggingFace (varies by model size and network speed).

### cuDNN Library Errors

If you see errors like:

```
Unable to load any of {libcudnn_ops.so.9.1.0, libcudnn_ops.so.9.1, libcudnn_ops.so.9, libcudnn_ops.so}
Invalid handle. Cannot load symbol cudnnCreateTensorDescriptor
```

This means the Docker image is missing cuDNN libraries. The `faster-whisper` library uses CTranslate2 which requires **system cuDNN libraries** (unlike PyTorch which bundles its own).

**Solution**: The Dockerfile must use `nvidia/cuda:12.6.0-cudnn-runtime-ubuntu22.04` as the base image, not `cuda:12.6.0-base`. This adds ~1.7GB to the image size but is necessary for GPU transcription.

If you encounter this after a Docker update or base image change, rebuild the container:

```bash
cd docker
docker compose build --no-cache
docker compose up -d
```

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
- PyAnnote Audio (optional, for diarization)
- PyTorch + TorchAudio
- SQLite with FTS5

### Client

- Python 3.11
- aiohttp (async HTTP client)
- PyAudio (audio recording)
- PyQt6 (KDE/Windows) or GTK3+AppIndicator (GNOME)
- pyperclip (clipboard)
