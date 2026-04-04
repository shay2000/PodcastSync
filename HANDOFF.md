# HANDOFF.md — Podcast Downloader & Hoster

## Project overview
PodcastSync is a macOS app that monitors YouTube channels/playlists, downloads audio as MP3, and serves podcast RSS feeds on the local network. It consists of a Python backend (FastAPI) and a Swift menu bar app wrapper. Currently M1 (core fetching & database) is complete and tested.

## Tech stack
- Python 3.11.6 (at `/usr/local/bin/python3.11`)
- FastAPI + uvicorn (HTTP server)
- yt-dlp + ffmpeg (audio downloading/conversion)
- google-api-python-client (YouTube Data API v3)
- feedparser (YouTube RSS/Atom feeds)
- feedgen (podcast RSS generation)
- APScheduler 3.x (periodic polling)
- SQLite via stdlib sqlite3
- Swift/SwiftUI for macOS menu bar app (M5)
- Virtual environment at `./venv/`

## Architecture summary
```
Swift Menu Bar App → manages → Python Backend (FastAPI)
                                  ├── FetcherOrchestrator (API→RSS fallback)
                                  ├── DownloadManager (yt-dlp)
                                  ├── RSSGenerator (feedgen)
                                  ├── Scheduler (APScheduler)
                                  └── SQLite Database
```
- FetcherOrchestrator tries YouTubeApiFetcher first, falls back to YouTubeRssFetcher on quota/error
- Downloads stored at ~/PodcastMirror/<source-name>/<video-id>.mp3
- DB stored at ~/.podcastsync/podcastsync.db

## Repository structure
```
PodcastSync/
├── backend/
│   ├── __init__.py              # Package marker
│   ├── config.py                # Settings dataclass, env var loading, LAN IP detection
│   ├── database.py              # SQLite manager with migration runner
│   ├── models.py                # Pydantic API models (SourceCreate, VideoResponse, etc.)
│   ├── test_fetch.py            # CLI test script for M1 fetcher pipeline
│   ├── fetcher/
│   │   ├── __init__.py          # Re-exports FetcherOrchestrator, VideoInfo
│   │   ├── base.py              # ABC YouTubeSourceFetcher, VideoInfo dataclass, QuotaExceededError
│   │   ├── api_fetcher.py       # YouTube Data API v3 implementation with pagination
│   │   ├── rss_fetcher.py       # YouTube RSS/Atom feed parser via feedparser
│   │   ├── orchestrator.py      # API-first with RSS fallback coordinator
│   │   └── url_parser.py        # YouTube URL → (source_type, youtube_id) parser
│   ├── routes/
│   │   └── __init__.py          # (empty, routes to be added in M3)
│   ├── migrations/
│   │   └── 001_initial.sql      # Schema: sources, videos, settings tables
│   └── static/                  # (empty, web UI to be added in M4)
├── macos/
│   └── PodcastSync/             # (empty, Swift app to be added in M5)
├── scripts/
│   └── dev.sh                   # Development run script (uvicorn + test-fetch mode)
├── pyproject.toml               # Python project config with dependencies
├── requirements.txt             # Pinned dependencies
├── .gitignore                   # Python, macOS, env exclusions
└── HANDOFF.md                   # This file
```

## Completed milestones
1. **M1: Core Backend — Fetching & Database** — Project scaffolding, config, database with migrations, Pydantic models, all four fetcher components (base ABC, URL parser, API fetcher, RSS fetcher, orchestrator). Tested: RSS fetcher returns real MKBHD videos, database insert + dedup works, URL parser handles all YouTube URL formats.

## Current milestone
**M2: Download Pipeline** — Implement yt-dlp integration for audio-only downloading with MP3 conversion, metadata embedding, cover art, progress tracking, and de-duplication.

## Next steps (ordered)
1. Implement `backend/downloader.py` — yt-dlp wrapper with: bestaudio→MP3 192kbps, thumbnail embedding, progress hooks, concurrent downloads via asyncio semaphore, sanitize_filename(), sync_source() function
2. Implement `backend/rss_generator.py` — feedgen podcast RSS with proper enclosure tags, MIME types, durations
3. Implement `backend/routes/api.py` — Sources CRUD, sync trigger, status endpoint
4. Implement `backend/routes/feeds.py` — GET /feed/{source_id}.xml, GET /feeds
5. Implement `backend/routes/audio.py` — Serve MP3 files with Range support
6. Implement `backend/main.py` — FastAPI app with lifespan, mount routers + static
7. Implement `backend/scheduler.py` — APScheduler AsyncIOScheduler
8. Build web UI in `backend/static/` (index.html, style.css, app.js)
9. Build Swift menu bar app in `macos/PodcastSync/`
10. Package as .dmg

## Key decisions log
1. **MP3 at 192kbps** over M4A — universal podcast client compatibility; YouTube audio already lossy
2. **API-primary, RSS-fallback** — API gives full history + duration; RSS free but ~15 items. Fallback on QuotaExceededError
3. **Bind 0.0.0.0** for LAN access — firewall prompts once; needed so podcast apps on other devices can subscribe
4. **APScheduler 3.x** — 4.x still alpha with unstable API
5. **UC→UU fallback** for uploads playlist in RSS-only mode; canonical API call when key available
6. **SQLite** via stdlib — lightweight, no ORM overhead, sufficient for single-user local app
7. **Python 3.11.6** at /usr/local/bin/python3.11 (system Python is 3.9.6, too old)

## Known issues / blockers
- YouTube API key not yet tested (RSS fallback confirmed working)
- ffmpeg must be installed for yt-dlp MP3 conversion (`brew install ffmpeg`)

## Environment & setup
```bash
cd "/Users/shayprasad/Documents/Coding/Youtube Podcast Sync"
/usr/local/bin/python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Optional: set YouTube API key
export YOUTUBE_API_KEY="your-key-here"

# Test fetcher
PYTHONPATH="." python -m backend.test_fetch "https://www.youtube.com/@mkbhd"

# Run server (once M3 is complete)
./scripts/dev.sh
```

## External dependencies / credentials
- **YOUTUBE_API_KEY** — YouTube Data API v3 key. Set as env var or configured via web UI (stored in SQLite settings table). Optional: app falls back to RSS feeds without it.
- **ffmpeg** — Required for yt-dlp audio extraction. Install via `brew install ffmpeg`.
