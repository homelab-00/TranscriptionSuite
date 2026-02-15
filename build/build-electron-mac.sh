#!/bin/bash
# Build Electron DMG + ZIP for macOS (Apple Silicon arm64)
# Requires: Node.js 24+, npm
#
# For signed/notarized builds, set these env vars:
#   CSC_LINK          — Base64-encoded .p12 certificate (or path)
#   CSC_KEY_PASSWORD  — Certificate password
#   APPLE_ID          — Apple Developer account email
#   APPLE_APP_PASSWORD— App-specific password
#   APPLE_TEAM_ID     — 10-char Team ID
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DASHBOARD_DIR="$PROJECT_ROOT/dashboard"

echo "=================================================="
echo "Building TranscriptionSuite macOS DMG + ZIP (arm64)"
echo "=================================================="

# Ensure Node.js is available
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js not found. Install Node.js 24+ first."
    exit 1
fi

echo "→ Node.js $(node --version)"
echo "→ npm $(npm --version)"

# Check signing status
if [[ -n "$CSC_LINK" ]]; then
    echo "→ Code signing: ENABLED"
else
    echo "⚠ Code signing: DISABLED (CSC_LINK not set)"
fi

if [[ -n "$APPLE_ID" && -n "$APPLE_APP_PASSWORD" && -n "$APPLE_TEAM_ID" ]]; then
    echo "→ Notarization: ENABLED"
else
    echo "⚠ Notarization: DISABLED (Apple credentials not set)"
fi

# Install dependencies
echo "→ Installing dependencies..."
cd "$DASHBOARD_DIR"
npm ci

# Build renderer (Vite) + main process (tsc)
echo "→ Building renderer and main process..."
npm run build:electron

# Package as DMG + ZIP
echo "→ Packaging for macOS..."
npm run package:mac

echo ""
echo "=================================================="
echo "✓ macOS builds created in: $DASHBOARD_DIR/release/"
echo "=================================================="
