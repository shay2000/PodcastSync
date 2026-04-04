#!/bin/bash
# Bundle the Python backend into a standalone directory using PyInstaller.
# Output: build/backend-dist/podcastsync-backend/
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"

cd "$PROJECT_DIR"
source venv/bin/activate

echo "=== Bundling Python backend with PyInstaller ==="

# Clean previous builds
rm -rf "$BUILD_DIR/backend-dist" "$BUILD_DIR/backend-build"

pyinstaller \
    --name podcastsync-backend \
    --distpath "$BUILD_DIR/backend-dist" \
    --workpath "$BUILD_DIR/backend-build" \
    --specpath "$BUILD_DIR" \
    --noconfirm \
    --collect-all feedgen \
    --hidden-import uvicorn.logging \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.protocols.http.h11_impl \
    --hidden-import uvicorn.protocols.http.httptools_impl \
    --hidden-import uvicorn.lifespan.on \
    --hidden-import uvicorn.lifespan.off \
    --hidden-import backend.routes.api \
    --hidden-import backend.routes.feeds \
    --hidden-import backend.routes.audio \
    --hidden-import backend.fetcher.api_fetcher \
    --hidden-import backend.fetcher.rss_fetcher \
    --hidden-import backend.fetcher.orchestrator \
    --hidden-import backend.fetcher.url_parser \
    backend/main.py

# Copy static files and migrations into the bundle
DIST="$BUILD_DIR/backend-dist/podcastsync-backend"
echo "=== Copying static assets ==="
mkdir -p "$DIST/_internal/backend"
cp -r "$PROJECT_DIR/backend/static" "$DIST/_internal/backend/static"
cp -r "$PROJECT_DIR/backend/migrations" "$DIST/_internal/backend/migrations"

echo "=== Backend bundle created at $DIST ==="
echo "  Size: $(du -sh "$DIST" | cut -f1)"
