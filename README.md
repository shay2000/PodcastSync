# PodcastSync

![Platform](https://img.shields.io/badge/platform-macOS%2013%2B-111827?style=flat-square)
![App Type](https://img.shields.io/badge/app-menu%20bar-0f766e?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-166534?style=flat-square)
![Status](https://img.shields.io/badge/status-active-9a3412?style=flat-square)
![Release](https://img.shields.io/badge/release-v0.2.0-1473e6?style=flat-square)
![Downloads](https://img.shields.io/badge/downloads-68.7MB-ec4899?style=flat-square)

Turn YouTube channels and playlists into self-hosted podcast feeds.

PodcastSync is a macOS menu bar app that monitors YouTube sources, downloads audio as MP3, and serves podcast RSS feeds on your local network. Subscribe to the feeds in Apple Podcasts, Downcast, or another podcast client on your LAN.

## Features

- **Add YouTube channels or playlists** — paste a URL, the app handles the rest
- **Automatic polling** — checks for new videos on a configurable schedule (default: every 30 minutes)
- **Audio-only downloads** — extracts audio as MP3 at 192kbps with embedded cover art
- **Podcast RSS feeds** — one feed per source, valid for any podcast client
- **LAN accessible** — feed URLs work from any device on your network
- **Web UI** — manage sources, trigger syncs, copy feed URLs from your browser
- **Menu bar app** — runs quietly in the background, no Dock icon

## Requirements

- macOS 13 (Ventura) or later
- (Optional) [YouTube Data API v3 key](https://console.cloud.google.com/apis/credentials) — enables full video history and handle resolution; without it, the app uses YouTube's public RSS feeds (~15 most recent videos)

## Installation

### From DMG

1. Download the latest `PodcastSync.dmg` from the [GitHub Releases page](https://github.com/shay2000/PodcastSync/releases) or build it locally
2. Open the DMG and drag `PodcastSync.app` to Applications
3. Right-click the app → **Open** (required once, to bypass Gatekeeper for this ad-hoc signed app)
4. The app appears in your menu bar

The packaged DMG bundles the Python backend, `yt-dlp`, `ffmpeg`, and `ffprobe`, so end users do not need to install Homebrew, Python, or extra media tools first.

### Development mode

```bash
git clone <repo-url>
cd "Youtube Podcast Sync"

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Development mode still expects ffmpeg on the local machine
brew install ffmpeg

# Run the backend directly
./scripts/dev.sh
# Open http://127.0.0.1:8642 in your browser
```

## Usage

### Adding a source

1. Click the menu bar icon → **Open Web UI**
2. Paste a YouTube URL into the "Add Source" form:
   - Channel: `https://www.youtube.com/@mkbhd` or `https://www.youtube.com/channel/UCBJycsmduvYEL83R_U4JriQ`
   - Playlist: `https://www.youtube.com/playlist?list=PLxxxxxxx`
3. Set a name (optional) and max backfill count
4. Click **Add**, then **Sync Now**

### Subscribing in a podcast app

1. In the web UI, click **Copy Feed URL** next to a source
2. In your podcast app:
   - **Apple Podcasts**: File → Subscribe to Show by URL → paste the URL
   - **Downcast**: Add → Feed URL → paste
3. The feed URL looks like `http://192.168.x.x:8642/feed/1.xml`

Overcast disclaimer:
Overcast is known to not work reliably with PodcastSync feeds at the moment. Use Apple Podcasts or Downcast instead.

### Setting up the YouTube API key

The API key is optional but recommended — it enables:
- Resolving `@handle` URLs to channel IDs
- Fetching full video history (not just the last ~15)
- Getting video duration metadata

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a project and enable the **YouTube Data API v3**
3. Create an API key (no OAuth required)
4. In the PodcastSync web UI, go to **Settings** and paste the key

## Building

```bash
# Install Python dependencies for the backend and the packager
pip install -r requirements.txt

# Ensure ffmpeg is available on the build machine so it can be bundled
brew install ffmpeg

# Build a fresh self-contained .app and .dmg
./scripts/build_app.sh

# Output: build/PodcastSync.dmg
```

## How it works

1. **Fetcher layer** checks YouTube for new videos (API first, RSS fallback)
2. **Download manager** uses yt-dlp to extract audio as MP3 at 192kbps with embedded thumbnails
3. **RSS generator** creates valid podcast XML with `<enclosure>` tags pointing to the local server
4. **HTTP server** (FastAPI on port 8642) serves the RSS feeds and audio files
5. **Scheduler** (APScheduler) runs the fetch→download cycle on a timer
6. **Menu bar app** (Swift) manages the Python backend process

## File locations

| What | Where |
|------|-------|
| Audio files | `~/PodcastMirror/<source-name>/` |
| Database | `~/.podcastsync/podcastsync.db` |
| Server | `http://0.0.0.0:8642` |

## Legal / ToS considerations

- YouTube Data API usage with an API key is within Google's Terms of Service
- YouTube's public RSS feeds are intended for consumption
- Audio downloading is performed by yt-dlp as a user-controlled action
- Downloaded content is served only on your local network and is not redistributed
- **This tool is for personal use only** — respect content creators' rights

## Known limitations

- The app is ad-hoc signed, not notarized, so Gatekeeper will prompt on first launch
- Building the DMG still requires `ffmpeg` on the machine doing the build; the finished DMG bundles it for end users
- Overcast is known to not work reliably with PodcastSync feeds
- YouTube's RSS feeds return only ~15 most recent videos (use an API key for full history)
- Podcast clients may cache feeds aggressively (new episodes can take up to an hour to appear)
- The server must be running for podcast clients to fetch episodes
