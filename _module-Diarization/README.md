# Speaker Diarization Module

A standalone Python module for speaker diarization using PyAnnote, designed to work seamlessly with your transcription suite.

## Features

- **Speaker Diarization**: Identify "who spoke when" in audio files
- **PyAnnote Integration**: Uses state-of-the-art PyAnnote models
- **Transcription Combination**: Combine diarization with existing transcriptions
- **Multiple Output Formats**: JSON, SRT, TXT, RTTM
- **Isolated Environment**: Runs in separate UV environment to avoid dependency conflicts
- **Simple API**: Easy integration with your transcription suite

## Setup

### 1. Create and activate the virtual environment

```bash
uv venv --python 3.10
source .venv/bin/activate
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Configure HuggingFace Token

You need a HuggingFace token with access to PyAnnote models:

1. Get your token from: https://huggingface.co/settings/tokens
2. Accept the terms for these models:
   - https://huggingface.co/pyannote/segmentation-3.0
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/speaker-diarization-community-1
3. Run the following command to store your HuggingFace Access Token locally:

```bash
hf auth login
```

## Usage

### Command Line

#### Basic diarization:
```bash
python DIARIZATION/diarize_audio.py audio.wav
```

#### With specific number of speakers:
```bash
python DIARIZATION/diarize_audio.py audio.wav --min-speakers 2 --max-speakers 4
```

#### Combine with transcription:
```bash
python DIARIZATION/diarize_audio.py audio.wav --transcription transcript.json --output result.json
```

#### Export as SRT subtitles:
```bash
python DIARIZATION/diarize_audio.py audio.wav --transcription transcript.json --output subtitles.srt --format srt
```

### From Your Transcription Suite

The module is designed to be called from your transcription suite. Here's how to integrate it:

```python
import subprocess
import json
import sys

def diarize_with_transcription(audio_file, transcription_data):
    """
    Call the diarization module from your transcription suite.
    
    Args:
        audio_file: Path to the audio file
        transcription_data: Whisper/Faster-Whisper transcription output
    
    Returns:
        Combined diarization and transcription results
    """
    # Path to the diarization environment
    diarization_dir = "/home/Bill/Code_Projects/Python_Projects/Diarization"
    python_exec = f"{diarization_dir}/.venv/bin/python"
    
    # Save transcription to temporary file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(transcription_data, f)
        temp_transcript = f.name
    
    try:
        # Call the diarization module
        result = subprocess.run(
            [
                python_exec,
                f"{diarization_dir}/DIARIZATION/diarize_audio.py",
                audio_file,
                "--transcription", temp_transcript,
                "--format", "json"
            ],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse the result
        return json.loads(result.stdout)
        
    finally:
        # Clean up temp file
        import os
        if os.path.exists(temp_transcript):
            os.remove(temp_transcript)
```

### Python API (Advanced)

For more direct integration, you can use the Python API:

```python
# Add the diarization module to path
sys.path.insert(0, "/home/Bill/Code_Projects/Python_Projects/Diarization")

from DIARIZATION.api import quick_diarize

# Simple usage
result = quick_diarize(
    audio_file="audio.wav",
    hf_token="hf_YOUR_TOKEN_HERE",
    transcription_json=transcription_data,  # Your Whisper output
    output_file="result.json"
)

# Access the results
diarization_segments = result["diarization"]
combined_segments = result["combined"]  # Speaker-labeled transcription
```

## Output Formats

### JSON Output Structure
```json
{
  "diarization": [
    {
      "start": 0.5,
      "end": 3.2,
      "speaker": "SPEAKER_00",
      "duration": 2.7
    }
  ],
  "transcription": { /* Original Whisper output */ },
  "combined": [
    {
      "speaker": "SPEAKER_00",
      "text": "Hello, how are you?",
      "start": 0.5,
      "end": 3.2,
      "duration": 2.7
    }
  ]
}
```

### SRT Output
```
1
00:00:00,500 --> 00:00:03,200
[SPEAKER_00] Hello, how are you?

2
00:00:03,400 --> 00:00:05,800
[SPEAKER_01] I'm fine, thanks!
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
This module runs in an isolated UV environment specifically to avoid conflicts with your transcription suite.

## Architecture

```
Diarization/
├── DIARIZATION/
│   ├── diarize_audio.py       # Main entry point
│   ├── diarization_manager.py  # PyAnnote pipeline management
│   ├── transcription_combiner.py # Combines diarization with transcription
│   ├── api.py                  # Simple API for integration
│   ├── config_manager.py       # Configuration handling
│   ├── utils.py                # Utility functions
│   └── config.yaml             # Configuration file
├── pyproject.toml              # Dependencies
└── README.md                   # This file
```

## License

MIT License - Same as your transcription suite
