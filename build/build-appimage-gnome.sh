#!/bin/bash
# Build AppImage for TranscriptionSuite GNOME dashboard
# Note: GNOME dashboard uses GTK which is harder to bundle in AppImage
# This creates a "portable" package that expects GTK to be installed on the system
#
# Architecture Note:
# The GNOME dashboard uses a dual-process architecture because GTK3 (AppIndicator3)
# and GTK4 (libadwaita) cannot coexist in the same Python process. The tray runs
# with GTK3, and the Dashboard window spawns as a separate GTK4 process.
# Communication between them happens via D-Bus.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build/appimage-gnome"
DIST_DIR="$PROJECT_ROOT/build/dist"

echo "=================================================="
echo "Building TranscriptionSuite GNOME Package"
echo "=================================================="
echo ""
echo "NOTE: The GNOME dashboard requires system GTK3, GTK4, and AppIndicator."
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
cd "$PROJECT_ROOT/dashboard"
uv sync --frozen --extra gnome

# Copy all site-packages from venv to AppImage, excluding binary packages
# that must be provided by the target system (packages with compiled .so files
# that are ABI-specific and won't work across different Python versions/systems)
SITE_PACKAGES=$(find "$PROJECT_ROOT/dashboard/.venv/lib" -type d -name "site-packages" | head -1)
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

# Copy dashboard code
echo "→ Copying dashboard code..."
cp -r "$PROJECT_ROOT/dashboard" "$BUILD_DIR/AppDir/usr/lib/python3/dist-packages/"

# Copy README files for Help menu (to AppDir root and share directory)
echo "→ Copying README files..."
cp "$PROJECT_ROOT/README.md" "$BUILD_DIR/AppDir/"
cp "$PROJECT_ROOT/README_DEV.md" "$BUILD_DIR/AppDir/"
mkdir -p "$BUILD_DIR/AppDir/usr/share/transcriptionsuite"
cp "$PROJECT_ROOT/README.md" "$BUILD_DIR/AppDir/usr/share/transcriptionsuite/"
cp "$PROJECT_ROOT/README_DEV.md" "$BUILD_DIR/AppDir/usr/share/transcriptionsuite/"

# Copy default server config.yaml (for first-run setup)
echo "→ Copying default config.yaml..."
cp "$PROJECT_ROOT/server/config.yaml" "$BUILD_DIR/AppDir/usr/share/transcriptionsuite/"

# Copy assets for About dialog (profile picture, logo)
echo "→ Copying assets..."
mkdir -p "$BUILD_DIR/AppDir/usr/share/transcriptionsuite/assets"
cp "$PROJECT_ROOT/build/assets/profile.png" "$BUILD_DIR/AppDir/usr/share/transcriptionsuite/assets/"
cp "$PROJECT_ROOT/build/assets/logo.png" "$BUILD_DIR/AppDir/usr/share/transcriptionsuite/assets/"

# Create launcher script that uses system Python with GTK
cat > "$BUILD_DIR/AppDir/usr/bin/transcriptionsuite-gnome" << 'EOF'
#!/bin/bash
# TranscriptionSuite GNOME Launcher
# Requires: python3, python3-gi, gir1.2-appindicator3-0.1, gir1.2-adw-1

SELF=$(readlink -f "$0")
HERE=${SELF%/*}
APP_DIR="${HERE}/../lib/python3/dist-packages"

# Check GTK3 + AppIndicator3 dependencies (for tray)
python3 -c "import gi; gi.require_version('Gtk', '3.0'); gi.require_version('AppIndicator3', '0.1')" 2>/dev/null
if [[ $? -ne 0 ]]; then
    echo "Error: Missing GTK3 or AppIndicator3 dependencies (required for tray)."
    echo ""
    echo "Install with:"
    echo "  Arch Linux: sudo pacman -S gtk3 libappindicator-gtk3 python-gobject"
    echo "  Ubuntu/Debian: sudo apt install python3-gi gir1.2-appindicator3-0.1"
    echo "  Fedora: sudo dnf install gtk3 libappindicator-gtk3 python3-gobject"
    exit 1
fi

# Check GTK4 + libadwaita dependencies (for Dashboard window)
python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')" 2>/dev/null
if [[ $? -ne 0 ]]; then
    echo "Warning: GTK4/libadwaita not available. Dashboard window will not work."
    echo ""
    echo "Install with:"
    echo "  Arch Linux: sudo pacman -S gtk4 libadwaita"
    echo "  Ubuntu/Debian: sudo apt install gir1.2-adw-1 gir1.2-gtk-4.0"
    echo "  Fedora: sudo dnf install gtk4 libadwaita"
    echo ""
    echo "The tray will still work, but 'Show App' will be unavailable."
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

# Add bundled packages to PYTHONPATH:
# - dashboard/src: dashboard source code
# - dist-packages: bundled Python dependencies (markdown, pyyaml, etc.)
export PYTHONPATH="${APP_DIR}/dashboard/src:${APP_DIR}:${PYTHONPATH}"
exec python3 -m dashboard "$@"
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
StartupWMClass=com.transcriptionsuite.dashboard
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

# Also create a symlink with .DirIcon for AppImage standard
ln -sf transcriptionsuite.png "$BUILD_DIR/AppDir/.DirIcon"

# Copy icon to pixmaps as well (some systems look there)
mkdir -p "$BUILD_DIR/AppDir/usr/share/pixmaps"
cp "$BUILD_DIR/AppDir/transcriptionsuite.png" \
   "$BUILD_DIR/AppDir/usr/share/pixmaps/"

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
echo "  - GTK3 and AppIndicator3 (for tray icon)"
echo "  - GTK4 and libadwaita (for Dashboard window)"
echo "  - python3-numpy (for audio processing)"
echo "  - python3-aiohttp (for HTTP client)"
echo ""
echo "The tray (GTK3) and Dashboard (GTK4) run as separate processes"
echo "and communicate via D-Bus."
echo "=================================================="
