#!/bin/bash
# TranscriptionSuite - Start Server in Remote Mode (HTTPS/TLS)
# Starts the server on https://localhost:8443
# Requires TLS certificates configured in config.yaml
# This script can run from the docker/ folder OR from ~/.config/TranscriptionSuite

set -e

# ============================================================================
# Constants
# ============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================================
# Helper Functions
# ============================================================================
print_status() {
    echo -e "\033[1;32m==>\033[0m $1"
}

print_error() {
    echo -e "\033[1;31mError:\033[0m $1" >&2
}

print_info() {
    echo -e "\033[1;34mInfo:\033[0m $1"
}

# ============================================================================
# Pre-flight Checks
# ============================================================================

# Check if Docker daemon is running
if ! docker info &> /dev/null 2>&1; then
    print_error "Docker daemon is not running."
    echo ""
    echo "Please start Docker:"
    echo "  sudo systemctl start docker"
    exit 1
fi

# Check docker-compose.yml exists in script directory
if [[ ! -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
    print_error "docker-compose.yml not found in $SCRIPT_DIR"
    echo ""
    echo "Run setup.sh first to set up TranscriptionSuite."
    exit 1
fi

# ============================================================================
# Find Config and .env Files
# ============================================================================
# This script works in two scenarios:
#   1. Development: Run from docker/ directory (finds config at ../server/)
#   2. End user: Run from ~/.config/TranscriptionSuite/ (finds config in same dir)
#
# Priority order for config.yaml:
#   1. ../server/config.yaml (development - when running from docker/ dir)
#   2. $SCRIPT_DIR/config.yaml (end user - when running from ~/.config/TranscriptionSuite/)
#   3. ~/.config/TranscriptionSuite/config.yaml (fallback)
#
# Priority order for .env:
#   1. ../server/.env (development - alongside dev config)
#   2. $SCRIPT_DIR/.env (end user running from ~/.config/TranscriptionSuite/)
#   3. ~/.config/TranscriptionSuite/.env (fallback)

# Find config.yaml
CONFIG_FILE=""
CONFIG_DIR_TO_MOUNT=""

# Check 1: Development location (../config.yaml relative to script dir)
DEV_CONFIG="$SCRIPT_DIR/../config.yaml"
if [[ -f "$DEV_CONFIG" ]]; then
    CONFIG_FILE="$DEV_CONFIG"
    CONFIG_DIR_TO_MOUNT="$(cd "$SCRIPT_DIR/.." && pwd)"
    print_info "Using development config: $CONFIG_FILE"
# Check 2: Script directory (end user running from ~/.config/TranscriptionSuite/)
elif [[ -f "$SCRIPT_DIR/config.yaml" ]]; then
    CONFIG_FILE="$SCRIPT_DIR/config.yaml"
    CONFIG_DIR_TO_MOUNT="$SCRIPT_DIR"
    print_info "Using config: $CONFIG_FILE"
# Check 3: Standard user config location (fallback)
elif [[ -f "$HOME/.config/TranscriptionSuite/config.yaml" ]]; then
    CONFIG_FILE="$HOME/.config/TranscriptionSuite/config.yaml"
    CONFIG_DIR_TO_MOUNT="$HOME/.config/TranscriptionSuite"
    print_info "Using user config: $CONFIG_FILE"
else
    print_error "No config.yaml found"
    echo ""
    echo "Checked locations:"
    echo "  1. $DEV_CONFIG (development)"
    echo "  2. $SCRIPT_DIR/config.yaml (script directory)"
    echo "  3. $HOME/.config/TranscriptionSuite/config.yaml (user config)"
    echo ""
    echo "For end users: Run setup.sh first to create the config file."
    echo "For development: config.yaml should be in server/ directory."
    exit 1
fi

# Find .env file (harmonized with config.yaml search order - optional for remote mode)
ENV_FILE=""
ENV_FILE_ARG=""

# Check 1: Development location (../.env - alongside dev config)
DEV_ENV="$SCRIPT_DIR/../.env"
if [[ -f "$DEV_ENV" ]]; then
    ENV_FILE="$DEV_ENV"
# Check 2: Script directory (end user running from ~/.config/TranscriptionSuite/)
elif [[ -f "$SCRIPT_DIR/.env" ]]; then
    ENV_FILE="$SCRIPT_DIR/.env"
# Check 3: Standard user config location (fallback)
elif [[ -f "$HOME/.config/TranscriptionSuite/.env" ]]; then
    ENV_FILE="$HOME/.config/TranscriptionSuite/.env"
fi

# ============================================================================
# Parse TLS Paths from Config
# ============================================================================
# Simple grep-based YAML parsing for host_cert_path and host_key_path
# These are under remote_server.tls section

HOST_CERT_PATH=$(grep -E "^\s+host_cert_path:" "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*host_cert_path:[[:space:]]*//' | tr -d '"' | tr -d "'" | tr -d ' ')
HOST_KEY_PATH=$(grep -E "^\s+host_key_path:" "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*host_key_path:[[:space:]]*//' | tr -d '"' | tr -d "'" | tr -d ' ')

# Expand ~ to home directory
HOST_CERT_PATH="${HOST_CERT_PATH/#\~/$HOME}"
HOST_KEY_PATH="${HOST_KEY_PATH/#\~/$HOME}"

# ============================================================================
# Validate TLS Configuration
# ============================================================================
if [[ -z "$HOST_CERT_PATH" || "$HOST_CERT_PATH" == "" ]]; then
    print_error "remote_server.tls.host_cert_path is not set in config.yaml"
    echo ""
    echo "Please edit $CONFIG_FILE and set the TLS certificate paths:"
    echo ""
    echo "  remote_server:"
    echo "    tls:"
    echo "      host_cert_path: \"~/.config/Tailscale/my-machine.crt\""
    echo "      host_key_path: \"~/.config/Tailscale/my-machine.key\""
    echo ""
    echo "See README_DEV.md for Tailscale certificate generation instructions."
    exit 1
fi

if [[ -z "$HOST_KEY_PATH" || "$HOST_KEY_PATH" == "" ]]; then
    print_error "remote_server.tls.host_key_path is not set in config.yaml"
    echo ""
    echo "Please edit $CONFIG_FILE and set the TLS key path."
    exit 1
fi

if [[ ! -f "$HOST_CERT_PATH" ]]; then
    print_error "Certificate file not found: $HOST_CERT_PATH"
    echo ""
    echo "Please ensure the certificate file exists."
    echo "For Tailscale, generate certificates with:"
    echo "  sudo tailscale cert <your-machine>.tail<xxxx>.ts.net"
    exit 1
fi

if [[ ! -f "$HOST_KEY_PATH" ]]; then
    print_error "Key file not found: $HOST_KEY_PATH"
    echo ""
    echo "Please ensure the key file exists."
    exit 1
fi

print_info "Certificate: $HOST_CERT_PATH"
print_info "Key: $HOST_KEY_PATH"

# Log .env file status
if [[ -n "$ENV_FILE" ]]; then
    print_info "Using secrets from: $ENV_FILE"
    ENV_FILE_ARG="--env-file $ENV_FILE"
else
    print_info "No .env file found (diarization may not work without HF token)"
    ENV_FILE_ARG=""
fi

# ============================================================================
# Check for Existing Container and Mode Conflicts
# ============================================================================
CONTAINER_NAME="transcription-suite"

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    print_info "Container already exists, checking mode..."

    # Get current TLS_ENABLED value from running/stopped container
    CURRENT_TLS=$(docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep "^TLS_ENABLED=" | cut -d'=' -f2 || echo "false")

    # We're starting in remote mode (TLS enabled)
    if [[ "$CURRENT_TLS" != "true" ]]; then
        print_info "Mode conflict: container is in local mode, but starting in remote/TLS mode"
        print_info "Removing existing container..."
        cd "$SCRIPT_DIR"
        docker compose down 2>&1 | grep -v "No resource found to remove"
    else
        print_info "Container is already in remote/TLS mode"
    fi
fi

# Check if image exists
if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^ghcr.io/homelab-00/transcriptionsuite-server:latest$"; then
    print_info "Using existing image: ghcr.io/homelab-00/transcriptionsuite-server:latest"
else
    print_info "Image will be built on first run"
fi

# ============================================================================
# Start Container with TLS
# ============================================================================
print_status "Starting TranscriptionSuite server (remote/TLS mode)..."

cd "$SCRIPT_DIR"

# Set environment variables for docker-compose
export TLS_ENABLED=true
export TLS_CERT_PATH="$HOST_CERT_PATH"
export TLS_KEY_PATH="$HOST_KEY_PATH"
export USER_CONFIG_DIR="$CONFIG_DIR_TO_MOUNT"

# shellcheck disable=SC2086
docker compose $ENV_FILE_ARG up -d 2>&1 | grep -v "WARN\[0000\] No services to build"

echo ""
echo "=========================================================="
echo "  TranscriptionSuite Server Started (Remote/TLS Mode)"
echo "=========================================================="
echo ""
echo "  HTTPS URL:   https://localhost:8443"
echo "  Web UI:      https://localhost:8443/record"
echo "  Notebook:    https://localhost:8443/notebook"
echo ""
echo "  Certificate: $HOST_CERT_PATH"
echo "  Key:         $HOST_KEY_PATH"
echo ""
echo "  Note: On first run, an admin token will be generated."
echo "        Wait ~10 seconds, then run:"
echo "        docker compose logs | grep \"Admin Token:\""
echo ""
echo "  View logs:   docker compose logs -f"
echo "  Stop:        ./stop.sh"
echo ""
echo "=========================================================="
