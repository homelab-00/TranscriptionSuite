#!/bin/bash
# TranscriptionSuite - Stop Server
# Stops the Docker container

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR" || exit 1
docker compose stop

echo ""
echo "TranscriptionSuite server stopped."
echo ""
echo "To restart:"
echo "  ./start-local.sh    # HTTP mode"
echo "  ./start-remote.sh   # HTTPS mode"
