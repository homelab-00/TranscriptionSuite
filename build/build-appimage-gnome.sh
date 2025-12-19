#!/bin/bash
# Build AppImage for TranscriptionSuite GNOME client
# Note: GNOME client uses GTK which is harder to bundle in AppImage
# This creates a "portable" package that expects GTK to be installed on the system

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build/appimage-gnome"
DIST_DIR="$PROJECT_ROOT/dist"

echo "=================================================="
echo "Building TranscriptionSuite GNOME Package"
echo "=================================================="
echo ""
echo "NOTE: The GNOME client requires system GTK3 and AppIndicator."
echo "This builds a portable package, not a fully standalone AppImage."
echo ""

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/AppDir/usr/bin"
mkdir -p "$BUILD_DIR/AppDir/usr/lib/python3/dist-packages"
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

# Copy client code
echo "→ Copying client code..."
cp -r "$PROJECT_ROOT/client" "$BUILD_DIR/AppDir/usr/lib/python3/dist-packages/"

# Create launcher script that uses system Python with GTK
cat > "$BUILD_DIR/AppDir/usr/bin/transcriptionsuite-gnome" << 'EOF'
#!/bin/bash
# TranscriptionSuite GNOME Launcher
# Requires: python3, python3-gi, gir1.2-appindicator3-0.1, python3-pyaudio

SELF=$(readlink -f "$0")
HERE=${SELF%/*}
APP_DIR="${HERE}/../lib/python3/dist-packages"

# Check dependencies
python3 -c "import gi; gi.require_version('Gtk', '3.0'); gi.require_version('AppIndicator3', '0.1')" 2>/dev/null
if [[ $? -ne 0 ]]; then
    echo "Error: Missing GTK3 or AppIndicator3 dependencies."
    echo ""
    echo "Install with:"
    echo "  Arch Linux: sudo pacman -S gtk3 libappindicator-gtk3 python-gobject"
    echo "  Ubuntu/Debian: sudo apt install python3-gi gir1.2-appindicator3-0.1"
    echo "  Fedora: sudo dnf install gtk3 libappindicator-gtk3 python3-gobject"
    exit 1
fi

export PYTHONPATH="${APP_DIR}:${PYTHONPATH}"
exec python3 -m client --platform gnome "$@"
EOF
chmod +x "$BUILD_DIR/AppDir/usr/bin/transcriptionsuite-gnome"

# Create .desktop file
cat > "$BUILD_DIR/AppDir/transcriptionsuite-gnome.desktop" << EOF
[Desktop Entry]
Type=Application
Name=TranscriptionSuite
Comment=Speech-to-text transcription client
Exec=transcriptionsuite-gnome
Icon=transcriptionsuite
Categories=AudioVideo;Audio;Utility;
Terminal=false
EOF

cp "$BUILD_DIR/AppDir/transcriptionsuite-gnome.desktop" \
   "$BUILD_DIR/AppDir/usr/share/applications/"

# Create icon (placeholder)
cat > "$BUILD_DIR/AppDir/transcriptionsuite.svg" << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="45" fill="#ff7800"/>
  <circle cx="50" cy="35" r="12" fill="white"/>
  <rect x="44" y="45" width="12" height="25" rx="3" fill="white"/>
</svg>
EOF

cp "$BUILD_DIR/AppDir/transcriptionsuite.svg" \
   "$BUILD_DIR/AppDir/usr/share/icons/hicolor/256x256/apps/"

# Create AppRun
cat > "$BUILD_DIR/AppDir/AppRun" << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
exec "${HERE}/usr/bin/transcriptionsuite-gnome" "$@"
EOF
chmod +x "$BUILD_DIR/AppDir/AppRun"

# Build AppImage
echo "→ Building AppImage..."
cd "$BUILD_DIR"
ARCH=x86_64 "$APPIMAGETOOL" AppDir "$DIST_DIR/TranscriptionSuite-GNOME-x86_64.AppImage"

echo ""
echo "=================================================="
echo "✓ AppImage created: $DIST_DIR/TranscriptionSuite-GNOME-x86_64.AppImage"
echo ""
echo "NOTE: This AppImage requires system GTK3 and AppIndicator3."
echo "It is NOT fully standalone like the KDE version."
echo "=================================================="
