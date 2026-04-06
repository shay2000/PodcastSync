# HANDOFF.md — Podcast Downloader & Hoster

## Project overview
PodcastSync is a macOS menu bar app that monitors YouTube channels/playlists, downloads audio as MP3, and serves podcast RSS feeds on the local network. It consists of a Python backend (FastAPI) and a Swift menu bar wrapper. **All milestones (M1–M6) are complete.** The app is packaged as a 67 MB `.dmg` at `build/PodcastSync.dmg`.

## Tech stack
- Python 3.9.6+ (system Python at `/usr/bin/python3`; 3.11 was originally used but the bundle runs on 3.9)
- FastAPI 0.128+ + uvicorn 0.39+ (HTTP server)
- yt-dlp 2026.3.17 + ffmpeg (audio downloading/conversion)
- google-api-python-client 2.193 (YouTube Data API v3)
- feedparser 6.0.12 (YouTube RSS/Atom feeds)
- feedgen 1.0.0 (podcast RSS generation)
- APScheduler 3.11.2 (periodic polling)
- SQLite via stdlib sqlite3
- Swift 6.3 / SwiftUI / MenuBarExtra (macOS 13+ menu bar app)
- PyInstaller 6.19.0 (Python bundling)
- Virtual environment at `./venv/`

## Architecture summary
```
Swift Menu Bar App → manages → Python Backend (FastAPI on port 8642)
                                  ├── FetcherOrchestrator (API→RSS fallback)
                                  ├── DownloadManager (yt-dlp)
                                  ├── RSSGenerator (feedgen)
                                  ├── Scheduler (APScheduler)
                                  ├── Web UI (vanilla HTML/JS/CSS)
                                  └── SQLite Database
```
- FetcherOrchestrator tries YouTubeApiFetcher first, falls back to YouTubeRssFetcher on quota/error
- Downloads stored at `~/PodcastMirror/<source-name>/<video-id>.mp3`
- DB stored at `~/.podcastsync/podcastsync.db`
- Server binds `0.0.0.0:8642` for LAN access

## Repository structure
```
PodcastSync/
├── backend/
│   ├── __init__.py              # Package marker
│   ├── config.py                # Settings dataclass, env var loading, LAN IP detection
│   ├── database.py              # SQLite manager with migration runner
│   ├── downloader.py            # yt-dlp wrapper, download queue, sync_source()
│   ├── main.py                  # FastAPI app, lifespan, startup/shutdown
│   ├── models.py                # Pydantic API models (SourceCreate, VideoResponse, etc.)
│   ├── rss_generator.py         # Podcast RSS feed generation via feedgen
│   ├── scheduler.py             # APScheduler AsyncIOScheduler setup
│   ├── test_fetch.py            # CLI test script for fetcher pipeline
│   ├── fetcher/
│   │   ├── __init__.py          # Re-exports FetcherOrchestrator, VideoInfo
│   │   ├── base.py              # ABC YouTubeSourceFetcher, VideoInfo dataclass, QuotaExceededError
│   │   ├── api_fetcher.py       # YouTube Data API v3 with pagination + duration fetching
│   │   ├── rss_fetcher.py       # YouTube RSS/Atom feed parser via feedparser (~15 items)
│   │   ├── orchestrator.py      # API-first with RSS fallback coordinator
│   │   └── url_parser.py        # YouTube URL → (source_type, youtube_id) parser
│   ├── routes/
│   │   ├── __init__.py          # Package marker
│   │   ├── api.py               # REST API: sources CRUD, sync, status, settings
│   │   ├── feeds.py             # GET /feed/{id}.xml, GET /feeds
│   │   └── audio.py             # GET /audio/{source_id}/{filename} with path traversal protection
│   ├── migrations/
│   │   └── 001_initial.sql      # Schema: sources, videos, settings tables
│   └── static/
│       ├── index.html           # Web UI single-page app
│       ├── style.css            # Dark/light mode, system font stack
│       └── app.js               # Vanilla JS: source management, polling, feed URL copy
├── macos/
│   └── PodcastSync/
│       ├── Package.swift        # Swift Package Manager config (macOS 13+)
│       └── Sources/
│           ├── PodcastSyncApp.swift    # @main with MenuBarExtra, menu items
│           └── BackendProcess.swift    # Python process lifecycle, health checks
├── scripts/
│   ├── dev.sh                   # Dev mode: run uvicorn with --reload
│   ├── build_backend.sh         # PyInstaller bundle (output: build/backend-dist/)
│   └── build_app.sh             # Assemble .app + codesign + create .dmg
├── build/                       # (gitignored) Build artifacts
│   ├── PodcastSync.app          # Assembled app bundle (157 MB)
│   └── PodcastSync.dmg          # Distribution image (67 MB)
├── pyproject.toml               # Python project config with dependencies
├── requirements.txt             # Pinned dependencies
├── .gitignore                   # Python, macOS, env, build exclusions
├── HANDOFF.md                   # This file
└── README.md                    # User-facing documentation
```

## Completed milestones
1. **M1: Core Backend — Fetching & Database** — Config, database with migrations, Pydantic models, all fetcher components (ABC, URL parser, API fetcher, RSS fetcher, orchestrator). Tested with real MKBHD channel.
2. **M2: Download Pipeline** — yt-dlp integration: bestaudio→MP3 192kbps, thumbnail embed, concurrent downloads via asyncio semaphore, deduplication, sanitize_filename(), sync_source(). Tested: MP3 files created with embedded cover art.
3. **M3: RSS Feeds + HTTP Server** — feedgen podcast RSS, FastAPI routes for feeds/audio/API, FileResponse with path traversal protection. Tested: valid RSS in Apple Podcasts.
4. **M4: Scheduler + Web UI** — APScheduler AsyncIOScheduler, vanilla JS web UI with source management, settings, status polling, feed URL copy.
5. **M5: macOS Menu Bar App** — Swift/SwiftUI MenuBarExtra with BackendProcess lifecycle management, health checks, dev-mode uvicorn detection, project root auto-discovery.
6. **M6: Packaging as .dmg** — PyInstaller backend bundle (157 MB), .app assembly with Info.plist + LSUIElement, ad-hoc codesign (with xattr cleanup), hdiutil DMG creation (67 MB).

## Current milestone
**Done.** All milestones complete.

## Next steps (optional enhancements)
1. Test with YouTube API key set (API fetcher + handle resolution)
2. Add retention/cleanup for old episodes (per-source `retention_days`)
3. Add `POST /api/update-ytdlp` endpoint to update yt-dlp when downloads start failing
4. Add SSE endpoint for real-time download progress in web UI
5. Bundle ffmpeg binary inside the .app for fully self-contained distribution
6. Add "Launch at Login" via SMAppService

## Key decisions log
1. **MP3 at 192kbps** over M4A — universal podcast client compatibility; YouTube audio already lossy
2. **API-primary, RSS-fallback** — API gives full history + duration; RSS free but ~15 items. Fallback on QuotaExceededError
3. **Bind 0.0.0.0** for LAN access — firewall prompts once; needed so podcast apps on other devices can subscribe
4. **APScheduler 3.x** — 4.x still alpha with unstable API
5. **UC→UU fallback** for uploads playlist in RSS-only mode; canonical API call when key available
6. **SQLite** via stdlib — lightweight, no ORM overhead, sufficient for single-user local app
7. **Python 3.11.6** at /usr/local/bin/python3.11 (system Python is 3.9.6, too old)
8. **PyInstaller --onedir** over --onefile — faster startup, allows static asset copy into bundle
9. **xattr -cr before codesign** — macOS cp leaves resource forks that break ad-hoc signing
10. **findProjectRoot() walks up from executable** — replaced #filePath (compile-time only) with runtime discovery for dev mode

## Known issues / blockers
- ffmpeg must be installed separately (`brew install ffmpeg`) — not bundled in the .dmg
- YouTube API key not tested end-to-end (RSS fallback confirmed working)
- PyInstaller build takes ~60 minutes on first run (cached subsequent runs are faster)
- The app is unsigned — macOS Gatekeeper will prompt; right-click → Open to bypass
- The original Python 3.11 Homebrew installation has been removed; the project now runs on Python 3.9.6 (system Python). The `venv/` was recreated with Python 3.9.6 and all packages installed. `pyproject.toml` updated to `requires-python = ">=3.9"`.
- The `build/` directory was cleaned up (Apr 2026): removed numbered intermediates (PodcastSync 2/3/4.app, PodcastSync 2.dmg). The canonical working build is `build/PodcastSync.dmg` + `build/PodcastSync.app` (arm64, Python 3.9, ~56 MB DMG). Confirmed: backend starts, all HTTP endpoints return 200 OK.

## Environment & setup
```bash
# Development
cd "/Users/shayprasad/Documents/Coding/Youtube Podcast Sync"
# Python 3.9.6 (system) works — the Homebrew Python 3.11 is no longer present
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Optional: set YouTube API key
export YOUTUBE_API_KEY="your-key-here"

# Run server in dev mode (with hot reload)
./scripts/dev.sh
# Then open http://127.0.0.1:8642 in browser

# Build .app + .dmg
./scripts/build_backend.sh   # ~60 min first time
./scripts/build_app.sh       # ~3 min
# Output: build/PodcastSync.dmg

# Install from DMG
open build/PodcastSync.dmg
# Drag PodcastSync.app to Applications
# Right-click → Open (first launch, to bypass Gatekeeper)
```

## External dependencies / credentials
- **YOUTUBE_API_KEY** — YouTube Data API v3 key. Set as env var or configured via web UI (stored in SQLite settings table). Optional: app falls back to RSS feeds without it.
- **ffmpeg** — Required for yt-dlp audio extraction. Install via `brew install ffmpeg`. Located at `/usr/local/bin/ffmpeg` on this machine.
