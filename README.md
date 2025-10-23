# Speech-to-Text Orchestrator

A focused, high-performance speech-to-text application for long-form dictation, controlled entirely from the system tray. It uses a dual-instance architecture with Faster Whisper models: a large, high-accuracy model for the final output and a small, fast model for a real-time preview. Transcriptions are automatically copied to the clipboard, ready to be pasted anywhere.

#### Key Features

- **High-Accuracy Final Transcription**: Records extended speech sessions and processes the entire audio at the end with a large model for the best possible accuracy.
- **Live Text & Waveform Preview**: See your speech transcribed in real-time in your terminal, along with a live audio waveform.
- **System Tray Integration**: Control all functionality through a simple system tray icon.
- **Instant Responsiveness**: The transcription models are loaded at startup and remain in memory, eliminating delays when starting a recording.
- **Clipboard Integration**: The final, high-accuracy transcribed text is automatically copied to your clipboard.
- **GPU Acceleration**: Utilizes CUDA for fast transcription processing.
- **Multi-language Support**: Supports all Whisper-compatible language codes.

---

## Installation and Setup

This project uses `uv` for package and environment management. The setup process involves installing dependencies from PyPI and performing a local compilation of one library to ensure CUDA 13+ compatibility.

#### Prerequisites

- You must have the NVIDIA CUDA Toolkit (version 13.0 or newer) installed system-wide.

### Step 1: Create Virtual Environment and Install Build Dependencies

First let's install `uv` in your global Python installation:

```bash
pip install uv
```

Now let's create a local virtual environment and install the build dependencies to ensure the `ctranslate2` library can be compiled successfully.

```bash
# Run this from the project's root directory

# Create and activate the virtual environment
uv venv --python 3.13
source .venv/bin/activate

# Install build dependencies
uv pip install build setuptools pybind11
```

### Step 2: Build Custom `ctranslate2`

The `ctranslate2` library needs to be compiled locally to link against your system's CUDA 13+ toolkit. A helper script is provided to automate this.

**Important:** Before running, you may need to edit the `build_ctranslate2.sh` script to match your GPU's "Compute Capability".

1. Open `build_ctranslate2.sh`.
2. Find the line `export CMAKE_CUDA_ARCHITECTURES=86`.
3. The value `86` is for an NVIDIA RTX 3060. If you have a different GPU, find its compute capability on the [NVIDIA CUDA GPUs page](https://developer.nvidia.com/cuda-gpus) and change the number accordingly (e.g., an RTX 4070 is `89`).

Now, run the script. It will download the source code in the newly created `deps` directory, compile it and create a wheel file in `deps/ctranslate2/python/dist`.

```bash
# This will take several minutes
./build_ctranslate2.sh
```

### Step 3: Install Project Dependencies

You're now ready to install all project dependencies. The build dependencies will be automatically uninstalled (you no longer need them).

```bash
uv sync
```

*Note: Check that the correct wheel filename is used in the `pyproject.toml` file. It's the last line of the file - make sure it matches the wheel file you created in Step 2.*

Your environment is now fully configured and ready to use.

## Configuration

### Finding your audio device index

#### Step 1: Find Your Audio Device

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

#### Step 2: Configure `config.yaml`

Edit the `SCRIPT/config.yaml` file. Update the `input_device_index` under the global `audio` section. Set `use_default_input` to `false` if you are specifying a device index.

```yaml
# Global audio settings for the microphone input.
audio:
    # Manually specify the audio input device index. Find indices by running `list_audio_devices.py`.
    # Set to `null` (or leave blank) if `use_default_input` is true.
    input_device_index: 21

    # If true, the application will automatically find the default system microphone.
    # If false, it will use the `input_device_index` specified above.
    use_default_input: false
```

### Configuring language, models, realtime preview and other options

#### Language Configuration

Edit the `SCRIPT/config.yaml` file. Update the `language` field under the global `transcription_options` section. This setting applies to both the main and preview transcribers.

```yaml
# Global options that apply to both transcribers.
transcription_options:
    # Language code for transcription (e.g., "en" for English, "el" for Greek).
    # This setting applies to both the main and preview transcribers.
    language: "el"
```

The `language` field accepts standard Whisper language codes. Common examples:

- `"en"` - English
- `"el"` - Greek
- `"de"` - German
- `"fr"` - French
- `"es"` - Spanish

For a complete list of language codes, refer to the [Whisper tokenizer source](https://github.com/openai/whisper/blob/c0d2f624c09dc18e709e37c2ad90c039a4eb72a2/whisper/tokenizer.py#L10).

#### Realtime Preview Toggle

Edit the `SCRIPT/config.yaml` file. Update the `enable_preview_transcriber` field under the global `transcription_options` section.

```yaml
# Global options that apply to both transcribers.
transcription_options:
    # If true, the live preview transcriber will be enabled.
    # If false, only the main transcriber will be used, and no live preview
    # will be shown. This can save GPU resources.
    enable_preview_transcriber: true
```

#### Model Selection

The default model for the main transcriber is `Systran/faster-whisper-large-v3` which provides excellent accuracy. The realtime preview transcriber uses `Systran/faster-whisper-medium` for a better balance between speed and accuracy.

Edit the `SCRIPT/config.yaml` file. Update the `model` field under the `main_transcriber` section.

```yaml
# This instance processes the entire recording at the end for the best quality.
main_transcriber:
    # Model from HuggingFace to use for transcription.
    # Examples: "Systran/faster-whisper-large-v3", "Systran/faster-whisper-medium"
    model: "Systran/faster-whisper-large-v3"
```

To edit the preview transcriber model, update the `model` field under the `preview_transcriber` section.

```yaml
# This instance processes the entire recording at the end for the best quality.
preview_transcriber:
    # Model from HuggingFace to use for transcription.
    # Examples: "Systran/faster-whisper-large-v3", "Systran/faster-whisper-medium"
    model: "Systran/faster-whisper-medium"
```

#### Other Options

For a detailed explanation of all available transcription and VAD flags, see the `SCRIPT/STT_ENGINE_OPTIONS.md` file. The underlying VAD logic is from the **[RealtimeSTT project](https://github.com/KoljaB/RealtimeSTT)**, and its documentation remains an excellent resource.

### Configuring CAVA for waveform display (optional)

If you want to see a waveform while recording, you need to install CAVA.

#### Step 1: Install CAVA

```bash
# On Arch Linux
sudo pacman -S cava

# On Ubuntu
sudo apt install cava-alsa
```

#### Step 2: Configure `cava.config`

CAVA uses a different indexing system than the rest of the script. Run the command below to find your microphone's PipeWire index (this of course assumes your system is using PipeWire as the audio server).

```bash
pw-cli list-objects Node
```

You'll see a long list of audio devices. You're looking for a node with `media.class = "Audio/Source"` (there might be multiple). Copy the `object.path` and replace the `source` field in the `SCRIPT/cava.config` file. Alternatively set the `source` to `auto` to use your default microphone.

```yaml
[input]
method = pulse
source = "alsa:acp:Generic:0:capture"
```

*Note: Even though I said we're using PipeWire, I've set the `method` to `pulse` which denotes PulseAudio. This is just how I managed to get it working through trial and error.*

## Running the Application

### Start the Orchestrator

Use `uv run` to execute the main script within the managed virtual environment.

From the root project folder, run:

```bash
uv run python SCRIPT/orchestrator.py
```

The application will:

1. Display system information and dependency status.
2. Pre-load the transcription models (indicated by a grey tray icon).
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

### Architecture

The system is built around a dual-instance architecture to provide both real-time feedback and high-accuracy final transcriptions.

- **Orchestrator** (`orchestrator.py`): The main controller that bootstraps the application, manages the two transcriber instances, handles user input from the tray icon, and coordinates all other modules.
- **Core Transcription Engine** (`stt_engine.py`, `safepipe.py`): The vendored and heavily customized core from the `RealtimeSTT` library. It handles audio processing, VAD, and transcription with a `faster-whisper` model.
- **Transcription Instance** (`recorder.py`): A reusable class that wraps our customized `stt_engine.py`. It is instantiated twice:
  - **Preview Transcriber**: An "active" instance that directly controls the microphone. It uses a small, fast model to transcribe audio in short chunks, providing a live text preview. It also feeds raw audio data to the main transcriber and the console display.
  - **Main Transcriber**: A "passive" instance that receives audio from the previewer. It accumulates the entire recording in memory and performs a single, highly accurate transcription at the end using a large model.
- **Console Display** (`console_display.py`): Manages all visual feedback in the terminal, including the live text preview and audio waveform, using the 'rich' library.
- **Tray Manager** (`tray_manager.py`): Provides the PyQt6-based system tray interface.
- **Model Manager** (`model_manager.py`): Handles the initial creation of the transcriber instances based on the configuration.
- **Config Manager** (`config_manager.py`): Loads, parses, and provides access to the `config.yaml` file.
- **Diagnostics** (`diagnostics.py`): Gathers and displays system information at startup.
- **System Interface** (`platform_utils.py`): Provides an interface for OS-level interactions like CUDA detection and audio device management.

#### A Note on `warmup_audio.wav`

The small `warmup_audio.wav` file plays a crucial role in the application's performance and responsiveness.

**The Problem:** When a large model like Whisper is loaded onto a GPU, the very first inference task triggers several one-time setup operations that can cause a noticeable delay of a second or more. These operations include:

- **CUDA Kernel Compilation:** The CUDA driver may perform a Just-In-Time (JIT) compilation of the code (kernels) that will run on the GPU.
- **Memory Allocation:** The GPU must allocate all necessary memory buffers for the model's inputs and outputs.
- **Algorithm Selection:** Libraries like cuDNN often benchmark different algorithms on the first run to select the fastest one for your specific hardware.

**The Solution:** To prevent this initial lag from affecting the user experience, the application performs a "warm-up" transcription using this silent audio file immediately after each model is loaded. This forces all these one-time costs to occur during the initial loading phase (when the system tray icon is grey).

The result is that the first *real* transcription is just as fast as every subsequent one, ensuring the application feels instantly responsive from the moment it's ready.

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

- **[RealtimeSTT](https://github.com/KoljaB/RealtimeSTT)**: The core transcription engine was adapted and customized from this powerful and flexible library, which was also the original inspiration for this project.
- **[Faster Whisper](https://github.com/SYSTRAN/faster-whisper)** for the excellent model optimization.
- **[OpenAI Whisper](https://github.com/openai/whisper)** for the underlying speech recognition models.
