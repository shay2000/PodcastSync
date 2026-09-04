#!/bin/bash
# Debug script to run PodcastSync app from the .dmg and capture errors

set -x  # Print all commands

echo "=== PodcastSync Debug ==="
echo ""

# Check if app is in Applications
if [ -d "/Applications/PodcastSync.app" ]; then
    APP_PATH="/Applications/PodcastSync.app"
    echo "Found app at: $APP_PATH"
else
    echo "ERROR: PodcastSync.app not found in /Applications"
    exit 1
fi

# Check for bundled backend
BACKEND_PATH="$APP_PATH/Contents/Resources/backend/podcastsync-backend"
if [ -f "$BACKEND_PATH" ]; then
    echo "✓ Bundled backend exists: $BACKEND_PATH"
    file "$BACKEND_PATH"
    ls -lah "$BACKEND_PATH"
else
    echo "✗ Bundled backend NOT found at: $BACKEND_PATH"
    echo "  Available Resources:"
    ls -la "$APP_PATH/Contents/Resources/" 2>/dev/null || echo "  (no Resources directory)"
fi

echo ""
echo "=== Checking system dependencies ==="

# Check ffmpeg
if command -v ffmpeg &> /dev/null; then
    echo "✓ ffmpeg: $(ffmpeg -version | head -1)"
else
    echo "✗ ffmpeg: NOT FOUND (required!)"
    echo "  Install with: brew install ffmpeg"
fi

# Check Python (only needed to rebuild the bundled backend; the app is self-contained)
if command -v python3.12 &> /dev/null; then
    echo "✓ python3.12: $(python3.12 --version)"
else
    echo "✗ python3.12: NOT FOUND (only needed for local rebuilds; not required to run the app)"
fi

echo ""
echo "=== Attempting to run backend directly ==="

if [ -f "$BACKEND_PATH" ]; then
    echo "Running: $BACKEND_PATH"
    "$BACKEND_PATH" 2>&1 | head -20
    echo "[... truncated]"
else
    echo "Cannot test—backend not found"
fi

echo ""
echo "=== Check if app code-signed properly ==="
codesign -v "$APP_PATH" 2>&1

echo ""
echo "Done."
