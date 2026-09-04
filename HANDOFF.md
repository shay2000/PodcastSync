# HANDOFF.md

## Overview
PodcastSync is a macOS menu bar app that turns YouTube channels and playlists into self-hosted podcast feeds. It has:

- a Python backend built with FastAPI
- a Swift menu bar wrapper that launches and monitors that backend
- a packaged `.app` and `.dmg` for end users

Current packaged outputs:

- `build/PodcastSync.app`
- `build/PodcastSync.dmg`

The current DMG is intended to be self-contained for end users. It bundles:

- the Python backend
- `yt-dlp`
- `ffmpeg`
- `ffprobe`

## Current state
Recent work completed:

- major frontend redesign
- shared app/browser branding icon
- bundled `ffmpeg` and `ffprobe` inside the app
- rewritten dylib paths so the packaged app does not depend on Homebrew on the target machine
- rebuilt standalone DMG packaging

## Stack
- Python 3.12 in `./venv`
- FastAPI + uvicorn
- yt-dlp
- feedgen
- APScheduler
- SQLite
- Swift / SwiftUI / MenuBarExtra
- PyInstaller

## Key files
- `backend/main.py`: FastAPI entrypoint
- `backend/services/`: source creation, sync orchestration, cookie probing, and path helpers
- `backend/downloader/`: download manager, ffmpeg discovery, and MP3 artwork helpers
- `backend/routes/api.py`: thin `/api` route aggregator
- `backend/routes/`: source, video, sync, status, settings, and cookie API routes
- `backend/routes/feeds.py`: RSS feed routes
- `backend/static/index.html`: frontend shell
- `backend/static/js/main.js`: frontend entrypoint and delegated event wiring
- `backend/static/js/`: frontend API, store, render, action, modal, and polling modules
- `backend/static/css/main.css`: frontend stylesheet entrypoint
- `backend/static/css/`: token, base, layout, and component styles
- `backend/static/app-icon.svg`: shared app/browser icon source
- `macos/PodcastSync/Sources/PodcastSyncApp.swift`: menu bar app UI
- `macos/PodcastSync/Sources/BackendProcess.swift`: backend process startup
- `scripts/dev.sh`: local dev run
- `scripts/build_backend.sh`: PyInstaller backend bundle
- `scripts/build_app.sh`: app and DMG build
- `scripts/bundle_macos_tool.sh`: bundles `ffmpeg`/`ffprobe` and rewrites dylib references
- `scripts/generate_app_icon.swift`: generates the icon raster assets

## Run locally
```bash
cd "<repo root, e.g. ~/Documents/Side Projects:Hobbies/Coding/PodcastSync>"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
./scripts/dev.sh
```

Then open:

- `http://127.0.0.1:8642`

## Running tests

Install the optional development dependencies into the project environment, then run:

```bash
source venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest tests/ -q
```

The characterization suite is offline: it uses temporary SQLite/storage paths and
replaces the YouTube fetcher and download manager after application startup.

## Build packaged app
```bash
cd "<repo root>"
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
./scripts/build_app.sh
```

Outputs:

- `build/PodcastSync.app`
- `build/PodcastSync.dmg`

## User install flow
1. Download `PodcastSync.dmg` from the GitHub Releases page.
2. Open the DMG.
3. Drag `PodcastSync.app` into Applications.
4. Right-click `PodcastSync.app` and choose `Open` on first launch because the app is ad-hoc signed, not notarized.

## Known limitations
- The app is ad-hoc signed, not notarized.
- Overcast is known not to work reliably with PodcastSync feeds. Apple Podcasts and Downcast are better-supported clients.
- Without a YouTube API key, RSS fallback only exposes roughly the latest 15 videos from a channel.
- Podcast clients cache feeds aggressively.
- The server must be running for clients to fetch feeds and audio.

## Notes
- `macos/PodcastSync/.build/` is local Swift build output and should not be committed.
- `build/` is packaging output and scratch space. The main user-facing artifact is `build/PodcastSync.dmg`.
- If packaging fails, likely causes are Swift toolchain issues, `hdiutil`, or macOS extended attributes interfering with codesign.
