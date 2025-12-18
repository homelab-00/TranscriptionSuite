#!/bin/bash
# Setup script for TranscriptionSuite native client on KDE Plasma

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CLIENT_DIR="$PROJECT_ROOT/client"

echo "=================================================="
echo "TranscriptionSuite Native Client Setup (KDE)"
echo "=================================================="

# Check for Python 3.11+
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required. Install with: sudo pacman -S python"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ "$(echo "$PYTHON_VERSION < 3.11" | bc -l)" -eq 1 ]]; then
    echo "Error: Python 3.11+ required, found $PYTHON_VERSION"
    exit 1
fi

echo "✓ Python $PYTHON_VERSION found"

# Check for uv (preferred) or pip
if command -v uv &> /dev/null; then
    echo "✓ Using uv for package management"
    USE_UV=1
else
    echo "→ uv not found, using pip"
    USE_UV=0
fi

# Create virtual environment
VENV_DIR="$CLIENT_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "→ Creating virtual environment..."
    if [[ $USE_UV -eq 1 ]]; then
        uv venv --python 3.11 "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
fi

echo "✓ Virtual environment at $VENV_DIR"

# Install dependencies
echo "→ Installing dependencies..."

if [[ $USE_UV -eq 1 ]]; then
    uv pip install --python "$VENV_DIR/bin/python" -e "$CLIENT_DIR"
    uv pip install --python "$VENV_DIR/bin/python" PyQt6 pyaudio aiohttp pyyaml numpy pyperclip
else
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -e "$CLIENT_DIR"
    "$VENV_DIR/bin/pip" install PyQt6 pyaudio aiohttp pyyaml numpy pyperclip
fi

echo "✓ Dependencies installed"

# Check system dependencies
echo ""
echo "Checking system dependencies..."

# Check PortAudio (required for PyAudio)
if ! pkg-config --exists portaudio-2.0 2>/dev/null; then
    echo "⚠ PortAudio not found. Install with: sudo pacman -S portaudio"
fi

echo ""
echo "=================================================="
echo "Setup complete!"
echo ""
echo "To run the client:"
echo "  $VENV_DIR/bin/python -m client"
echo ""
echo "Or add this alias to your shell config:"
echo "  alias transcription-client='$VENV_DIR/bin/python -m client'"
echo "=================================================="

# Create config directory if needed
CONFIG_DIR="$HOME/.config/transcription-suite"
if [[ ! -d "$CONFIG_DIR" ]]; then
    mkdir -p "$CONFIG_DIR"
    echo "✓ Created config directory: $CONFIG_DIR"
fi

# Copy example config if no config exists
if [[ ! -f "$CONFIG_DIR/client.yaml" ]] && [[ -f "$PROJECT_ROOT/config/client.yaml.example" ]]; then
    cp "$PROJECT_ROOT/config/client.yaml.example" "$CONFIG_DIR/client.yaml"
    echo "✓ Created default config: $CONFIG_DIR/client.yaml"
fi
