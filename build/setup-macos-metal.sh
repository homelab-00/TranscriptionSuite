#!/bin/bash
# setup-macos-metal.sh — One-liner setup for TranscriptionSuite on Apple Silicon
#
# Installs system dependencies (Homebrew, uv, Node.js), builds the Electron
# dashboard, and bundles the Python/MLX backend into the .app at its final
# location.  The result is a self-contained TranscriptionSuite.app placed in
# the repository root that can be dragged straight to /Applications.
#
# Usage (from anywhere inside the repo, or as a one-liner):
#   bash build/setup-macos-metal.sh [--install]
#
# Options:
#   --install    Also copy the finished app to /Applications/ and remove the
#                copy in the repo root.
#
# Requirements:
#   • Apple Silicon Mac (M1 or later), macOS 12+
#   • An internet connection (Homebrew, npm packages, Python packages, and
#     optionally uv-managed Python 3.13 are downloaded on first run)
#   • ~5 GB free disk space for the venv + node_modules
#
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DASHBOARD_DIR="$PROJECT_ROOT/dashboard"
OUTPUT_APP="$PROJECT_ROOT/TranscriptionSuite.app"

# ─────────────────────────────────────────────────────────────────────────────
# Options
# ─────────────────────────────────────────────────────────────────────────────
INSTALL_TO_APPS=false
for arg in "$@"; do
  case $arg in
    --install) INSTALL_TO_APPS=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

echo "=================================================="
echo "  TranscriptionSuite — macOS Metal/MLX Setup"
echo "=================================================="
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Platform check
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "❌  This script is for macOS only." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "❌  This script requires Apple Silicon (M1 or later, arm64)." >&2
  exit 1
fi
echo "✓  Apple Silicon macOS detected."

# ─────────────────────────────────────────────────────────────────────────────
# 2. Homebrew
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo ""
  echo "Homebrew is not installed. It is needed to install Node.js and uv."
  read -rp "Install Homebrew now? [y/N] " yn
  case "$yn" in
    [yY] | [yY][eE][sS])
      echo "→ Installing Homebrew…"
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      # Add Homebrew to PATH for the rest of this script session.
      eval "$(/opt/homebrew/bin/brew shellenv)"
      ;;
    *)
      echo "❌  Homebrew is required. Install it from https://brew.sh and re-run." >&2
      exit 1
      ;;
  esac
fi
echo "✓  Homebrew: $(brew --version | head -1)"

# ─────────────────────────────────────────────────────────────────────────────
# 3. uv — Python package / venv manager
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  echo "→ Installing uv via Homebrew…"
  brew install uv
fi
echo "✓  uv: $(uv --version)"

# ─────────────────────────────────────────────────────────────────────────────
# 4. Node.js 20+
# ─────────────────────────────────────────────────────────────────────────────
NODE_OK=false
if command -v node &>/dev/null; then
  NODE_MAJOR="$(node --version | sed 's/v//' | cut -d. -f1)"
  if [[ "$NODE_MAJOR" -ge 20 ]]; then
    NODE_OK=true
  fi
fi
if [[ "$NODE_OK" == false ]]; then
  echo "→ Installing Node.js via Homebrew…"
  brew install node
fi
echo "✓  Node.js: $(node --version), npm: $(npm --version)"

# ─────────────────────────────────────────────────────────────────────────────
# 5. ffmpeg — required by the Python backend for audio decoding
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
  echo "→ Installing ffmpeg via Homebrew…"
  brew install ffmpeg
fi
echo "✓  ffmpeg: $(ffmpeg -version 2>&1 | head -1)"

# ─────────────────────────────────────────────────────────────────────────────
# 6. logo.icns — needed by electron-builder
# ─────────────────────────────────────────────────────────────────────────────
ICNS_PATH="$PROJECT_ROOT/docs/assets/logo.icns"
if [[ ! -f "$ICNS_PATH" ]]; then
  echo "→ Generating logo.icns from logo.png…"
  SRC_PNG="$PROJECT_ROOT/docs/assets/logo.png"
  if [[ ! -f "$SRC_PNG" ]]; then
    echo "❌  docs/assets/logo.png not found — ensure the repository is complete." >&2
    exit 1
  fi
  ICONSET_TMP="$(mktemp -d)/logo.iconset"
  mkdir -p "$ICONSET_TMP"
  for sz in 16 32 64 128 256 512; do
    sips -z "$sz" "$sz" "$SRC_PNG" --out "$ICONSET_TMP/icon_${sz}x${sz}.png"      &>/dev/null
    dbl=$((sz * 2))
    sips -z "$dbl" "$dbl" "$SRC_PNG" --out "$ICONSET_TMP/icon_${sz}x${sz}@2x.png" &>/dev/null
  done
  iconutil -c icns -o "$ICNS_PATH" "$ICONSET_TMP"
  rm -rf "$(dirname "$ICONSET_TMP")"
  echo "✓  logo.icns created."
fi

# ─────────────────────────────────────────────────────────────────────────────
# 7. Build the Electron dashboard
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "─── Electron Build ───────────────────────────────────────────────────────"
echo "→ Installing npm dependencies…"
cd "$DASHBOARD_DIR"
npm ci

echo "→ Compiling renderer (Vite) + main process (TypeScript)…"
npm run build:electron

echo "→ Packaging app bundle (arm64)…"
# Use the 'dir' target to produce an unpacked .app — faster than building a DMG
# and sufficient for local installation.  No dmgbuild dependency required.
npx electron-builder --mac dir --arm64

RELEASE_APP="$DASHBOARD_DIR/release/mac-arm64/TranscriptionSuite.app"
if [[ ! -d "$RELEASE_APP" ]]; then
  echo "❌  Expected app bundle not found at: $RELEASE_APP" >&2
  echo "    Check the electron-builder output above for errors." >&2
  exit 1
fi
echo "✓  App bundle built."

# ─────────────────────────────────────────────────────────────────────────────
# 8. Place the .app at its final location
#    The Python venv is created AFTER this move so that all absolute paths
#    embedded in the venv (e.g. the uvicorn console-script shebang) point to
#    the location the app will actually run from.
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "─── App Placement ────────────────────────────────────────────────────────"

if [[ "$INSTALL_TO_APPS" == true ]]; then
  # Install directly to /Applications/ — the venv will be created there.
  FINAL_APP="/Applications/TranscriptionSuite.app"
  echo "→ Installing to /Applications/…"
else
  # Leave the app in the repo root — user can drag it to /Applications/ later.
  FINAL_APP="$OUTPUT_APP"
  echo "→ Placing app bundle in repository root…"
fi

if [[ -d "$FINAL_APP" ]]; then
  echo "   Removing existing ${FINAL_APP}..."
  rm -rf "$FINAL_APP"
fi

# Copy (not move) so the release/ directory is preserved for reference.
cp -a "$RELEASE_APP" "$FINAL_APP"
echo "OK App placed at: ${FINAL_APP}"

# ─────────────────────────────────────────────────────────────────────────────
# 9. Install the Python/MLX backend into the app bundle
# ─────────────────────────────────────────────────────────────────────────────
# The venv lives inside the app bundle so the server spawned by Electron
# (via mlxServerManager.ts) finds uvicorn at:
#   <app>/Contents/Resources/backend/.venv/bin/uvicorn
#
# Key design decisions:
#   --no-editable  — bakes the server Python package into site-packages rather
#                    than creating a .pth file that references the source tree.
#                    This makes the venv self-contained (no repo dependency at
#                    runtime).
#   uv venv first  — creates the venv at the FINAL path so that any absolute
#                    paths written during 'uv sync' (e.g. in uvicorn's console
#                    script shebang) point to the correct location and remain
#                    valid after the user moves the app.  However, note that
#                    mlxServerManager.ts is patched to invoke
#                    'python -m uvicorn' instead of the console script, so the
#                    shebang is never executed directly; the venv is still
#                    created in-place for clarity and forward compatibility.
echo ""
echo "─── Python/MLX Backend Install ───────────────────────────────────────────"
echo "→ Installing PyTorch, MLX, Whisper, Parakeet, Canary, and dependencies…"
echo "   This step downloads several GB of packages on first run."
echo ""

BACKEND_DIR="$FINAL_APP/Contents/Resources/backend"
VENV_DIR="$BACKEND_DIR/.venv"

mkdir -p "$BACKEND_DIR"

# Hatchling uses [tool.hatch.build.targets.wheel] packages = ["server"], which
# means it looks for a directory named "server" inside server/backend/.  That
# directory is provided by a self-referential symlink (server/backend/server →
# .) which is gitignored and therefore absent after a fresh clone.  Create it
# now — before uv sync — so hatchling can discover the package source and bake
# it into site-packages (--no-editable).  Without this, the wheel is built
# empty and `import server` fails at runtime.
BACKEND_SRC="$PROJECT_ROOT/server/backend"
if [[ ! -L "$BACKEND_SRC/server" ]]; then
  ln -sf . "$BACKEND_SRC/server"
  echo "✓  Created server/backend/server symlink for wheel build."
fi

# Create a Python 3.13 venv managed by uv. uv auto-downloads Python 3.13 if
# it is not present on this machine.
uv venv "$VENV_DIR" --python 3.13

# Install the server package and all MLX extras.
# UV_PROJECT_ENVIRONMENT tells uv to use our venv instead of the default
# .venv next to pyproject.toml, while --directory points to the project root.
UV_PROJECT_ENVIRONMENT="$VENV_DIR" \
  uv sync \
    --directory "$PROJECT_ROOT/server/backend" \
    --extra mlx \
    --no-editable

echo ""
echo "✓  Python/MLX backend installed."

# ─────────────────────────────────────────────────────────────────────────────
# 10. Summary
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "=================================================="
echo "✓  Setup complete!"
echo ""
echo "  App: $FINAL_APP"
echo ""
if [[ "$INSTALL_TO_APPS" == false ]]; then
  echo "  ┌─────────────────────────────────────────────────────────────────┐"
  echo "  │  Drag TranscriptionSuite.app from the repository root into      │"
  echo "  │  /Applications — or double-click it to run from the repo.      │"
  echo "  │                                                                 │"
  echo "  │  macOS Gatekeeper note: on first launch, right-click the app   │"
  echo "  │  and choose Open if you see an 'unidentified developer' alert.  │"
  echo "  └─────────────────────────────────────────────────────────────────┘"
else
  echo "  ┌─────────────────────────────────────────────────────────────────┐"
  echo "  │  macOS Gatekeeper note: on first launch, right-click the app   │"
  echo "  │  and choose Open if you see an 'unidentified developer' alert.  │"
  echo "  └─────────────────────────────────────────────────────────────────┘"
fi
echo ""
echo "  In the Dashboard:"
echo "    Settings → Runtime Profile → Metal (Apple Silicon)"
echo "    then click 'Start Metal Server'."
echo "=================================================="
