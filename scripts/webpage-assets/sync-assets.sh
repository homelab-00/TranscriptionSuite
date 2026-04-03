#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEBPAGE_REPO="${1:-$(realpath "$SCRIPT_DIR/../../../TypeScript_Projects/TranscriptionSuite_Webpage")}"
R2_BUCKET="${R2_BUCKET:-transcriptionsuite-assets}"

echo "=== Webpage repo: ${WEBPAGE_REPO} ==="
echo "=== R2 bucket:    ${R2_BUCKET} ==="
echo ""

# Check the webpage repo exists
if [ ! -d "$WEBPAGE_REPO/src/assets/screenshots" ]; then
  echo "ERROR: Webpage repo not found at ${WEBPAGE_REPO}"
  echo "Usage: $0 [path-to-webpage-repo]"
  exit 1
fi

echo "=== Step 1: Capturing screenshots ==="
cd "$SCRIPT_DIR"
SCREENSHOT_OUTPUT_DIR="${WEBPAGE_REPO}/src/assets/screenshots" npx playwright test capture-screenshots.ts
echo ""

echo "=== Step 2: Recording videos ==="
npx playwright test record-videos.ts
echo ""

echo "=== Step 3: Uploading videos to R2 ==="
if ! command -v wrangler &> /dev/null; then
  echo "WARNING: wrangler CLI not found. Skipping R2 upload."
  echo "Install with: npm install -g wrangler"
  echo "Then run: wrangler r2 object put ${R2_BUCKET}/videos/<file> --file <path>"
else
  for f in "$SCRIPT_DIR/output/videos"/*.webm; do
    [ -f "$f" ] || continue
    echo "Uploading $(basename "$f")..."
    wrangler r2 object put "${R2_BUCKET}/videos/$(basename "$f")" --file "$f"
  done
fi
echo ""

echo "=== Done ==="
echo "Screenshots → ${WEBPAGE_REPO}/src/assets/screenshots/"
echo "Videos      → R2 bucket '${R2_BUCKET}' (if wrangler was available)"
