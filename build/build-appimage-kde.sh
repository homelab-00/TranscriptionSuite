#!/bin/bash
# Build AppImage for TranscriptionSuite KDE client
# Requires: appimagetool, pyinstaller, and the KDE client dependencies

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build/appimage-kde"
DIST_DIR="$PROJECT_ROOT/build/dist"

echo "=================================================="
echo "Building TranscriptionSuite KDE AppImage"
echo "=================================================="

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/AppDir/usr/bin"
mkdir -p "$BUILD_DIR/AppDir/usr/share/applications"
mkdir -p "$BUILD_DIR/AppDir/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$DIST_DIR"

# Check for appimagetool
if ! command -v appimagetool &> /dev/null; then
    echo "Installing appimagetool..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
        -O /tmp/appimagetool
    chmod +x /tmp/appimagetool
    APPIMAGETOOL="/tmp/appimagetool"
else
    APPIMAGETOOL="appimagetool"
fi

# Ensure build dependencies are installed
echo "→ Syncing build dependencies..."
cd "$SCRIPT_DIR"
if [[ ! -d ".venv" ]]; then
    echo "Creating build virtual environment..."
    uv venv
fi
uv sync

# Build with PyInstaller
echo "→ Building with PyInstaller..."
cd "$PROJECT_ROOT"

# Use PyInstaller from build venv
PYINSTALLER="$SCRIPT_DIR/.venv/bin/pyinstaller"

"$PYINSTALLER" --clean --distpath "$BUILD_DIR/AppDir/usr/bin" \
    --workpath "$BUILD_DIR/work" \
    client/src/client/build/pyinstaller-kde.spec

# Create .desktop file
cat > "$BUILD_DIR/AppDir/transcriptionsuite-kde.desktop" << EOF
[Desktop Entry]
Type=Application
Name=TranscriptionSuite
Comment=Speech-to-text transcription client
Exec=TranscriptionSuite-KDE
Icon=transcriptionsuite
Categories=AudioVideo;Audio;Utility;
Terminal=false
EOF

# Copy desktop file to standard location
cp "$BUILD_DIR/AppDir/transcriptionsuite-kde.desktop" \
   "$BUILD_DIR/AppDir/usr/share/applications/"

# Create application icon (resize from logo.png: 1024x1024 → 256x256)
echo "→ Creating application icon (256x256)..."
if [[ ! -f "$PROJECT_ROOT/build/assets/logo.png" ]]; then
    echo "ERROR: logo.png not found at $PROJECT_ROOT/build/assets/logo.png"
    exit 1
fi

# Check for ImageMagick
if command -v magick &> /dev/null; then
    MAGICK_CMD="magick"
elif command -v convert &> /dev/null; then
    MAGICK_CMD="convert"
else
    echo "ERROR: ImageMagick not found. Cannot resize icon."
    echo "Install with: sudo pacman -S imagemagick"
    exit 1
fi

# Resize logo.png (1024x1024) to 256x256 for AppImage
$MAGICK_CMD "$PROJECT_ROOT/build/assets/logo.png" -resize 256x256 \
    "$BUILD_DIR/AppDir/transcriptionsuite.png"

cp "$BUILD_DIR/AppDir/transcriptionsuite.png" \
   "$BUILD_DIR/AppDir/usr/share/icons/hicolor/256x256/apps/"

# Create AppRun script
cat > "$BUILD_DIR/AppDir/AppRun" << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${LD_LIBRARY_PATH}"
exec "${HERE}/usr/bin/TranscriptionSuite-KDE" "$@"
EOF
chmod +x "$BUILD_DIR/AppDir/AppRun"

# Build AppImage
echo "→ Building AppImage..."
cd "$BUILD_DIR"
ARCH=x86_64 "$APPIMAGETOOL" AppDir "$DIST_DIR/TranscriptionSuite-KDE-x86_64.AppImage"

echo ""
echo "=================================================="
echo "✓ AppImage created: $DIST_DIR/TranscriptionSuite-KDE-x86_64.AppImage"
echo "=================================================="
