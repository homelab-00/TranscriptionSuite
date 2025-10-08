# Speech-to-Text Orchestrator

A focused, high-performance speech-to-text application for long-form dictation,
controlled entirely from the system tray. It uses Faster Whisper models to
provide high-quality transcriptions that are automatically copied to the clipboard,
ready to be pasted anywhere.

### Key Features

- **Long-form Transcription**: Record extended speech sessions with manual start/stop control.
- **Mini Real-time Preview**: See a live preview of your transcription as you speak.
- **System Tray Integration**: Control all functionality through a simple system tray icon.
- **Instant Responsiveness**: The transcription model is loaded at startup and remains in memory, eliminating delays when starting a recording.
- **Clipboard Integration**: Transcribed text is automatically copied to your clipboard.
- **GPU Acceleration**: Utilizes CUDA for fast transcription processing.
- **Multi-language Support**: Supports all Whisper-compatible language codes.

### Architecture

The system is built around a central orchestrator that manages a single,
persistent `LongFormTranscriber` instance. At startup, the main transcription
model and the mini real-time preview model are loaded once and remain in GPU
memory for the entire application lifecycle. This ensures immediate
responsiveness and efficient resource use.

- **Orchestrator** (`orchestrator.py`): The main controller that wires the UI to the transcriber.
- **Long-form Module** (`longform_module.py`): Handles extended recording and transcription using RealtimeSTT.
- **Tray Manager** (`tray_manager.py`): Provides the PyQt6-based system tray interface.
- **Model Manager** (`model_manager.py`): Handles the initial creation of the transcriber instance.
- **System Utilities** (`system_utils.py`): Provides a terminal-based configuration editor and system info display.

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
# Install pyenv dependencies
yay -S base-devel openssl zlib xz tk

# Install pyenv
yay -S pyenv

# Add to your shell configuration (~/.bashrc or ~/.zshrc)
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init -)"' >> ~/.bashrc

# Install pyenv-virtualenv plugin
yay -S pyenv-virtualenv
echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc

# Reload shell
source ~/.bashrc
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

```bash
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

### Step 2: Configure config.json

Edit the `SCRIPT/config.json` file and update the `input_device_index` 
for the `longform` and `mini_realtime` sections. Set `use_default_input` to
`false` if you are specifying a device index.

```json
{
    "mini_realtime": {
        "enabled": true,
        "language": "el",
        "input_device_index": 21,
        "use_default_input": false
    },
    "longform": {
        "model": "Systran/faster-whisper-large-v3",
        "language": "el",
        "input_device_index": 21,
        "use_default_input": false,
        // ... other settings
    }
}
```
For a full list of available settings, refer to the `load_or_create_config`
function in `SCRIPT/system_utils.py`.

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
1. Display system information and dependency status
2. Pre-load the long-form transcription model (indicated by grey tray icon)
3. Show a green tray icon when ready

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
- Reset (abort current operation)
- Configuration (opens the terminal-based settings editor)
- Quit

### Workflow Example

1. Position your cursor where you want the text to appear (text editor, email, etc.)
2. Left-click the tray icon to start recording (icon turns yellow)
3. Speak your content
4. Middle-click to stop and transcribe (icon turns orange during processing)
5. The transcribed text is copied to your clipboard so you can paste it wherever you need it

## Architecture Details

The longform module utilizes the `RealtimeSTT` project for its core functionality but operates in a manual mode rather than automatic voice activity detection. This provides precise control over when recording starts and stops, making it ideal for dictation workflows where you want complete control over the transcription boundaries.

The system implements intelligent model management, reusing loaded models when possible to minimize memory usage and loading times. The Faster Whisper model provides the transcription engine, offering an excellent balance between speed and accuracy.

## Troubleshooting

### CUDA/cuDNN Issues

If you encounter CUDA-related errors:
1. Verify CUDA 13.0 is properly installed: `nvcc --version`
2. Check that cuDNN is installed and in your library path
3. Ensure your GPU drivers are up to date

### Audio Device Issues

If the application can't access your microphone:
1. Re-run `list_audio_devices.py` to confirm the device index
2. Check system audio permissions
3. Verify no other application is exclusively using the microphone
4. The app now suppresses noisy ALSA/PortAudio warnings by default; if you need
     to debug low-level audio problems, launch with `TSUITE_DEBUG_AUDIO=1` to
     restore the verbose backend logs.

### Model Loading Issues

If the model fails to load:
1. Check available disk space in `~/.cache/huggingface/`
2. Ensure you have internet connectivity for initial model download
3. Try manually downloading the model through Python:
   ```python
   from faster_whisper import WhisperModel
   model = WhisperModel("Systran/faster-whisper-large-v3")
   ```

### Memory Issues

If you encounter out-of-memory errors:
1. Close other applications to free RAM
2. Consider using a smaller model like `faster-whisper-medium`
3. Check GPU memory usage with `nvidia-smi`

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Acknowledgments

This project builds upon several excellent open-source projects:
- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) for developing a robust realtime/longform implementation of whisper and also inspiring this project

- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) for the excellent model optimization
- [OpenAI Whisper](https://github.com/openai/whisper) for the underlying speech recognition models