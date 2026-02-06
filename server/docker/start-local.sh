#!/bin/bash
# TranscriptionSuite - Start Server in Local Mode (HTTP)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start-common.sh" local "$@"
