#!/bin/bash
# Generate platform-specific icons from a source PNG (1024x1024).
# Requires: ImageMagick (convert) and png2icns (macOS) or icotool (Linux).
#
# Usage: ./generate-icons.sh source-1024.png

set -e
SRC="${1:-icon-1024.png}"

if [ ! -f "$SRC" ]; then
  echo "Usage: $0 <source-1024.png>"
  echo "Provide a 1024x1024 PNG as input."
  exit 1
fi

echo "Generating icons from $SRC..."

# PNG sizes for electron-builder (Linux)
for SIZE in 16 24 32 48 64 128 256 512 1024; do
  convert "$SRC" -resize ${SIZE}x${SIZE} "icon-${SIZE}.png"
  echo "  icon-${SIZE}.png"
done

# Copy main sizes
cp icon-256.png icon.png
cp icon-16.png tray-icon.png

# Windows .ico (multi-resolution)
if command -v convert &> /dev/null; then
  convert icon-16.png icon-24.png icon-32.png icon-48.png icon-64.png icon-128.png icon-256.png icon.ico
  echo "  icon.ico"
fi

# macOS .icns
if command -v png2icns &> /dev/null; then
  png2icns icon.icns icon-16.png icon-32.png icon-128.png icon-256.png icon-512.png icon-1024.png
  echo "  icon.icns"
elif command -v iconutil &> /dev/null; then
  # macOS native method
  ICONSET="HomePilot.iconset"
  mkdir -p "$ICONSET"
  cp icon-16.png "$ICONSET/icon_16x16.png"
  cp icon-32.png "$ICONSET/icon_16x16@2x.png"
  cp icon-32.png "$ICONSET/icon_32x32.png"
  cp icon-64.png "$ICONSET/icon_32x32@2x.png"
  cp icon-128.png "$ICONSET/icon_128x128.png"
  cp icon-256.png "$ICONSET/icon_128x128@2x.png"
  cp icon-256.png "$ICONSET/icon_256x256.png"
  cp icon-512.png "$ICONSET/icon_256x256@2x.png"
  cp icon-512.png "$ICONSET/icon_512x512.png"
  cp icon-1024.png "$ICONSET/icon_512x512@2x.png"
  iconutil -c icns "$ICONSET"
  rm -rf "$ICONSET"
  echo "  icon.icns"
fi

echo "Done!"
