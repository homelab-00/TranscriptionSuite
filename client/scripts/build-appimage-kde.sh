#!/bin/bash
# Build AppImage for TranscriptionSuite KDE client
# Requires: appimagetool, pyinstaller, and the KDE client dependencies

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build/appimage-kde"
DIST_DIR="$PROJECT_ROOT/dist"

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

# Build with PyInstaller first
echo "→ Building with PyInstaller..."
cd "$PROJECT_ROOT"

# Activate venv if exists
if [[ -f "client/.venv/bin/activate" ]]; then
    source "client/.venv/bin/activate"
fi

pyinstaller --clean --distpath "$BUILD_DIR/AppDir/usr/bin" \
    --workpath "$BUILD_DIR/work" \
    --specpath "$BUILD_DIR" \
    client/build/pyinstaller-kde.spec

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

# Create a simple icon (placeholder - replace with actual icon)
# TODO: Add proper application icon
cat > "$BUILD_DIR/AppDir/transcriptionsuite.svg" << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="45" fill="#3daee9"/>
  <circle cx="50" cy="35" r="12" fill="white"/>
  <rect x="44" y="45" width="12" height="25" rx="3" fill="white"/>
</svg>
EOF

cp "$BUILD_DIR/AppDir/transcriptionsuite.svg" \
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
