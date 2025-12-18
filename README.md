# TranscriptionSuite

<img align="left" style="margin-right: 20px" width="90" height="90" src="./logo.png">

<pre>A comprehensive Speech-to-Text Transcription Suite with Docker-first
architecture. Written in Python, utilizing faster_whisper with
CUDA 12.6 acceleration. Inspired by RealtimeSTT by KoljaB.
</pre>

## Features

- **Multilingual**: Supports [90+ languages](https://whisper-api.com/docs/languages/)
- **GPU Accelerated**: CUDA 12.6 with NVIDIA GPU support
- **Long-form Dictation**: Real-time transcription with optional live preview
- **File Transcription**: Transcribe audio/video files
- **Speaker Diarization**: PyAnnote-based speaker identification
- **Audio Notebook**: Calendar-based audio notes with full-text search, LLM chat via LM Studio
- **Remote Access**: Secure access via Tailscale from anywhere
- **Cross-Platform Clients**: Native system tray apps for KDE, GNOME, and Windows

📌 *Half an hour of audio transcribed in under a minute (RTX 3060)!*

## Table of Contents

- [Architecture](#architecture)
- [Quick Start (Docker)](#quick-start-docker)
- [Native Client](#native-client)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Development](#development)
- [License](#license)

## Architecture

TranscriptionSuite uses a **client-server architecture**:

- **Server** (Docker): All ML/transcription runs in a GPU-accelerated container
- **Client** (Native): Lightweight tray apps for system integration (microphone, clipboard)

```
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

### Project Structure

```
TranscriptionSuite/
├── server/                       # Server code (runs in Docker)
│   ├── api/                      # FastAPI application
│   │   ├── main.py               # App factory
│   │   └── routes/               # API endpoints
│   ├── core/                     # ML engines
│   │   ├── transcription_engine.py
│   │   ├── diarization_engine.py
│   │   └── model_manager.py
│   ├── database/                 # SQLite + FTS5
│   └── pyproject.toml            # Server dependencies
│
├── client/                       # Native client (runs locally)
│   ├── common/                   # Shared client code
│   │   ├── api_client.py         # Server communication
│   │   ├── audio_recorder.py     # PyAudio recording
│   │   └── orchestrator.py       # Main controller
│   ├── kde/                      # KDE Plasma tray (PyQt6)
│   ├── gnome/                    # GNOME tray (GTK+AppIndicator)
│   ├── windows/                  # Windows tray (PyQt6)
│   └── pyproject.toml            # Client dependencies
│
├── docker/                       # Docker infrastructure
│   ├── Dockerfile                # Multi-stage build
│   ├── docker-compose.yml        # Local deployment
│   └── docker-compose.remote.yml # Remote/Tailscale deployment
│
├── native_src/                   # Python source for local development
│   ├── MAIN/                     # Core transcription logic
│   ├── DIARIZATION/              # Speaker diarization
│   ├── AUDIO_NOTEBOOK/           # Audio Notebook frontend + backend
│   ├── REMOTE_SERVER_WEB/        # Remote UI frontend
│   ├── config.yaml               # Local config file
│   └── pyproject.toml            # Dependencies (mirrors Docker)
│
├── config/                       # Configuration templates
│   ├── server.yaml.example
│   └── client.yaml.example
│
├── scripts/                      # Setup and build scripts
│   ├── build-appimage-kde.sh     # Build KDE AppImage
│   ├── build-appimage-gnome.sh   # Build GNOME AppImage
│   └── setup-client-*.sh         # Client setup scripts
│
└── pyproject.toml                # Dev tools only
```

---

## Quick Start (Docker)

### 1. Prerequisites

- Docker with [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- NVIDIA GPU with CUDA support

Verify GPU support:
```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

### 2. Clone and Build

```bash
git clone https://github.com/homelab-00/TranscriptionSuite.git
cd TranscriptionSuite/docker
docker compose build
```

### 3. First Run (Interactive Setup)

On first run, the container will prompt for configuration:

```bash
docker compose run --rm transcription-suite --setup
```

This wizard will ask for:
- **HuggingFace token** (for speaker diarization) - get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
- **Admin token** (auto-generated or custom)
- **LM Studio URL** (optional, for AI chat features)

Configuration is saved to persistent storage and won't be asked again.

### 4. Start the Server

```bash
docker compose up -d
```

The server is now running at **http://localhost:8000**

### 5. Access the Web UI

Open [http://localhost:8000](http://localhost:8000) in your browser for the Audio Notebook interface.

### Alternative: Environment Variables

Skip the interactive setup by providing environment variables:

```bash
ADMIN_TOKEN=your-secret-token \
HUGGINGFACE_TOKEN=hf_xxx \
docker compose up -d
```

Or create a `.env` file in `docker/`:

```bash
# .env
HF_TOKEN=hf_your_actual_token_here
LOG_LEVEL=INFO
```

Then start the container normally:

```bash
docker compose up -d
```

**Alternative: Pass via command line:**

```bash
HF_TOKEN=hf_xxxxx docker compose up -d
```

### Health Check

The container includes a health check endpoint:

```bash
curl http://localhost:8000/health
```

---

## Native Client

The Native Client is a lightweight tray application that connects to the Docker server for audio recording and transcription. It provides microphone access and clipboard integration—features unavailable inside containers.

### Download Pre-built Clients

| Platform | Download | Notes |
|----------|----------|-------|
| **KDE Plasma** | `TranscriptionSuite-KDE-x86_64.AppImage` | Standalone, no dependencies |
| **GNOME** | `TranscriptionSuite-GNOME-x86_64.AppImage` | Requires system GTK3 |
| **Windows** | `TranscriptionSuite.exe` | Standalone executable |

### Building from Source

#### KDE / Windows (PyQt6)

```bash
# Install build dependencies
./scripts/setup-client-kde.sh

# Build AppImage (Linux)
./scripts/build-appimage-kde.sh
# Output: dist/TranscriptionSuite-KDE-x86_64.AppImage

# Build .exe (Windows - run on Windows)
pip install pyinstaller
pyinstaller client/build/pyinstaller-windows.spec
# Output: dist/TranscriptionSuite.exe
```

#### GNOME (GTK + AppIndicator)

```bash
# Install system dependencies first
sudo pacman -S gtk3 libappindicator-gtk3 python-gobject  # Arch
# sudo apt install python3-gi gir1.2-appindicator3-0.1   # Ubuntu/Debian

# Build AppImage
./scripts/build-appimage-gnome.sh
# Output: dist/TranscriptionSuite-GNOME-x86_64.AppImage
```

**Note:** GNOME requires the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/) for system tray support.

### Running the Client

```bash
# Run the AppImage directly
./TranscriptionSuite-KDE-x86_64.AppImage

# Or run from source (development)
cd client
uv venv --python 3.11
uv pip install -e ".[kde]"  # or [gnome] or [windows]
python -m client --host localhost --port 8000
```

### Tray Icon Controls

**Click Actions:**

| Click | Action |
|-------|--------|
| Left-click | Start recording (when in standby) |
| Middle-click | Stop recording and transcribe |
| Right-click | Open context menu |

**Context Menu (right-click):**

- **Start Recording** — Begin microphone capture
- **Stop Recording** — Stop and transcribe (result copied to clipboard)
- **Transcribe File...** — Select an audio/video file
- **Open Audio Notebook** — Launch web UI in browser
- **Open Remote Server** — Launch remote UI in browser
- **Settings** — Configure connection and audio
- **Quit** — Exit the client

### Tray Icon States

| Color | State |
|-------|-------|
| Grey | Disconnected from server |
| Orange | Connecting... |
| Green | Ready (standby) |
| Yellow | Recording |
| Blue | Uploading audio |
| Orange | Transcribing |
| Red | Error |

### Client Configuration

The client stores settings in `~/.config/transcription-suite/client.yaml`:

```yaml
server:
  host: localhost
  port: 8000
  use_https: false
  token: ""  # Set after first connection

recording:
  sample_rate: 16000
  device_index: null  # null = default device

clipboard:
  auto_copy: true
```

---

## API Reference

The server exposes a unified REST API at `http://localhost:8000`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/status` | GET | Server status, GPU info |
| `/api/transcribe/audio` | POST | Transcribe uploaded audio file |
| `/api/notebook/recordings` | GET | List all recordings |
| `/api/notebook/recordings/{id}` | GET | Get recording details |
| `/api/notebook/calendar` | GET | Calendar view data |
| `/api/search` | GET | Full-text search |
| `/api/admin/tokens` | GET/POST | Token management |

Full API documentation available at `http://localhost:8000/docs` (Swagger UI).

---

## Remote Access (Tailscale)

For accessing the server from other devices:

```bash
# Use the remote docker-compose
cd docker
docker compose -f docker-compose.remote.yml up -d
```

With Tailscale HTTPS:

```bash
# Get Tailscale certs
tailscale cert your-machine.tailnet-name.ts.net

# Set cert paths
export TLS_CERT_PATH=/path/to/cert.crt
export TLS_KEY_PATH=/path/to/cert.key
export TLS_ENABLED=true

docker compose -f docker-compose.remote.yml up -d
```

---

## Development

### Dev Tools Setup

```bash
# Install dev dependencies
uv sync --extra dev --extra build

# Run linting
ruff check .

# Type checking  
pyright
```

### Building Docker Image

```bash
cd docker
docker compose build
```

### Building Client Executables

```bash
# KDE AppImage
./scripts/build-appimage-kde.sh

# GNOME AppImage
./scripts/build-appimage-gnome.sh

# Windows exe (run on Windows)
pyinstaller client/build/pyinstaller-windows.spec
```

---

## Data Storage (Docker)

All persistent data is stored in the Docker volume:

| Type | Container Path | Description |
|------|----------------|-------------|
| Database | `/data/database/notebook.db` | SQLite with FTS5 |
| Audio Files | `/data/audio/` | Recorded audio |
| Config | `/data/config/secrets.json` | API keys, tokens |
| Logs | `/data/logs/` | Server logs |

---

## License

MIT License — See [LICENSE](LICENSE).

---

## Acknowledgments

- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) — Core transcription engine adapted from this library
- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper)
- [PyAnnote Audio](https://github.com/pyannote/pyannote-audio)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)
- [Tailscale](https://tailscale.com/) — Secure networking for remote access
