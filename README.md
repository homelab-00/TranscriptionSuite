# TranscriptionSuite

A comprehensive Speech-to-Text Transcription Suite for Linux. Written in Python, utilizing`faster_whisper` w/ `CUDA 12.6` acceleration. Inspired from [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) written by [KoljaB](https://github.com/KoljaB).

**Features:**

- Truly multilingual, supports [90+ languages](https://whisper-api.com/docs/languages/)
- CUDA 12.6 acceleration
- Longform dictation (optional live preview)
- Static file transcription
- Diarization using `PyAnnote`
- **Server mode**: Turn your desktop into a server that can be accessed securely from anywhere on the internet. Get audio transcriptions to your smartphone remotely while your desktop at home is doing all the work! Implementation using [Tailscale](https://tailscale.com/). Works with Linux/Android. Web GUI frontend built using React TypeScript and Tailwind CSS. Dual security layer (belt and suspenders): Tailscale identity authentication + HTTPS authentication.
- **Audio Notebook mode**: Open a calendar view where you can create audio notebook entries. Chat about your notes with your favorite clanker via LM Studio integration! Includes web GUI, full-text search (SQLite FTS5), word-level timestamps, diarization. Web GUI frontend built using React TypeScript and Tailwind CSS.

📌 *Half an hour of audio transcribed in under a minute (RTX 3060)!*

## Table of Contents

- [Project Architecture](#project-architecture)
- [Installation](#installation)
- [Docker Deployment](#docker-deployment)
- [Native Client](#native-client)
- [Configuration](#configuration)
- [Usage](#usage)
- [Audio Notebook Web App](#audio-notebook-web-app)
- [Remote Transcription Server](#remote-transcription-server)
- [Output Format](#output-format)
- [How It Works](#how-it-works)
- [Scripts Overview](#scripts-overview)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Project Architecture

```txt
TranscriptionSuite/
├── config.yaml                   # Configuration file
├── pyproject.toml                # Dependencies
├── .venv/                        # Python 3.11 virtual environment
├── MAIN/                         # Application source
│   ├── orchestrator.py           # Main entry point
│   ├── recorder.py               # Recording wrapper
│   ├── static_transcriber.py     # Static file transcription
│   ├── stt_engine.py             # Transcription engine, VAD, audio
│   ├── model_manager.py          # AI model lifecycle
│   ├── tray_manager.py           # System tray (PyQt6)
│   ├── console_display.py        # Terminal UI (Rich)
│   ├── config_manager.py         # Configuration loader
│   ├── logging_setup.py          # Logging setup
│   ├── platform_utils.py         # Linux paths, CUDA
│   ├── dependency_checker.py     # Package verification
│   ├── diagnostics.py            # Hardware info
│   └── utils.py                  # Utilities
├── AUDIO_NOTEBOOK/               # Web application
│   ├── backend/                  # FastAPI backend
│   │   ├── database.py           # SQLite with FTS5
│   │   ├── routers/              # API endpoints
│   │   └── data/                 # Database & audio storage
│   ├── src/                      # React + TypeScript frontend
│   └── vite.config.ts            # Build configuration
├── DIARIZATION/                  # Speaker diarization
│   ├── diarization_manager.py    # PyAnnote pipeline
│   ├── service.py                # Service wrapper
│   ├── combiner.py               # Merges transcription + speakers
│   └── utils.py                  # Utilities
├── REMOTE_SERVER/                # Remote transcription server
│   ├── run_server.py             # Server entry point
│   ├── web_server.py             # Combined HTTPS + WSS server (aiohttp)
│   ├── server.py                 # Legacy WebSocket server
│   ├── token_store.py            # Persistent JSON token storage
│   ├── auth.py                   # Token authentication & session lock
│   ├── protocol.py               # Audio/control protocols
│   ├── transcription_engine.py   # Integration with Whisper
│   ├── server_logging.py         # Server-mode logging
│   ├── client.py                 # Python client (Linux/Android)
│   ├── web/                      # React frontend (Vite + TS + Tailwind)
│   └── data/                     # Tokens, TLS certs
├── DOCKER/                       # Docker container support
│   ├── entrypoint.py             # Container entrypoint
│   └── container_services.py     # Service manager (FastAPI + aiohttp)
├── NATIVE_CLIENT/                # Cross-platform tray client
│   ├── __main__.py               # CLI entry point
│   ├── client_orchestrator.py    # Main controller
│   ├── server_connection.py      # HTTP/WebSocket client
│   ├── audio_recorder.py         # PyAudio recording
│   ├── config.py                 # Client configuration
│   └── tray/                     # Platform-specific tray implementations
│       ├── base.py               # Abstract tray interface
│       ├── qt6_tray.py           # PyQt6 (KDE/Windows)
│       ├── gtk4_tray.py          # GTK+AppIndicator (GNOME)
│       └── factory.py            # Platform detection
├── Dockerfile                    # Multi-stage container build
├── docker-compose.yml            # Container orchestration
└── .list_audio_devices.py        # Audio device utility
```

Everything runs in a single Python 3.11 environment.

---

## Installation

### Prerequisites

- Linux (tested on Arch)
- Python 3.11
- NVIDIA GPU with CUDA 12.x support
- `uv` package manager
- Node.js 18+ and npm
- FFmpeg
- PortAudio

### 1. Clone Repository

```bash
git clone https://github.com/homelab-00/TranscriptionSuite.git
cd TranscriptionSuite
```

### 2. Install System Dependencies

```bash
sudo pacman -S --needed python cuda cudnn uv base-devel git openblas ffmpeg nodejs npm portaudio

# Optional: for waveform display during recording
sudo pacman -S --needed cava
```

### 3. Install CUDA 12.6

The `ctranslate2` library (used by `faster-whisper`) requires CUDA 12.x libraries. Arch's `cuda` package is version 13, so CUDA 12.6 must be installed alongside it.

```bash
# Download CUDA 12.6 runfile installer
wget https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.28.03_linux.run

# Install toolkit only (no driver) to /opt/cuda-12.6
sudo sh cuda_12.6.0_560.28.03_linux.run --toolkit --toolkitpath=/opt/cuda-12.6 --silent

# Verify installation
ls /opt/cuda-12.6/lib64/libcublas.so.12
```

After this you'll have `/opt/cuda` (13.0 from pacman) and `/opt/cuda-12.6` (from runfile). The application automatically sets `LD_LIBRARY_PATH` to use CUDA 12.6 on startup.

### 4. Create Virtual Environment and Install Dependencies

```bash
uv venv --python 3.11
uv sync --extra desktop
```

The `desktop` extra includes PyQt6 (system tray) and PyAudio (microphone recording) for local use.

### 5. Configure HuggingFace Access (Required for Diarization)

1. Get token from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Accept terms for:
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
3. Login:

```bash
hf auth login
```

### 6. Build Web Frontend (Audio Notebook)

```bash
cd AUDIO_NOTEBOOK
npm install
npm run build
cd ..
```

### 7. Build Remote Server Frontend

```bash
cd REMOTE_SERVER/web
npm install
npm run build
cd ../..
```

### 8. Run the Application

```bash
uv run python MAIN/orchestrator.py
```

The system tray icon appears — right-click for options.

---

## Docker Deployment

For headless servers or simplified deployment, TranscriptionSuite can run entirely in a Docker container with GPU passthrough. The container bundles both the Audio Notebook and Remote Server, while a lightweight native client handles microphone recording and clipboard operations on your local machine.

### Docker Prerequisites

- Docker with [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- NVIDIA GPU with CUDA support
- Docker Compose V2 (included with Docker Desktop, or install `docker-compose-plugin`)

Verify GPU support:

```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

### Building the Image

Build the container image from the project root:

```bash
docker compose build
```

This runs a multi-stage build:

1. **Stage 1**: Builds React frontends (Audio Notebook + Remote Server)
2. **Stage 2**: Sets up Python runtime with CUDA 12.6, installs dependencies, copies source and built frontends

### Starting the Container

```bash
docker compose up -d
```

Or build and start in one command:

```bash
docker compose up -d --build
```

The container exposes:

- **Port 8000**: Audio Notebook (HTTP)
- **Port 8443**: Remote Server (HTTPS/WSS)

### Container Management

```bash
# View logs
docker compose logs -f

# Stop container
docker compose down

# Stop and remove volumes (clears data)
docker compose down -v

# Rebuild after code changes
docker compose up -d --build
```

### Data Persistence

A named volume `transcription-data` stores:

- SQLite database
- Audio recordings
- TLS certificates
- Authentication tokens

Your `config.yaml` is mounted read-only into the container.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_TOKEN` | - | HuggingFace token (required for diarization) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

Example with HuggingFace token:

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

The Native Client is a lightweight tray application that connects to the Docker container (or any TranscriptionSuite server) for audio recording and transcription. It runs natively on your desktop to access the microphone and clipboard—features unavailable inside containers.

### Supported Platforms

| Platform | Tray Implementation | Notes |
|----------|---------------------|-------|
| Linux KDE (Wayland/X11) | PyQt6 | Native integration |
| Linux GNOME | GTK3 + AppIndicator | Requires AppIndicator extension |
| Windows 11 | PyQt6 | Full support |

### Client Installation

From the project root:

```bash
cd NATIVE_CLIENT

# Create virtual environment
uv venv --python 3.11
source .venv/bin/activate

# Install with PyQt6 (KDE/Windows)
uv pip install -e ".[qt,audio]"

# Or for GNOME (uses system GTK)
uv pip install -e ".[audio]"
sudo pacman -S python-gobject gtk3 libappindicator-gtk3  # Arch
```

### Running

```bash
# Connect to localhost (default)
python -m NATIVE_CLIENT

# Connect to remote server
python -m NATIVE_CLIENT --host 192.168.1.100

# Use HTTPS
python -m NATIVE_CLIENT --host myserver.local --https

# List audio devices
python -m NATIVE_CLIENT --list-devices
```

### Tray Menu

Right-click the tray icon for:

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

### Configuration File

The client stores settings in `~/.config/transcription-suite/client.yaml`:

```yaml
server:
  host: localhost
  audio_notebook_port: 8000
  remote_server_port: 8443
  use_https: false
  timeout: 30

recording:
  sample_rate: 16000
  device_index: null  # null = default device

clipboard:
  auto_copy: true
```

### GNOME Setup

GNOME doesn't natively support system trays. Install the AppIndicator extension:

1. Install extension: [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/)
2. Install system packages:

```bash
# Fedora
sudo dnf install gtk3 libappindicator-gtk3

# Arch
sudo pacman -S gtk3 libappindicator-gtk3
```

---

## Configuration

Edit `config.yaml`:

```yaml
transcription_options:
    language: null              # null = auto-detect, or "en", "el", etc.
    enable_preview_transcriber: false  # Live preview uses more GPU VRAM

longform_recording:
    include_in_viewer: false    # Save recordings to Audio Notebook
    word_timestamps: false      # Enable for click-to-seek
    enable_diarization: false   # Usually not needed for dictation

static_transcription:
    enable_diarization: false   # Speaker labels
    word_timestamps: false      # Required for searchable transcriptions
    max_segment_chars: 500      # Split long segments

main_transcriber:
    model: "Systran/faster-whisper-large-v3"

preview_transcriber:
    model: "Systran/faster-whisper-base"

storage:
    audio_dir: "data/audio"
    audio_format: "mp3"
    audio_bitrate: 160

local_llm:
    enabled: true
    base_url: "http://127.0.0.1:1234"
    model: ""                    # Empty = use model loaded in LM Studio
    max_tokens: 4096
    temperature: 0.7
```

The `main_transcriber` settings are used by all transcription modes (longform, static, web UI).

### Local LLM Priority

When using LM Studio:

| Setting | config.yaml | LM Studio UI | Used |
|---------|-------------|--------------|------|
| `max_tokens` | 4096 | 8192 | 4096 (config wins) |
| `temperature` | 0.7 | 0.9 | 0.7 (config wins) |
| `model` | "" | llama-3.2-8b | llama-3.2-8b (LM Studio wins) |
| `model` | "specific" | llama-3.2-8b | specific (config wins) |

### Audio Device

```bash
uv run python .list_audio_devices.py
```

Update `config.yaml`:

```yaml
audio:
    input_device_index: 21
    use_default_input: false
```

### CAVA Waveform (Optional)

```bash
sudo pacman -S cava
pw-cli list-objects Node  # Find your audio source
```

Edit `MAIN/cava.config`:

```ini
[input]
method = pulse
source = "alsa:acp:Generic:0:capture"
```

Enable in `config.yaml`:

```yaml
display:
    show_waveform: true
```

### File Storage

| Type | Location |
|------|----------|
| Database | `AUDIO_NOTEBOOK/backend/data/transcriptions.db` |
| Audio Files | `AUDIO_NOTEBOOK/backend/data/audio/` |
| Logs | `transcription_suite.log`, `audio_notebook_webapp.log` (project root, wiped on start) |
| Models | `~/.cache/huggingface/` |
| Temp Files | `/tmp/transcription-suite/` |
| Server Data | `REMOTE_SERVER/data/` (tokens, TLS certs) |

---

## Usage

### Longform Recording

1. **Start:** Tray → Start Recording (or press configured hotkey)
2. **Speak:** Live preview shows in terminal (if enabled)
3. **Stop:** Tray → Stop Recording
4. **Result:** Final transcription displayed, copied to clipboard

Extended silences (>10 seconds) are automatically trimmed during recording to prevent Whisper hallucinations.

### Static File Transcription

1. **Tray → Transcribe File**
2. Select audio/video file
3. JSON saved as `{filename}_transcription.json`

Enable `enable_diarization: true` for speaker labels.

---

## Audio Notebook Web App

Web-based UI for managing and searching transcriptions. Launch from the system tray menu.

**Features:** Calendar view, full-text search (FTS5), fuzzy matching, date filtering, click-to-play timestamps, audio player, speaker labels, file import, dark mode.

**Stack:** React 18 + TypeScript + Tailwind (frontend), FastAPI (backend), SQLite FTS5, Howler.js, Vite.

### Starting

**From tray:** Right-click → "Start Audio Notebook" → Opens at [http://localhost:8000](http://localhost:8000)

**Development:**

```bash
cd AUDIO_NOTEBOOK
npm install  # First time
npm run build  # For production
npm run dev  # Hot reload on port 1420
```

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Remote Transcription Server

Web-based server allowing remote clients to transcribe audio via a browser interface. Designed for secure remote access over Tailscale VPN.

**Features:**

- Web UI with React frontend (record, file upload, admin panel)
- HTTPS + WebSocket Secure (WSS)
- Token-based authentication (no expiry, manual revocation)
- Admin panel for token management
- Single-user mode (rejects concurrent connections)
- File upload transcription support
- Tailscale VPN integration for secure remote access

### Starting Server Mode

Server Mode can be started in two ways:

**From system tray (recommended):**
Right-click the tray icon → "Start Server Mode"

This integrates with the orchestrator, shares the main log file (`transcription_suite.log`), and properly manages model loading/unloading.

**Standalone (for development/testing):**

```bash
uv run python REMOTE_SERVER/run_server.py

# Custom ports
uv run python REMOTE_SERVER/run_server.py --https-port 9443 --wss-port 9444
```

On first run, an admin token is generated and printed to the console. Save this token to access the admin panel.

### Web UI Features

1. **Login**: Enter your token to authenticate
2. **Record Tab**: Hold button to record, release to transcribe
3. **Upload Tab**: Drag & drop audio/video files for transcription
4. **Admin Tab** (admin only): Create and revoke tokens

### Server Configuration

In `config.yaml`:

```yaml
remote_server:
    enabled: true
    host: "0.0.0.0"           # Listen on all interfaces
    https_port: 8443          # HTTPS (web UI + REST API)
    wss_port: 8444            # WebSocket Secure (audio streaming)
    token_store: "REMOTE_SERVER/data/tokens.json"
    
    tls:
        enabled: true
        cert_file: "REMOTE_SERVER/data/my-machine.crt"
        key_file: "REMOTE_SERVER/data/my-machine.key"
        auto_generate: false  # Set to true for self-signed certs
```

**Production Mode:**

For stricter security headers (CSP without `unsafe-inline`):

```bash
export ENVIRONMENT=production
uv run python REMOTE_SERVER/run_server.py
```

### Using with Tailscale

The server is designed for use over [Tailscale](https://tailscale.com/) VPN, providing secure remote access from anywhere.

#### Quick Start (Self-Signed Certificates)

For local network or testing:

1. Set `auto_generate: true` in `config.yaml`
2. Start the server — self-signed certificates are generated automatically
3. Access via `https://localhost:8443` or `https://<tailscale-ip>:8443`
4. Accept the browser security warning (self-signed cert)

#### Tailscale HTTPS with Valid Certificates (Recommended)

For browser-trusted HTTPS without security warnings, use Tailscale's built-in Let's Encrypt certificate provisioning.

**Prerequisites:**

- [Tailscale](https://tailscale.com/download) installed and running on your server
- MagicDNS enabled in your tailnet
- HTTPS Certificates enabled in the [Tailscale admin console](https://login.tailscale.com/admin/dns) (under DNS → HTTPS Certificates)

##### Step 1: Find your machine's Tailscale hostname

```bash
tailscale status
```

This will show the Tailscale IP of all machines that have been verified with your Tailscale account. You want to note the machine name and IP of the device you want to use as the server.

##### Step 2: Generate the Tailscale certificate

```bash
cd /path/to/TranscriptionSuite/REMOTE_SERVER/data
sudo tailscale cert <your-machine>.<your-tailnet>.ts.net
```

This creates two files:

- `<your-machine>.<your-tailnet>.ts.net.crt`
- `<your-machine>.<your-tailnet>.ts.net.key`

##### Step 3: Rename the certificate files (optional but recommended)

```bash
mv <your-machine>.<your-tailnet>.ts.net.crt my-machine.crt
mv <your-machine>.<your-tailnet>.ts.net.key my-machine.key
```

##### Step 4: Fix file permissions

The certificate files are created with root ownership. The server needs read access:

```bash
sudo chown $USER:$USER my-machine.crt my-machine.key
```

##### Step 5: Update `config.yaml`

```yaml
remote_server:
    tls:
        enabled: true
        cert_file: "REMOTE_SERVER/data/my-machine.crt"
        key_file: "REMOTE_SERVER/data/my-machine.key"
        auto_generate: false  # Important: don't overwrite with self-signed
```

##### Step 6: Start the server and access via Tailscale hostname

```bash
uv run python MAIN/orchestrator.py
# Then: Tray → Start Server Mode
```

Access from any device on your tailnet:

```bash
https://<your-machine>.<your-tailnet>.ts.net:8443
```

The certificate is only valid for the `*.ts.net` hostname. Accessing via IP address or `localhost` will still show certificate warnings.

**Certificate Renewal:**

Tailscale certificates from Let's Encrypt expire after 90 days. To renew:

```bash
cd /path/to/TranscriptionSuite/REMOTE_SERVER/data
sudo tailscale cert <your-machine>.<your-tailnet>.ts.net
sudo chown $USER:$USER <your-machine>.<your-tailnet>.ts.net.*
# Rename if needed, then restart the server
```

#### Troubleshooting Tailscale HTTPS

| Symptom | Cause | Solution |
|---------|-------|----------|
| `SSL_ERROR_RX_RECORD_TOO_LONG` | Server running HTTP instead of HTTPS | Check `tls.enabled: true` and certificate file paths |
| `MOZILLA_PKIX_ERROR_SELF_SIGNED_CERT` | Using self-signed instead of Tailscale cert | Follow the Tailscale certificate setup above |
| "Secure Site Not Available" | Accessing via wrong hostname | Use the exact `*.ts.net` hostname, not IP |
| Permission denied on cert files | Root ownership | Run `sudo chown $USER:$USER` on cert files |
| Certificate not found | Wrong path in config | Verify paths are relative to project root |

### Security Features

**Authentication & Tokens:**

- Tokens are SHA-256 hashed before storage (plaintext shown only at creation)
- Regular user tokens expire after 30 days (admin tokens never expire)
- Token IDs are 128-bit for sufficient entropy
- Rate limiting: 5 failed auth attempts per IP triggers 5-minute lockout
- Automatic migration from plaintext to hashed storage (regenerates tokens)

**Network Security:**

- HTTPS with TLS 1.2+ required
- HSTS header enforces HTTPS for 1 year
- WebSocket origin validation prevents unauthorized connections
- Content Security Policy (CSP) headers:
  - Development: allows `unsafe-inline` for Vite hot reload
  - Production: strict CSP (set `ENVIRONMENT=production`)
- Security headers: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`

**Access Control:**

- Single-user mode: only one client can record at a time
- Session lock validates both token hash and token_id
- Admin-only endpoints for token management

**Data Validation:**

- File uploads validated by magic bytes (WAV, FLAC, OGG, MP3)
- Generic error messages sent to clients (verbose logging server-side only)

**Best Practices:**

- Use over Tailscale VPN for end-to-end encrypted tunnel access
- Use Tailscale certificates for browser-trusted HTTPS
- Revoke compromised tokens immediately via admin panel
- Regenerate tokens after 30 days for regular users

---

## Output Format

```json
{
  "segments": [{
    "text": "This is mercury metal.",
    "start": 0.0, "end": 1.52, "duration": 1.52,
    "speaker": "SPEAKER_00",
    "words": [
      {"word": "This", "start": 0.0, "end": 0.24, "probability": 0.99},
      {"word": "is", "start": 0.24, "end": 0.4, "probability": 0.98}
    ]
  }],
  "num_speakers": 1,
  "total_duration": 31.14,
  "total_words": 145,
  "metadata": {"source_file": "/path/to/audio.mp3", "num_segments": 12}
}
```

---

## How It Works

### Model Management

The orchestrator keeps one model type loaded at a time to manage GPU memory:

- On startup: loads longform model(s), ready for immediate recording
- When switching modes: unloads current model, loads new one
- Models cached for reuse within same mode

### Dual Transcriber Mode

When `enable_preview_transcriber: true`:

- **Preview** (base model): handles mic, VAD, live preview
- **Main** (large model): receives audio feed, produces final transcription

### Transcription Pipeline

1. FFmpeg converts to 16kHz mono WAV
2. WebRTC VAD removes silence (optional)
3. Faster Whisper transcribes with word timestamps
4. If diarization enabled: PyAnnote identifies speakers, combiner merges results

### Extended Silence Trimming (Longform)

During longform recording, a dual-stage VAD (WebRTC + Silero) monitors audio in real-time:

- Silences under 10 seconds: frames saved normally
- Silences over 10 seconds: frames discarded until speech resumes
- Prevents Whisper hallucinations from extended pauses
- Trimming happens on-the-fly (silent frames never buffered)

### Speaker Assignment

Each word assigned to speaker by:

1. Calculate word midpoint: `(start + end) / 2`
2. Find diarization segment containing midpoint
3. Use that segment's speaker label
4. Group consecutive words by speaker
5. Split if exceeding `max_segment_chars`

---

## Scripts Overview

### MAIN/

| Module | Purpose |
|--------|---------|
| `orchestrator.py` | Main controller, state management, API server |
| `model_manager.py` | AI model lifecycle |
| `recorder.py` | Recording sessions |
| `stt_engine.py` | Transcription engine, VAD, audio, silence trimming |
| `static_transcriber.py` | Static file processing |
| `tray_manager.py` | System tray (PyQt6) |
| `console_display.py` | Terminal UI (Rich) |
| `config_manager.py` | Configuration loader |
| `logging_setup.py` | Logging |
| `platform_utils.py` | Linux paths, CUDA |
| `dependency_checker.py` | Package verification |
| `diagnostics.py` | Hardware info |
| `utils.py` | Utilities |

### AUDIO_NOTEBOOK/backend/

| Module | Purpose |
|--------|---------|
| `database.py` | SQLite + FTS5 |
| `routers/recordings.py` | Recording CRUD |
| `routers/search.py` | Full-text search |
| `routers/transcribe.py` | Import/transcription |
| `routers/llm.py` | LM Studio integration |

### DIARIZATION/

| Module | Purpose |
|--------|---------|
| `diarization_manager.py` | PyAnnote pipeline |
| `service.py` | Service wrapper |
| `combiner.py` | Merge transcription + speakers |
| `utils.py` | Utilities |

### REMOTE_SERVER/

| Module | Purpose |
|--------|---------|
| `run_server.py` | Server entry point |
| `web_server.py` | Combined HTTPS + WSS server (aiohttp) |
| `server.py` | Legacy WebSocket server |
| `token_store.py` | Persistent JSON token storage (file-locked) |
| `auth.py` | Token authentication & session lock |
| `server_logging.py` | Server-mode logging (`server_mode.log`) |
| `protocol.py` | Audio/control message formats |
| `transcription_engine.py` | Integration with Whisper |
| `client.py` | Python client for Linux/Android |
| `web/` | React frontend (Vite + TypeScript + Tailwind) |

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
