#!/bin/bash
# Bundle the Python backend into a standalone directory using PyInstaller.
# Output: build/backend-dist/podcastsync-backend/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
VENV_DIR="${PODCASTSYNC_VENV:-$PROJECT_DIR/venv}"
PYTHON_BIN="$VENV_DIR/bin/python"
PYINSTALLER_CONFIG_DIR="$BUILD_DIR/pyinstaller-config"

cd "$PROJECT_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: Python virtual environment not found at $VENV_DIR"
    echo "Create it first, then install the project requirements."
    exit 1
fi

if ! "$PYTHON_BIN" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "ERROR: PyInstaller is not installed in $VENV_DIR"
    echo "Run: $PYTHON_BIN -m pip install -r requirements.txt"
    exit 1
fi

echo "=== Bundling Python backend with PyInstaller ==="
echo "  Using Python: $PYTHON_BIN"

rm -rf "$BUILD_DIR/backend-dist" "$BUILD_DIR/backend-build"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

PYINSTALLER_CONFIG_DIR="$PYINSTALLER_CONFIG_DIR" \
"$PYTHON_BIN" -m PyInstaller \
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

DIST="$BUILD_DIR/backend-dist/podcastsync-backend"
if [ ! -x "$DIST/podcastsync-backend" ]; then
    echo "ERROR: Expected backend executable not found at $DIST/podcastsync-backend"
    exit 1
fi

echo "=== Copying static assets ==="
mkdir -p "$DIST/_internal/backend"
cp -r "$PROJECT_DIR/backend/static" "$DIST/_internal/backend/static"
cp -r "$PROJECT_DIR/backend/migrations" "$DIST/_internal/backend/migrations"

echo "=== Backend bundle created at $DIST ==="
echo "  Size: $(du -sh "$DIST" | cut -f1)"
