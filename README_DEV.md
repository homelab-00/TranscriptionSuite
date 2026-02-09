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
  - [6.4 Docker Image Selection](#64-docker-image-selection)
  - [6.5 Server Update Lifecycle](#65-server-update-lifecycle)
- [7. API Reference](#7-api-reference)
  - [7.1 API Endpoints](#71-api-endpoints)
  - [7.2 WebSocket Protocol](#72-websocket-protocol)
  - [7.3 Live Mode WebSocket Protocol](#73-live-mode-websocket-protocol)
- [8. Backend Development](#8-backend-development)
  - [8.1 Backend Structure](#81-backend-structure)
  - [8.2 Running the Server Locally](#82-running-the-server-locally)
  - [8.3 Configuration System](#83-configuration-system)
  - [8.4 Testing](#84-testing)
- [9. Dashboard Development](#9-dashboard-development)
  - [9.1 Running from Source](#91-running-from-source)
  - [9.2 Verbose Logging](#92-verbose-logging)
  - [9.3 Key Modules](#93-key-modules)
    - [9.3.1 Settings Exposure Rules](#931-settings-exposure-rules)
  - [9.4 Dashboard Architecture & Refactoring](#94-dashboard-architecture--refactoring)
  - [9.5 Server Busy Handling](#95-server-busy-handling)
  - [9.6 Model Management](#96-model-management)
- [10. Configuration Reference](#10-configuration-reference)
  - [10.1 Server Configuration](#101-server-configuration)
  - [10.2 Dashboard Configuration](#102-dashboard-configuration)
- [11. Data Storage](#11-data-storage)
  - [11.1 Database Schema](#111-database-schema)
  - [11.2 Database Migrations](#112-database-migrations)
  - [11.3 Automatic Backups](#113-automatic-backups)
- [12. Code Quality Checks](#12-code-quality-checks)
  - [12.1 Python Code Quality](#121-python-code-quality)
  - [12.2 Complete Quality Check Workflow](#122-complete-quality-check-workflow)
  - [12.3 GitHub CodeQL Layout](#123-github-codeql-layout)
- [13. Troubleshooting](#13-troubleshooting)
  - [13.1 Docker GPU Access](#131-docker-gpu-access)
  - [13.2 Health Check Issues](#132-health-check-issues)
  - [13.3 Tailscale DNS Resolution](#133-tailscale-dns-resolution)
  - [13.4 AppImage Startup Failures](#134-appimage-startup-failures)
  - [13.5 Windows Docker Networking](#135-windows-docker-networking)
  - [13.6 Checking Installed Packages](#136-checking-installed-packages)
- [14. Dependencies](#14-dependencies)
  - [14.1 Server (Docker)](#141-server-docker)
  - [14.2 Dashboard](#142-dashboard)
- [15. Known Issues & Future Work](#15-known-issues--future-work)
  - [15.1 Live Mode Language Setting](#151-live-mode-language-setting)

---

## 1. Quick Reference

### 1.1 Development Commands

```bash
# 1. Setup virtual environments
cd dashboard && uv venv --python 3.13 && uv sync --extra kde && cd ..
cd build && uv venv --python 3.13 && uv sync && cd ..

# 2. Build and run Docker server
cd server/docker && docker compose build && docker compose up -d

# 3. Run dashboard
cd dashboard && uv run transcription-dashboard
```

### 1.2 Running from Source (Development)

```bash
# 1. Run backend server (native Python)
cd server/backend
uv venv --python 3.13 && uv sync
uv run uvicorn server.api.main:app --reload --host 0.0.0.0 --port 8000

# 2. Run dashboard (in a separate terminal)
cd dashboard
uv venv --python 3.13 && uv sync --extra kde  # or --extra gnome / --extra windows
uv run transcription-dashboard --host localhost --port 8000
```

**Notes:**
- Backend runs on port 8000
- Dashboard connects directly to backend API on port 8000
- Backend must be running for dashboard to function
- This setup enables hot-reload for the backend

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
│  │  - Live Mode (RealtimeSTT) continuous transcribe  │  │
│  │  - Real-time STT with VAD (Silero + WebRTC)       │  │
│  │  - PyAnnote diarization                           │  │
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
│                      │  (PyQt6)   │                     │
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
- **Live Mode**: Continuous sentence-by-sentence transcription with automatic model swapping to manage VRAM
- **LM Studio Integration**: Native v1 REST API support for LM Studio 0.4.0+ with stateful chat sessions and Docker-compatible model management

### 2.2 Platform Architectures

| Platform | Architecture | UI Toolkit | Notes |
|----------|--------------|------------|-------|
| **KDE Plasma** | Single-process | PyQt6 | Tray and Dashboard share one process |
| **Windows** | Single-process | PyQt6 | Same as KDE |
| **GNOME** | Dual-process | GTK3 + PyQt6 | Tray (GTK3) and Dashboard (PyQt6) via D-Bus |

**GNOME Dual-Process Design**: The tray uses GTK3 + AppIndicator3, while the Dashboard uses PyQt6. They run in separate processes and communicate via D-Bus (`com.transcriptionsuite.Dashboard`).

**Dashboard UI Design**: All platforms feature a **sidebar navigation** layout:
- Left sidebar with navigation buttons and real-time status lights
- Status lights show Server and Client states with color indicators (green=running, red=unhealthy, blue=starting, orange=stopped, gray=not set up)
- Main content area on the right with views: Home, Notebook, Docker Server, Client
- Notebook tab contains Calendar, Search, and Import sub-tabs
- Settings accessible via hamburger menu with four tabs: App, Client, Server, Notebook

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
│   │   │   ├── dashboard.py      # Main window (654 lines)
│   │   │   ├── server_mixin.py   # Server control methods (739 lines)
│   │   │   ├── client_mixin.py   # Client control methods (530 lines)
│   │   │   ├── dialogs.py        # About/README dialogs (458 lines)
│   │   │   ├── log_window.py     # Log viewer with highlighting (406 lines)
│   │   │   ├── styles.py         # Stylesheets (566 lines)
│   │   │   ├── utils.py          # Utilities & constants (106 lines)
│   │   │   ├── views/            # View creation functions
│   │   │   │   ├── server_view.py # Server management view (341 lines)
│   │   │   │   └── client_view.py # Client management view (339 lines)
│   │   │   ├── tray.py           # System tray
│   │   │   ├── settings_dialog.py # Settings UI
│   │   │   ├── notebook_view.py  # Audio notebook
│   │   │   └── ... (other UI components)
│   │   ├── gnome/                # GNOME tray + D-Bus IPC
│   │   │   ├── tray.py           # GTK3 AppIndicator tray
│   │   │   ├── dbus_service.py   # D-Bus IPC for tray ↔ dashboard
│   │   │   └── qt_dashboard_main.py # Qt dashboard entrypoint
│   │   ├── windows/              # Windows (PyQt6)
│   │   │   ├── tray.py           # System tray
│   │   │   └── ... (other UI components)
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
│   │   ├── Dockerfile            # Runtime-bootstrap image (small base + first-run sync)
│   │   ├── docker-compose.yml    # Container orchestration
│   │   └── entrypoint.py         # Container entrypoint
│   ├── backend/                  # FastAPI backend
│   │   ├── api/                  # FastAPI routes
│   │   ├── core/                 # ML engines (transcription, diarization, VAD)
│   │   ├── database/             # SQLite + FTS5 + migrations
│   │   └── pyproject.toml        # Server dependencies (pinned versions)
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
uv venv --python 3.13
uv sync --extra kde    # or --extra gnome / --extra windows
cd ..

# Build tools virtual environment
cd build
uv venv --python 3.13
uv sync
cd ..
```

### 4.2 Step 2: Build Docker Image

```bash
cd server/docker
docker compose build
```

**What happens:**
1. Builds a small server image with app code and bootstrap tooling
2. Defers Python dependency install to first startup (`bootstrap_runtime.py`)
3. Stores runtime venv in `transcriptionsuite-runtime` and uv cache in `transcriptionsuite-uv-cache`

**Build with specific tag:**
To build an image with a specific tag (instead of default `latest`):
```bash
TAG=v0.4.7 docker compose build
```
This produces `ghcr.io/homelab-00/transcriptionsuite-server:v0.4.7`.

**Note:** The `build/docker-build-push.sh` script is used to **push** the image you just built. It also supports the `TAG` environment variable:
```bash
TAG=v0.4.7 ./build/docker-build-push.sh
```

**Force rebuild:**
```bash
docker compose build --no-cache
```

**Managing Image Tags:**

Tag existing local images:
```bash
# Create a new tag pointing to an existing image
# e.g. make existing image 'v0.4.7' also be tagged as 'latest'
docker tag ghcr.io/homelab-00/transcriptionsuite-server:v0.4.7 ghcr.io/homelab-00/transcriptionsuite-server:latest

# List all tags for this repository
docker image ls ghcr.io/homelab-00/transcriptionsuite-server
```

Remove tags:
```bash
# Remove a tag (only deletes the tag, not the image if other tags reference it)
docker rmi ghcr.io/homelab-00/transcriptionsuite-server:old-tag

# Remove all untagged images (clean up)
docker image prune -f
```

**Typical tag management workflow:**
1. Build and push a release: `TAG=v0.4.7 docker compose build && ./build/docker-build-push.sh v0.4.7`
2. Create an alias: `docker tag ghcr.io/homelab-00/transcriptionsuite-server:v0.4.7 ghcr.io/homelab-00/transcriptionsuite-server:latest`
3. Push the alias: `docker push ghcr.io/homelab-00/transcriptionsuite-server:latest`
4. Remove old tags when no longer needed: `docker rmi ghcr.io/homelab-00/transcriptionsuite-server:v0.4.6`

**Note:** The `docker-build-push.sh` script automatically creates and pushes a `latest` tag when pushing release versions (v*.*.* format).

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

Prerequisite: You must have built the image first (see Step 2).

```bash
# Push the most recent local image as 'latest'
./build/docker-build-push.sh

# Push a specific tag (must exist locally)
./build/docker-build-push.sh v0.4.7

# Push a custom tag
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
uv venv --python 3.13
uv sync    # Installs PyInstaller, build, ruff, pytest
```

### 5.2 Build Matrix

| Platform | Method | Output | Target Requirements |
|----------|--------|--------|---------------------|
| **KDE (Linux)** | PyInstaller + AppImage | Fully standalone | None |
| **GNOME (Linux)** | Source bundle + AppImage | Semi-portable | Python 3.13+, GTK3, AppIndicator3, PyQt6 |
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
sudo pacman -S --needed python gtk3 libappindicator-gtk3 python-gobject python-pyaudio \
    python-numpy python-aiohttp python-pyqt6 wl-clipboard

# Ubuntu/Debian
sudo apt install python3 python3-gi gir1.2-appindicator3-0.1 python3-pyaudio \
    python3-numpy python3-aiohttp python3-pyqt6 wl-clipboard
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
uv venv --python 3.13
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

**`transcriptionsuite-data`** (mounted to `/data`):

| Path | Description |
|------|-------------|
| `/data/database/` | SQLite database and backups |
| `/data/audio/` | Recorded audio files |
| `/data/logs/` | Server logs |
| `/data/tokens/` | Authentication tokens |

**`transcriptionsuite-models`** (mounted to `/models`):

| Path | Description |
|------|-------------|
| `/models/hub/` | HuggingFace models cache (Whisper, PyAnnote) |

**`transcriptionsuite-runtime`** (mounted to `/runtime`):

| Path | Description |
|------|-------------|
| `/runtime/.venv/` | Runtime Python virtualenv used by the server |
| `/runtime/.runtime-bootstrap-marker.json` | Fingerprint + sync metadata |
| `/runtime/bootstrap-status.json` | Bootstrap feature status (diarization availability, etc.) |

**`transcriptionsuite-uv-cache`** (mounted to `/runtime-cache`):

| Path | Description |
|------|-------------|
| `/runtime-cache/` | uv package cache used for delta dependency updates |

**Optional user config** (bind mount to `/user-config`):

When `USER_CONFIG_DIR` is set, mounts custom config and logs.

### 6.4 Docker Image Selection

The application uses a hardcoded remote image (`ghcr.io/homelab-00/transcriptionsuite-server`) with flexible tag selection:

**Default behavior:**
- The Dashboard automatically selects the most recent local image by build date (not the `:latest` tag)
- A dropdown in the Server tab allows selecting a specific image from available local images
- Each image entry shows: tag, build date, and size
- The "Most Recent (auto)" option (default) picks the newest image by build date
- If no local images exist, the system falls back to pulling `:latest` from the registry
- Runtime dependency volumes are preserved across normal image updates
- Dependency refresh uses `uv sync` against existing runtime venv (delta update path)

**Using specific versions:**
```bash
# Use a specific tag (must exist locally or will be pulled from ghcr.io)
TAG=v0.4.7 docker compose up -d

# Set TAG as environment variable
export TAG=dev-branch
docker compose up -d
```

**Building and using local images:**
```bash
# Build with custom tag
TAG=my-custom docker compose build

# Use the local image you just built
TAG=my-custom docker compose up -d
```

**Note:** The `TAG` environment variable is the only way to override which image version is used. If you have multiple local images with different tags, you must explicitly specify which one via `TAG=...` or it defaults to looking for the `latest` tag.

### 6.5 Server Update Lifecycle

This section describes exactly what updates when the Docker image changes versus when runtime dependency volumes change.

**At server start (`docker compose up -d`)**
1. Docker starts/recreates the container from the selected image tag.
2. `docker-entrypoint.sh` runs `bootstrap_runtime.py`.
3. Bootstrap checks `/runtime/.runtime-bootstrap-marker.json` against current dependency fingerprint (`uv.lock` + Python ABI + arch + schema version).
4. If marker + fingerprint match, bootstrap runs full runtime integrity validation:
   - `uv sync --check --frozen --no-dev --project /app/server`
   - with `UV_PROJECT_ENVIRONMENT=/runtime/.venv`
5. Bootstrap chooses one path:
   - `skip`: marker matches **and** integrity check passes.
   - `delta-sync`: marker mismatch, or marker matches but integrity check fails.
   - `rebuild-sync`: `/runtime/.venv` missing, ABI/arch incompatibility, or `delta-sync` fails/does not heal integrity.

**What changes when the Docker image is updated**
- Updated:
  - Application code in the image (`/app/server`).
  - Bootstrap scripts and defaults shipped in the image.
  - Any base OS/image-layer changes included in the new tag.
- Usually not updated:
  - `transcriptionsuite-runtime` (`/runtime/.venv`) unless bootstrap decides sync/rebuild is needed.
  - `transcriptionsuite-uv-cache` (`/runtime-cache`) unless explicitly removed.
  - `transcriptionsuite-data` and `transcriptionsuite-models`.

In short: an image update mainly changes code and runtime tooling; dependency downloads happen only if bootstrap detects dependency drift, runtime incompatibility, or runtime integrity failure.

**When the runtime dependency volume is updated**
- `delta-sync` (incremental update) happens when:
  - `uv.lock` content changed between image versions.
  - Marker fingerprint no longer matches current runtime fingerprint.
  - Marker exists but is from an older bootstrap schema/fingerprint mode.
  - Marker matches but lock-level runtime integrity check fails.
- `rebuild-sync` (fresh venv + sync) happens when:
  - `/runtime/.venv` is missing.
  - Runtime reset is requested (Dashboard: `Remove Runtime`).
  - ABI/arch incompatibility is detected (with `BOOTSTRAP_REBUILD_POLICY=abi_only`).
  - `delta-sync` fails or post-sync integrity check still fails.

**How runtime updates minimize download size**
- Bootstrap runs `uv sync --frozen --no-dev` against existing `/runtime/.venv` for delta updates.
- `UV_CACHE_DIR` is persisted in `transcriptionsuite-uv-cache` (`/runtime-cache`), so rebuilt venvs can reuse cached wheels.
- Only changed packages are downloaded when possible; unchanged packages are reused.
- Large dependency jumps (for example major torch/CUDA changes) may still require large downloads.
- If UV cache is enabled in `.env` but the Docker `transcriptionsuite-uv-cache` volume is manually deleted, startup keeps cache mode enabled, logs a cold-cache warning, and Docker recreates the volume on next `up -d`.

**Operational scenarios**

| Scenario | Image Pull | Runtime Venv (`/runtime`) | UV Cache (`/runtime-cache`) | Expected Network Cost |
|----------|------------|---------------------------|-----------------------------|-----------------------|
| App-only release, unchanged `uv.lock` | Yes (new image layers) | `skip` | Reused | Low (image only) |
| Release with dependency changes in `uv.lock` | Yes | `delta-sync` | Reused | Medium (changed deps only) |
| Runtime venv removed, cache kept | No/Yes | `rebuild-sync` | Reused | Medium (often reduced via cache) |
| Runtime + cache removed | No/Yes | `rebuild-sync` | Recreated empty | High (full dependency fetch) |
| UV cache removed manually (decision still enabled) | No/Yes | `skip`/`delta-sync` based on runtime integrity and lock drift | Recreated empty | Low to High (depends on dependency drift) |
| Python ABI/arch incompatibility | Usually Yes | `rebuild-sync` | Reused | Medium to High |

**Recommended update flow (least disruption)**
```bash
cd server/docker
docker compose pull
docker compose up -d
```

Use runtime reset only for recovery/maintenance. Prefer keeping `transcriptionsuite-uv-cache` unless you explicitly want a fully cold reinstall.

**Config reset semantics**
- Normal image/runtime updates do **not** require deleting `~/.config/TranscriptionSuite` (or platform equivalent).
- Manually deleting UV cache volume does **not** require config removal.
- Remove config only for full reset or severe config corruption/recovery scenarios.
- Dashboard "Also remove config directory" now performs a full dashboard state reset:
  - Removes primary config directory (`~/.config/TranscriptionSuite` on Linux).
  - Removes dashboard external state cache (`~/.cache/TranscriptionSuite` or `$XDG_CACHE_HOME/TranscriptionSuite`), including:
    - `docker-user-config/` (effective `/user-config` bind mount copy),
    - fallback managed `.env`,
    - fallback saved Docker auth token.

---

## 7. API Reference

### 7.1 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (no auth) |
| `/api/status` | GET | Server status, GPU info |
| `/api/auth/login` | POST | Authenticate with token |
| `/api/admin/models/load` | POST | Load transcription models (admin only) |
| `/api/admin/models/unload` | POST | Unload models to free GPU memory (admin only) |
| `/api/transcribe/audio` | POST | Transcribe uploaded audio (`translation_enabled`, `translation_target_language` supported) |
| `/api/transcribe/cancel` | POST | Cancel running transcription |
| `/ws` | WebSocket | Real-time audio streaming |
| `/ws/live` | WebSocket | Live Mode continuous transcription |
| `/api/notebook/recordings` | GET | List all recordings |
| `/api/notebook/recordings/{id}` | GET/DELETE | Get or delete recording |
| `/api/notebook/recordings/{id}/export` | GET | Export recording (`txt` for pure notes, `srt`/`ass` for timestamp-capable notes) |
| `/api/notebook/transcribe/upload` | POST | Upload and transcribe with diarization (`translation_enabled`, `translation_target_language` supported) |
| `/api/notebook/calendar` | GET | Get recordings by date range |
| `/backups` | GET | List available database backups |
| `/backup` | POST | Create new database backup |
| `/restore` | POST | Restore database from backup |
| `/api/search` | GET | Full-text search |
| `/api/llm/chat` | POST | LLM chat integration |

**LM Studio chat context:** When a new chat is started for a recording, the server injects the
recording transcript as context using the **pure transcript** (no timestamps). Speaker tags are
included **only** when diarization is enabled.

### 7.2 WebSocket Protocol

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

### 7.3 Live Mode WebSocket Protocol

**Connection flow:**
1. Connect to `/ws/live`
2. Send auth: `{"type": "auth", "data": {"token": "<token>"}}`
3. Receive: `{"type": "auth_ok"}`
4. Send start:
   `{"type": "start", "data": {"config": {"model": "Systran/faster-whisper-large-v3", "language": "el", "translation_enabled": true, "translation_target_language": "en"}}}`
5. Stream binary audio (16kHz PCM Int16)
6. Receive real-time updates:
   - `{"type": "partial", "data": {"text": "..."}}` - Interim transcription
   - `{"type": "sentence", "data": {"text": "..."}}` - Completed sentence
   - `{"type": "state", "data": {"state": "LISTENING|PROCESSING"}}` - Engine state changes
7. Send stop: `{"type": "stop"}`

**Key differences from `/ws`:**
- Continuous operation: Engine stays active between utterances
- Sentence-by-sentence output: Completed sentences sent immediately
- Mute control: Client can pause/resume audio capture without disconnecting
- Model swapping: Unloads main model to free VRAM for Live Mode model

**Audio format:**
- Sample rate: 16kHz, Format: Int16 PCM (little-endian)
- Binary messages: `[4 bytes metadata length][metadata JSON][PCM Int16 data]`

---

## 8. Backend Development

### 8.1 Backend Structure

```
server/backend/
├── api/
│   ├── main.py                   # App factory, lifespan, routing
│   └── routes/                   # API endpoint modules
├── core/
│   ├── stt/engine.py             # AudioToTextRecorder (main STT engine)
│   ├── diarization_engine.py     # PyAnnote wrapper
│   ├── model_manager.py          # Model lifecycle, job tracking
│   ├── realtime_engine.py        # Async wrapper for real-time STT
│   ├── live_engine.py            # Live Mode engine (RealtimeSTT)
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
uv venv --python 3.13
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

### 8.4 Testing

```bash
./build/.venv/bin/pytest server/backend/tests
```

---

## 9. Dashboard Development

### 9.1 Running from Source

```bash
cd dashboard
uv venv --python 3.13
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

**Common (Shared):**

| Module | Purpose |
|--------|---------|
| `common/api_client.py` | HTTP client, WebSocket, error handling, backup/export methods |
| `common/orchestrator.py` | Main controller, state machine |
| `common/docker_manager.py` | Docker server control |
| `common/setup_wizard.py` | First-time setup |
| `common/tailscale_resolver.py` | Tailscale IP fallback when DNS fails |

**KDE (PyQt6) - Modular Architecture:**

| Module | Purpose | Lines |
|--------|---------|-------|
| `kde/dashboard.py` | Main window with sidebar, navigation, and lifecycle | 654 |
| `kde/server_mixin.py` | Server control methods (start/stop, image/volume mgmt, logs) | 739 |
| `kde/client_mixin.py` | Client control methods (start/stop, models, live transcriber) | 530 |
| `kde/dialogs.py` | About dialog, README viewer, hamburger menu | 458 |
| `kde/log_window.py` | Log viewer with syntax highlighting and line numbers | 406 |
| `kde/styles.py` | Stylesheet definitions for consistent theming | 566 |
| `kde/utils.py` | Utility functions (path resolution) and constants | 106 |
| `kde/views/server_view.py` | Server management view UI creation | 341 |
| `kde/views/client_view.py` | Client management view UI creation | 339 |
| `kde/settings_dialog.py` | Settings dialog with Notebook backup/restore tab |  |
| `kde/notebook_view.py` | Audio Notebook with Calendar, Search, Import tabs |  |
| `kde/calendar_widget.py` | Calendar view with export context menu |  |

**GNOME (GTK3 Tray + Qt Dashboard):**

| Module | Purpose |
|--------|---------|
| `gnome/tray.py` | GTK3 AppIndicator tray + D-Bus service |
| `gnome/dbus_service.py` | D-Bus IPC interface |
| `gnome/qt_dashboard_main.py` | Qt dashboard entrypoint |

**Architecture Notes:**
- **KDE**: Fully modularized with mixins (`ServerControlMixin`, `ClientControlMixin`, `DialogsMixin`) for clean separation of concerns. Main dashboard.py is 654 lines.
- **GNOME**: Uses the same PyQt6 dashboard as KDE/Windows, launched from the GTK3 tray via D-Bus.
- **View Creation**: KDE uses factory functions in `views/` package for server and client views, keeping dashboard.py focused on navigation and lifecycle.

### 9.3.1 Settings Exposure Rules

- **Single-source UI exposure**: Every setting must be shown **either** in one of the Dashboard Client/Server views or the Settings dialog tabs (App/Client/Notebook) **or** in the Settings dialog Server tab — never both.
- **Server tab descriptions**: The Server tab reads descriptions directly from comments in the active user `config.yaml` (e.g., `~/.config/TranscriptionSuite/config.yaml`). If you change those comments, the UI descriptions update automatically on next open.

### 9.4 Dashboard Architecture & Refactoring

#### KDE Dashboard Refactoring (Completed)

The KDE dashboard was refactored from a single 4035-line `dashboard.py` file into modular, maintainable components:

**Refactoring Strategy:**
1. **Mixins for Functionality**: Extracted server and client control logic into reusable mixins
2. **Utility Modules**: Separated stylesheets, utilities, and constants into dedicated files
3. **Dialog Management**: Centralized all dialog-related code (About, README viewer, menus)
4. **View Factories**: Created factory functions for server and client views to keep main dashboard focused

**File Breakdown:**

| Component | File | Lines | Responsibility |
|-----------|------|-------|-----------------|
| **Main Window** | `dashboard.py` | 654 | Window setup, navigation, lifecycle, view management |
| **Server Control** | `server_mixin.py` | 739 | Docker server start/stop, image/volume management, server logs |
| **Client Control** | `client_mixin.py` | 530 | Client start/stop, model management, live transcriber, notifications |
| **Dialogs** | `dialogs.py` | 458 | About dialog, README viewer, hamburger menu, help menu |
| **Log Viewer** | `log_window.py` | 406 | Syntax-highlighted log display with line numbers |
| **Stylesheets** | `styles.py` | 566 | QSS stylesheets for consistent theming |
| **Utilities** | `utils.py` | 106 | Path resolution, constants (GitHub URLs) |
| **Server View** | `views/server_view.py` | 341 | Server management UI (status, controls, volumes) |
| **Client View** | `views/client_view.py` | 339 | Client management UI (status, controls, live preview) |

**Total**: 4,139 lines across 9 files (all under 800 lines each)

**Benefits:**
- **Maintainability**: Each file has a single, clear responsibility
- **Testability**: Mixins can be tested independently
- **Reusability**: Mixins can be shared with other UI frameworks if needed
- **Readability**: Reduced cognitive load per file
- **Scalability**: Easy to add new features without bloating main dashboard

**Mixin Architecture:**

```python
class DashboardWindow(ServerControlMixin, ClientControlMixin, DialogsMixin, QMainWindow):
    """Main dashboard inherits all control logic from mixins."""
    # Focuses on: window setup, navigation, view management, lifecycle
```

#### Future Refactoring Opportunities

- **Windows Dashboard**: Apply mixin pattern once fully implemented
- **Shared Mixins**: Consider moving `ServerControlMixin` and `ClientControlMixin` to `common/` for potential reuse across platforms

### 9.5 Server Busy Handling

The dashboard handles server busy conditions automatically:
- HTTP transcription: Server returns 409, dashboard shows "Server Busy" notification
- WebSocket recording: Server sends `session_busy` message, dashboard shows error

### 9.6 Model Management

The dashboard provides a convenient way to manage GPU memory via the system tray and client view:
- Automatically disabled when server is stopped or becomes unhealthy
- Checks server for active transcriptions before unloading
- Returns HTTP 409 if server is busy

**Live Mode Model Swapping:**
- When Live Mode starts, main transcription model is automatically unloaded to free VRAM
- Live Mode uses the same model as main_transcriber by default (configurable in config.yaml)
- When Live Mode stops, main model is reloaded for normal transcription
- This ensures efficient VRAM usage on consumer GPUs (e.g., RTX 3060 12GB)

---

## 10. Configuration Reference

### 10.1 Server Configuration

Config file: `~/.config/TranscriptionSuite/config.yaml` (Linux) or `$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml` (Windows)

**Key sections:**
- `main_transcriber` - Primary Whisper model, device, batch settings
- `live_transcriber` - Live Mode continuous transcription (uses same model as main by default)
- `diarization` - PyAnnote model and speaker detection
- `remote_server` - Host, port, TLS settings
- `storage` - Database path, audio storage
- `local_llm` - LM Studio integration (supports v1 REST API for LM Studio 0.4.0+)
- `backup` - Automatic database backup settings

**Live Mode Configuration:**
- `live_transcriber.enabled` - Enable/disable Live Mode feature
- `live_transcriber.post_speech_silence_duration` - Grace period after silence (default: 3.0s)
- `live_transcriber.live_language` - Language code for Live Mode (default: "en"; modified via Dashboard Client view)
- `live_transcriber.translation_enabled` - Enable source-language -> English translation in Live Mode
- `live_transcriber.translation_target_language` - Translation target (v1: `"en"` only)
- Model is inherited from `main_transcriber.model` if not explicitly set
- Automatically swaps models to free VRAM when Live Mode starts
- **Note:** Live Mode always unloads the main model and starts its own engine. The dashboard currently sends the main model on Live Mode start unless you explicitly wire `live_transcriber.model` through the client/server path.

**Main Transcription Translation (v1):**
- `longform_recording.translation_enabled` - Enable translation for longform/static/notebook transcription flows
- `longform_recording.translation_target_language` - Translation target (v1: `"en"` only)
- Translation uses native Whisper/Faster-Whisper `task="translate"` (source-language -> English)

**Environment variables:**
| Variable | Purpose |
|----------|---------|
| `HF_TOKEN` | HuggingFace token for PyAnnote models |
| `HUGGINGFACE_TOKEN_DECISION` | One-time onboarding state: `unset`, `provided`, `skipped` |
| `UV_CACHE_VOLUME_DECISION` | One-time UV cache onboarding state: `unset`, `enabled`, `skipped` |
| `BOOTSTRAP_CACHE_DIR` | Runtime package cache path (`/runtime-cache` when enabled, `/tmp/uv-cache` when skipped) |
| `USER_CONFIG_DIR` | Path to user config directory |
| `LOG_LEVEL` | Logging verbosity (DEBUG, INFO, WARNING) |
| `TLS_ENABLED` | Enable HTTPS |
| `TLS_CERT_PATH` | Path to TLS certificate |
| `TLS_KEY_PATH` | Path to TLS private key |

**Diarization prerequisites:** a valid HuggingFace token is not enough by itself; users must also accept the model terms at `https://huggingface.co/pyannote/speaker-diarization-community-1`.

### 10.2 Dashboard Configuration

Config file: `~/.config/TranscriptionSuite/dashboard.yaml`

```yaml
server:
  host: localhost              # Local server hostname
  port: 8000                   # Server port
  use_https: false             # Enable HTTPS (required for remote/Tailscale)
  token: ""                    # Authentication token
  use_remote: false            # Use remote_host instead of host
  remote_host: ""              # Remote server hostname (no protocol/port)
  auto_reconnect: true         # Auto-reconnect on disconnect
  reconnect_interval: 10       # Seconds between attempts

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
1. Add a new file in `migrations/versions/` (e.g., `004_schema_sanity_and_segment_backfill.py`)
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

**Manual Backup/Restore via Dashboard:**

The Dashboard provides a graphical interface for backup management in Settings → Notebook tab:
- **Create Backup**: Manually trigger a database backup
- **List Backups**: View all available backups with timestamps and sizes
- **Restore Backup**: Restore database from any backup (creates safety backup first)

**Export Individual Recordings:**

Recordings can be exported from the Audio Notebook Calendar view:
- Right-click on any recording → "Export transcription"
- **Text format (.txt)**: Available only for pure transcription notes (no word-level timestamps, no diarization)
- **SubRip format (.srt)**: Available for timestamp-capable notes (word timestamps enabled, with or without diarization)
- **Advanced SubStation Alpha (.ass)**: Available for timestamp-capable notes (word timestamps enabled, with or without diarization)

**API Endpoints:**
- `GET /api/notebook/recordings/{id}/export?format=txt|srt|ass` - Export recording (capability-gated)
- `GET /backups` - List available backups
- `POST /backup` - Create new backup
- `POST /restore` - Restore from backup (requires `filename` in request body)

---

## 12. Code Quality Checks

### 12.1 Python Code Quality

All Python code quality tools are installed in the build environment. Run these from the repository root:

```bash
# Lint check (identifies issues without fixing)
./build/.venv/bin/ruff check .

# Auto-format code (fixes style issues automatically)
./build/.venv/bin/ruff format .

# Type checking (static type analysis)
./build/.venv/bin/pyright
```

**Check specific directories:**
```bash
./build/.venv/bin/ruff check server/backend/
./build/.venv/bin/ruff format dashboard/
./build/.venv/bin/pyright dashboard/
```

**Preview changes without modifying files:**
```bash
./build/.venv/bin/ruff format --diff .
```

**Typical workflow:**
1. Run `ruff check` to identify issues
2. Run `ruff format` to auto-fix style issues
3. Run `pyright` for type errors (requires manual fixes)

### 12.2 Complete Quality Check Workflow

Run all checks across the entire codebase:

```bash
# From repository root

# 1. Python checks
./build/.venv/bin/ruff check .
./build/.venv/bin/ruff format .
./build/.venv/bin/pyright

# 2. Python tests
./build/.venv/bin/pytest server/backend/tests
```

### 12.3 GitHub CodeQL Layout

The repository uses two different `.github` locations for different purposes:

- `.github/workflows/`: GitHub Actions workflow definitions (when jobs run, trigger rules, runner setup).
- `.github/codeql/`: CodeQL configuration consumed by workflows (for example, `codeql-config.yml` path filters and query configuration).

Keep one active CodeQL workflow in `.github/workflows/` to avoid duplicate runs and conflicting results.

---

## 13. Troubleshooting

### 13.1 Docker GPU Access

```bash
# Verify GPU is accessible
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu24.04 nvidia-smi

# Check container logs
docker compose logs -f
```

### 13.2 Health Check Issues

```bash
# Check health status
docker compose ps
docker inspect transcriptionsuite-container | grep Health -A 10

# Test health endpoint
docker compose exec transcriptionsuite-container curl -f http://localhost:8000/health
```

### 13.3 Tailscale DNS Resolution

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

### 13.4 AppImage Startup Failures

```bash
# Run from terminal to see errors
./TranscriptionSuite-KDE-x86_64.AppImage

# Check for missing libraries
./TranscriptionSuite-KDE-x86_64.AppImage --appimage-extract
ldd squashfs-root/usr/bin/TranscriptionSuite-KDE
```

### 13.5 Windows Docker Networking

**Issue**: On Windows Docker Desktop, `network_mode: "host"` doesn't expose container ports to the Windows host because containers run inside a Linux VM (WSL2/Hyper-V). The server listens inside the VM but Windows can't reach `localhost:8000`.

**Solution**: The setup wizard automatically generates platform-specific `docker-compose.yml`:
- **Linux**: Uses `network_mode: "host"` for direct access
- **Windows**: Uses explicit port mappings (`8000:8000`, `8443:8443`) with bridge networking
- **LM Studio URL**: Windows uses `host.docker.internal:1234` to reach host services (works with LM Studio 0.4.0+ v1 API)

**For existing installations**, manually edit `docker-compose.yml`:
```yaml
# Replace:
network_mode: "host"

# With:
ports:
  - "8000:8000"
  - "8443:8443"
```

Then restart: `docker compose down && docker compose up -d`

### 13.6 Checking Installed Packages

To inspect packages in the runtime venv used by the server:

```bash
docker exec transcriptionsuite-container /runtime/.venv/bin/python -c "
from importlib.metadata import distributions
for dist in sorted(distributions(), key=lambda d: d.name.lower()):
    print(f'{dist.name:40} {dist.version}')
"
```

To validate full lock-level runtime integrity (all packages, not piecemeal checks):

```bash
docker exec transcriptionsuite-container env \
  UV_PROJECT_ENVIRONMENT=/runtime/.venv \
  UV_CACHE_DIR=/runtime-cache \
  UV_PYTHON=/usr/bin/python3.13 \
  uv sync --check --frozen --no-dev --project /app/server
```

If persistent UV cache is disabled, use `UV_CACHE_DIR=/tmp/uv-cache` instead.

If this command exits non-zero, the runtime environment is not fully aligned with `uv.lock`.

These checks are useful for:
- Verifying package versions
- Debugging dependency conflicts
- Confirming successful repair after bootstrap `delta-sync` or `rebuild-sync`

---

## 14. Dependencies

### 14.1 Server (Docker)

- Python 3.13
- FastAPI + Uvicorn
- faster-whisper (CTranslate2 backend)
- RealtimeSTT 0.3.104+ (Live Mode continuous transcription)
- PyAnnote Audio 4.0.3+ (speaker diarization)
- PyTorch 2.8.0 + TorchAudio 2.8.0
- SQLite with FTS5
- NVIDIA GPU with CUDA support

### 14.2 Dashboard

- Python 3.13
- aiohttp (async HTTP client)
- PyAudio (audio recording)
- PyQt6 (KDE/Windows) or GTK3+AppIndicator (GNOME)

---

## 15. Known Issues & Future Work

### 15.1 Live Mode Language Setting

**Issue**: The `live_language` setting in `server/config.yaml` (line 117) is currently not being respected by the Live Mode transcription engine.

**Current State**:
- Setting is commented out in config.yaml with a TODO note
- Dashboard UIs (KDE/GNOME) have a language selector, but it may not override the server's behavior
- Language can be set through the dashboard, but effectiveness needs verification

**Action Required**:
- Investigate why the setting isn't being applied to the Live Mode engine
- Verify the data flow from dashboard → API → live engine configuration
- Ensure language preference is properly passed to the underlying transcription model
- Test with various languages to confirm the setting takes effect

**Workaround**: Use the language selector in the dashboard Client view, which attempts to set the language via the WebSocket configuration payload.
