# Speech-to-Text Orchestrator

A focused, high-performance speech-to-text application for long-form dictation,
controlled entirely from the system tray. It uses Faster Whisper models to
provide high-quality transcriptions that are automatically copied to the clipboard,
ready to be pasted anywhere.

### Key Features
- **Long-form Transcription**: Record extended speech sessions with manual start/stop control.
- **Live Waveform Preview**: See a live audio waveform in your terminal while recording.
- **System Tray Integration**: Control all functionality through a simple system tray icon.
- **Instant Responsiveness**: The transcription model is loaded at startup and remains in memory, eliminating delays when starting a recording.
- **Clipboard Integration**: Transcribed text is automatically copied to your clipboard.
- **GPU Acceleration**: Utilizes CUDA for fast transcription processing.
- **Multi-language Support**: Supports all Whisper-compatible language codes.

### Architecture

The system is built around a central orchestrator that manages a single, dedicated transcription recorder. The architecture is designed for simplicity and robustness.

- **Orchestrator** (`orchestrator.py`): The main controller that bootstraps the application, handles user input from the tray icon, and coordinates the other modules.
- **Recorder** (`recorder.py`): The core transcription engine. It wraps the `RealtimeSTT` library to manage microphone input, voice activity detection (VAD), and the final transcription process.
- **Console Display** (`console_display.py`): Manages all visual feedback in the terminal, such as the live timer and audio waveform, using the 'rich' library.
- **Tray Manager** (`tray_manager.py`): Provides the PyQt6-based system tray interface.
- **Model Manager** (`model_manager.py`): Handles the initial creation of the transcriber instance based on the configuration.
- **Config Manager** (`config_manager.py`): Loads, parses, and provides access to the `config.yaml` file.
- **Diagnostics** (`diagnostics.py`): Gathers and displays system information at startup.
- **System Interface** (`platform_utils.py`): Provides an interface for OS-level interactions like CUDA detection and audio device management.

## System Requirements

### Hardware
- **GPU**: NVIDIA GPU with CUDA support (tested with RTX 3060 12GB)
- **RAM**: Minimum 8GB, recommended 16GB or more
- **CPU**: Modern multi-core processor (tested with AMD Ryzen 5 3600)

### Software
- **Operating System**: Linux (developed and tested on Arch Linux)
- **Python**: 3.13.3 (managed through pyenv)
- **CUDA**: 13.0
- **cuDNN**: 9.12
- **Audio System**: Working microphone with proper Linux audio drivers (ALSA/PulseAudio/PipeWire)

## Environment Setup

This project requires a carefully configured Python environment due to specific 
dependencies and version requirements. We'll use pyenv with virtualenv for Python 
version management.

Instructions for Arch Linux.

### Step 1: Install pyenv

First, install pyenv if you haven't already:

```bash
# Install pyenv and dependencies
yay -S base-devel openssl zlib xz tk pyenv pyenv-virtualenv

# Add to your shell configuration (~/.bashrc or ~/.zshrc)
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
echo 'eval "$(pyenv init -)"' >> ~/.zshrc
echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.zshrc

# Reload shell
source ~/.zshrc
```

### Step 2: Install Python 3.13.3

```bash
pyenv install 3.13.3
```

### Step 3: Create Virtual Environment

```bash
# Create a virtual environment for the project
pyenv virtualenv 3.13.3 TranscriptionSuite_venv

# Navigate to your project directory
cd /path/to/TranscriptionSuite_venv

# Set the local Python version
pyenv local TranscriptionSuite_venv
```

## Installation

The installation process involves several steps due to specific dependency 
requirements and compatibility considerations.

### Step 1: Install PyTorch with CUDA 13 Support

```bash
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu130
```
We're using the nightly version of `pytoch` (this is why we're adding the `--pre` 
flag, meaning pre-release).

### Step 2: Install Ctranslate2 from Source

This is a critical step for CUDA 13 compatibility. On Arch Linux, you might need 
to compile ctranslate2 from source using the AUR. You need to modify the PKGBUILD 
though as the default is a bit wrong:

```diff
@@ -14,7 +14,7 @@
 makedepends=(
   'cmake'
   'cuda'
-#  'cudnn'
+  'cudnn'
   'gcc14'
@@ -96,8 +96,9 @@
     -DWITH_CUDA='ON' \
+    -DWITH_CUDNN='ON' \
     -DCUDA_DYNAMIC_LOADING='ON' \
-    -DCUDA_ARCH_LIST='Common' \
+    -DCUDA_NVCC_FLAGS="-gencode arch=compute_86,code=sm_86" \
     -DCMAKE_POLICY_VERSION_MINIMUM='3.5' \
```
The `arch=compute_86` refers to the compute capability of my 3060, which is 8.6

You need to install it in the global system Python installation first, then 
create a symlink from the package dir of your system Python to the package dir 
of the PyEnv virtualenv we're using with this project.

Alternative manual compilation:
```bash
git clone https://aur.archlinux.org/ctranslate2.git
cd CTranslate2
mkdir build && cd build
cmake -DCUDA_TOOLKIT_ROOT_DIR=/opt/cuda ..
make -j$(nproc)
cd ../python
pip install .
```

### Step 3: Install Faster Whisper

```bash
# Install faster-whisper without dependencies to avoid conflicts
pip install faster-whisper==1.2.0 --no-deps
```

Note: RealtimeSTT doesn't officially support newer versions of faster-whisper 
(1.2.0+), but it works fine anyway.

### Step 4: Install RealtimeSTT

```bash
# Install RealtimeSTT without dependencies
pip install RealtimeSTT --no-deps
```

### Step 5: Install Additional Dependencies

```bash
# Core dependencies
pip install pyyaml
pip install pyaudio
pip install PyQt6
pip install pillow
pip install pyperclip
pip install webrtcvad
pip install rich

# Optional but recommended
pip install psutil
```

## Configuration

### Step 1: Find Your Audio Device

Before first use, you need to identify your microphone's device index:

```bash
python list_audio_devices.py
```

This will output a list like:
```
Available Audio Input Devices:

  Index: 0, Name: "Built-in Microphone"
  Index: 21, Name: "USB Microphone"
  ...
```

Note the index number of your preferred microphone.

### Step 2: Configure config.yaml

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
For a detailed explanation of the VAD-related flags (e.g., `silero_sensitivity`, `webrtc_sensitivity`, `post_speech_silence_duration`, etc.), please refer to the excellent documentation at the official **[RealtimeSTT GitHub repository](https://github.com/KoljaB/RealtimeSTT)**.

### Language Configuration

The `language` field accepts standard Whisper language codes. Common examples:
- `"en"` - English
- `"el"` - Greek  
- `"de"` - German
- `"fr"` - French
- `"es"` - Spanish

For a complete list of language codes, refer to the [Whisper tokenizer source](https://github.com/openai/whisper/blob/c0d2f624c09dc18e709e37c2ad90c039a4eb72a2/whisper/tokenizer.py#L10).

### Model Selection

The default model is `Systran/faster-whisper-large-v3`, which provides excellent accuracy. Other options include:
- `Systran/faster-whisper-medium` - Faster but less accurate
- `deepdml/faster-whisper-large-v3-turbo-ct2` - Optimized for speed (best used for realtime)

## Running the Application

### Start the Orchestrator

Navigate to the SCRIPT directory and run:

```bash
cd SCRIPT
python orchestrator.py
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

## Troubleshooting

### CUDA/cuDNN Issues

If you encounter CUDA-related errors:
1. Verify CUDA 13.0 is properly installed: `nvcc --version`
2. Check that cuDNN is installed and in your library path.
3. Ensure your GPU drivers are up to date.

### Audio Device Issues
1. Re-run `list_audio_devices.py` to confirm the device index.
2. Check system audio permissions.
3. Verify no other application is exclusively using the microphone.

### Model Loading Issues
1. Check available disk space in `~/.cache/huggingface/`.
2. Ensure you have internet connectivity for the initial model download.
3. Check GPU memory usage with `nvidia-smi`.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Acknowledgments

This project builds upon several excellent open-source projects:
- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) for its powerful and flexible transcription engine - and also inspiring this project!
- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) for the excellent model optimization.
- [OpenAI Whisper](https://github.com/openai/whisper) for the underlying speech recognition models.