# TranscriptionSuite

A comprehensive speech-to-text transcription suite for Linux with speaker diarization support. Built with Python, leveraging `faster-whisper` for high-performance transcription and `pyannote-audio` for state-of-the-art speaker identification. Accelerated by **CUDA 13+** for GPU inference.

> **Key Features:**
>
> - 🎙️ **Longform Dictation** - Start/stop voice recording with live preview
> - 📁 **Static File Transcription** - Transcribe any audio/video file
> - 👥 **Speaker Diarization** - Identify "who spoke when"
> - ⏱️ **Word-Level Timestamps** - Precise timing for every word
> - 🔍 **Searchable Output** - JSON output with full text search capability
> - 🖥️ **Web Viewer App** - Browse, search, and play transcriptions in your browser
> - 🚀 **Extremely Fast** - 30 minutes of audio in ~40 seconds (RTX 3060)
> - 🌍 **Multilingual** - Works with Greek, English, and 90+ languages

---

## Table of Contents

- [Project Architecture](#project-architecture)
- [Dual Virtual Environment Design](#dual-virtual-environment-design)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [File Storage](#file-storage)
- [Usage](#usage)
- [Transcription Viewer App](#transcription-viewer-app)
- [Output Format](#output-format)
- [How It Works](#how-it-works)
- [Module Architecture](#module-architecture)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Project Architecture

The project is split into **two main modules** with separate Python virtual environments due to dependency conflicts.

```text
TranscriptionSuite/
├── config.yaml                   # Unified configuration file
├── _core/                        # Main application (Python 3.13)
│   ├── SCRIPT/                   # Application source code
│   │   ├── orchestrator.py       # Main entry point & central controller
│   │   ├── static_transcriber.py
│   │   ├── stt_engine.py
│   │   ├── tray_manager.py
│   │   └── ...
│   ├── APP_VIEWER/               # Web viewer application
│   │   ├── backend/              # FastAPI backend
│   │   │   ├── database.py       # SQLite with FTS5
│   │   │   ├── routers/          # API endpoints
│   │   │   └── data/             # Database & audio storage
│   │   ├── src/                  # React frontend
│   │   ├── dev.sh                # Development launcher
│   │   └── package.json
│   ├── DIARIZATION_SERVICE/      # Bridge to diarization module
│   │   ├── service.py            # Subprocess caller
│   │   └── combiner.py           # Combines transcription + diarization
│   ├── .venv/                    # Core virtual environment
│   └── pyproject.toml
│
├── _module-diarization/          # Speaker diarization (Python 3.11)
│   ├── DIARIZATION/              # Diarization source code
│   │   ├── diarize_audio.py      # CLI entry point
│   │   ├── diarization_manager.py
│   │   └── ...
│   ├── .venv/                    # Diarization virtual environment
│   └── pyproject.toml
│
└── README.md
```

### Why Two Environments?

| Module | Python | Key Dependencies | Purpose |
|--------|--------|------------------|---------|
| `_core` | 3.13 | `faster-whisper`, `torch 2.9+`, `FastAPI`, `ctranslate2` | Transcription, VAD, Web API, UI |
| `_module-diarization` | 3.11 | `pyannote-audio`, `torch 2.x` | Speaker identification |

The `pyannote-audio` library has strict dependency requirements that conflict with the latest `faster-whisper` and `torch` versions. Running them in separate environments solves this elegantly.

**Note:** The web viewer app (frontend + backend) is **fully integrated into `_core`** (in `APP_VIEWER/`), sharing the same virtual environment. All transcription modes (longform, static, web UI) use the **same model settings** from `main_transcriber` in `config.yaml`.

---

## Dual Virtual Environment Design

### Communication Between Modules

When you run static file transcription, the following happens:

```text
┌─────────────────────────────────────────────────────────────────┐
│                         _core (Python 3.13)                     │
│                                                                 │
│  1. User selects audio file via tray menu                       │
│  2. orchestrator.py → static_transcriber.py                     │
│  3. Faster Whisper transcribes with word_timestamps=True        │
│  4. DIARIZATION_SERVICE/service.py calls subprocess:            │
│                                                                 │
│     subprocess.run([                                            │
│       "_module-diarization/.venv/bin/python",  ← Different venv │
│       "diarize_audio.py", "audio.wav"                           │
│     ])                                                          │
│                                                                 │
│  5. Receives JSON via stdout, combines with transcription       │
│  6. Saves result to {audio_name}_transcription.json             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (subprocess)
┌─────────────────────────────────────────────────────────────────┐
│                  _module-diarization (Python 3.11)              │
│                                                                 │
│  - Receives audio file path                                     │
│  - Runs PyAnnote speaker-diarization-3.1                        │
│  - Outputs JSON to stdout (logs go to stderr)                   │
│  - Returns: {"segments": [...], "num_speakers": N}              │
└─────────────────────────────────────────────────────────────────┘
```

**Key Point:** The diarization module's Python interpreter is called directly via its absolute path. This ensures it uses its own venv packages, regardless of which venv is active in your shell.

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/homelab-00/TranscriptionSuite.git
cd TranscriptionSuite

# 2. Set up _core environment (Python 3.13)
cd _core
uv venv --python 3.13
source .venv/bin/activate
# Build ctranslate2 (see Installation section for details)
./build_ctranslate2.sh
uv sync
deactivate

# 3. Set up diarization environment (Python 3.11)
cd ../_module-diarization
uv venv --python 3.11
source .venv/bin/activate
uv sync
hf auth login  # Required for PyAnnote models
deactivate

# 4. Install frontend dependencies (optional, for web viewer)
cd ../_core/APP_VIEWER
npm install
cd ../..

# 5. Run the application
cd _core
source .venv/bin/activate
python SCRIPT/orchestrator.py
```

---

## Installation

### Prerequisites

- **Arch Linux** (or compatible distro)
- **NVIDIA GPU** with CUDA 13.0+ support
- **Python 3.11** and **Python 3.13** (both required)
- **uv** package manager

### System Dependencies

```bash
# Install system packages
sudo pacman -S --needed cuda cudnn uv base-devel git openblas ffmpeg

# For the system tray and waveform display (optional)
sudo pacman -S --needed cava
```

### Setting Up _core

#### Step 1: Create Virtual Environment (_core)

```bash
cd _core
uv venv --python 3.13
source .venv/bin/activate
```

#### Step 2: Install Build Dependencies

```bash
uv add build setuptools wheel pybind11==2.11.1
sudo pacman -S --needed base-devel git openblas
```

#### Step 3: Build Custom ctranslate2

The `ctranslate2` library needs to be compiled locally to link against your system's CUDA 13+ toolkit.

**Important:** Before running, edit `build_ctranslate2.sh` to match your GPU's Compute Capability:

1. Open `build_ctranslate2.sh`
2. Find the line `export CMAKE_CUDA_ARCHITECTURES=86`
3. The value `86` is for RTX 3060. Find your GPU's capability at [NVIDIA CUDA GPUs](https://developer.nvidia.com/cuda-gpus)

```bash
chmod +x build_ctranslate2.sh
./build_ctranslate2.sh
```

#### Step 4: Install Dependencies

```bash
uv sync
deactivate
```

### Setting Up _module-diarization

#### Step 1: Create Virtual Environment (_module-diarization)

```bash
cd _module-diarization
uv venv --python 3.11
source .venv/bin/activate
```

#### Step 2: Install Dependencies

```bash
uv sync
```

#### Step 3: Configure HuggingFace Access

You need a HuggingFace token with access to PyAnnote models:

1. Get your token from: [Hugging Face settings](https://huggingface.co/settings/tokens)
2. Accept the terms for these models:
    - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
    - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
3. Login:

```bash
hf auth login
```

#### Step 4: Test Installation

```bash
python -c "from DIARIZATION import diarize_audio; print('Diarization module OK')"
deactivate
```

---

## Configuration

All settings are in a single `config.yaml` file at the project root. This file controls:

- Transcription language and models
- Static transcription options (diarization, word timestamps)
- Longform recording options
- Audio device selection
- Storage locations
- Logging settings

### Key Configuration Sections

```yaml
# Language for transcription (null = auto-detect)
transcription_options:
    language: null
    enable_preview_transcriber: false

# Static file transcription
static_transcription:
    enable_diarization: false
    word_timestamps: true
    max_segment_chars: 500

# Longform recording
longform_recording:
    include_in_viewer: true    # Show in viewer app
    word_timestamps: false
    enable_diarization: false

# Speaker diarization
diarization:
    model: "pyannote/speaker-diarization-3.1"
    device: "cuda"
    min_speakers: null  # Auto-detect
    max_speakers: null

# Model selection (used by ALL transcription modes)
main_transcriber:
    model: "Systran/faster-whisper-large-v3"
    device: "cuda"
    compute_type: "default"
    beam_size: 5
    initial_prompt: null
    faster_whisper_vad_filter: true

# Storage for viewer app
storage:
    audio_dir: "data/audio"
    audio_format: "mp3"
    audio_bitrate: 128
```

### Unified Model Settings

The `main_transcriber` section is the **single source of truth** for model configuration. These settings are used by:

| Mode | Uses `main_transcriber` settings |
|------|----------------------------------|
| Longform Recording | ✅ model, device, compute_type, beam_size, initial_prompt, vad_filter |
| Static File Transcription | ✅ model, device, compute_type, beam_size, initial_prompt, vad_filter |
| Audio Notebook (Web UI) | ✅ model, device, compute_type, beam_size, initial_prompt, vad_filter |

This ensures consistent transcription quality across all modes. Change the model once, and it applies everywhere.

### Finding Your Audio Device

```bash
cd _core
python list_audio_devices.py
```

Update `config.yaml`:

```yaml
audio:
    input_device_index: 21  # Your device index
    use_default_input: false
```

### Configuring CAVA for Waveform Display (Optional)

```bash
sudo pacman -S cava
```

Find your PipeWire audio source:

```bash
pw-cli list-objects Node
```

Edit `_core/SCRIPT/cava.config`:

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
| **Database** | `_core/APP_VIEWER/backend/data/transcriptions.db` | SQLite with FTS5 for word search |
| **Audio Files** | `_core/APP_VIEWER/backend/data/audio/` | Imported audio stored as MP3 |
| **Transcriptions** | Database | Stored in SQLite tables, not as JSON files |
| **Logs** | Project root | `transcription_suite.log` |
| **Models** | `~/.cache/huggingface/` | Downloaded Whisper/PyAnnote models |
| **Temp Files** | `/tmp/transcription-suite/` | Intermediate WAV files during processing |

### Audio Import Process

When you import an audio/video file through the viewer app:

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
    recorded_at, word_count, has_diarization
)

-- Segments (speaker turns)
segments (
    id, recording_id, segment_index, speaker, 
    text, start_time, end_time
)

-- Individual words with timestamps
words (
    id, recording_id, segment_id, word_index, 
    word, start_time, end_time, confidence
)

-- FTS5 virtual table for search
words_fts (word)
```

---

## Usage

### Starting the Application

Always run from the `_core` directory with its venv activated:

```bash
cd _core
source .venv/bin/activate
python SCRIPT/orchestrator.py
```

### System Tray Controls

| Action | Effect |
|--------|--------|
| **Left-click** | Start recording |
| **Middle-click** | Stop recording & transcribe |
| **Right-click** | Open context menu |

### Tray Icon Colors

| Color | State |
|-------|-------|
| 🔘 Grey | Loading models |
| 🟢 Green | Ready/standby (no models loaded) |
| 🟡 Yellow | Recording audio |
| 🟠 Orange | Transcribing |
| 🩵 Aquamarine | Audio Notebook running |
| 🔴 Red | Error state |

### Transcription Modes

#### 1. Longform Dictation (Live Recording)

1. Left-click the tray icon to start recording
2. Speak into your microphone
3. Watch the live preview (if enabled)
4. Middle-click to stop and get final transcription
5. Text is automatically copied to clipboard

**Saving to Viewer App:**

When `include_in_viewer: true` and either `word_timestamps: true` or `enable_diarization: true` is set in `config.yaml` under `longform_recording`, your recordings will automatically be:

1. Converted to MP3 and stored in `_core/APP_VIEWER/backend/data/audio/`
2. Saved to the viewer database with word-level timestamps
3. Available in the viewer app's calendar and search

Configure in `config.yaml`:

```yaml
longform_recording:
    include_in_viewer: true    # Enable saving to viewer app
    word_timestamps: true      # Enable word-level timestamps
    enable_diarization: false  # Enable speaker diarization
```

#### 2. Static File Transcription (with Diarization)

1. Right-click tray → "Static Transcription"
2. Select an audio file (wav, mp3, opus, flac, m4a, ogg)
3. Wait for processing:
   - Step 1/3: Transcription with word timestamps
   - Step 2/3: Speaker diarization (if enabled)
   - Step 3/3: Combining results
4. Result saved to: `{audio_directory}/{filename}_transcription.json`

**Note:** Diarization is optional and controlled by `config.yaml`. It's typically used for multi-speaker recordings like meetings or interviews.

### Model Management (Smart Model Switching)

The system uses **smart model switching** to optimize GPU memory and startup time:

- **Longform model preloaded at startup** - ready for immediate recording
- **Models switch only when changing modes** - not after every operation
- **Only one model type loaded at a time** - prevents GPU memory overflow
- **Manual control available** via tray menu: "Unload All Models" / "Reload All Models"

#### Model Switching Behavior

| From | To | Action |
|------|-----|--------|
| Startup | - | Preload longform model |
| Longform | Static Transcription | Unload longform → Load static |
| Longform | Audio Notebook | Unload longform → Load static |
| Static | Longform | Unload static → Load longform |
| Audio Notebook | Longform | Unload static → Load longform |
| Static | Static (another file) | Keep static model (no reload) |
| Longform | Longform (another recording) | Keep longform model (no reload) |

**All operations use the same model settings** from `main_transcriber` in `config.yaml`.

---

## Transcription Viewer App

The Transcription Viewer is a **web-based application** for managing and searching your transcribed recordings. It runs in your browser and is launched from the system tray menu.

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
| 🌙 **Dark Mode** | Modern Material Design dark theme |

### Tech Stack

| Component | Technology |
|-----------|------------|
| **Frontend** | React 18 + TypeScript + MUI (Material-UI) |
| **Backend** | FastAPI (Python) - integrated into `_core` |
| **Database** | SQLite with FTS5 for full-text search |
| **Audio** | Howler.js for playback |

### Starting the Viewer

The viewer can be launched in two ways:

#### Option 1: From System Tray (Recommended)

1. Start the orchestrator: `python SCRIPT/orchestrator.py`
2. Right-click the system tray icon
3. Select **"Start Audio Notebook"**
4. The web interface opens at [http://localhost:8000](http://localhost:8000)

#### Option 2: Using dev.sh (Development)

```bash
cd _core/APP_VIEWER

# Install frontend dependencies (first time only)
npm install

# Start orchestrator + frontend dev server
./dev.sh --frontend
```

This starts:

- **Orchestrator (backend)**: [http://localhost:8000](http://localhost:8000) - API + model
- **Frontend (dev server)**: [http://localhost:1420](http://localhost:1420) - Hot reload
- **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI)

### Views

#### Calendar View (Home)

The home screen shows a monthly calendar where each day with recordings displays a badge. Click a day to see all recordings from that date.

#### Search View

Full-text search across all transcribed words:

- **Query field**: Enter word or phrase to search
- **Fuzzy toggle**: Enable prefix matching
- **Date range**: Filter results by date
- Results show matched word with context, recording info, and play button

#### Recording View

View and play a recording with its transcription:

- **Audio player** with play/pause, ±10 second skip, time slider
- **Clickable transcript**: Each word is clickable—click to seek audio
- **Speaker chips**: Speaker labels appear if diarization was enabled

#### Import View

Import audio files for transcription:

- **Drag & drop**: Drag audio files into the drop zone
- **File browser**: Click to browse for audio files
- **Diarization toggle**: Enable speaker identification
- **Progress tracking**: See transcription job status

### Development Notes

When modifying the frontend source files in `_core/APP_VIEWER/src/`, you **must rebuild** the production bundle for changes to take effect:

```bash
cd _core/APP_VIEWER

# Rebuild the production bundle
npm run build
```

The orchestrator serves static files from `_core/APP_VIEWER/dist/`. Without rebuilding, your changes will not be visible when running from the system tray.

**Cleanup old builds**: After rebuilding, old JavaScript bundles remain in `dist/assets/`. To save disk space, delete old bundles:

```bash
# Remove old bundles (keep only the latest)
cd _core/APP_VIEWER/dist/assets
ls -t *.js | tail -n +2 | xargs rm -f  # Keep newest, delete rest
```

---

## Output Format

The static transcription output includes **word-level timestamps** and **speaker labels**:

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

### Smart Model Switching

The orchestrator manages GPU memory by keeping only one model type loaded:

```text
Application Startup
    │
    ▼
┌───────────────────────────────────────┐
│ Orchestrator starts                   │
│ - Preload LONGFORM model              │
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
│    - Model stays loaded for reuse     │
└───────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────┐
│ 3. Process files (can do multiple)    │
│    - No reload between files          │
│    - Tray: ORANGE/AQUAMARINE          │
└───────────────────────────────────────┘
    │
    ▼ (User starts longform recording)
┌───────────────────────────────────────┐
│ Switch back to LONGFORM model         │
│ - Unload static → Load longform       │
└───────────────────────────────────────┘
```

### Transcription Pipeline

```text
Audio File
    │
    ▼
┌───────────────────────────────────────┐
│ 1. FFmpeg Conversion                  │
│    - Convert any format to 16kHz WAV  │
│    - Mono channel, PCM format         │
└───────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────┐
│ 2. Faster Whisper Transcription       │
│    - word_timestamps=True             │
│    - Silero VAD for segmentation      │
│    - Returns segments with words[]    │
└───────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────┐
│ 3. PyAnnote Diarization (subprocess)  │
│    - Identifies speaker segments      │
│    - Returns JSON via stdout          │
└───────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────┐
│ 4. Combination                        │
│    - Assign speaker to each word      │
│    - Group by speaker + max length    │
│    - Preserve word timestamps         │
└───────────────────────────────────────┘
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

### Core Application Logic (`_core/SCRIPT/`)

| Script | Purpose |
|--------|---------|
| `orchestrator.py` | Central controller, manages state, connects UI to backend, serves API |
| `model_manager.py` | Loads and manages AI models, reads config |
| `recorder.py` | High-level wrapper for recording sessions |
| `stt_engine.py` | Low-level transcription engine, VAD, audio processing |
| `static_transcriber.py` | Handles static file transcription |

### User Interface & Display

| Script | Purpose |
|--------|---------|
| `tray_manager.py` | System tray icon and menu (PyQt6) |
| `console_display.py` | Terminal UI: timer, waveform, preview (Rich) |

### Configuration & Utilities

| Script | Purpose |
|--------|---------|
| `config_manager.py` | Loads and validates `config.yaml` |
| `logging_setup.py` | Application-wide logging setup |
| `platform_utils.py` | Platform-specific code (Linux paths, CUDA) |
| `dependency_checker.py` | Verifies required packages and programs |
| `diagnostics.py` | Hardware info and startup banner |

### Viewer Backend (`_core/APP_VIEWER/backend/`)

| File | Purpose |
|------|---------||
| `database.py` | SQLite + FTS5 schema and queries |
| `routers/recordings.py` | Recording CRUD endpoints |
| `routers/search.py` | Full-text search endpoints |
| `routers/transcribe.py` | Import and transcription endpoints |
| `routers/llm.py` | Local LLM integration (LM Studio) |

### Diarization Service (`_core/DIARIZATION_SERVICE/`)

| File | Purpose |
|------|---------|
| `service.py` | Subprocess bridge to `_module-diarization` |
| `combiner.py` | Merges transcription + speaker labels |

### Diarization Module (`_module-diarization/DIARIZATION/`)

| File | Purpose |
|------|---------|
| `diarize_audio.py` | CLI entry point |
| `diarization_manager.py` | PyAnnote pipeline management |
| `api.py` | API wrapper |
| `config_manager.py` | Configuration handling |

---

## Troubleshooting

### Common Issues

#### "Diarization not available"

Ensure the diarization venv is set up:

```bash
cd _module-diarization
source .venv/bin/activate
python -c "from DIARIZATION import diarize_audio; print('OK')"
```

#### CUDA out of memory

With on-demand model loading, this should be rare. However, if it occurs:

1. Models are automatically unloaded after each operation
2. Ensure no other GPU-intensive apps are running
3. Set `device: "cpu"` in `main_transcriber` config (slower but uses system RAM)
4. Use a smaller model (e.g., `Systran/faster-whisper-medium`)

#### HuggingFace token issues

```bash
cd _module-diarization
source .venv/bin/activate
hf auth login
```

Then accept model terms at the HuggingFace links above.

#### CUDA/cuDNN Issues

1. Verify CUDA: `nvcc --version`
2. Check cuDNN is installed and in library path
3. Confirm correct `CMAKE_CUDA_ARCHITECTURES` in build script

#### Audio Device Issues

1. Re-run `list_audio_devices.py` to confirm device index
2. Check system audio permissions
3. Verify no other app is using the microphone exclusively

---

## License

MIT License - See [LICENSE](LICENSE) for details.

## Acknowledgments

This project builds upon several excellent open-source projects:

- **[RealtimeSTT](https://github.com/KoljaB/RealtimeSTT)** - The core transcription engine was adapted from this library
- **[Faster Whisper](https://github.com/SYSTRAN/faster-whisper)** - Excellent model optimization
- **[PyAnnote Audio](https://github.com/pyannote/pyannote-audio)** - State-of-the-art speaker diarization
- **[OpenAI Whisper](https://github.com/openai/whisper)** - Original speech recognition models
