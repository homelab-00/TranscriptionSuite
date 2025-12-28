#!/bin/bash
# TranscriptionSuite - Start Server in Local Mode (HTTP)
# Starts the server on http://localhost:8000
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
USER_CONFIG_DIR=""

# Check 1: Development location (../server/config.yaml relative to script dir)
DEV_CONFIG="$SCRIPT_DIR/../server/config.yaml"
if [[ -f "$DEV_CONFIG" ]]; then
    CONFIG_FILE="$DEV_CONFIG"
    USER_CONFIG_DIR="$(cd "$SCRIPT_DIR/../server" && pwd)"
    print_info "Using development config: $CONFIG_FILE"
# Check 2: Script directory (end user running from ~/.config/TranscriptionSuite/)
elif [[ -f "$SCRIPT_DIR/config.yaml" ]]; then
    CONFIG_FILE="$SCRIPT_DIR/config.yaml"
    USER_CONFIG_DIR="$SCRIPT_DIR"
    print_info "Using config: $CONFIG_FILE"
# Check 3: Standard user config location (fallback)
elif [[ -f "$HOME/.config/TranscriptionSuite/config.yaml" ]]; then
    CONFIG_FILE="$HOME/.config/TranscriptionSuite/config.yaml"
    USER_CONFIG_DIR="$HOME/.config/TranscriptionSuite"
    print_info "Using user config: $CONFIG_FILE"
else
    print_info "No config.yaml found (using container defaults)"
    USER_CONFIG_DIR=""
fi

# Export USER_CONFIG_DIR for docker-compose
export USER_CONFIG_DIR

# Find .env file (harmonized with config.yaml search order)
ENV_FILE=""
ENV_FILE_ARG=""

# Check 1: Development location (../server/.env - alongside dev config)
DEV_ENV="$SCRIPT_DIR/../server/.env"
if [[ -f "$DEV_ENV" ]]; then
    ENV_FILE="$DEV_ENV"
    print_info "Using secrets from: $ENV_FILE"
    ENV_FILE_ARG="--env-file $ENV_FILE"
# Check 2: Script directory (end user running from ~/.config/TranscriptionSuite/)
elif [[ -f "$SCRIPT_DIR/.env" ]]; then
    ENV_FILE="$SCRIPT_DIR/.env"
    print_info "Using secrets from: $ENV_FILE"
    ENV_FILE_ARG="--env-file $ENV_FILE"
# Check 3: Standard user config location (fallback)
elif [[ -f "$HOME/.config/TranscriptionSuite/.env" ]]; then
    ENV_FILE="$HOME/.config/TranscriptionSuite/.env"
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

    # We're starting in local mode (TLS disabled)
    if [[ "$CURRENT_TLS" == "true" ]]; then
        print_info "Mode conflict: container is in remote/TLS mode, but starting in local mode"
        print_info "Removing existing container..."
        cd "$SCRIPT_DIR"
        docker compose down 2>&1 | grep -v "No resource found to remove"
    else
        print_info "Container is already in local mode"
    fi
fi

# Check if image exists
if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^bvcsfd/transcription-suite:latest$"; then
    print_info "Using existing image: bvcsfd/transcription-suite:latest"
else
    print_info "Image will be built on first run"
fi

# ============================================================================
# Start Container
# ============================================================================
print_status "Starting TranscriptionSuite server (local mode)..."

cd "$SCRIPT_DIR"

# TLS_ENABLED defaults to false in docker-compose.yml
# shellcheck disable=SC2086
docker compose $ENV_FILE_ARG up -d 2>&1 | grep -v "WARN\[0000\] No services to build"

echo ""
echo "=========================================================="
echo "  TranscriptionSuite Server Started (Local Mode)"
echo "=========================================================="
echo ""
echo "  Server URL:  http://localhost:8000"
echo "  Web UI:      http://localhost:8000/record"
echo "  Notebook:    http://localhost:8000/notebook"
echo ""
echo "  Note: On first run, an admin token will be generated."
echo "        Wait ~10 seconds, then run:"
echo "        docker compose logs | grep \"Admin Token:\""
echo ""
echo "  View logs:   docker compose logs -f"
echo "  Stop:        ./stop.sh"
echo ""
echo "=========================================================="
