# AGENTS.md

Guidance for AI agents and developers working in the PodcastSync repository. Read `README.md` (user-facing features) and `HANDOFF.md` (release/ops state) alongside this file.

## What this project is

PodcastSync is a macOS 13+ **menu bar app** that turns YouTube channels/playlists into self-hosted podcast RSS feeds. A Python backend (FastAPI) monitors sources, downloads audio as MP3 via yt-dlp, and serves podcast RSS + audio over the LAN on port 8642. A thin SwiftUI `MenuBarExtra` wrapper launches and supervises the backend. Release artifacts (`.app`, `.dmg`) are built by shell scripts and CI.

Key product facts:
- One RSS feed per source at `/feed/{source_id}.xml`; audio at `/audio/{source_id}/{video_id}.mp3`.
- No API auth on the server; it binds `0.0.0.0` and is intended for a personal LAN. Never expose it publicly.
- Without a YouTube Data API key it falls back to YouTube public RSS (only ~15 most-recent videos, no durations). API key enables handle resolution, full history, durations.
- Audio files live under `~/PodcastMirror/<sanitized-source-name>/<video_id>.mp3`; SQLite DB at `~/.podcastsync/podcastsync.db`.

## Repository layout

```
backend/                  Python FastAPI backend (the real product logic)
  main.py                 Composition root: FastAPI app, lifespan, router/static mounts
  config.py               Settings dataclass (env vars + DB-stored overrides)
  database.py             Raw sqlite3 access + migration runner
  models.py               Pydantic request/response models
  scheduler.py            APScheduler wrapper
  rss_generator.py        Podcast RSS/XML generation (feedgen)
  _resources.py           Dev vs PyInstaller resource path resolution
  migrations/*.sql        Numbered schema migrations (001, 002, 003)
  routes/                 Thin HTTP layer. api.py aggregates /api/*; feeds.py & audio.py
                          are mounted at root in main.py (NOT under /api)
  services/               Business logic: sources, sync, paths, cookies
  fetcher/                YouTube metadata: url_parser, rss_fetcher, api_fetcher, orchestrator
  downloader/             DownloadManager (yt-dlp), ffmpeg discovery, MP3 artwork
  static/                 Vanilla-JS web UI + CSS (no framework, no bundler)
  test_fetch.py           Manual CLI harness — NOT a pytest module (excluded by testpaths)
macos/PodcastSync/        SwiftUI menu bar app (SwiftPM executable target, 2 source files)
scripts/                  dev.sh, build_backend.sh (PyInstaller), build_app.sh (.app + .dmg),
                          bundle_macos_tool.sh (ffmpeg/dylibs), generate_app_icon.swift
tests/                    Hermetic offline characterization suite (pytest + httpx)
.github/workflows/        build-release.yml — tag-push / manual release build on macos-14
build/                    Local packaging output — git-ignored
```

## Commands

Run from repo root. The repo path contains spaces; always quote it.

```bash
# Dev server (backend + web UI at http://127.0.0.1:8642, --reload enabled)
./scripts/dev.sh

# Manual fetcher CLI (requires a real YouTube URL; hits live network/DB)
./scripts/dev.sh test-fetch "<youtube-url>"     # same as: python -m backend.test_fetch <url>

# Tests (need a venv with Python >= 3.10; system python is 3.9 — create one first)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
python -m pytest tests/ -q

# Swift menu bar app in dev mode (spawns its own uvicorn from venv — don't run with dev.sh)
(cd macos/PodcastSync && swift build)   # then run the binary; or open via SPM

# Full package build (.app + .dmg into build/)
./scripts/build_app.sh
# The Swift app + menu bar backend can also be run/debugged via the DMG install + debug_app.sh

# One-off packaging pieces
./scripts/build_backend.sh               # PyInstaller onedir into build/backend-dist/
./scripts/bundle_macos_tool.sh <bin> <root>   # bundle one Homebrew binary + dylibs
```

### Environment variables

Backend `Settings` (env-first, then DB-stored overrides for the starred ones):
- `YOUTUBE_API_KEY` — Google Data API v3 key (optional; enables full fetcher)
- `PODCASTSYNC_STORAGE` — default `~/PodcastMirror`
- `PODCASTSYNC_DB` — default `~/.podcastsync/podcastsync.db`
- `PODCASTSYNC_PORT` — default `8642`
- `PODCASTSYNC_POLL_INTERVAL` — minutes, default `30`
- `PODCASTSYNC_MAX_DOWNLOADS` — default `2`
- `PODCASTSYNC_FFMPEG` — set by the Swift launcher when bundling; else discovered from PATH/Homebrew
- `PODCASTSYNC_PROJECT_ROOT` / `PODCASTSYNC_VENV` — used by Swift launcher and packaging

DB-stored settings that override env at startup (via `settings` table): `youtube_api_key`, `poll_interval_minutes`, `server_port`, `storage_path`, `max_concurrent_downloads`, `cookies_from_browser`, `cookies_file_path`.

## Backend architecture

### Startup flow (`backend/main.py`)

`lifespan()` builds everything and hangs it off `app.state`: `settings`, `db`, `orchestrator`, `download_manager`, `scheduler`. Routes pull collaborators from `request.app.state.*` per request — **never** from module globals or a DI container. This indirection is a hard contract: the test suite stubs fetcher/downloader by replacing `app.state.orchestrator` / `app.state.download_manager` after lifespan startup (see Testing). Preserve it when refactoring.

Router mounting order matters: `/api` aggregate, feeds, audio, then **StaticFiles at `/` LAST** (it would shadow later routes).

### Layering

- `routes/` — HTTP only. Handlers are `async def`, no `Depends()`; deps come from `request.app.state`. `backend/routes/api.py` owns `prefix="/api"` and includes sources, videos, sync, status, settings, cookies. `feeds.py` and `audio.py` are included directly in `main.py` (no `/api` prefix) because they serve XML/files.
- `services/` — orchestration + DTOs. `create_source` (URL parse → resolve handles → enrich channel metadata → insert), `sync_source`/`sync_all_sources` (fetch metadata → dedupe insert videos → process pending downloads), `paths` (sanitize filename, output dirs, audio path resolution), `cookies` (yt-dlp cookie probing/testing).
- `fetcher/` — `url_parser` (channel/@handle/custom/user/playlist shapes; single `/watch` and `/shorts` deliberately rejected), `rss_fetcher` (public feeds, ~15 items, no durations), `api_fetcher` (YouTube Data API, paginated, batch durations, resolves handles), `orchestrator` (API first, falls back to RSS on any failure incl. quota; returns `[]` if both fail).
- `downloader/` — `DownloadManager` runs yt-dlp in a thread (`run_in_executor`), `bestaudio` → MP3 192k via `FFmpegExtractAudio`, file named `<video_id>.mp3` in the per-source dir, optional channel-icon embedding (mutagen APIC), cooperative cancel, `asyncio.Semaphore` concurrency, rolling delete of old episodes.

### Database

Raw `sqlite3` (no ORM), single shared connection (`check_same_thread=False`, WAL). Migration runner applies `migrations/NNN_*.sql` in lexical order; version stored in `settings` table (`schema_version`). Tables: `sources`, `videos` (`UNIQUE(source_id, video_id)`), `settings` (key/value). All helpers commit per statement. Video `download_status` ∈ pending|downloading|completed|failed|skipped|deleted.

### API surface

```
GET/POST   /api/sources                    POST returns 201
GET/PATCH/DELETE /api/sources/{source_id}  DELETE 204; PATCH partial via model_dump(exclude_unset=True)
GET        /api/sources/{source_id}/videos             newest first, DB row shape (no file_path)
DELETE     /api/sources/{source_id}/videos/{video_db_id}        → status 'skipped' (204)
DELETE     /api/sources/{source_id}/videos/{video_db_id}/file   removes file + sets 'deleted' (204)
POST       /api/sources/{source_id}/videos/{video_db_id}/requeue → 'pending' (204)
POST       /api/sources/{source_id}/sync    202 — background task
POST       /api/sync-all                    202
POST       /api/downloads/cancel-all
GET        /api/downloads/progress          keyed by video DB id
GET        /api/status
GET/PATCH  /api/settings                    GET never returns the API key, only youtube_api_key_set
POST       /api/pick-directory              osascript choose folder (macOS only)
GET        /api/cookies/detect
POST       /api/cookies/test
GET        /feed/{source_id}.xml            RSS (completed videos only), Cache-Control max-age=300
GET        /feeds                           feed metadata list
GET        /audio/{source_id}/{filename}    path-traversal guarded (403 outside storage root)
GET        /                                static web UI
```

Route conventions: `source_id` = DB row id; `video_id` = YouTube string; `video_db_id` = DB row id of a video; `{filename}` = `<youtube_id>.mp3`. Errors: `HTTPException(404/403/400)` with `detail`, no global handler. Success JSON is ad-hoc dicts; typed routes set `response_model`.

## Frontend (backend/static)

Vanilla ES modules, no framework/bundler/package.json. `index.html` loads `js/main.js?v=N`; all JS/CSS cache-busting is **manual** (`?v=9` in `index.html`) — bump it when changing assets.

- `js/store.js` — single mutable state singleton + subscribe/notify pub/sub.
- `js/api.js` — `api(method, path, body)` fetch wrapper; throws `Error(error.detail)` on non-2xx.
- `js/poll.js` — polling timers (status/sources every 5s, download progress every 1s), reload helpers.
- `js/render/*` — pure innerHTML template-literal renderers.
- `js/actions/*` — imperative handlers for data-action dispatch; `js/ui/*` — modals, toasts.
- `js/main.js` — composition root: one delegated `click` listener switches on `event.target.closest("[data-action]")`; ids via `data-source-id` / `data-video-id`; a delegated `change` listener handles enabled toggles. New interactive elements must follow the `data-action` convention.

CSS: `css/main.css` is a `@import` manifest, BUT `css/overrides.css` re-imports the monolithic legacy `style.css` **last**, so `style.css` (1,808 lines) wins most specificity ties. The modular `tokens.css`/`base.css`/`layout.css`/`components/*` files are mostly shadowed scaffolding mid-refactor. If a visual change "does nothing", the rule you need probably lives in `style.css`. Frontend text is escaped with `esc()` (does NOT escape double quotes) — don't put user text into double-quoted attributes without care.

## Swift menu bar app (macos/PodcastSync)

`PodcastSyncApp.swift` = `@main App` + `MenuBarExtra` UI (status, Open Web UI, Sync All, cookie status, Start/Stop server, Quit). `BackendProcess.swift` (`@MainActor ObservableObject`) starts at `init()`: resolves the PyInstaller backend (`Contents/Resources/backend/podcastsync-backend`) or dev uvicorn, strips `com.apple.quarantine` xattrs, sets `PODCASTSYNC_FFMPEG` + PATH for bundled `tools/bin`, spawns the process, and health-checks `GET /api/status` every 3s (cookie probe every ~60s). No auto-restart: a crash leaves the menu in "Stopped" until the user starts it.

## Packaging

Build pipeline: `build_app.sh` → `build_backend.sh` (PyInstaller onedir `podcastsync-backend`, `--collect-all feedgen`, long explicit `--hidden-import` list), generates the icon, `swift build -c release`, assembles `Contents/MacOS/PodcastSync` + `Contents/Resources/backend` + `Contents/Resources/tools/{bin,lib}` (ffmpeg/ffprobe via `bundle_macos_tool.sh`, Homebrew dylibs rewritten to `@loader_path`/`@executable_path`), writes Info.plist (`LSUIElement=true`), ad-hoc codesigns inside-out, and builds the DMG via hdiutil.

Hard cross-file contracts to keep in sync when changing packaging:
- Bundle layout: `Resources/backend/…` + `Resources/tools/bin` is assumed by `BackendProcess.swift:39-44`, `build_app.sh`, and `backend/downloader/ffmpeg.py` `_bundled_ffmpeg_candidates`.
- **New backend module imported lazily → add it to the `--hidden-import` list in `build_backend.sh`**, or it will be missing only in the packaged app.
- New non-Python resource dirs must be copied in `build_backend.sh` and be consistent with `backend/_resources.py` (`sys._MEIPASS/backend/<rel>`).
- Version is single-sourced from `pyproject.toml`, overridden by `PODCASTSYNC_VERSION` in CI (git tag minus `v`). Keep tag, pyproject version, and the workflow's default `release_tag` aligned.

CI (`.github/workflows/build-release.yml`) runs on `macos-14` (arm64; the app is native-arch, no universal binary), Python 3.12, installs deps + ffmpeg, runs `pytest tests/ -q`, then `build_app.sh`, uploads DMG + sha256 artifact, and publishes via `gh release` (ad-hoc signed, un-notarized; no secrets configured).

## Code conventions

- Imports: absolute `backend.`-prefixed everywhere (no relative imports). `from __future__ import annotations` first statement in nearly every module.
- Heavy deps are imported lazily inside functions to keep startup fast: `yt_dlp` (~60s import), `googleapiclient`, `feedgen`/lxml. Do not move them to module scope.
- DB rows are `sqlite3.Row`; services convert to DTO dicts (`*_dto` naming) validated by Pydantic at the route boundary. Internally collaborators are typed loosely (`Any`) for testability.
- Error handling: catch narrowly + `logger.exception` where tracebacks are useful; background sync failures are logged and swallowed per-source; routes raise HTTPException. Non-fatal enrichment (channel icon, uploads playlist) is intentionally fail-open.
- Python floor is 3.10 (uses modern builtin generics). Style follows the existing flat snake_case modules; no linter/formatter config is checked in.

## Testing

Hermetic offline characterization suite. Run: `python -m pytest tests/ -q` (config in `pyproject.toml`: `asyncio_mode=auto`, `testpaths=["tests"]`).

- `tests/conftest.py` sets `PODCASTSYNC_DB`/`PODCASTSYNC_STORAGE` to per-test `tmp_path`, `PODCASTSYNC_POLL_INTERVAL=1440`, `YOUTUBE_API_KEY=""`, then imports `backend.main`.
- httpx `AsyncClient` over `ASGITransport` (lifespan NOT auto-run): the `api` fixture drives `app.router.lifespan_context(app)` for real migrations + startup, then **swaps `app.state.orchestrator`/`app.state.download_manager` for `StubOrchestrator`/`StubDownloadManager`** that record calls. This works only because routes read `request.app.state` per request.
- New tests must follow the same pattern — never hit the network, never construct real fetchers/downloaders, fake MP3 bytes on disk via the `seeded` fixture, keep fixtures function-scoped.
- If you change call signatures of `fetch_videos`/`resolve_to_channel_id`/`process_pending_downloads`/`cancel_all`/etc., update the stubs in lockstep (tests assert recorded call tuples).

## Known gotchas & risks

- **Rolling delete (`max_keep_episodes`) looks inverted**: `get_overflow_completed_videos` orders by `publish_date ASC … OFFSET max_keep`, and downloads proceed oldest-first, so a keep-N source may delete freshly-downloaded episodes and keep the oldest N. Verify semantics before relying on this feature (untested).
- Migrations run via `executescript` with no lock/transaction; two concurrent starts can crash on duplicate `ALTER TABLE`. Migration 003 does a fragile full `videos` table rebuild that depends on exact column order.
- `database.py` `update_source`/`update_video_status` build dynamic SQL from `**fields` (internal callers only; don't expose unfiltered request keys).
- Shared single sqlite connection + synchronous DB calls inside async handlers is fine under single-worker uvicorn but blocks the event loop on heavy queries; do not add multi-worker/multi-thread concurrency without revisiting.
- `Settings.load_from_db` parses DB values with bare `int()`/`Path()` — a corrupt `settings` row can crash startup. `Settings.from_env()` also has eager side effects (mkdir of `~/.podcastsync`).
- Dependency drift: `requirements.txt` pins `yt-dlp>=2026.01.01` and includes `mutagen`/`pyinstaller`, while `pyproject.toml` says `yt-dlp>=2024.01.01` and omits `mutagen` (artwork would break under a pure `pip install -e .`). Keep both files aligned.
- Feed `guid` is a bare YouTube ID (not a URL) and `base_url` in settings (LAN IP) differs from the request-derived base used for feed/audio URLs.
- Overcast is an unsupported podcast client; Apple Podcasts/Downcast are the reference clients.
- No auth on any HTTP endpoint (LAN only). Audio route's only guard is path containment.
- Frontend: legacy `style.css` shadows the modular CSS (above); no frontend tests; cache-buster `?v=` must be bumped; keep `data-action` names in sync between HTML/JS.
