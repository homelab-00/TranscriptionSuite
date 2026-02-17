#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
# Version defaults (easy to edit here)
DEFAULT_SERVER_VERSION="1.0.2"
DEFAULT_DASHBOARD_VERSION="1.0.2"

# Optional CLI overrides:
#   ./build/run-linux-rebuild.sh [server_version] [dashboard_version]
SERVER_VERSION="${1:-$DEFAULT_SERVER_VERSION}"
DASHBOARD_VERSION="${2:-$DEFAULT_DASHBOARD_VERSION}"

BUILD_DIR="$PROJECT_ROOT/build"
SERVER_BACKEND_DIR="$PROJECT_ROOT/server/backend"
DASHBOARD_DIR="$PROJECT_ROOT/dashboard"
SERVER_DOCKER_DIR="$PROJECT_ROOT/server/docker"
DASHBOARD_RELEASE_DIR="$PROJECT_ROOT/dashboard/release"
APPIMAGE="TranscriptionSuite-${DASHBOARD_VERSION}.AppImage"
CONFIG_DIR="$HOME/.config/TranscriptionSuite"

STEP_INDEX=0
CURRENT_STEP="initialization"
SHOULD_REBUILD_DOCKER=false
DOCKER_REBUILD_STATUS="skipped"

print_step() {
    local label="$1"
    STEP_INDEX=$((STEP_INDEX + 1))
    CURRENT_STEP="$label"
    echo
    echo "=================================================="
    echo "Step ${STEP_INDEX}: ${label}"
    echo "=================================================="
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

handle_error() {
    local exit_code="$1"
    local line_no="$2"
    local cmd="$3"
    echo
    echo "ERROR: Step failed: ${CURRENT_STEP}" >&2
    echo "ERROR: Command: ${cmd}" >&2
    echo "ERROR: Line: ${line_no}" >&2
    exit "$exit_code"
}
trap 'handle_error "$?" "${LINENO}" "${BASH_COMMAND}"' ERR

require_command() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        fail "Required command not found: ${cmd}"
    fi
}

require_directory() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        fail "Required directory not found: ${dir}"
    fi
}

print_step "Validate prerequisites"
require_command uv
require_command npm
require_directory "$BUILD_DIR"
require_directory "$SERVER_BACKEND_DIR"
require_directory "$DASHBOARD_DIR"
require_directory "$DASHBOARD_RELEASE_DIR"

print_step "Set runtime options"
echo "Server version:    $SERVER_VERSION"
echo "Dashboard version: $DASHBOARD_VERSION"
if [[ -t 0 && -t 1 ]]; then
    rebuild_answer=""
    if ! read -r -p "Rebuild Docker image with TAG=${SERVER_VERSION}? [y/N]: " rebuild_answer; then
        rebuild_answer=""
    fi
    rebuild_answer="${rebuild_answer,,}"
    if [[ "$rebuild_answer" == "y" || "$rebuild_answer" == "yes" ]]; then
        SHOULD_REBUILD_DOCKER=true
    fi
else
    echo "Non-interactive shell detected. Docker image rebuild defaults to no."
fi
if [[ "$SHOULD_REBUILD_DOCKER" == "true" ]]; then
    require_command docker
    require_directory "$SERVER_DOCKER_DIR"
    echo "Docker image rebuild: enabled"
else
    echo "Docker image rebuild: skipped"
fi

if [[ "$SHOULD_REBUILD_DOCKER" == "true" ]]; then
    print_step "Remove Docker containers matching transcriptionsuite"
    mapfile -t container_ids < <(
        docker ps -a --format '{{.ID}}\t{{.Names}}' \
        | awk -F '\t' 'BEGIN { IGNORECASE=1 } $2 ~ /transcriptionsuite/ { print $1 }'
    )
    if [[ "${#container_ids[@]}" -gt 0 ]]; then
        docker rm -f "${container_ids[@]}"
    else
        echo "No matching containers found, skipping."
    fi

    print_step "Remove Docker images matching transcriptionsuite"
    mapfile -t image_ids < <(
        docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}' \
        | awk -F '\t' 'BEGIN { IGNORECASE=1 } $1 ~ /transcriptionsuite/ { print $2 }' \
        | awk '!seen[$0]++'
    )
    if [[ "${#image_ids[@]}" -gt 0 ]]; then
        docker rmi -f "${image_ids[@]}"
    else
        echo "No matching images found, skipping."
    fi

    print_step "Remove Docker volumes matching transcriptionsuite"
    mapfile -t volume_names < <(
        docker volume ls --format '{{.Name}}' \
        | awk 'BEGIN { IGNORECASE=1 } /transcriptionsuite/ { print $0 }'
    )
    if [[ "${#volume_names[@]}" -gt 0 ]]; then
        docker volume rm "${volume_names[@]}"
    else
        echo "No matching volumes found, skipping."
    fi

    print_step "Build Docker image with TAG=${SERVER_VERSION} (this may take several minutes)"
    pushd "$SERVER_DOCKER_DIR" > /dev/null
    TAG="$SERVER_VERSION" docker compose build --no-cache
    popd > /dev/null
    DOCKER_REBUILD_STATUS="completed"
else
    print_step "Skip all Docker operations"
    echo "Skipping Docker container/image/volume cleanup and image rebuild by user choice/default."
fi

print_step "Refresh Python dependencies in build/"
pushd "$BUILD_DIR" > /dev/null
uv lock --upgrade
uv sync
popd > /dev/null

print_step "Refresh Python dependencies in server/backend/"
pushd "$SERVER_BACKEND_DIR" > /dev/null
uv lock --upgrade
uv sync
popd > /dev/null

print_step "Install, validate, and package dashboard AppImage"
pushd "$DASHBOARD_DIR" > /dev/null
npm update --package-lock-only
npm ci
npm run format
npm run typecheck
npm run ui:contract:check
npm run package:linux
popd > /dev/null

print_step "Remove user config directory"
if [[ -d "$CONFIG_DIR" ]]; then
    rm -rf "$CONFIG_DIR"
    echo "Removed: $CONFIG_DIR"
else
    echo "Not found, skipping: $CONFIG_DIR"
fi

print_step "Mark AppImage executable"
if [[ ! -f "$DASHBOARD_RELEASE_DIR/$APPIMAGE" ]]; then
    fail "Expected AppImage not found: $DASHBOARD_RELEASE_DIR/$APPIMAGE"
fi
chmod +x "$DASHBOARD_RELEASE_DIR/$APPIMAGE"

echo
echo "SUCCESS: Rebuild flow completed."
echo "Server version:    ${SERVER_VERSION}"
echo "Dashboard version: ${DASHBOARD_VERSION}"
echo "Docker rebuild:    ${DOCKER_REBUILD_STATUS}"

print_step "Launch AppImage in foreground"
"$DASHBOARD_RELEASE_DIR/$APPIMAGE"
