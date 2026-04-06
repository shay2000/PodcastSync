#!/bin/bash
# Build a standalone PodcastSync.app bundle and create a branded DMG installer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
APP_NAME="PodcastSync"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
DMG_PATH="$BUILD_DIR/$APP_NAME.dmg"
ICONSET_DIR="$BUILD_DIR/$APP_NAME.iconset"
ICON_MASTER_PNG="$BUILD_DIR/$APP_NAME-1024.png"
ICON_TIFF_DIR="$BUILD_DIR/$APP_NAME.icon-tiff"
ICON_FAMILY_TIFF="$BUILD_DIR/$APP_NAME.icon-family.tiff"
ICON_FILE="$BUILD_DIR/$APP_NAME.icns"
TOOLS_SCRIPT="$SCRIPT_DIR/bundle_macos_tool.sh"
SWIFT_CACHE_DIR="$BUILD_DIR/swift-cache"
PREBUILT_APP_BIN="$BUILD_DIR/$APP_NAME.app/Contents/MacOS/$APP_NAME"
FALLBACK_LAUNCHER_BIN="$BUILD_DIR/$APP_NAME-launcher"

mkdir -p "$BUILD_DIR"
mkdir -p "$SWIFT_CACHE_DIR/clang" "$SWIFT_CACHE_DIR/swiftpm"

if [ -x "$PREBUILT_APP_BIN" ]; then
    cp "$PREBUILT_APP_BIN" "$FALLBACK_LAUNCHER_BIN"
fi

echo "=== Building bundled backend ==="
"$SCRIPT_DIR/build_backend.sh"

echo "=== Generating app icon ==="
CLANG_MODULE_CACHE_PATH="$SWIFT_CACHE_DIR/clang" \
swift "$SCRIPT_DIR/generate_app_icon.swift" "$ICONSET_DIR"
rm -f "$ICON_FILE"
sips -s format png "$ICONSET_DIR/icon_512x512@2x.png" --out "$ICON_MASTER_PNG" >/dev/null
rm -rf "$ICON_TIFF_DIR"
mkdir -p "$ICON_TIFF_DIR"
for size in 16 32 48 128 256 512 1024; do
    sips -z "$size" "$size" -s format tiff "$ICON_MASTER_PNG" \
        --out "$ICON_TIFF_DIR/icon-${size}.tiff" >/dev/null
done
tiffutil -cat \
    "$ICON_TIFF_DIR/icon-16.tiff" \
    "$ICON_TIFF_DIR/icon-32.tiff" \
    "$ICON_TIFF_DIR/icon-48.tiff" \
    "$ICON_TIFF_DIR/icon-128.tiff" \
    "$ICON_TIFF_DIR/icon-256.tiff" \
    "$ICON_TIFF_DIR/icon-512.tiff" \
    "$ICON_TIFF_DIR/icon-1024.tiff" \
    -out "$ICON_FAMILY_TIFF" >/dev/null
tiff2icns "$ICON_FAMILY_TIFF" "$ICON_FILE" >/dev/null

echo "=== Building Swift menu bar app ==="
cd "$PROJECT_DIR/macos/PodcastSync"
SWIFT_BIN=""

if CLANG_MODULE_CACHE_PATH="$SWIFT_CACHE_DIR/clang" \
   SWIFTPM_MODULECACHE_OVERRIDE="$SWIFT_CACHE_DIR/swiftpm" \
   swift build -c release 2>&1; then
    SWIFT_BIN="$(
        CLANG_MODULE_CACHE_PATH="$SWIFT_CACHE_DIR/clang" \
        SWIFTPM_MODULECACHE_OVERRIDE="$SWIFT_CACHE_DIR/swiftpm" \
        swift build -c release --show-bin-path
    )/PodcastSync"
fi

if [ -z "$SWIFT_BIN" ] || [ ! -f "$SWIFT_BIN" ]; then
    if [ -x "$FALLBACK_LAUNCHER_BIN" ]; then
        echo "  Reusing existing menu bar launcher binary at $FALLBACK_LAUNCHER_BIN"
        SWIFT_BIN="$FALLBACK_LAUNCHER_BIN"
    else
        echo "ERROR: Swift launcher build failed and no prebuilt launcher binary is available."
        exit 1
    fi
fi

echo "=== Assembling $APP_NAME.app ==="
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

cp "$SWIFT_BIN" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"
cp "$ICON_FILE" "$APP_BUNDLE/Contents/Resources/$APP_NAME.icns"

BACKEND_DIST="$BUILD_DIR/backend-dist/podcastsync-backend"
if [ ! -d "$BACKEND_DIST" ] || [ ! -x "$BACKEND_DIST/podcastsync-backend" ]; then
    echo "ERROR: Bundled backend not found at $BACKEND_DIST"
    exit 1
fi
echo "  Embedding bundled Python backend..."
cp -R "$BACKEND_DIST" "$APP_BUNDLE/Contents/Resources/backend"

echo "=== Bundling ffmpeg and ffprobe ==="
FFMPEG_BIN="$(command -v ffmpeg || true)"
FFPROBE_BIN="$(command -v ffprobe || true)"
TOOLS_ROOT="$APP_BUNDLE/Contents/Resources/tools"

if [ -z "$FFMPEG_BIN" ] || [ -z "$FFPROBE_BIN" ]; then
    echo "ERROR: ffmpeg and ffprobe must be installed on the build machine."
    exit 1
fi

rm -rf "$TOOLS_ROOT"
"$TOOLS_SCRIPT" "$FFMPEG_BIN" "$TOOLS_ROOT"
"$TOOLS_SCRIPT" "$FFPROBE_BIN" "$TOOLS_ROOT"

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
    <key>CFBundleIconFile</key>
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

echo "=== Code signing (ad-hoc) ==="
xattr -cr "$APP_BUNDLE"
codesign --force --deep --sign - "$APP_BUNDLE" 2>&1
echo "  Signed."

echo "=== Creating DMG ==="
rm -f "$DMG_PATH"

DMG_STAGE="$BUILD_DIR/dmg-stage"
RW_DMG="$BUILD_DIR/$APP_NAME-temp.dmg"
TMP_RSRC="$BUILD_DIR/$APP_NAME.rsrc"
rm -rf "$DMG_STAGE"
rm -f "$RW_DMG" "$TMP_RSRC"
mkdir -p "$DMG_STAGE"
cp -R "$APP_BUNDLE" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"
cp "$ICON_FILE" "$DMG_STAGE/.VolumeIcon.icns"

hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_STAGE" \
    -ov \
    -format UDRW \
    "$RW_DMG" 2>&1

MOUNT_POINT="$(hdiutil attach -readwrite -noverify -noautoopen "$RW_DMG" | awk '/\/Volumes\// {print $3; exit}')"
if [ -z "$MOUNT_POINT" ]; then
    echo "ERROR: Failed to mount $RW_DMG"
    exit 1
fi

cp "$ICON_FILE" "$MOUNT_POINT/.VolumeIcon.icns"
SetFile -a V "$MOUNT_POINT/.VolumeIcon.icns"
SetFile -a C "$MOUNT_POINT"
bless --folder "$MOUNT_POINT" --openfolder "$MOUNT_POINT" >/dev/null 2>&1 || true
hdiutil detach "$MOUNT_POINT" >/dev/null

hdiutil convert "$RW_DMG" -ov -format UDZO -o "$DMG_PATH" 2>&1

sips -i "$ICON_FILE" >/dev/null
DeRez -only icns "$ICON_FILE" > "$TMP_RSRC"
Rez -append "$TMP_RSRC" -o "$DMG_PATH"
SetFile -a C "$DMG_PATH"

rm -rf "$DMG_STAGE"
rm -f "$RW_DMG" "$TMP_RSRC"

echo ""
echo "=== Build complete! ==="
echo "  App:  $APP_BUNDLE"
echo "  DMG:  $DMG_PATH"
echo "  Size: $(du -sh "$DMG_PATH" | cut -f1)"
