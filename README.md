# TranscriptionSuite

A Speech-to-Text Transcription Suite for Linux. Written in Python and utilizing the `faster_whisper` library with `CUDA 12.6` acceleration. Integrates diarization using `PyAnnote`. Implements full web GUI (built with React TS) allowing the user to create a notebook containing their audio notes and relevant transcriptions. GUI fully integrates with local LM Studio server allowing the user to converse with an LLM about their notes.

**Features:**

- Truly multilingual, supports [90+ languages](https://whisper-api.com/docs/languages/)
- CUDA 12.6 acceleration
- Longform dictation (optional live preview)
- Static file transcription (audio/video)
- Speaker diarization
- Word-level timestamps
- Full-text search (SQLite FTS5)
- Audio Notebook web app for browsing and searching recordings
- Remote transcription server (WebSocket-based, works with Linux/Android clients)

📌 *Half an hour of audio transcribed in under a minute (RTX 3060)*

## Table of Contents

- [Project Architecture](#project-architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Audio Notebook Web App](#audio-notebook-web-app)
- [Remote Transcription Server](#remote-transcription-server)
- [Output Format](#output-format)
- [How It Works](#how-it-works)
- [Scripts overview](#scripts-overview)
- [License](#license)

## Project Architecture

```bash
TranscriptionSuite/
├── config.yaml                   # Configuration file
├── pyproject.toml                # Dependencies
├── .venv/                        # Python 3.11 virtual environment
├── SCRIPT/                       # Application source
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
└── list_audio_devices.py         # Audio device utility
```

Everything runs in a single Python 3.11 environment. One `uv sync` installs all dependencies.

## Installation

### Prerequisites

- Arch Linux (or compatible)
- NVIDIA GPU with CUDA
- Python 3.11
- `uv` package manager
- Node.js 18+ and npm (for web frontend)

### 1. Clone the Repository

```bash
git clone https://github.com/homelab-00/TranscriptionSuite.git
cd TranscriptionSuite
```

### 2. Install System Dependencies

```bash
sudo pacman -S --needed cuda cudnn uv base-devel git openblas ffmpeg nodejs npm

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
source .venv/bin/activate
uv sync
```

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
uv run python SCRIPT/orchestrator.py
```

The system tray icon appears — right-click for options.

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
uv run python list_audio_devices.py
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

Edit `SCRIPT/cava.config`:

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
- HTTPS + WebSocket Secure (WSS) with self-signed certificates
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

Access the web UI at: `https://localhost:8443` (or your Tailscale IP)

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
        cert_file: "REMOTE_SERVER/data/cert.pem"
        key_file: "REMOTE_SERVER/data/key.pem"
        auto_generate: true   # Generate self-signed if missing
```

### Using with Tailscale

The server is designed for use over Tailscale VPN:

1. Install Tailscale on both server and client machines
2. Start the server on your home machine
3. Access from anywhere via Tailscale IP (e.g., `https://100.x.x.x:8443`)
4. Traffic is encrypted end-to-end through Tailscale's WireGuard tunnel

### Security Notes

- Tokens never expire - revoke them manually when needed
- Self-signed certificates auto-generated on first run
- Browser will warn about self-signed cert (accept once)
- Only one user can record at a time
- Use over Tailscale VPN for encrypted tunnel access

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

## Scripts overview

### SCRIPT/

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

## Acknowledgments

- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) — Core transcription engine adapted from this library
- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper)
- [PyAnnote Audio](https://github.com/pyannote/pyannote-audio)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)
