#!/bin/bash
APP="/Applications/TranscriptionSuite.app"
echo ""
echo "TranscriptionSuite — quarantine removal helper"
echo "================================================"
echo ""
if [[ ! -d "$APP" ]]; then
  echo "⚠️  TranscriptionSuite.app was not found in /Applications."
  echo "   Please copy the app from this DMG to /Applications first,"
  echo "   then run this script again."
  echo ""
  read -rp "Press Enter to close..."
  exit 1
fi
echo "→ Removing quarantine attribute from $APP..."
xattr -dr com.apple.quarantine "$APP"
echo ""
echo "✓ Done! You can now open TranscriptionSuite normally."
echo ""
read -rp "Press Enter to close..."
