# TranscriptionSuite

Speech-to-text transcription suite for Linux with speaker diarization. Uses `faster-whisper` for transcription and `pyannote-audio` for speaker identification.

**Features:**

- Truly multilingual, supports [90+ languages](https://whisper-api.com/docs/languages/)
- CUDA 12.6 acceleration
- Longform dictation (optional live preview)
- Static file transcription (audio/video)
- Speaker diarization
- Word-level timestamps
- Full-text search (SQLite FTS5)
- Audio Notebook web app for browsing and searching recordings

📌 *Half an hour of audio transcribed in under a minute (RTX 3060)*

## Table of Contents

- [Project Architecture](#project-architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Audio Notebook Web App](#audio-notebook-web-app)
- [Output Format](#output-format)
- [How It Works](#how-it-works)
- [Module Architecture](#module-architecture)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Project Architecture

```
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

### 6. Install Frontend Dependencies (Optional)

Only needed if you want to modify the Audio Notebook web interface:

```bash
cd AUDIO_NOTEBOOK && npm install && cd ..
```

### 7. Verify Installation

```bash
uv run python -c "from DIARIZATION import DiarizationManager; print('Diarization OK')"
uv run python -c "import faster_whisper; print('Faster Whisper OK')"
```

### 8. Run

```bash
uv run SCRIPT/orchestrator.py
```

## Configuration

All settings are in `config.yaml` at the project root.

### Key Sections

```yaml
transcription_options:
    language: null               # "en", "el", etc. or null for auto-detect
    enable_preview_transcriber: true

static_transcription:
    enable_diarization: false
    word_timestamps: true
    max_segment_chars: 500

longform_recording:
    include_in_viewer: true      # Save to Audio Notebook
    word_timestamps: true
    enable_diarization: false

diarization:
    model: "pyannote/speaker-diarization-3.1"
    device: "cuda"
    min_speakers: null           # null = auto-detect
    max_speakers: null

main_transcriber:
    model: "Systran/faster-whisper-large-v3"
    device: "cuda"
    compute_type: "default"
    beam_size: 5
    initial_prompt: null
    faster_whisper_vad_filter: true

preview_transcriber:
    model: "Systran/faster-whisper-base"
    device: "cuda"

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
| Logs | `transcription_suite.log`, `webapp.log` (project root, wiped on start) |
| Models | `~/.cache/huggingface/` |
| Temp Files | `/tmp/transcription-suite/` |

## Usage

```bash
uv run SCRIPT/orchestrator.py
```

### System Tray

| Action | Effect |
|--------|--------|
| Left-click | Start recording |
| Middle-click | Stop & transcribe |
| Right-click | Context menu |

**Icon Colors:** Grey (loading), Green (ready), Yellow (recording), Orange (transcribing longform), Mauve (static transcription), Aquamarine (web server running), Red (error)

### Context Menu

- Start/Stop Recording
- Transcribe Audio File...
- Start/Stop Audio Notebook
- Unload/Reload All Models
- Quit

### Longform Dictation

1. Left-click tray to start
2. Speak (live preview in terminal if enabled)
3. Middle-click to stop
4. Text copied to clipboard

When `include_in_viewer: true`, recordings are saved to Audio Notebook with word timestamps.

### Static Transcription

1. Right-click → "Transcribe Audio File..."
2. Select file (WAV, MP3, FLAC, OGG, OPUS, M4A, MP4, MKV, etc.)
3. JSON saved as `{filename}_transcription.json`

Enable `enable_diarization: true` for speaker labels.

### CLI Mode

```bash
uv run python SCRIPT/orchestrator.py --static /path/to/audio.mp3
```

---

## Audio Notebook Web App

Web-based UI for managing and searching transcriptions. Launch from the system tray menu.

**Features:** Calendar view, full-text search (FTS5), fuzzy matching, date filtering, click-to-play timestamps, audio player, speaker labels, file import, dark mode.

**Stack:** React 18 + TypeScript + Tailwind (frontend), FastAPI (backend), SQLite FTS5, Howler.js, Vite.

### Starting

**From tray:** Right-click → "Start Audio Notebook" → Opens at http://localhost:8000

**Development:**

```bash
cd AUDIO_NOTEBOOK
npm install  # First time
npm run build  # For production
npm run dev  # Hot reload on port 1420
```

API docs: http://localhost:8000/docs

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

### Speaker Assignment

Each word assigned to speaker by:
1. Calculate word midpoint: `(start + end) / 2`
2. Find diarization segment containing midpoint
3. Use that segment's speaker label
4. Group consecutive words by speaker
5. Split if exceeding `max_segment_chars`

---

## Module Architecture

### SCRIPT/

| Module | Purpose |
|--------|---------|
| `orchestrator.py` | Main controller, state management, API server |
| `model_manager.py` | AI model lifecycle |
| `recorder.py` | Recording sessions |
| `stt_engine.py` | Transcription engine, VAD, audio |
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

---

## Troubleshooting

**Diarization not available:** Run `hf auth login` and accept model terms.

**CUDA out of memory:** Use "Unload All Models" menu, close other GPU apps, or set `device: "cpu"`.

**ctranslate2/CUDA errors:** Ensure CUDA 12.6 is installed at `/opt/cuda-12.6`. See [CUDA Setup](#cuda-setup).

**Audio device issues:** Run `uv run python list_audio_devices.py` and update `config.yaml`.

**Audio Notebook not opening:** Check if port 8000 is in use, check `webapp.log`.

## License

MIT License — See [LICENSE](LICENSE).

## Acknowledgments

- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) — Core transcription engine adapted from this library
- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper)
- [PyAnnote Audio](https://github.com/pyannote/pyannote-audio)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)
