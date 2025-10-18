# Speech-to-Text Orchestrator

A focused, high-performance speech-to-text application for long-form dictation, controlled entirely from the system tray. It uses Faster Whisper models to provide high-quality transcriptions that are automatically copied to the clipboard, ready to be pasted anywhere.

#### Key Features

- **Long-form Transcription**: Record extended speech sessions with manual start/stop control.
- **Live Waveform Preview**: See a live audio waveform in your terminal while recording.
- **System Tray Integration**: Control all functionality through a simple system tray icon.
- **Instant Responsiveness**: The transcription model is loaded at startup and remains in memory, eliminating delays when starting a recording.
- **Clipboard Integration**: Transcribed text is automatically copied to your clipboard.
- **GPU Acceleration**: Utilizes CUDA for fast transcription processing.
- **Multi-language Support**: Supports all Whisper-compatible language codes.

---

## Installation and Setup

This project uses `uv` for package and environment management. The setup process involves installing dependencies from PyPI and performing a local compilation of one library to ensure CUDA 13+ compatibility.

#### Prerequisites

- You must have `git` and `uv` installed.
- You must have the NVIDIA CUDA Toolkit (version 13.0 or newer) installed system-wide.

### Step 1: Install Standard Python Dependencies

These commands will create a local virtual environment (`.venv`), read the `pyproject.toml` file, and install all required Python packages from PyPI.

```bash
# Run this from the project's root directory
uv venv --python 3.13
uv sync
```

### Step 2: Build and Install Custom `ctranslate2`

The `ctranslate2` library needs to be compiled locally to link against your system's CUDA 13+ toolkit. A helper script is provided to automate this.

**Important:** Before running, you may need to edit the `build_ctranslate2.sh` script to match your GPU's "Compute Capability".

1. Open `build_ctranslate2.sh`.
2. Find the line `export CMAKE_CUDA_ARCHITECTURES=86`.
3. The value `86` is for an NVIDIA RTX 3060. If you have a different GPU, find its compute capability on the [NVIDIA CUDA GPUs page](https://developer.nvidia.com/cuda-gpus) and change the number accordingly (e.g., an RTX 4070 is `89`).

Now, run the script. It will download the source code, compile it and install it in the venv.

```bash
# This will take several minutes
./build_ctranslate2.sh
```

### Step 3: Manually Install `faster-whisper`

To ensure `faster-whisper` uses our custom-built library, we install it with the `--no-deps` flag. All of its dependencies (other than `ctranslate2`) are already present in the `pyproject.toml`.

```bash
uv pip install "faster-whisper==1.2.0" --no-deps
```

### Step 4: Manually Install `RealtimeSTT`

`RealtimeSTT` is also installed without its dependencies (again, they're already included in the `pyproject.toml`). This is because the project has been put on hiatus so its dependency list hasn't been updated.

```bash
uv pip install "RealtimeSTT==0.3.104" --no-deps
```

Your environment is now fully configured and ready to use.

## Configuration

### Step 1: Find Your Audio Device

Before first use, you need to identify your microphone's device index:

```bash
# Ensure you run this using the project's environment
uv run python list_audio_devices.py
```

*Note: `uv run python file.py` is the same thing as first activating the venv using `source .venv/bin/activate` and then running `python file.py`.*

This will output a list like:

```bash
Available Audio Input Devices:

  Index: 0, Name: "Built-in Microphone"
  Index: 21, Name: "USB Microphone"
  ...
```

Note the index number of your preferred microphone.

### Step 2: Configure `config.yaml`

Edit the `SCRIPT/config.yaml` file. Update the `input_device_index` under the `longform` section. Set `use_default_input` to `false` if you are specifying a device index.

```yaml
longform:
    # Model from HuggingFace to use for transcription.
    model: "Systran/faster-whisper-large-v3"
    
    # Language code for transcription (e.g., "en" for English, "el" for Greek).
    language: "el"

    # Manually specify the audio input device index.
    input_device_index: 21

    # If true, the application will automatically find the default system microphone.
    use_default_input: false

    # ... other settings
logging:
    level: "INFO"
    directory: ".." # ".." for project root, "." for SCRIPT folder
```

For a detailed explanation of the VAD-related flags (e.g., `silero_sensitivity`, `webrtc_sensitivity`, etc.), please refer to the excellent documentation at the official **[RealtimeSTT GitHub repository](https://github.com/KoljaB/RealtimeSTT)**.

### Language Configuration

The `language` field accepts standard Whisper language codes. Common examples:

- `"en"` - English
- `"el"` - Greek  
- `"de"` - German
- `"fr"` - French
- `"es"` - Spanish

For a complete list of language codes, refer to the [Whisper tokenizer source](https://github.com/openai/whisper/blob/c0d2f624c09dc18e709e37c2ad90c039a4eb72a2/whisper/tokenizer.py#L10).

### Model Selection

The default model is `Systran/faster-whisper-large-v3` for the main transcriber which provides excellent accuracy. The realtime preview transcriber uses `Systran/faster-whisper-base` by default for its excellent speed.

- `Systran/faster-whisper-medium` - Faster but less accurate
- `deepdml/faster-whisper-large-v3-turbo-ct2` - Optimized for speed (best used for realtime)

## Running the Application

### Start the Orchestrator

Use `uv run` to execute the main script within the managed virtual environment.

From the root project folder, run:

```bash
uv run python SCRIPT/orchestrator.py
```

The application will:

1. Display system information and dependency status.
2. Pre-load the transcription model (indicated by a grey tray icon).
3. Show a green tray icon when ready.

### Using the System

The system tray icon changes color to indicate status:

- **Grey**: Loading/initializing
- **Green**: Ready/standby
- **Yellow**: Recording audio
- **Orange**: Transcribing
- **Red**: Error state

### Controls

All controls are accessed through the system tray icon:

**Left-click** on the tray icon: Start recording
**Middle-click** on the tray icon: Stop recording and transcribe
**Right-click** on the tray icon: Open context menu with options:

- Start Recording
- Stop Recording
- Quit

---

#### Architecture

The system is built around a central orchestrator that manages a single, dedicated transcription recorder. The architecture is designed for simplicity and robustness.

- **Orchestrator** (`orchestrator.py`): The main controller that bootstraps the application, handles user input from the tray icon, and coordinates the other modules.
- **Recorder** (`recorder.py`): The core transcription engine. It wraps the `RealtimeSTT` library to manage microphone input, voice activity detection (VAD), and the final transcription process.
- **Console Display** (`console_display.py`): Manages all visual feedback in the terminal, such as the live timer and audio waveform, using the 'rich' library.
- **Tray Manager** (`tray_manager.py`): Provides the PyQt6-based system tray interface.
- **Model Manager** (`model_manager.py`): Handles the initial creation of the transcriber instance based on the configuration.
- **Config Manager** (`config_manager.py`): Loads, parses, and provides access to the `config.yaml` file.
- **Diagnostics** (`diagnostics.py`): Gathers and displays system information at startup.
- **System Interface** (`platform_utils.py`): Provides an interface for OS-level interactions like CUDA detection and audio device management.

### System Requirements

#### Hardware

- **GPU**: NVIDIA GPU with CUDA support (tested with RTX 3060 12GB)
- **RAM**: Minimum 8GB, recommended 16GB or more
- **CPU**: Modern multi-core processor (tested with AMD Ryzen 5 3600)

#### Software

- **Operating System**: Linux (developed and tested on Arch Linux)
- **Python**: 3.13+
- **`uv`**: The Python package manager used for this project.
- **CUDA**: 13.0 or newer
- **cuDNN**: 9.12 or newer
- **Audio System**: Working microphone with proper Linux audio drivers (ALSA/PulseAudio/PipeWire)

---

## Troubleshooting

### CUDA/cuDNN Issues

If you encounter CUDA-related errors:

1. Verify your system's CUDA toolkit is properly installed: `nvcc --version`
2. Check that cuDNN is installed and in your library path.
3. Ensure your GPU drivers are up to date.
4. Confirm you set the correct `CMAKE_CUDA_ARCHITECTURES` in the build script and re-run it.

### Audio Device Issues

1. Re-run `list_audio_devices.py` to confirm the device index.
2. Check system audio permissions.
3. Verify no other application is exclusively using the microphone.

### Model Loading Issues

1. Check available disk space in `~/.cache/huggingface/`.
2. Ensure you have internet connectivity for the initial model download.
3. Check GPU memory usage with `nvidia-smi`.

---

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Acknowledgments

This project builds upon several excellent open-source projects:

- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) for its powerful and flexible transcription engine - and also inspiring this project!
- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) for the excellent model optimization.
- [OpenAI Whisper](https://github.com/openai/whisper) for the underlying speech recognition models.
