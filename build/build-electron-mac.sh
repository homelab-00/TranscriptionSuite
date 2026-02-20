#!/bin/bash
# Build Electron DMG + ZIP for macOS (Apple Silicon arm64)
# Requires: Node.js 24+, npm, Python 3 + pip3 (for dmgbuild)
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

# electron-builder's bundled dmgbuild binary (dmg-builder >= 1.2.0) requires
# macOS 15.7+. On older macOS versions, install dmgbuild via pip and point
# CUSTOM_DMGBUILD_PATH at it so electron-builder uses the local copy instead.
if [[ -z "${CUSTOM_DMGBUILD_PATH:-}" ]]; then
    if ! command -v dmgbuild &> /dev/null; then
        echo "→ Installing dmgbuild via pip3 (bundled binary requires macOS 15.7+)..."
        pip3 install --quiet dmgbuild
    fi
    # Resolve the dmgbuild path. pip3 --user installs may land outside PATH
    # (e.g. ~/Library/Python/3.x/bin on macOS), so fall back to asking Python.
    CUSTOM_DMGBUILD_PATH="$(command -v dmgbuild 2>/dev/null || python3 -c \
        'import sysconfig; print(sysconfig.get_path("scripts", "posix_user") + "/dmgbuild")' 2>/dev/null || true)"
    if [[ -z "$CUSTOM_DMGBUILD_PATH" || ! -f "$CUSTOM_DMGBUILD_PATH" ]]; then
        echo "ERROR: dmgbuild not found after install. Add its location to PATH or set CUSTOM_DMGBUILD_PATH manually."
        exit 1
    fi
    export CUSTOM_DMGBUILD_PATH
    echo "→ Using local dmgbuild: $CUSTOM_DMGBUILD_PATH"
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
