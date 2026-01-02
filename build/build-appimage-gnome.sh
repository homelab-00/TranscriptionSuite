#!/bin/bash
# Build AppImage for TranscriptionSuite GNOME client
# Note: GNOME client uses GTK which is harder to bundle in AppImage
# This creates a "portable" package that expects GTK to be installed on the system

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build/appimage-gnome"
DIST_DIR="$PROJECT_ROOT/build/dist"

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

# Install Python dependencies using uv
echo "→ Installing Python dependencies..."
cd "$PROJECT_ROOT/client"
uv sync --frozen --extra gnome

# Copy all site-packages from venv to AppImage, excluding binary packages
# that must be provided by the target system (packages with compiled .so files
# that are ABI-specific and won't work across different Python versions/systems)
SITE_PACKAGES=$(find "$PROJECT_ROOT/client/.venv/lib" -type d -name "site-packages" | head -1)
if [[ -d "$SITE_PACKAGES" ]]; then
    echo "→ Copying dependencies from $SITE_PACKAGES (excluding packages with compiled extensions)"
    for item in "$SITE_PACKAGES"/*; do
        basename=$(basename "$item")
        # Skip packages with compiled extensions (must be system-provided)
        if [[ "$basename" == numpy* ]] || \
           [[ "$basename" == aiohttp* ]] || \
           [[ "$basename" == multidict* ]] || \
           [[ "$basename" == yarl* ]] || \
           [[ "$basename" == frozenlist* ]]; then
            echo "  Skipping $basename (system package required)"
            continue
        fi
        cp -r "$item" "$BUILD_DIR/AppDir/usr/lib/python3/dist-packages/"
    done
else
    echo "ERROR: Could not find site-packages directory in venv"
    exit 1
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

# Check for packages with compiled extensions (required, can't be bundled)
python3 -c "import numpy" 2>/dev/null
if [[ $? -ne 0 ]]; then
    echo "Error: Missing numpy."
    echo ""
    echo "Install with:"
    echo "  Arch Linux: sudo pacman -S python-numpy"
    echo "  Ubuntu/Debian: sudo apt install python3-numpy"
    echo "  Fedora: sudo dnf install python3-numpy"
    exit 1
fi

python3 -c "import aiohttp" 2>/dev/null
if [[ $? -ne 0 ]]; then
    echo "Error: Missing aiohttp."
    echo ""
    echo "Install with:"
    echo "  Arch Linux: sudo pacman -S python-aiohttp"
    echo "  Ubuntu/Debian: sudo apt install python3-aiohttp"
    echo "  Fedora: sudo dnf install python3-aiohttp"
    exit 1
fi

export PYTHONPATH="${APP_DIR}/client/src:${PYTHONPATH}"
exec python3 -m client "$@"
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
echo "NOTE: This AppImage requires system packages:"
echo "  - GTK3 and AppIndicator3 (for UI)"
echo "  - python3-numpy (for audio processing)"
echo "  - python3-aiohttp (for HTTP client)"
echo "It is NOT fully standalone like the KDE version."
echo "=================================================="
