# Speaker Diarization Module

A standalone Python module for speaker diarization using PyAnnote, designed to work with the TranscriptionSuite.

## Architecture Note

**This module performs DIARIZATION ONLY.** The combining of transcription + diarization results is handled by `_core/diarization_service/`. This separation exists because the diarization dependencies (pyannote.audio) are incompatible with the transcription dependencies.

## Features

- **Speaker Diarization**: Identify "who spoke when" in audio files
- **PyAnnote Integration**: Uses state-of-the-art PyAnnote models
- **Multiple Output Formats**: JSON, RTTM, segments
- **Isolated Environment**: Runs in separate UV environment to avoid dependency conflicts
- **Simple API**: Easy integration via subprocess from `_core`

## Setup

### 1. Create and activate the virtual environment

```bash
cd _module-diarization
uv venv --python 3.10
source .venv/bin/activate
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Configure HuggingFace Token

You need a HuggingFace token with access to PyAnnote models:

1. Get your token from: [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Accept the terms for these models:
   - [https://huggingface.co/pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   - [https://huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
3. Run the following command to store your HuggingFace Access Token locally:

```bash
huggingface-cli login
```

Or add your token to `DIARIZATION/config.yaml`:

```yaml
pyannote:
  hf_token: "hf_YOUR_TOKEN_HERE"
```

## Usage

### Command Line (Standalone)

#### Basic diarization

```bash
python DIARIZATION/diarize_audio.py audio.wav
```

#### With specific number of speakers

```bash
python DIARIZATION/diarize_audio.py audio.wav --min-speakers 2 --max-speakers 4
```

#### Save results

```bash
python DIARIZATION/diarize_audio.py audio.wav --output diarization.json
```

#### Export as RTTM

```bash
python DIARIZATION/diarize_audio.py audio.wav --output diarization.rttm --format rttm
```

### From _core (Integrated Usage)

The diarization is called automatically from `_core` via the `diarization_service` module:

```python

# In _core/SCRIPT/static_transcriber.py
from diarization_service import DiarizationService, TranscriptionCombiner

# The StaticFileTranscriber class has a method:
transcriber.transcribe_file_with_diarization(
    "audio.wav",
    min_speakers=2,
    max_speakers=4,
    output_file="result.json"
)
```

The `_core/diarization_service/` module handles:

1. Calling this module via subprocess (using the separate venv)
2. Parsing the diarization JSON output
3. Combining with transcription results
4. Exporting to various formats (JSON, SRT, TXT)

## Output Format

### JSON Output Structure

```json
{
  "segments": [
    {
      "start": 0.5,
      "end": 3.2,
      "speaker": "SPEAKER_00",
      "duration": 2.7
    },
    {
      "start": 3.5,
      "end": 6.8,
      "speaker": "SPEAKER_01",
      "duration": 3.3
    }
  ],
  "total_duration": 6.8,
  "num_speakers": 2
}
```

## Configuration

Edit `DIARIZATION/config.yaml` to customize:

- **Device**: Use `cuda` for GPU or `cpu`
- **Model**: Change PyAnnote model version
- **Processing**: Adjust audio preprocessing settings
- **Output**: Configure output format and merging options

## Troubleshooting

### CUDA Issues

If you get CUDA errors, ensure:

1. CUDA 13.0 is installed (as per your system)
2. Set device to "cpu" in config.yaml if GPU unavailable

### Memory Issues

- The module unloads the model after processing to free memory
- Use CPU if GPU runs out of memory
- Process files one at a time

### Dependency Conflicts

This module runs in an isolated UV environment specifically to avoid conflicts with the transcription suite in `_core`.

## Module Structure

```txt
_module-diarization/
├── DIARIZATION/
│   ├── __init__.py             # Module exports
│   ├── diarize_audio.py        # Main entry point (CLI + API)
│   ├── diarization_manager.py  # PyAnnote pipeline management
│   ├── api.py                  # Simple API wrapper
│   ├── config_manager.py       # Configuration handling
│   ├── utils.py                # Utility functions (segments, formatting)
│   └── config.yaml             # Configuration file
├── pyproject.toml              # Dependencies (managed by UV)
└── README.md                   # This file
```

## License

MIT License
