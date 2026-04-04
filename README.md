# PodcastSync

Turn YouTube channels and playlists into self-hosted podcast feeds.

PodcastSync is a macOS menu bar app that monitors YouTube sources, downloads audio as MP3, and serves podcast RSS feeds on your local network. Subscribe to the feeds in Apple Podcasts, Overcast, Downcast, or any podcast client.

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
- [ffmpeg](https://ffmpeg.org/) — install via `brew install ffmpeg`
- (Optional) [YouTube Data API v3 key](https://console.cloud.google.com/apis/credentials) — enables full video history and handle resolution; without it, the app uses YouTube's public RSS feeds (~15 most recent videos)

## Installation

### From DMG

1. Download or build `PodcastSync.dmg`
2. Open the DMG and drag `PodcastSync.app` to Applications
3. Right-click the app → **Open** (required once, to bypass Gatekeeper for unsigned apps)
4. The app appears in your menu bar

### Development mode

```bash
git clone <repo-url>
cd "Youtube Podcast Sync"

# Set up Python environment
/usr/local/bin/python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

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
   - **Overcast**: Add URL → paste
   - **Downcast**: Add → Feed URL → paste
3. The feed URL looks like `http://192.168.x.x:8642/feed/1.xml`

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
# Bundle the Python backend (~60 min first time)
./scripts/build_backend.sh

# Build the .app and .dmg (~3 min)
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

- ffmpeg must be installed separately (not bundled)
- The app is unsigned — Gatekeeper will prompt on first launch
- YouTube's RSS feeds return only ~15 most recent videos (use an API key for full history)
- Podcast clients may cache feeds aggressively (new episodes can take up to an hour to appear)
- The server must be running for podcast clients to fetch episodes
