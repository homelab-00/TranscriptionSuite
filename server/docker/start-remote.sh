#!/bin/bash
# TranscriptionSuite - Start Server in Remote Mode (HTTPS/TLS)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start-common.sh" remote "$@"
