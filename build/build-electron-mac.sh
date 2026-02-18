#!/bin/bash
# Build Electron DMG + ZIP for macOS (Apple Silicon arm64)
# Requires: Node.js 24+, npm
#
# Optional release signing:
#   GPG_KEY_ID         - key id / fingerprint used for detached .asc signatures
#   GPG_PASSPHRASE     - passphrase for non-interactive signing
#   GPG_TIMEOUT_MINUTES- signing timeout (default: 45)
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

# Optional detached signature generation
if [[ -n "${GPG_KEY_ID:-}" ]]; then
    echo "→ Signing release artifacts with GPG armor..."
    "$PROJECT_ROOT/build/sign-electron-artifacts.sh" "$DASHBOARD_DIR/release"
else
    echo "→ GPG signing skipped (set GPG_KEY_ID to enable)"
fi

echo ""
echo "=================================================="
echo "✓ macOS builds created in: $DASHBOARD_DIR/release/"
echo "=================================================="
