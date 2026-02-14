#!/bin/bash
# Build Electron AppImage for TranscriptionSuite
# Requires: Node.js 24+, npm
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DASHBOARD_DIR="$PROJECT_ROOT/dashboard"

echo "=================================================="
echo "Building TranscriptionSuite Electron AppImage"
echo "=================================================="

# Ensure Node.js is available
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js not found. Install Node.js 24+ first."
    exit 1
fi

echo "→ Node.js $(node --version)"
echo "→ npm $(npm --version)"

# Install dependencies
echo "→ Installing dependencies..."
cd "$DASHBOARD_DIR"
npm ci

# Build renderer (Vite) + main process (tsc)
echo "→ Building renderer and main process..."
npm run build:electron

# Package as AppImage
echo "→ Packaging as AppImage..."
npm run package:linux

echo ""
echo "=================================================="
echo "✓ AppImage created in: $DASHBOARD_DIR/release/"
echo "=================================================="
