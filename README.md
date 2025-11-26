# TranscriptionSuite

A comprehensive speech-to-text transcription suite for Linux with **speaker diarization** support. Built with Python, leveraging `faster-whisper` for high-performance transcription and `pyannote-audio` for state-of-the-art speaker identification. Accelerated by **CUDA 13+** for GPU inference.

> **Key Features:**
>
> - 🎙️ **Longform Dictation** - Start/stop voice recording with live preview
> - 📁 **Static File Transcription** - Transcribe any audio/video file
> - 👥 **Speaker Diarization** - Identify "who spoke when"
> - ⏱️ **Word-Level Timestamps** - Precise timing for every word
> - 🔍 **Searchable Output** - JSON output with full text search capability
> - 🚀 **Extremely Fast** - 30 minutes of audio in ~40 seconds (RTX 3060)
> - 🌍 **Multilingual** - Works with Greek, English, and 90+ languages

---

## Table of Contents

- [Project Architecture](#project-architecture)
- [Dual Virtual Environment Design](#dual-virtual-environment-design)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Output Format](#output-format)
- [How It Works](#how-it-works)
- [Recent Development](#recent-development)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Project Architecture

The project is split into **two separate modules**, each with its own Python virtual environment. This separation is intentional due to dependency conflicts between the transcription and diarization libraries.

```text
TranscriptionSuite/
├── _core/                      # Main transcription engine (Python 3.13)
│   ├── SCRIPT/                 # Application source code
│   │   ├── orchestrator.py     # Main entry point
│   │   ├── static_transcriber.py
│   │   ├── stt_engine.py
│   │   └── ...
│   ├── diarization_service/    # Bridge to diarization module
│   │   ├── service.py          # Subprocess caller
│   │   └── combiner.py         # Combines transcription + diarization
│   ├── .venv/                  # Core virtual environment
│   └── pyproject.toml
│
├── _module-diarization/        # Speaker diarization (Python 3.10)
│   ├── DIARIZATION/            # Diarization source code
│   │   ├── diarize_audio.py    # CLI entry point
│   │   ├── diarization_manager.py
│   │   └── ...
│   ├── .venv/                  # Diarization virtual environment
│   └── pyproject.toml
│
└── README.md                   # This file
```

### Why Two Environments?

| Module | Python | Key Dependencies | Purpose |
|--------|--------|------------------|---------|
| `_core` | 3.13 | `faster-whisper`, `torch 2.9+`, `ctranslate2` | Transcription, VAD, UI |
| `_module-diarization` | 3.10 | `pyannote-audio`, `torch 2.x` | Speaker identification |

The `pyannote-audio` library has strict dependency requirements that conflict with the latest `faster-whisper` and `torch` versions. Running them in separate environments solves this elegantly.

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
│  4. diarization_service/service.py calls subprocess:            │
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
│                  _module-diarization (Python 3.10)              │
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
# Build ctranslate2 (see _core/README.md for details)
./build_ctranslate2.sh
uv sync
deactivate

# 3. Set up diarization environment (Python 3.10)
cd ../_module-diarization
uv venv --python 3.10
source .venv/bin/activate
uv sync
huggingface-cli login  # Required for PyAnnote models
deactivate

# 4. Run the application
cd ../_core
source .venv/bin/activate
python SCRIPT/orchestrator.py
```

---

## Installation

### Prerequisites

- **Arch Linux** (or compatible distro)
- **NVIDIA GPU** with CUDA 13.0+ support
- **Python 3.10** and **Python 3.13** (both required)
- **uv** package manager

### System Dependencies

```bash
# Install system packages
sudo pacman -S --needed cuda cudnn uv base-devel git openblas ffmpeg

# For the system tray and waveform display (optional)
sudo pacman -S --needed cava
```

### Setting Up _core

See [`_core/README.md`](_core/README.md) for detailed instructions on:

- Building the custom `ctranslate2` library
- Configuring your audio device
- Setting up models and language

### Setting Up _module-diarization

See [`_module-diarization/README.md`](_module-diarization/README.md) for:

- HuggingFace token configuration
- Accepting PyAnnote model terms
- Testing the diarization standalone

---

## Configuration

### Main Configuration (`_core/SCRIPT/config.yaml`)

```yaml
# Language for transcription (applies to both modes)
transcription_options:
    language: "el"  # Greek, "en" for English, etc.
    enable_preview_transcriber: true

# Audio input device
audio:
    input_device_index: 21  # Run list_audio_devices.py to find yours
    use_default_input: false

# Model selection
main_transcriber:
    model: "Systran/faster-whisper-large-v3"  # Best accuracy
    device: "cuda"
    compute_type: "float16"

preview_transcriber:
    model: "Systran/faster-whisper-medium"  # Faster for live preview
    device: "cuda"
    compute_type: "float16"

# Optional features
display:
    show_waveform: true  # Requires cava
```

### Diarization Configuration (`_module-diarization/DIARIZATION/config.yaml`)

```yaml
pyannote:
    hf_token: null  # Use huggingface-cli login instead (recommended)
    model: "pyannote/speaker-diarization-3.1"
    device: "cuda"  # or "cpu"

processing:
    sample_rate: 16000
    min_speakers: null  # Auto-detect
    max_speakers: null  # Auto-detect
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
| 🔘 Grey | Loading/initializing |
| 🟢 Green | Ready/standby |
| 🟡 Yellow | Recording audio |
| 🟠 Orange | Transcribing |
| 🔴 Red | Error state |

### Transcription Modes

#### 1. Longform Dictation (Live Recording)

1. Left-click the tray icon to start recording
2. Speak into your microphone
3. Watch the live preview (if enabled)
4. Middle-click to stop and get final transcription
5. Text is automatically copied to clipboard

#### 2. Static File Transcription (with Diarization)

1. Right-click tray → "Static Transcription"
2. Select an audio file (wav, mp3, opus, flac, m4a, ogg)
3. Wait for processing:
   - Step 1/3: Transcription with word timestamps
   - Step 2/3: Speaker diarization
   - Step 3/3: Combining results
4. Result saved to: `{audio_directory}/{filename}_transcription.json`

**Note:** Diarization is **only available for static file transcription**, not for live recording.

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
    },
    {
      "text": "It's one of the only elements that's liquid at room temperature.",
      "start": 1.52,
      "end": 5.2,
      "duration": 3.68,
      "speaker": "SPEAKER_00",
      "words": [
        {"word": "It's", "start": 1.52, "end": 1.72, "probability": 0.98},
        ...
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

### What You Can Do With This Output

- **Search for specific words** using Ctrl+F and find exactly when they were spoken
- **Jump to timestamps** - Each word has precise start/end times in seconds
- **Identify speakers** - Know who said what in multi-speaker recordings
- **Build applications** - Parse the JSON to create:
  - Searchable transcription archives
  - Interactive audio players with clickable transcripts
  - Meeting minutes with speaker attribution
  - Subtitle/caption files (SRT export planned)

---

## How It Works

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

## Recent Development

### Changes in Current Session

1. **Word-Level Timestamps** - Rewrote `static_transcriber.py` to use Faster Whisper directly with `word_timestamps=True`, instead of the realtime engine which only returns final text.

2. **New Data Structures** - Added `WordSegment` and `TranscriptSegment` dataclasses for proper typing and JSON serialization.

3. **Improved Combination Logic** - New `_combine_transcription_with_diarization()` method that:
   - Assigns speakers at the word level (not sentence level)
   - Respects maximum segment length to avoid huge blocks
   - Preserves all word timestamps in the output

4. **JSON Output Enhancement** - Output now includes:
   - `words[]` array with individual word timing
   - `total_words` count
   - `speakers` list in metadata

5. **Fixed Diarization Integration** - Resolved JSON parsing issues caused by logging messages polluting stdout. All logs now go to stderr.

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

#### "JSON parse error" during diarization

This was fixed. If you still see it, ensure you have the latest code that redirects logging to stderr.

#### CUDA out of memory

The system loads models into GPU memory. If you run out:

1. Use the "Unload All Models" option in the tray menu
2. Set `device: "cpu"` in config.yaml for one of the transcribers
3. Use smaller models (e.g., `medium` instead of `large-v3`)

#### HuggingFace token issues

```bash
cd _module-diarization
source .venv/bin/activate
huggingface-cli login
```

Then accept the model terms at:

- <https://huggingface.co/pyannote/segmentation-3.0>
- <https://huggingface.co/pyannote/speaker-diarization-3.1>

---

## Performance Benchmarks

Tested on RTX 3060 12GB, Ryzen 5 3600:

| Audio Length | Transcription | Diarization | Total |
|--------------|---------------|-------------|-------|
| 30 seconds | ~3s | ~2s | ~5s |
| 5 minutes | ~15s | ~8s | ~25s |
| 30 minutes | ~40s | ~30s | ~1.5min |

---

## License

MIT License - See [LICENSE](LICENSE) for details.

## Acknowledgments

- **[RealtimeSTT](https://github.com/KoljaB/RealtimeSTT)** - Core transcription engine foundation
- **[Faster Whisper](https://github.com/SYSTRAN/faster-whisper)** - Optimized Whisper implementation
- **[PyAnnote Audio](https://github.com/pyannote/pyannote-audio)** - State-of-the-art speaker diarization
- **[OpenAI Whisper](https://github.com/openai/whisper)** - Original speech recognition models

---

*Built with ❤️ for multilingual transcription, especially Greek.*
