#!/bin/bash
# Development script — run the backend directly with uvicorn
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Prefer venv if it has uvicorn; otherwise fall back to system Python locations
if [ -f "venv/bin/uvicorn" ]; then
    source venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

export PYTHONPATH="$PROJECT_DIR"

if [ "$1" = "test-fetch" ]; then
    # Test fetcher: pass a YouTube URL as $2
    shift
    python -m backend.test_fetch "$@"
else
    # Run the server
    python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port "${PODCASTSYNC_PORT:-8642}"
fi
