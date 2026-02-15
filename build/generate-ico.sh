#!/bin/bash
# Generate raster/logo assets from SVG sources.
# Creates logo.png, logo.ico, logo.icns, logo_wide.png, and logo_wide_readme.png

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$SCRIPT_DIR/assets"

echo "→ Generating PNG/ICO assets from SVG sources..."

# Check source files
if [[ ! -f "$ASSETS_DIR/logo.svg" ]]; then
    echo "ERROR: Missing source file: $ASSETS_DIR/logo.svg"
    exit 1
fi

if [[ ! -f "$ASSETS_DIR/logo_wide.svg" ]]; then
    echo "ERROR: Missing source file: $ASSETS_DIR/logo_wide.svg"
    exit 1
fi

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

if command -v inkscape &> /dev/null; then
    SVG_RENDERER="inkscape"
    echo "→ SVG renderer: Inkscape"
else
    SVG_RENDERER="imagemagick"
    echo "→ SVG renderer: ImageMagick (high-density fallback)"
fi

render_svg_to_png_height() {
    local src_svg="$1"
    local out_png="$2"
    local target_height="$3"

    if [[ "$SVG_RENDERER" == "inkscape" ]]; then
        inkscape "$src_svg" \
            --export-type=png \
            --export-filename="$out_png" \
            --export-height="$target_height" \
            --export-background-opacity=0 \
            >/dev/null 2>&1
    else
        # Set density before loading SVG to avoid low-res rasterization then upscale.
        $MAGICK_CMD -background transparent -density 1200 "$src_svg" \
            -filter LanczosSharp -resize "x${target_height}" -strip \
            "$out_png"
    fi
}

render_svg_to_png_size() {
    local src_svg="$1"
    local out_png="$2"
    local target_width="$3"
    local target_height="$4"

    if [[ "$SVG_RENDERER" == "inkscape" ]]; then
        inkscape "$src_svg" \
            --export-type=png \
            --export-filename="$out_png" \
            --export-width="$target_width" \
            --export-height="$target_height" \
            --export-background-opacity=0 \
            >/dev/null 2>&1
    else
        # Set density before loading SVG to avoid low-res rasterization then upscale.
        $MAGICK_CMD -background transparent -density 1200 "$src_svg" \
            -filter LanczosSharp -resize "${target_width}x${target_height}" -strip \
            "$out_png"
    fi
}

# Generate high-resolution square PNG from SVG for icon pipelines.
render_svg_to_png_size "$ASSETS_DIR/logo.svg" "$ASSETS_DIR/logo.png" 1024 1024
echo "✓ Created logo.png (1024x1024)"

# Generate multi-resolution .ico from PNG (for Windows)
$MAGICK_CMD "$ASSETS_DIR/logo.png" -background transparent \
    -define icon:auto-resize=256,48,32,16 \
    "$ASSETS_DIR/logo.ico"

echo "✓ Created logo.ico with sizes: 16, 32, 48, 256"

# Generate macOS .icns icon from the master PNG.
# Uses an iconset directory with all required sizes, then converts with iconutil (macOS)
# or png2icns / ImageMagick fallback (Linux/CI).
generate_icns() {
    local src_png="$1"
    local out_icns="$2"

    # Attempt native macOS iconutil first
    if command -v iconutil &> /dev/null; then
        local iconset_dir
        iconset_dir=$(mktemp -d)/logo.iconset
        mkdir -p "$iconset_dir"
        for sz in 16 32 64 128 256 512; do
            $MAGICK_CMD "$src_png" -resize "${sz}x${sz}" "$iconset_dir/icon_${sz}x${sz}.png"
            local dbl=$((sz * 2))
            $MAGICK_CMD "$src_png" -resize "${dbl}x${dbl}" "$iconset_dir/icon_${sz}x${sz}@2x.png"
        done
        iconutil -c icns -o "$out_icns" "$iconset_dir"
        rm -rf "$(dirname "$iconset_dir")"
    elif command -v png2icns &> /dev/null; then
        # libicns tools (Linux: apt install icnsutils / pacman -S libicns)
        local tmp_dir
        tmp_dir=$(mktemp -d)
        for sz in 16 32 128 256 512 1024; do
            $MAGICK_CMD "$src_png" -resize "${sz}x${sz}" "$tmp_dir/icon_${sz}.png"
        done
        png2icns "$out_icns" "$tmp_dir"/icon_*.png
        rm -rf "$tmp_dir"
    else
        echo "⚠ Skipping .icns generation: neither iconutil (macOS) nor png2icns (libicns) found."
        echo "  Install with: sudo pacman -S libicns  OR  sudo apt install icnsutils"
        return 1
    fi
}

generate_icns "$ASSETS_DIR/logo.png" "$ASSETS_DIR/logo.icns" \
    && echo "✓ Created logo.icns (macOS app icon)" \
    || echo "⚠ logo.icns was not generated (see above)"

# Generate sharp wide-logo PNGs directly from the SVG's intrinsic geometry.
# Export by target height so width automatically follows the SVG's current trimmed bounds.
render_svg_to_png_height "$ASSETS_DIR/logo_wide.svg" "$ASSETS_DIR/logo_wide.png" 440
echo "✓ Created logo_wide.png (440px tall, aspect preserved)"

render_svg_to_png_height "$ASSETS_DIR/logo_wide.svg" "$ASSETS_DIR/logo_wide_readme.png" 880
echo "✓ Created logo_wide_readme.png (880px tall, aspect preserved)"
