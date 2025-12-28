#!/bin/bash
# Generate multi-resolution Windows icon from logo.svg
# Creates logo.ico with 16, 32, 48, and 256 pixel sizes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$SCRIPT_DIR/assets"

echo "→ Generating multi-resolution logo.ico from logo.svg..."

# Check for ImageMagick
if command -v magick &> /dev/null; then
    MAGICK_CMD="magick"
elif command -v convert &> /dev/null; then
    MAGICK_CMD="convert"
else
    echo "ERROR: ImageMagick not found. Cannot generate .ico file."
    echo "Install with: sudo pacman -S imagemagick"
    exit 1
fi

# Generate multi-resolution .ico from PNG (preserves transparency better than SVG)
# Using logo.png as source instead of logo.svg ensures transparent background
$MAGICK_CMD "$ASSETS_DIR/logo.png" -background transparent \
    -define icon:auto-resize=256,48,32,16 \
    "$ASSETS_DIR/logo.ico"

echo "✓ Created logo.ico with sizes: 16, 32, 48, 256"
