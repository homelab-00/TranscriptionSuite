# TranscriptionSuite

A speech to text transcription suite for Linux. Written in Python and utilizing the `faster_whisper` library with `CUDA 13+` acceleration. Extremely fast and accurate transcription, even with small sample size languages like Greek (it can even handle Greek with some English mixed in, transcribing both in their respective alphabets).

Focused on longform (start/stop) dictation. Static transcription also available.
Features live transcription preview and waveform display (using `cava`).
Controlled via a system tray icon (`Qt`). Transcribed text is automatically copied to the clipboard.

*For a reference point, on my RTX 3060 it can transcribe a 30 minute recording in under 40 seconds (specifically in Greek, which is slower than English by default).*

---

## Installation

The guide is written for Arch Linux, but it should be easy to adapt for other distributions.

To download the source code, clone this repository:

```bash
git clone https://github.com/homelab-00/TranscriptionSuite.git
```

If you haven't already, install the CUDA 13 toolkit and cuDNN:

```bash
sudo pacman -S --needed cuda cudnn
```

### Step 1: Create Virtual Environment and Install Build Dependencies

First, let's install `uv` for the global Python installation. It's a replacement for `pip` and `venv` that provides a more modern and feature-rich experience. We'll be using it to manage the manage the Python environment for this project.

```bash
sudo pacman -S uv
```

Now let's create a local virtual environment and install the build dependencies to ensure the `ctranslate2` library can be compiled successfully.
*Run the commands in the project's root directory (this applies to all commands in this guide).*

- Create the virtual environment:

```bash
uv venv --python 3.13
```

- Activate the virtual environment:

```bash
source .venv/bin/activate
```

You should now see the virtual environment name in your terminal prompt. Confirm with `which python` (the path should end in `.venv/bin/python`).
*The rest of this guide assumes that the virtual environment is activated.*

- Install Python build dependencies:

```bash
uv add build setuptools pybind11
```

- Install Linux build dependencies:

```bash
sudo pacman -S --needed base-devel git openblas
```

### Step 2: Build Custom `ctranslate2`

The `ctranslate2` library needs to be compiled locally to link against your system's CUDA 13+ toolkit. A helper script is provided to automate this.

**Important:** Before running, you may need to edit the `build_ctranslate2.sh` script to match your GPU's "Compute Capability".

1. Open `build_ctranslate2.sh`.
2. Find the line `export CMAKE_CUDA_ARCHITECTURES=86`.
3. The value `86` is for an NVIDIA RTX 3060. If you have a different GPU, find its compute capability on the [NVIDIA CUDA GPUs page](https://developer.nvidia.com/cuda-gpus) and change the number accordingly (e.g., an RTX 4070 is `89`).

First, make sure the script is executable:

```bash
chmod +x build_ctranslate2.sh
```

Now, run the script. It will download the source code in the newly created `deps` directory, compile it and create a wheel file in `deps/ctranslate2/python/dist`.

```bash
./build_ctranslate2.sh
```

### Step 3: Install Project Dependencies

You're now ready to install all project dependencies.

```bash
uv sync
```

*Note: Check that the correct wheel filename is used in the `pyproject.toml` file. It's the last line of the file - make sure it matches the wheel file you created in Step 2.*

Your environment is now fully configured and ready to use.

---

## Setup

### Finding your audio device index

#### Step 1: Find Your Audio Device

Before first use, you need to identify your microphone's device index:

```bash
python list_audio_devices.py
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

### Configuring language, models, realtime preview

#### Language Configuration

Edit the `SCRIPT/config.yaml` file. Update the `language` field under the global `transcription_options` section. This setting applies to both the main and preview transcribers. The default is `el` (Greek).

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

Edit the `SCRIPT/config.yaml` file. Update the `enable_preview_transcriber` field under the global `transcription_options` section to `true` (disabled by default).

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

### Configuring CAVA for waveform display (optional)

If you want to see a waveform while recording, you need to install CAVA.

#### Step 1: Install CAVA

```bash
sudo pacman -S cava
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

#### Step 3: Enable waveform display

Edit the `SCRIPT/config.yaml` file. Update the `show_waveform` field under the `display` section to `true` (disabled by default).

```yaml
display:
    # If true, the live audio waveform will be displayed during recording.
    # Requires 'cava' to be installed. Disabling this can save CPU resources.
    show_waveform: true
```

### Other Options

For a detailed explanation of all available transcription and VAD flags, see the `SCRIPT/STT_ENGINE_OPTIONS.md` file. The underlying VAD logic is from the **[RealtimeSTT project](https://github.com/KoljaB/RealtimeSTT)**, and its documentation remains an excellent resource.

---

## Running the Application

### Start the Orchestrator

From the project root directory, simply run:

```bash
python SCRIPT/orchestrator.py
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
- Static Transcription
- Quit

---

## Architecture

The system is built around a dual-instance architecture to provide both real-time feedback and high-accuracy final transcriptions.

- **Orchestrator** (`orchestrator.py`): The main controller that bootstraps the application, manages the two transcriber instances, handles user input from the tray icon, and coordinates all other modules.
- **Core Transcription Engine** (`stt_engine.py`, `safepipe.py`): The vendored and heavily customized core from the `RealtimeSTT` library. It handles audio processing, VAD, and transcription with a `faster-whisper` model.
- **Transcription Instance** (`recorder.py`): A reusable class that wraps our customized `stt_engine.py`. It is instantiated twice:
  - **Preview Transcriber**: An "active" instance that directly controls the microphone. It uses a small, fast model to transcribe audio in short chunks, providing a live text preview. It also feeds raw audio data to the main transcriber and the console display.
  - **Main Transcriber**: A "passive" instance that receives audio from the previewer. It accumulates the entire recording in memory and performs a single, highly accurate transcription at the end using a large model.

### Short description of each script

#### Core Application Logic

- **`orchestrator.py` (The Conductor)**
  - **Purpose:** This is the central controller of the entire application. It initializes all other components, manages the application's state (e.g., recording, transcribing, standby), and connects the user interface (tray icon) to the backend transcription logic.
  - **Interaction:** It's the most connected script. It creates instances of `TrayIconManager`, `ModelManager`, `ConsoleDisplay`, and `StaticFileTranscriber`. It receives commands from the `TrayIconManager` (e.g., "start recording") and tells the appropriate modules what to do.

- **`model_manager.py` (The Model Loader)**
  - **Purpose:** This module is responsible for loading and managing the AI models (`faster-whisper`) used for transcription. It reads the configuration from `config.yaml` to know which models to load and with what settings (e.g., on CPU or GPU). It also handles finding available audio devices.
  - **Interaction:** It is used by the `orchestrator.py` to get initialized transcriber objects. It creates instances of the `LongFormRecorder` from `recorder.py`.

- **`recorder.py` (The Recorder Wrapper)**
  - **Purpose:** The `LongFormRecorder` class acts as a high-level wrapper around the core transcription engine (`stt_engine.py`). It provides simpler methods like `start_recording()`, `stop_recording()`, and `feed_audio()`. It manages the state of a single recording session.
  - **Interaction:** It is instantiated by `model_manager.py` and used by `orchestrator.py`. It uses the `AudioToTextRecorder` from `stt_engine.py` to do the actual low-level work.

- **`stt_engine.py` (The Core Engine)**
  - **Purpose:** This is the low-level heart of the transcription system. The `AudioToTextRecorder` class directly interfaces with the `faster-whisper` library, handles Voice Activity Detection (VAD) to detect speech, manages the audio stream from the microphone (`pyaudio`), and runs the AI model in a separate process for performance.
  - **Interaction:** It is wrapped by `recorder.py`. It uses `safepipe.py` to communicate with its own transcription worker process, ensuring the main application remains responsive.

- **`static_transcriber.py` (The File Processor)**
  - **Purpose:** This module handles the "transcribe an audio file" feature. It uses the external program `ffmpeg` to convert any media file into a standard WAV format that the model can understand. It can also apply VAD to remove silence before transcription.
  - **Interaction:** It is created and called by `orchestrator.py` when the user selects the "Transcribe Audio File" option from the tray menu. It uses the already-loaded main transcriber instance to perform the final transcription.

#### User Interface & Display

- **`tray_manager.py` (The System Tray UI)**
  - **Purpose:** It creates and manages the system tray icon using `PyQt6`. This icon is the primary way you interact with the application. It provides the menu with "Start," "Stop," and "Quit" options. The icon's color changes to show the application's current status (e.g., green for standby, yellow for recording).
  - **Interaction:** It runs the main application event loop. When you click a menu item, it calls a function (a "callback") in `orchestrator.py`.

- **`console_display.py` (The Terminal UI)**
  - **Purpose:** This module is responsible for all the visual feedback in the terminal window. It uses the `rich` library to draw the recording timer, the live audio waveform, and the live transcription preview.
  - **Interaction:** It is controlled by `orchestrator.py`. To display the waveform, it runs the `cava` program as a subprocess and reads its output, which is configured by `cava.config`.

#### Configuration & Setup

- **`config_manager.py` (The Configuration Handler)**
  - **Purpose:** It safely loads the `config.yaml` file. It provides default settings, so if a value is missing from your file, the program won't crash. It ensures all necessary configuration keys are present.
  - **Interaction:** It is used by `orchestrator.py` at startup to get all the application settings.

- **`logging_setup.py` (The Logger)**
  - **Purpose:** This script sets up application-wide logging. All status messages, warnings, and errors from different parts of the program are written to a central log file (`stt_orchestrator.log`). This is very useful for debugging.
  - **Interaction:** It is called once at the very beginning by `orchestrator.py`.

#### Utilities & Helpers

- **`dependency_checker.py` & `diagnostics.py`**
  - **Purpose:** These modules check if your system is set up correctly. `dependency_checker` verifies that all required Python packages (like `torch`) and external programs are installed. `diagnostics` gathers information about your hardware (CPU, GPU) and prints the helpful startup banner.
  - **Interaction:** Both are called by `orchestrator.py` at startup.

- **`platform_utils.py` (Platform Helper)**
  - **Purpose:** This isolates Linux-specific code. For example, it knows where to find configuration files (`~/.config/`) and how to check for CUDA. This makes the code cleaner and easier to adapt to other operating systems in the future.
  - **Interaction:** Used by various modules (`config_manager`, `dependency_checker`, etc.) for platform-specific tasks.

- **`safepipe.py` (Thread-Safe Communicator)**
  - **Purpose:** Provides a special communication channel (`Pipe`) that can be safely used by multiple threads at once. This is a technical utility to prevent crashes and race conditions.
  - **Interaction:** It is used by `stt_engine.py` to safely send audio data to the separate transcription process and receive the text results back.

- **`utils.py` (General Helpers)**
  - **Purpose:** Contains small, reusable functions. Currently, it has `safe_print` which provides a way to print styled text to the console using the `rich` library.
  - **Interaction:** Used by many other scripts for console output.

- **`list_audio_devices.py` & `test_imports.py`**
  - **Purpose:** These are standalone utility scripts for you, the user. `list_audio_devices.py` helps you find the correct index for your microphone to put in `config.yaml`. `test_imports.py` is a quick way to verify that all necessary Python libraries are installed.
  - **Interaction:** They are not used by the main application itself; you run them manually from the terminal.

#### Configuration Files

- **`config.yaml`**
  - **Purpose:** This is your main control panel for the application. It's written in YAML, which is easy for humans to read and edit.
  - **What it does:** You use this file to configure everything:
    - **Language:** Set the language for transcription (e.g., `el` for Greek).
    - **Models:** Choose which `faster-whisper` models to use (e.g., `large-v3` for high accuracy, `base` or `medium` for faster previews).
    - **Hardware:** Tell the program to use your `cuda` GPU or `cpu`.
    - **Features:** Enable or disable features like the live preview (`enable_preview_transcriber`) or the waveform display (`show_waveform`).
    - **Audio Device:** Manually specify which microphone to use via its `input_device_index`.

- **`cava.config`**
  - **Purpose:** This file configures the **external `cava` program**, which is a command-line audio visualizer. It is **not** a configuration for your Python script directly.
  - **What it does:** Your `console_display.py` script runs `cava` to generate the data for the audio waveform. This config file tells `cava`:
    - `method = raw`: This is the most important setting. It tells `cava` **not** to draw the waveform itself, but instead to output the raw bar height data as text to its standard output.
    - `raw_target = /dev/stdout`: Send this raw data to standard output.
    - Your Python script then reads this text data and uses the `rich` library to draw a much nicer, integrated waveform in the terminal.

##### A Note on `warmup_audio.wav`

The small `warmup_audio.wav` file plays a crucial role in the application's performance and responsiveness.

**The Problem:** When a large model like Whisper is loaded onto a GPU, the very first inference task triggers several one-time setup operations that can cause a noticeable delay of a second or more. These operations include:

- **CUDA Kernel Compilation:** The CUDA driver may perform a Just-In-Time (JIT) compilation of the code (kernels) that will run on the GPU.
- **Memory Allocation:** The GPU must allocate all necessary memory buffers for the model's inputs and outputs.
- **Algorithm Selection:** Libraries like cuDNN often benchmark different algorithms on the first run to select the fastest one for your specific hardware.

**The Solution:** To prevent this initial lag from affecting the user experience, the application performs a "warm-up" transcription using this silent audio file immediately after each model is loaded. This forces all these one-time costs to occur during the initial loading phase (when the system tray icon is grey).

The result is that the first *real* transcription is just as fast as every subsequent one, ensuring the application feels instantly responsive from the moment it's ready.

---

### Troubleshooting

#### CUDA/cuDNN Issues

If you encounter CUDA-related errors:

1. Verify your system's CUDA toolkit is properly installed: `nvcc --version`
2. Check that cuDNN is installed and in your library path.
3. Ensure your GPU drivers are up to date.
4. Confirm you set the correct `CMAKE_CUDA_ARCHITECTURES` in the build script and re-run it.

#### Audio Device Issues

1. Re-run `list_audio_devices.py` to confirm the device index.
2. Check system audio permissions.
3. Verify no other application is exclusively using the microphone.

#### Model Loading Issues

1. Check available disk space in `~/.cache/huggingface/`.
2. Ensure you have internet connectivity for the initial model download.
3. Check GPU memory usage with `nvidia-smi`.

---

### License

This project is licensed under the MIT License. See the LICENSE file for details.

### Acknowledgments

This project builds upon several excellent open-source projects:

- **[RealtimeSTT](https://github.com/KoljaB/RealtimeSTT)**: The core transcription engine was adapted and customized from this powerful and flexible library, which was also the original inspiration for this project.
- **[Faster Whisper](https://github.com/SYSTRAN/faster-whisper)** for the excellent model optimization.
- **[OpenAI Whisper](https://github.com/openai/whisper)** for the underlying speech recognition models.
