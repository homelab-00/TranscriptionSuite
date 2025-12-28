#!/bin/bash
# TranscriptionSuite - First-Time Setup Script (Linux)
# Run this once to set up your environment before starting the server.
# After setup, all scripts and configs will be in ~/.config/TranscriptionSuite

set -e

# ============================================================================
# Constants
# ============================================================================
DOCKER_IMAGE="ghcr.io/homelab-00/transcriptionsuite-server"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GITHUB_RAW_URL="https://raw.githubusercontent.com/homelab-00/TranscriptionSuite/main"

# ============================================================================
# Helper Functions
# ============================================================================
print_status() {
    echo -e "\033[1;32m==>\033[0m $1"
}

print_error() {
    echo -e "\033[1;31mError:\033[0m $1" >&2
}

print_warning() {
    echo -e "\033[1;33mWarning:\033[0m $1"
}

print_info() {
    echo -e "\033[1;34mInfo:\033[0m $1"
}

# ============================================================================
# Determine Config Directory
# ============================================================================
get_config_dir() {
    if [[ -n "$XDG_CONFIG_HOME" ]]; then
        echo "$XDG_CONFIG_HOME/TranscriptionSuite"
    else
        echo "$HOME/.config/TranscriptionSuite"
    fi
}

CONFIG_DIR="$(get_config_dir)"

# ============================================================================
# Pre-flight Checks
# ============================================================================
print_status "Running pre-flight checks..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed."
    echo ""
    echo "Please install Docker first:"
    echo "  - Arch Linux: sudo pacman -S docker"
    echo "  - Ubuntu/Debian: sudo apt install docker.io"
    echo "  - Or download from: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null 2>&1; then
    print_error "Docker daemon is not running."
    echo ""
    echo "Please start Docker:"
    echo "  sudo systemctl start docker"
    echo ""
    echo "To enable Docker at boot:"
    echo "  sudo systemctl enable docker"
    exit 1
fi

# Check if NVIDIA GPU is available and toolkit is installed
if command -v nvidia-smi &> /dev/null; then
    if nvidia-smi &> /dev/null; then
        print_info "NVIDIA GPU detected"
        if ! docker info 2>/dev/null | grep -iq "nvidia"; then
            print_warning "NVIDIA Container Toolkit might not be configured for Docker."
            echo "To enable GPU support, please install nvidia-container-toolkit and restart Docker."
        fi
    fi
else
    print_warning "NVIDIA GPU not detected or drivers not installed. Server will run on CPU (slow)."
fi

print_info "Docker is installed and running"

# ============================================================================
# Create Config Directory
# ============================================================================
print_status "Creating config directory: $CONFIG_DIR"
mkdir -p "$CONFIG_DIR"

# ============================================================================
# Copy Config File
# ============================================================================
SOURCE_CONFIG="$PROJECT_ROOT/server/config.yaml"
DEST_CONFIG="$CONFIG_DIR/config.yaml"
DOCKER_DIR="$PROJECT_ROOT/server/docker"

if [[ -f "$DEST_CONFIG" ]]; then
    print_warning "Config already exists at $DEST_CONFIG"
    read -r -p "Overwrite with default config? (y/N): " OVERWRITE
    if [[ "$OVERWRITE" != "y" && "$OVERWRITE" != "Y" ]]; then
        print_info "Keeping existing config"
    else
        if [[ -f "$SOURCE_CONFIG" ]]; then
            print_status "Copying config from repository..."
            cp "$SOURCE_CONFIG" "$DEST_CONFIG"
        else
            print_status "Downloading config from GitHub..."
            curl -sSL "https://raw.githubusercontent.com/homelab-00/TranscriptionSuite/main/server/config.yaml" \
                -o "$DEST_CONFIG"
        fi
        print_info "Config file updated"
    fi
else
    if [[ -f "$SOURCE_CONFIG" ]]; then
        print_status "Copying config from repository..."
        cp "$SOURCE_CONFIG" "$DEST_CONFIG"
    else
        print_status "Downloading config from GitHub..."
        curl -sSL "https://raw.githubusercontent.com/homelab-00/TranscriptionSuite/main/server/config.yaml" \
            -o "$DEST_CONFIG"
    fi
    print_info "Config file created"
fi

# ============================================================================
# Create .env File for Secrets
# ============================================================================
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
ENV_FILE="$CONFIG_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    print_info ".env file already exists (keeping existing secrets)"
else
    if [[ -f "$ENV_EXAMPLE" ]]; then
        print_status "Creating .env file for secrets..."
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        print_info ".env file created at $ENV_FILE"
    else
        print_warning ".env.example not found - skipping .env creation"
    fi
fi

# ============================================================================
# Copy Docker Compose and Scripts to Config Directory
# ============================================================================
print_status "Setting up Docker files in config directory..."

# Copy docker-compose.yml
if [[ -f "$DOCKER_DIR/docker-compose.yml" ]]; then
    cp "$DOCKER_DIR/docker-compose.yml" "$CONFIG_DIR/docker-compose.yml"
else
    print_status "Downloading docker-compose.yml from GitHub..."
    curl -sSL "$GITHUB_RAW_URL/server/docker/docker-compose.yml" -o "$CONFIG_DIR/docker-compose.yml"
fi

# Copy start/stop scripts
for script in start-local.sh start-remote.sh stop.sh; do
    if [[ -f "$DOCKER_DIR/$script" ]]; then
        cp "$DOCKER_DIR/$script" "$CONFIG_DIR/$script"
        chmod +x "$CONFIG_DIR/$script"
    else
        print_status "Downloading $script from GitHub..."
        curl -sSL "$GITHUB_RAW_URL/server/docker/$script" -o "$CONFIG_DIR/$script"
        chmod +x "$CONFIG_DIR/$script"
    fi
done

print_info "Docker files copied to $CONFIG_DIR"

# ============================================================================
# Pull Docker Image
# ============================================================================
print_status "Pulling Docker image: $DOCKER_IMAGE:latest"
echo "This may take a few minutes on first run..."
echo ""

if docker pull "$DOCKER_IMAGE:latest"; then
    print_info "Docker image pulled successfully"
else
    print_warning "Could not pull from GitHub Container Registry (image may not be published yet)"
    print_info "You can build locally instead: cd docker && docker compose build"
fi

# ============================================================================
# Success Message
# ============================================================================
echo ""
echo "=========================================================="
echo "  TranscriptionSuite Setup Complete!"
echo "=========================================================="
echo ""
echo "All files are in: $CONFIG_DIR"
echo ""
echo "  config.yaml      - Server settings"
echo "  .env             - Secrets (HuggingFace token)"
echo "  docker-compose.yml"
echo "  start-local.sh   - Start in HTTP mode"
echo "  start-remote.sh  - Start in HTTPS mode"
echo "  stop.sh          - Stop the server"
echo ""
echo "Important: On first run, an Admin Token is generated."
echo "Wait ~10 seconds after starting, then run:"
echo "  docker compose logs | grep \"Admin Token:\""
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit the .env file to add your HuggingFace token:"
echo "     nano $CONFIG_DIR/.env"
echo ""
echo "  2. (Optional) For remote/TLS access, edit config.yaml:"
echo "     nano $CONFIG_DIR/config.yaml"
echo ""
echo "     Set your Tailscale certificate paths:"
echo "       host_cert_path: \"~/.config/Tailscale/my-machine.crt\""
echo "       host_key_path: \"~/.config/Tailscale/my-machine.key\""
echo ""
echo "  3. Start the server:"
echo "     cd $CONFIG_DIR"
echo "     ./start-local.sh    # HTTP on port 8000"
echo "     ./start-remote.sh   # HTTPS on port 8443"
echo ""
echo "=========================================================="
