#!/bin/bash
# TranscriptionSuite - Stop Server
# Stops the container (supports Docker and Podman)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect container runtime (same logic as start-common.sh)
if [[ -n "${CONTAINER_RUNTIME:-}" ]]; then
    RT="$(printf '%s' "$CONTAINER_RUNTIME" | tr '[:upper:]' '[:lower:]')"
elif command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    RT="docker"
elif command -v podman &>/dev/null && podman info &>/dev/null 2>&1; then
    RT="podman"
else
    echo "Error: Neither Docker nor Podman is available." >&2
    exit 1
fi

cd "$SCRIPT_DIR" || exit 1
$RT compose stop

echo ""
echo "TranscriptionSuite server stopped."
echo ""
echo "To restart:"
echo "  ./start-local.sh    # HTTP mode"
echo "  ./start-remote.sh   # HTTPS mode"
