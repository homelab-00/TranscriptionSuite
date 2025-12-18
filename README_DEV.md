# TranscriptionSuite - Developer Notes

This document contains technical details, architecture decisions, and development notes for TranscriptionSuite.

---

## Architecture Overview

TranscriptionSuite uses a **client-server architecture**:

```txt
┌─────────────────────────────────────────────────────────────┐
│                     Docker Container                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  TranscriptionSuite Server                          │    │
│  │  - FastAPI REST API                                 │    │
│  │  - faster-whisper transcription                     │    │
│  │  - PyAnnote diarization                             │    │
│  │  - Audio Notebook (React frontend)                  │    │
│  │  - SQLite + FTS5 search                             │    │
│  └─────────────────────────────────────────────────────┘    │
│                          ↕ HTTP/WebSocket                    │
└─────────────────────────────────────────────────────────────┘
                           ↕
┌─────────────────────────────────────────────────────────────┐
│                     Native Clients                           │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │ KDE Tray  │  │GNOME Tray │  │Windows Tray│               │
│  │ (PyQt6)   │  │(GTK+AppInd)│ │ (PyQt6)   │               │
│  └───────────┘  └───────────┘  └───────────┘               │
│  - Microphone recording                                      │
│  - Clipboard integration                                     │
│  - System notifications                                      │
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
├── server/                       # Server code (runs in Docker)
│   ├── api/                      # FastAPI application
│   │   ├── main.py               # App factory, lifespan, static mounting
│   │   └── routes/               # API endpoints
│   │       ├── health.py         # /health endpoint
│   │       ├── transcription.py  # /api/transcribe/* endpoints
│   │       ├── notebook.py       # /api/notebook/* endpoints
│   │       ├── search.py         # /api/search endpoint
│   │       └── admin.py          # /api/admin/* endpoints
│   ├── core/                     # ML engines
│   │   ├── transcription_engine.py  # Unified Whisper wrapper
│   │   ├── diarization_engine.py    # PyAnnote wrapper
│   │   ├── model_manager.py         # Model lifecycle management
│   │   └── audio_utils.py           # Audio processing utilities
│   ├── database/                 # SQLite + FTS5
│   │   └── database.py           # Schema, CRUD operations
│   ├── logging/                  # Centralized logging
│   │   └── setup.py              # Structured JSON logging
│   ├── setup_wizard.py           # First-run configuration wizard
│   ├── config.py                 # Server configuration loader
│   └── pyproject.toml            # Server dependencies
│
├── client/                       # Native client (runs locally)
│   ├── common/                   # Shared client code
│   │   ├── api_client.py         # HTTP client for server communication
│   │   ├── audio_recorder.py     # PyAudio recording wrapper
│   │   ├── orchestrator.py       # Main controller, state machine
│   │   ├── tray_base.py          # Abstract tray interface
│   │   ├── config.py             # Client configuration
│   │   └── models.py             # Shared data models
│   ├── kde/                      # KDE Plasma (PyQt6)
│   │   └── tray.py               # Qt6 system tray implementation
│   ├── gnome/                    # GNOME (GTK + AppIndicator)
│   │   └── tray.py               # GTK/AppIndicator implementation
│   ├── windows/                  # Windows (PyQt6)
│   │   └── tray.py               # Windows tray (same as KDE)
│   ├── build/                    # Build configurations
│   │   ├── pyinstaller-kde.spec
│   │   └── pyinstaller-windows.spec
│   ├── __main__.py               # CLI entry point
│   └── pyproject.toml            # Client dependencies
│
├── docker/                       # Docker infrastructure
│   ├── Dockerfile                # Multi-stage build (frontend + Python)
│   ├── docker-compose.yml        # Local deployment
│   ├── docker-compose.remote.yml # Remote/Tailscale deployment
│   ├── entrypoint.py             # Container entrypoint with setup wizard
│   └── .dockerignore             # Build context exclusions
│
├── native_src/                   # Python source for local development
│   ├── MAIN/                     # Legacy: Core transcription logic
│   ├── DIARIZATION/              # Legacy: Speaker diarization
│   ├── AUDIO_NOTEBOOK/           # Frontend + backend source
│   ├── REMOTE_SERVER_WEB/        # Remote UI frontend source
│   ├── config.yaml               # Local configuration file
│   ├── .env                      # Local environment variables
│   └── pyproject.toml            # Dependencies (mirrors Docker)
│
├── config/                       # Configuration templates
│   ├── server.yaml.example       # Server config template
│   └── client.yaml.example       # Client config template
│
└── build_scripts/                # Build and setup scripts
    ├── build-appimage-kde.sh     # Build KDE AppImage
    ├── build-appimage-gnome.sh   # Build GNOME AppImage
    ├── setup-client-kde.sh       # Setup KDE dev environment
    ├── setup-client-gnome.sh     # Setup GNOME dev environment
    ├── setup-client-windows.ps1  # Setup Windows dev environment
    └── pyproject.toml            # Dev tools (ruff, pyright)
```

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
source .venv/bin/activate
```

### Docker Development

```bash
cd docker
docker compose build
docker compose up
```

### Client Development

```bash
cd client
uv venv --python 3.11
uv pip install -e ".[kde]"  # or [gnome] or [windows]
python -m client --host localhost --port 8000
```

### Dev Tools

```bash
cd build_scripts
uv sync --extra dev

# Linting (from project root)
ruff check .
ruff format .

# Type checking
pyright
```

---

## Building Executables

### KDE AppImage

```bash
./build_scripts/build-appimage-kde.sh
# Output: dist/TranscriptionSuite-KDE-x86_64.AppImage
```

### GNOME AppImage

```bash
# Requires system GTK3 and AppIndicator
sudo pacman -S gtk3 libappindicator-gtk3 python-gobject

./build_scripts/build-appimage-gnome.sh
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

```bash
# Verify GPU is accessible
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi

# Check container logs
docker compose logs -f
```

### Model Loading

First transcription may take 30-60 seconds as models are downloaded and loaded into GPU memory.

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
