#!/bin/bash
# Build the PodcastSync.app bundle and create a .dmg installer.
# Prerequisites: run build_backend.sh first.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
APP_NAME="PodcastSync"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
DMG_PATH="$BUILD_DIR/$APP_NAME.dmg"

# ---------------------------------------------------------------------------
# Step 1: Build Swift binary (release)
# ---------------------------------------------------------------------------
echo "=== Building Swift menu bar app ==="
cd "$PROJECT_DIR/macos/PodcastSync"
swift build -c release 2>&1
SWIFT_BIN="$(swift build -c release --show-bin-path)/PodcastSync"

if [ ! -f "$SWIFT_BIN" ]; then
    echo "ERROR: Swift binary not found at $SWIFT_BIN"
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 2: Assemble .app bundle
# ---------------------------------------------------------------------------
echo "=== Assembling $APP_NAME.app ==="
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# Copy Swift binary
cp "$SWIFT_BIN" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"

# Copy bundled backend (from build_backend.sh)
BACKEND_DIST="$BUILD_DIR/backend-dist/podcastsync-backend"
if [ -d "$BACKEND_DIST" ]; then
    echo "  Embedding bundled Python backend..."
    cp -r "$BACKEND_DIST" "$APP_BUNDLE/Contents/Resources/backend"
else
    echo "  WARNING: Bundled backend not found at $BACKEND_DIST"
    echo "  The app will run in development mode only."
    echo "  Run scripts/build_backend.sh first for a standalone app."
fi

# Info.plist
cat > "$APP_BUNDLE/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.podcastsync.app</string>
    <key>CFBundleName</key>
    <string>PodcastSync</string>
    <key>CFBundleDisplayName</key>
    <string>PodcastSync</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleExecutable</key>
    <string>PodcastSync</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

echo "  .app bundle created at $APP_BUNDLE"

# ---------------------------------------------------------------------------
# Step 3: Ad-hoc codesign
# ---------------------------------------------------------------------------
echo "=== Code signing (ad-hoc) ==="
xattr -cr "$APP_BUNDLE"
codesign --force --deep --sign - "$APP_BUNDLE" 2>&1
echo "  Signed."

# ---------------------------------------------------------------------------
# Step 4: Create .dmg
# ---------------------------------------------------------------------------
echo "=== Creating DMG ==="
rm -f "$DMG_PATH"

# Create a temporary directory with the app and an Applications symlink
DMG_STAGE="$BUILD_DIR/dmg-stage"
rm -rf "$DMG_STAGE"
mkdir -p "$DMG_STAGE"
cp -r "$APP_BUNDLE" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"

hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_STAGE" \
    -ov \
    -format UDZO \
    "$DMG_PATH" 2>&1

rm -rf "$DMG_STAGE"

echo ""
echo "=== Build complete! ==="
echo "  App:  $APP_BUNDLE"
echo "  DMG:  $DMG_PATH"
echo "  Size: $(du -sh "$DMG_PATH" | cut -f1)"
