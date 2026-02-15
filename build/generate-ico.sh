#!/bin/bash
# Generate multi-resolution Windows icon from logo.svg
# Creates logo.ico with 16, 32, 48, and 256 pixel sizes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$SCRIPT_DIR/assets"

echo "→ Generating logo.png and logo.ico from logo.svg..."

# Check for ImageMagick
if command -v magick &> /dev/null; then
    MAGICK_CMD="magick"
elif command -v convert &> /dev/null; then
    MAGICK_CMD="convert"
else
    echo "ERROR: ImageMagick not found. Cannot generate icon files."
    echo "Install with: sudo pacman -S imagemagick"
    exit 1
fi

# Generate high-resolution PNG from SVG (for Linux AppImage icon)
$MAGICK_CMD -background transparent "$ASSETS_DIR/logo.svg" -resize 1024x1024 "$ASSETS_DIR/logo.png"
echo "✓ Created logo.png (1024x1024)"

# Generate multi-resolution .ico from PNG (for Windows)
$MAGICK_CMD "$ASSETS_DIR/logo.png" -background transparent \
    -define icon:auto-resize=256,48,32,16 \
    "$ASSETS_DIR/logo.ico"

echo "✓ Created logo.ico with sizes: 16, 32, 48, 256"
