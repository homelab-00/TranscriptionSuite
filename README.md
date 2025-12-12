# TranscriptionSuite

A comprehensive speech-to-text transcription suite for Linux with speaker diarization support. Built with Python, leveraging `faster-whisper` for high-performance transcription and `pyannote-audio` for state-of-the-art speaker identification. Supports **CUDA 12.x/13.x** for GPU inference (automatic CUDA 12.6 configuration for ctranslate2 compatibility).

> **Key Features:**
>
> - 🎙️ **Longform Dictation** — Start/stop voice recording with optional live preview
> - 📁 **Static File Transcription** — Transcribe any audio/video file with word timestamps
> - 👥 **Speaker Diarization** — Identify "who spoke when"
> - ⏱️ **Word-Level Timestamps** — Precise timing for every word
> - 🔍 **Full-Text Search** — SQLite FTS5 enables instant word search across all recordings
> - 🖥️ **Audio Notebook Web App** — Browse, search, and play transcriptions in your browser
> - 🚀 **Extremely Fast** — 30 minutes of audio in ~40 seconds (RTX 3060)
> - 🌍 **Multilingual** — Works with Greek, English, and 90+ languages

---

## Table of Contents

- [Project Architecture](#project-architecture)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [File Storage](#file-storage)
- [Usage](#usage)
- [Audio Notebook Web App](#audio-notebook-web-app)
- [Output Format](#output-format)
- [How It Works](#how-it-works)
- [Module Architecture](#module-architecture)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Project Architecture

```text
TranscriptionSuite/
├── config.yaml                   # Unified configuration file (single source of truth)
├── pyproject.toml                # All dependencies
├── .venv/                        # Unified virtual environment (Python 3.11)
├── SCRIPT/                       # Application source code
│   ├── orchestrator.py           # Main entry point & central controller
│   ├── recorder.py               # Long-form recording wrapper
│   ├── static_transcriber.py     # Static file transcription with preprocessing
│   ├── stt_engine.py             # Low-level transcription engine, VAD, audio
│   ├── model_manager.py          # AI model lifecycle management
│   ├── tray_manager.py           # System tray icon (PyQt6)
│   ├── console_display.py        # Terminal UI: timer, waveform, preview (Rich)
│   ├── config_manager.py         # Configuration loading and validation
│   ├── logging_setup.py          # Application-wide logging
│   ├── platform_utils.py         # Platform-specific code (Linux paths, CUDA)
│   ├── dependency_checker.py     # Verifies required packages
│   ├── diagnostics.py            # Hardware info and startup banner
│   └── utils.py                  # Shared utilities
├── AUDIO_NOTEBOOK/               # Audio Notebook web application
│   ├── backend/                  # FastAPI backend
│   │   ├── database.py           # SQLite with FTS5 for word search
│   │   ├── webapp_logging.py     # Web app logging configuration
│   │   ├── routers/              # API endpoints
│   │   │   ├── recordings.py     # Recording CRUD operations
│   │   │   ├── search.py         # Full-text search endpoints
│   │   │   ├── transcribe.py     # Import and transcription endpoints
│   │   │   └── llm.py            # Local LLM integration (LM Studio)
│   │   └── data/                 # Database & audio storage
│   ├── src/                      # React + TypeScript frontend
│   ├── package.json              # Frontend dependencies
│   └── vite.config.ts            # Vite build configuration
├── DIARIZATION/                  # PyAnnote speaker diarization (integrated)
│   ├── __init__.py               # Module exports
│   ├── diarization_manager.py    # PyAnnote pipeline management
│   ├── service.py                # Diarization service wrapper
│   ├── combiner.py               # Merges transcription + speaker labels
│   └── utils.py                  # Segment utilities
├── list_audio_devices.py         # Utility to find audio input devices
└── README.md
```

### Unified Python 3.11 Environment

All functionality now runs in a **single Python 3.11 environment**:

| Feature | Key Dependencies | Status |
|---------|------------------|--------|
| Faster Whisper Transcription | `faster-whisper`, `ctranslate2`, `torch 2.9+` | ✅ Integrated |
| Speaker Diarization | `pyannote-audio` | ✅ Integrated |
| Web API & UI | `FastAPI`, `PyQt6` | ✅ Integrated |

**Benefits of unified environment:**

- 🚀 Faster startup (no subprocess overhead)
- 💾 Shared GPU memory between models
- 🔧 Simpler debugging and maintenance
- 📦 Single `uv sync` installs everything

**Note:** The Audio Notebook web app (frontend + backend) is **fully integrated** (in `AUDIO_NOTEBOOK/`), sharing the same virtual environment. All transcription modes (longform, static, web UI) use the **same model settings** from `main_transcriber` in `config.yaml`.

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/homelab-00/TranscriptionSuite.git
cd TranscriptionSuite

# 2. Set up unified Python 3.11 environment
uv venv --python 3.11
source .venv/bin/activate

# 3. Install all dependencies
uv sync

# 4. Login to HuggingFace (required for PyAnnote diarization models)
huggingface-cli login

# 5. Install frontend dependencies (optional, for web viewer development)
cd AUDIO_NOTEBOOK
npm install
cd ..

# 6. Run the application
python SCRIPT/orchestrator.py
```

---

## Installation

### Prerequisites

- **Arch Linux** (or compatible distro)
- **NVIDIA GPU** with CUDA support
- **CUDA 12.6** installed at `/opt/cuda-12.6` (required for ctranslate2/faster-whisper; see CUDA Setup below)
- **Python 3.11** (single unified environment)
- **uv** package manager
- **Node.js 18+** and **npm** (for web viewer frontend)

### System Dependencies

```bash
# Install system packages
sudo pacman -S --needed cuda cudnn uv base-devel git openblas ffmpeg nodejs npm

# For the system tray and waveform display (optional)
sudo pacman -S --needed cava
```

### CUDA 12.6 Setup (Required for ctranslate2)

The `ctranslate2` library (used by `faster-whisper`) requires CUDA 12.x libraries. If your system has CUDA 13.x as the default (e.g., `/opt/cuda`), you need to install CUDA 12.6 in parallel:

```bash
# Download CUDA 12.6 runfile installer
wget https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.28.03_linux.run

# Install to /opt/cuda-12.6 (toolkit only, no driver)
sudo sh cuda_12.6.0_560.28.03_linux.run --toolkit --toolkitpath=/opt/cuda-12.6 --silent

# Verify installation
ls /opt/cuda-12.6/lib64/libcublas.so.12
```

The application automatically configures `LD_LIBRARY_PATH` to use CUDA 12.6 at startup via a re-exec pattern in `orchestrator.py`. No manual environment setup is required.

### Setting Up the Environment

#### Create Virtual Environment

```bash
uv venv --python 3.11
source .venv/bin/activate
```

#### Install All Dependencies

```bash
uv sync
```

This single command installs:

- Faster Whisper + ctranslate2 for transcription
- PyAnnote Audio for speaker diarization
- FastAPI, PyQt6, and all other dependencies

#### Configure HuggingFace Access (Required for Diarization)

You need a HuggingFace token with access to PyAnnote models:

1. Get your token from: [Hugging Face settings](https://huggingface.co/settings/tokens)
2. Accept the terms for these models:
    - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
    - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
3. Login:

```bash
huggingface-cli login
```

#### Test Installation

```bash
python -c "from DIARIZATION import DiarizationManager; print('Diarization OK')"
python -c "import faster_whisper; print('Faster Whisper OK')"
deactivate
```

---

## Configuration

All settings are in a single `config.yaml` file at the project root. This unified configuration controls all transcription modes, audio settings, diarization, and storage options.

### Key Configuration Sections

```yaml
# Language for transcription (null = auto-detect)
transcription_options:
    language: null               # "en", "el", "de", etc. or null for auto
    enable_preview_transcriber: true  # Show live preview during longform recording

# Static file transcription defaults
static_transcription:
    enable_diarization: false    # Identify speakers (requires diarization module)
    word_timestamps: true        # Include word-level timing
    max_segment_chars: 500       # Max characters per output segment

# Longform recording (live dictation)
longform_recording:
    include_in_viewer: true      # Auto-save to Audio Notebook database
    word_timestamps: true        # Get word timestamps when saving to viewer
    enable_diarization: false    # Run diarization on recordings

# Speaker diarization settings
diarization:
    model: "pyannote/speaker-diarization-3.1"
    device: "cuda"
    min_speakers: null           # null = auto-detect
    max_speakers: null

# Main transcription model (used by ALL modes)
main_transcriber:
    model: "Systran/faster-whisper-large-v3"
    device: "cuda"
    compute_type: "default"
    beam_size: 5
    initial_prompt: null
    faster_whisper_vad_filter: true

# Preview transcriber (lightweight model for live preview)
preview_transcriber:
    model: "Systran/faster-whisper-base"
    device: "cuda"
    compute_type: "default"
    # ... additional VAD settings

# Storage for Audio Notebook
storage:
    audio_dir: "data/audio"
    audio_format: "mp3"
    audio_bitrate: 160

# Local LLM integration (LM Studio)
local_llm:
    enabled: true
    base_url: "http://127.0.0.1:1234"
    model: ""                    # Empty = use whatever is loaded in LM Studio
    max_tokens: 2048
    temperature: 0.7
    default_system_prompt: |
        You are a helpful assistant that analyzes transcriptions...
```

### Local LLM Configuration Priority

When using LM Studio for LLM features (like transcript summarization), you may notice that both `config.yaml` and LM Studio's UI allow you to configure settings like `max_tokens`, `temperature`, and `model`. Here's how the priority works:

**Priority Hierarchy (highest to lowest):**

1. **API Request Parameters** — Values sent by the frontend when making a request
2. **config.yaml Settings** — Used if the API request doesn't specify them
3. **LM Studio UI Settings** — Only used if neither of the above specify them

**In Practice:**

Since this application **always sends** `max_tokens` and `temperature` in every API request (using either frontend values or `config.yaml` defaults), **LM Studio's UI settings for these parameters are ignored**.

Think of it this way: LM Studio is just a server waiting for instructions. When the app sends a request with `max_tokens: 2048`, LM Studio follows that instruction regardless of what its UI shows.

**The Model Exception:**

The `model` setting behaves differently. When `model: ""` (empty) in `config.yaml`, the application doesn't include a model in the API request, so **LM Studio uses whatever model is currently loaded in its UI**. This is intentional — it lets you switch models in LM Studio without editing the config file.

| Setting | config.yaml Value | LM Studio UI Value | **Value Used** |
|---------|-------------------|-------------------|----------------|
| `max_tokens` | 2048 | 4096 | **2048** (config wins) |
| `temperature` | 0.7 | 0.9 | **0.7** (config wins) |
| `model` | "" (empty) | llama-3.2-8b | **llama-3.2-8b** (LM Studio wins) |
| `model` | "specific-model" | llama-3.2-8b | **specific-model** (config wins) |

### Unified Model Settings

The `main_transcriber` section is the **single source of truth** for the transcription model. These settings are used by:

| Mode | Uses `main_transcriber` settings |
|------|----------------------------------|
| Longform Recording | ✅ model, device, compute_type, beam_size, initial_prompt, vad_filter |
| Static File Transcription | ✅ model, device, compute_type, beam_size, initial_prompt, vad_filter |
| Audio Notebook (Web UI) | ✅ model, device, compute_type, beam_size, initial_prompt, vad_filter |

This ensures consistent transcription quality across all modes. Change the model once, and it applies everywhere.

### Finding Your Audio Device

```bash
source .venv/bin/activate
python list_audio_devices.py
```

Update `config.yaml`:

```yaml
audio:
    input_device_index: 21  # Your device index
    use_default_input: false
```

### Configuring CAVA for Waveform Display (Optional)

The console display can show a live audio waveform during recording using CAVA.

```bash
sudo pacman -S cava
```

Find your PipeWire audio source:

```bash
pw-cli list-objects Node
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

---

## File Storage

Understanding where TranscriptionSuite stores files:

### Storage Locations

| Type | Location | Description |
|------|----------|-------------|
| **Database** | `AUDIO_NOTEBOOK/backend/data/transcriptions.db` | SQLite with FTS5 for word search |
| **Audio Files** | `AUDIO_NOTEBOOK/backend/data/audio/` | Imported audio stored as MP3 |
| **Transcriptions** | Database | Stored in SQLite tables, not as JSON files |
| **Logs** | Project root | `transcription_suite.log`, `webapp.log` |
| **Models** | `~/.cache/huggingface/` | Downloaded Whisper/PyAnnote models |
| **Temp Files** | `/tmp/transcription-suite/` | Intermediate WAV files during processing |
| **ctranslate2 Build** | `deps.bak/ctranslate2/` | Compiled ctranslate2 library (if custom built) |

### Log Files

All log files are stored in the **project root** and are **wiped on each application start**:

| Log File | Created By | Contents |
|----------|------------|----------|
| `transcription_suite.log` | `orchestrator.py` | Tray mode operations, recording, static transcription |
| `webapp.log` | `AUDIO_NOTEBOOK/backend` | Web app API requests, search queries |

### Audio Import Process

When you import an audio/video file through the Audio Notebook:

```text
Source File (any format)
    │
    ▼
┌───────────────────────────────────────┐
│ 1. FFmpeg converts to WAV             │
│    - 16kHz mono for Whisper           │
│    - Stored in temp directory         │
└───────────────────────────────────────┘
    │
    ├──────────────────────────────────────┐
    ▼                                      ▼
┌─────────────────────────────────────┐  ┌─────────────────────────────┐
│ 2a. Transcription                   │  │ 2b. Audio Storage           │
│     (uses WAV)                      │  │     - Source → MP3 (128kbps)│
└─────────────────────────────────────┘  │     - Stored in data/audio/ │
    │                                    └─────────────────────────────┘
    ▼
┌───────────────────────────────────────┐
│ 3. Results saved to SQLite            │
│    - recordings table                 │
│    - segments table                   │
│    - words table (with timestamps)    │
│    - words_fts (full-text search)     │
└───────────────────────────────────────┘
    │
    ▼
Temp WAV deleted
```

### Database Schema

```sql
-- Main recordings table
recordings (
    id, filename, filepath, duration_seconds, 
    recorded_at, word_count, has_diarization, summary
)

-- Segments (speaker turns or time-based chunks)
segments (
    id, recording_id, segment_index, speaker, 
    text, start_time, end_time
)

-- Individual words with timestamps
words (
    id, recording_id, segment_id, word_index, 
    word, start_time, end_time, confidence
)

-- FTS5 virtual table for instant search
words_fts (word)
```

---

## Usage

### Starting the Application

Always run from the project root with the venv activated:

```bash
source .venv/bin/activate
python SCRIPT/orchestrator.py
```

### System Tray Controls

| Action | Effect |
|--------|--------|
| **Left-click** | Start longform recording |
| **Middle-click** | Stop recording & transcribe |
| **Right-click** | Open context menu |

### Tray Icon Colors

| Color | State |
|-------|-------|
| ⚫ Grey | Loading models or models unloaded |
| 🟢 Green | Ready/standby |
| 🟡 Yellow | Recording audio |
| 🟠 Orange | Transcribing longform recording |
| 🟣 Mauve | Static file transcription in progress |
| 🩵 Aquamarine | Audio Notebook web server running |
| 🔴 Red | Error state |

### Context Menu Options

- **Start Recording** — Begin longform dictation
- **Stop Recording** — Stop and transcribe
- **Transcribe Audio File...** — Open file picker for static transcription
- **Start/Stop Audio Notebook** — Toggle the web viewer server
- **Unload/Reload All Models** — Free GPU memory or reload models
- **Quit** — Exit the application

### Transcription Modes

#### 1. Longform Dictation (Live Recording)

1. Left-click the tray icon to start recording
2. Speak into your microphone
3. Watch the live preview in terminal (if `enable_preview_transcriber: true`)
4. Middle-click to stop and get final transcription
5. Text is automatically copied to clipboard

**Saving to Audio Notebook:**

When `include_in_viewer: true` in `config.yaml` under `longform_recording`, your recordings will automatically be converted to MP3 and saved to the Audio Notebook database with word-level timestamps.

#### 2. Static File Transcription

1. Right-click → "Transcribe Audio File..."
2. Select any audio/video file (WAV, MP3, FLAC, OGG, OPUS, M4A, MP4, MKV, etc.)
3. Wait for processing (watch terminal for progress)
4. JSON output saved next to source file as `{filename}_transcription.json`

**With Diarization:**

Enable `enable_diarization: true` in `static_transcription` config. The output will include speaker labels for each segment.

#### 3. Audio Notebook Web App

See the [Audio Notebook Web App](#audio-notebook-web-app) section below.

### CLI Mode

For batch processing without the GUI:

```bash
source .venv/bin/activate
python SCRIPT/orchestrator.py --static /path/to/audio.mp3
```

This transcribes the file and saves the JSON output, then exits.

---

## Audio Notebook Web App

The Audio Notebook is a **web-based application** for managing and searching your transcribed recordings. It runs in your browser and is launched from the system tray menu.

### Features

| Feature | Description |
|---------|-------------|
| 📅 **Calendar View** | Browse recordings organized by date with badge indicators |
| 🔍 **Full-Text Search** | Find words/phrases across all transcriptions using SQLite FTS5 |
| 🎯 **Fuzzy Matching** | Enable prefix search for partial word matches |
| 📆 **Date Filtering** | Narrow search results to specific date ranges |
| ⏱️ **Click-to-Play** | Click any word to jump to that moment in the audio |
| 🎵 **Audio Player** | Built-in player with 10-second skip, seeking, timestamps |
| 👥 **Speaker Labels** | View speaker identification chips in transcripts |
| 📁 **Import Files** | Import audio files and auto-transcribe in background |
| 🌙 **Dark Mode** | Modern dark theme |

### Tech Stack

| Component | Technology |
|-----------|------------|
| **Frontend** | React 18 + TypeScript + Tailwind CSS |
| **Backend** | FastAPI (Python) — integrated into main app |
| **Database** | SQLite with FTS5 for full-text search |
| **Audio** | Howler.js for playback |
| **Build Tool** | Vite |

### Starting the Audio Notebook

#### Option 1: From System Tray (Recommended)

1. Start the orchestrator: `python SCRIPT/orchestrator.py`
2. Right-click the system tray icon
3. Select **"Start Audio Notebook"**
4. The web interface opens at [http://localhost:8000](http://localhost:8000)

#### Option 2: Manual Development Setup

```bash
cd AUDIO_NOTEBOOK

# Install frontend dependencies (first time only)
npm install

# Build the frontend (required for orchestrator to serve it)
npm run build

# Or run frontend dev server with hot reload (runs on port 1420)
npm run dev
```

This starts:

- **Orchestrator (backend)**: [http://localhost:8000](http://localhost:8000) — API + transcription
- **Frontend (dev server)**: [http://localhost:1420](http://localhost:1420) — Hot reload
- **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI)

### Views

#### Calendar View (Home)

The home screen shows a monthly calendar where each day with recordings displays a badge. Click a day to see all recordings from that date.

#### Recording Detail

Click any recording to see the full transcript with word-level highlighting, speaker labels (if diarization was enabled), and playback controls.

#### Search

Use the search page to find specific words or phrases across all your recordings. Results show the word in context with a link to the exact timestamp in the recording.

---

## Output Format

### JSON Output (Static Transcription)

```json
{
  "segments": [
    {
      "text": "This is mercury metal.",
      "start": 0.0,
      "end": 1.52,
      "duration": 1.52,
      "speaker": "SPEAKER_00",
      "words": [
        {"word": "This", "start": 0.0, "end": 0.24, "probability": 0.99},
        {"word": "is", "start": 0.24, "end": 0.4, "probability": 0.98},
        {"word": "mercury", "start": 0.4, "end": 0.88, "probability": 0.95},
        {"word": "metal.", "start": 0.88, "end": 1.52, "probability": 0.97}
      ]
    }
  ],
  "num_speakers": 1,
  "total_duration": 31.14,
  "total_words": 145,
  "metadata": {
    "source_file": "/path/to/audio.mp3",
    "num_segments": 12,
    "speakers": ["SPEAKER_00"]
  }
}
```

---

## How It Works

### Smart Model Management

The orchestrator manages GPU memory by keeping only one model type loaded at a time:

```text
Application Startup
    │
    ▼
┌───────────────────────────────────────┐
│ Orchestrator starts                   │
│ - Preload LONGFORM model(s)           │
│ - Tray icon: GREY → GREEN             │
│ - Ready for immediate recording       │
└───────────────────────────────────────┘
    │
    ├─────────────────────────────────────────────────────────┐
    │ (User starts longform recording)                        │
    ▼                                                         │
┌───────────────────────────────────────┐                     │
│ Longform model ALREADY LOADED         │                     │
│ - No model switch needed              │                     │
│ - Start recording immediately         │                     │
│ - Model stays loaded after finish     │                     │
└───────────────────────────────────────┘                     │
                                                              │
    ┌─────────────────────────────────────────────────────────┘
    │ (User starts static transcription OR audio notebook)
    ▼
┌───────────────────────────────────────┐
│ 1. Unload LONGFORM model              │
│    - Free GPU memory                  │
│    - Tray icon: GREY (loading)        │
└───────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────┐
│ 2. Load STATIC model                  │
│    - Uses main_transcriber settings   │
│    - Model cached for reuse           │
└───────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────┐
│ 3. Process files (can do multiple)    │
│    - No reload between files          │
│    - Tray: MAUVE/AQUAMARINE           │
└───────────────────────────────────────┘
    │
    ▼ (User starts longform recording)
┌───────────────────────────────────────┐
│ Switch back to LONGFORM model         │
│ - Unload static → Load longform       │
└───────────────────────────────────────┘
```

### Dual Transcriber Mode (Preview Enabled)

When `enable_preview_transcriber: true`, two models run simultaneously:

- **Preview Transcriber** (base model): Handles microphone, VAD, live preview
- **Main Transcriber** (large model): Receives audio feed, produces final transcription

This provides real-time feedback while maintaining high-quality final output.

### Transcription Pipeline (Static Files)

```text
Audio File
    │
    ▼
┌───────────────────────────────────────┐
│ 1. FFmpeg converts to 16kHz mono WAV  │
└───────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────┐
│ 2. WebRTC VAD removes silence         │
│    (optional, for cleaner input)      │
└───────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────┐
│ 3. Faster Whisper transcribes         │
│    - word_timestamps=True             │
│    - Returns words + timing           │
└───────────────────────────────────────┘
    │
    ├─── (if diarization enabled) ──────┐
    ▼                                   ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐
│ 4a. Output without speakers │  │ 4b. PyAnnote diarization    │
│     - Group into segments   │  │     - Returns speaker times │
└─────────────────────────────┘  └─────────────────────────────┘
                                        │
                                        ▼
                                 ┌─────────────────────────────┐
                                 │ 5. Combiner merges results  │
                                 │    - Assign speaker to word │
                                 │    - Group by speaker       │
                                 └─────────────────────────────┘
    │
    ▼
JSON Output File
```

### Speaker Assignment Algorithm

Each word is assigned to a speaker by:

1. Calculate the word's midpoint: `(start + end) / 2`
2. Find the diarization segment that contains this midpoint
3. Use that segment's speaker label
4. Group consecutive words with the same speaker
5. Split segments if they exceed `max_segment_chars` (default 500)

---

## Module Architecture

### Core Application Logic (`SCRIPT/`)

| Script | Purpose |
|--------|---------|
| `orchestrator.py` | Central controller, manages state, connects UI to backend, serves API |
| `model_manager.py` | Loads and manages AI models, handles cleanup |
| `recorder.py` | High-level wrapper for recording sessions |
| `stt_engine.py` | Low-level transcription engine, VAD, audio processing |
| `static_transcriber.py` | Handles static file transcription with preprocessing |

### User Interface & Display

| Script | Purpose |
|--------|---------|
| `tray_manager.py` | System tray icon and menu (PyQt6) |
| `console_display.py` | Terminal UI: recording timer, CAVA waveform, live preview (Rich) |

### Configuration & Utilities

| Script | Purpose |
|--------|---------|
| `config_manager.py` | Loads and validates `config.yaml` |
| `logging_setup.py` | Application-wide logging setup |
| `platform_utils.py` | Platform-specific code (Linux paths, CUDA detection) |
| `dependency_checker.py` | Verifies required packages and programs |
| `diagnostics.py` | Hardware info and startup banner |
| `utils.py` | Shared utilities (safe_print, format_timestamp) |

### Audio Notebook Backend (`AUDIO_NOTEBOOK/backend/`)

| File | Purpose |
|------|---------|
| `database.py` | SQLite + FTS5 schema, queries, and utilities |
| `webapp_logging.py` | Web app logging configuration |
| `routers/recordings.py` | Recording CRUD endpoints |
| `routers/search.py` | Full-text search endpoints |
| `routers/transcribe.py` | Import and transcription endpoints |
| `routers/llm.py` | Local LLM integration (LM Studio) |

### Diarization Module (`DIARIZATION/`)

| File | Purpose |
|------|---------|
| `diarization_manager.py` | PyAnnote pipeline management |
| `service.py` | Diarization service wrapper |
| `combiner.py` | Merges transcription + speaker labels |
| `utils.py` | Segment utilities and helpers |

---

## Troubleshooting

### Common Issues

#### "Diarization not available"

Ensure PyAnnote is installed and you've logged into HuggingFace:

```bash
source .venv/bin/activate
python -c "from DIARIZATION import DiarizationService; print('OK')"
```

If it fails, check that you've accepted the model terms on HuggingFace and run `huggingface-cli login`.

#### CUDA out of memory

With on-demand model loading, this should be rare. However, if it occurs:

1. Models are automatically unloaded when switching modes
2. Ensure no other GPU-intensive apps are running
3. Use the "Unload All Models" menu option to free memory
4. Set `device: "cpu"` in `main_transcriber` config (slower but uses system RAM)
5. Use a smaller model (e.g., `Systran/faster-whisper-medium`)

#### HuggingFace token issues

```bash
source .venv/bin/activate
huggingface-cli login
```

Then accept model terms at the HuggingFace links above.

#### CUDA/cuDNN Issues

1. Verify CUDA: `nvcc --version`
2. Check cuDNN is installed and in library path
3. Ensure PyTorch with CUDA support is installed

#### Audio Device Issues

1. Run `list_audio_devices.py` to confirm device index
2. Check system audio permissions
3. Verify no other app is using the microphone exclusively

#### ctranslate2 Build Failures

1. Ensure all build dependencies are installed: `sudo pacman -S --needed base-devel git openblas cmake`
2. Check that CUDA toolkit is properly installed
3. Verify `CMAKE_CUDA_ARCHITECTURES` matches your GPU
4. Look for errors in the build output

#### Audio Notebook Not Opening

1. Check if port 8000 is already in use
2. Ensure the orchestrator is running
3. Check `webapp.log` for errors

---

## License

MIT License — See [LICENSE](LICENSE) for details.

## Acknowledgments

This project builds upon several excellent open-source projects:

- **[RealtimeSTT](https://github.com/KoljaB/RealtimeSTT)** — The core transcription engine was adapted from this library
- **[Faster Whisper](https://github.com/SYSTRAN/faster-whisper)** — Excellent model optimization
- **[PyAnnote Audio](https://github.com/pyannote/pyannote-audio)** — State-of-the-art speaker diarization
- **[OpenAI Whisper](https://github.com/openai/whisper)** — Original speech recognition models
- **[CTranslate2](https://github.com/OpenNMT/CTranslate2)** — Fast inference engine for Transformer models
