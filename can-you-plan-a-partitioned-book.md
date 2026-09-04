# PodcastSync — Structural Refactor

## Context

PodcastSync works. This refactor is driven by craft, not by a fire: the codebase has
accumulated duplication, mixed concerns, and two frontend monoliths that make every
edit heavier than it should be. Nothing about the app's behavior should change.

Concretely, the problems worth fixing:

| Area | Problem |
|---|---|
| `backend/static/app.js` (1,337 lines) | 14 mutable module globals; rendering via `innerHTML` template strings; ~25 inline `onclick=`/`onchange=` handlers that force every function to stay global |
| `backend/static/style.css` (1,808 lines, 214 rules) | Essentially no section structure — only the auth panel is marked |
| `backend/routes/api.py` (445 lines) | Six concerns in one file (sources CRUD, videos, sync, status, settings, yt-dlp cookie probing); source-serialization dict repeated 4× (5× counting `feeds.py`); settings-response dict repeated 2×; raw SQL inline in `get_status` |
| `backend/downloader.py` (412 lines) | ffmpeg discovery + quarantine clearing + filename sanitizing + `DownloadManager` + `sync_source` orchestration in one module |
| No service layer | Routes wire `db` + `orchestrator` + `download_manager` themselves; the sync-all loop is duplicated verbatim in `main.py:56-64` and `api.py:229-235` |
| No tests | `backend/test_fetch.py` is a manual CLI script; pytest isn't a dependency |

**Success criterion:** the app does exactly what it did before, and the code reads better.

## Constraints

1. **Behavior-preserving.** No new features, no UI changes, no API contract changes.
   Every phase ends with the app working identically.
2. **No build step.** Native ES modules (`<script type="module">`) and plain CSS. A
   bundler would complicate `build_app.sh`/PyInstaller for zero gain on a LAN app.
3. **PyInstaller hidden-imports must track every new module.**
   [`scripts/build_backend.sh:49-55`](scripts/build_backend.sh:49) enumerates
   `--hidden-import backend.routes.api`, `backend.fetcher.*`, etc. A new backend module
   that isn't registered there produces an `ImportError` **only in the packaged app** —
   dev mode will look fine. This is the single biggest risk in the plan.
4. Frontend assets need no build change: `build_backend.sh:66` does `cp -r backend/static`,
   so new `js/` and `css/` subdirectories are bundled automatically.

---

## Phase 0 — Commit the pending work

There are 644 uncommitted lines across 11 files (cookie auth panel, delete/re-queue
actions, download progress bars, build script changes). Commit them first so the
refactor diff is reviewable in isolation. Do not fold feature work into refactor commits.

## Phase 1 — Characterization tests

Pin current behavior *before* changing structure, so later phases are verifiable rather
than hopeful.

Add to `pyproject.toml` as an optional dev group (not runtime deps, keeps the PyInstaller
bundle unchanged):

```
[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "httpx"]
```

**`tests/conftest.py`** — an app fixture that never touches the network or yt-dlp:

- Point `PODCASTSYNC_DB` and `PODCASTSYNC_STORAGE` at `tmp_path` via `monkeypatch.setenv`.
  `Settings.from_env()` ([config.py:44](backend/config.py:44)) already reads both, so no
  production code needs to change to become testable.
- Drive the app through `httpx.ASGITransport` so `lifespan` runs (migrations apply,
  `app.state` populates).
- **After** startup, replace `app.state.orchestrator` and `app.state.download_manager`
  with stubs. This is what keeps tests offline and fast — the real orchestrator would hit
  YouTube and the real download manager would invoke yt-dlp/ffmpeg.

**Tests (~18).** API-level, asserting on shape and DB effects:

- Sources: empty list; create with a direct `/channel/UC…` URL → 201 with `enabled` as a
  bool and `video_count`/`completed_count` present; create with garbage URL → 400;
  get/patch/delete; 404s for unknown ids.
- Videos: list; skip → status `skipped`; delete-file → status `deleted` **and** file gone
  from disk; requeue → status `pending`.
- Status & settings: `/api/status` shape; `PATCH /api/settings` persists to the `settings`
  table and is reflected by a following `GET`.
- Feeds: `GET /feed/{id}.xml` → 200, `application/rss+xml`, contains an `<enclosure>` with
  the expected `/audio/{source_id}/{video_id}.mp3` URL and the itunes namespace. Assert on
  structure, **not** a golden file — `feedgen` emits a `lastBuildDate` that changes per run.
- Audio: 200 for a file placed under the storage path; 404 for missing; traversal attempt
  (`..%2F`) is rejected.
- Pure units (cheap, high value): `sanitize_filename`, and `parse_youtube_url` across its
  URL forms ([fetcher/url_parser.py](backend/fetcher/url_parser.py)).

Gate: this suite must be green before Phase 2, and after every phase thereafter.

---

## Phase 2 — Frontend: `app.js` → ES modules

New tree under `backend/static/js/`:

| Module | Contents |
|---|---|
| `api.js` | `api()` fetch wrapper, `getSettings()` cache, `buildFeedUrl()`, `isLocalOrigin()` |
| `format.js` | `esc`, `formatNumber`, `formatFileSize`, `parseAppDate`, `timeAgo`, `formatSyncAge`, `formatDate`, `deriveDisplayNameFromUrl`, `normalizeDownloadStatus` |
| `store.js` | The 14 globals behind one `state` object + `getSourceById`, `replaceSource`, `ensureSelectedSource`, `hasSourceDataChanged` (the `sourceSignature` diff), and `subscribe`/`notify` |
| `render/sources.js` | `renderOverview`, `renderSourceGrid`, `renderSourceArtMarkup`, `buildSourceSummary`, `getPalette`, `SOURCE_PALETTES` |
| `render/detail.js` | `renderDetail`, `syncDetailTabUi`, `updateDetailFeedUrl` |
| `render/episodes.js` | `renderDetailVideos`, `showEpisodeLoading` |
| `actions/sources.js` | `patchSource`, `syncSource`, `toggleEnabled`, `deleteSource`, `saveDetailPath/Keep/Enabled` |
| `actions/videos.js` | `skipVideo`, `deleteVideoFile`, `requeueVideo` |
| `actions/settings.js` | Cookie/auth panel (`detectBrowserCookies`, `selectCookieBrowser`, `testCookies`, `clearTestResult`), API-key and poll-interval saves |
| `ui/modals.js` | `openAddSource`/`close*`, `syncModalState`, backdrop + Escape handling |
| `ui/toast.js` | `toast` |
| `poll.js` | `loadSources`, `loadStatus`, `refreshProgress`, `startPolling` |
| `main.js` | Entry point: all `addEventListener` wiring, store subscriptions, `startPolling()` |

`index.html`: `<script src="app.js">` → `<script type="module" src="js/main.js">`.

### The dependency cycle — this is the crux

A naive split creates `store → render → actions → store`. Files would move without the
coupling improving. Break it with one rule:

- **Actions never import renderers.** They mutate the store and call the API. The store
  notifies subscribers synchronously; `main.js` registers the renderers as subscribers.
- Today `patchSource`, `toggleEnabled`, and `selectSource` call `renderAll(true)` directly.
  After the change they call `store.replaceSource(x)` and the render happens via
  notification. Behavior is identical **provided notification is synchronous** — keep it so.

### Killing the inline handlers

Under ES modules nothing is global, so all ~25 inline `onclick=`/`onchange=` attributes
break — both the static ones in `index.html` and the ones generated inside template strings
in `renderSourceGrid`, `renderDetailVideos`, and `detectBrowserCookies`. Convert both to
one delegated listener:

```
<!-- before -->  <button onclick="openSettings()">
<!-- after  -->  <button data-action="open-settings">

<!-- before -->  onclick="selectSource(${source.id})"
<!-- after  -->  data-action="select-source" data-source-id="${source.id}"
```

`main.js` registers a single `click` listener (and one `change` listener) on `document`
that dispatches on `event.target.closest('[data-action]').dataset`. This also removes the
`event.stopPropagation()` juggling in the tile actions — the delegated handler naturally
resolves to the innermost matching `data-action` first.

### Deliberately out of scope

`renderSourceGrid` and `renderDetailVideos` rebuild entire lists via `innerHTML` on every
5-second poll. That is *why* `loadSources` carries the elaborate signature-diffing and why
`safeSetInputValue` guards on `document.activeElement`. Do **not** rewrite this into
incremental DOM updates — it is a behavior-risk rewrite, not a refactor. Move the diff
logic into `store.js` as the named `hasSourceDataChanged` and leave the strategy alone.

Rename the unnamed boolean threaded through `renderAll(forceInputs)` →
`renderDetail(forceInputs)` → `safeSetInputValue(…, force)` to
`renderAll({ resetInputs: true })`. Same behavior, states the intent ("selection changed,
so clobbering input values is safe").

## Phase 3 — Frontend: `style.css` → `css/`

Split into `backend/static/css/`: `tokens.css` (`:root` custom properties, reset),
`base.css` (element defaults, typography, scrollbars), `layout.css` (app shell, header,
library grid, detail columns, the 1200px breakpoint that `app.js` also keys off), and
`components/`: `buttons.css`, `source-tile.css`, `detail-panel.css`, `episodes.css`,
`modal.css`, `forms.css`, `auth-panel.css` (the already-marked block at
[style.css:1521-1674](backend/static/style.css:1521)), `toast.css`.

`main.css` `@import`s them in order; `index.html` keeps a single `<link>`.

**Cascade order is the risk here.** 214 rules written top-to-bottom almost certainly
contain later-wins overrides. Grouping a rule "correctly" into its component file can flip
which declaration wins. Therefore:

- Extract in **source order** — walk the file and cut at natural contiguous block
  boundaries. Since it was written top-down, component grouping and order preservation will
  usually coincide.
- Where a rule is *not* contiguous with its component (a straggler override appearing later
  in the file), do **not** hoist it into the component file. Put it in an explicit
  `overrides.css` imported last, with a comment noting its original position. Honest and safe.
- Verify by concatenating the files in `@import` order and diffing against the original with
  whitespace and comments normalized. For a clean partition this diff is empty — a strong,
  cheap check. Then confirm visually with before/after screenshots at desktop and mobile widths.

---

## Phase 4 — Backend: split `routes/api.py`

Split by concern, keeping `routes/api.py` as a thin aggregator that `include_router`s the
children under `/api` so [main.py:86](backend/main.py:86) needs no change:

- `routes/sources.py` — list / add / get / patch / delete
- `routes/videos.py` — list, skip, delete-file, requeue
- `routes/sync.py` — trigger sync, sync-all, cancel-all, progress
- `routes/status.py` — status
- `routes/settings.py` — settings get/patch, pick-directory
- `routes/cookies.py` — detect/test endpoints only; the yt-dlp probing moves to a service

De-duplicate while splitting:

- The `{**dict(source), "enabled": bool(…), "video_count": …, "completed_count": …}` dict
  appears at [api.py:36](backend/routes/api.py:36), `:101`, `:115`, `:135` and in a variant
  at [feeds.py:46](backend/routes/feeds.py:46) → one `source_dto(db, row)` in the sources
  service.
- The `SettingsResponse` dict appears at [api.py:291](backend/routes/api.py:291) and `:346`
  → one `settings_to_response(settings)`.
- The raw SQL in `get_status` ([api.py:272](backend/routes/api.py:272) and `:276`) → named
  `get_last_poll_time()` and `count_pending_videos()` on `DatabaseManager`, matching the
  existing named-helper style in [database.py](backend/database.py).
- Hoist the function-local `import os` / `import subprocess` to module top (both cheap).
  **Keep `import yt_dlp` lazy** — the comment at
  [downloader.py:269](backend/downloader.py:269) says it costs ~60s to load, and that is
  load-bearing for app startup.
- Delete the dead `settings = request.app.state.settings` in both functions of
  [feeds.py](backend/routes/feeds.py:17) — assigned, never used.

## Phase 5 — Backend: service layer

New `backend/services/`:

- **`sources.py`** — `create_source(...)` holding the parse → resolve-handle →
  uploads-playlist → icon → insert sequence currently inline in the route at
  [api.py:46-106](backend/routes/api.py:46); plus `list_source_dtos`, `get_source_dto`.
- **`sync.py`** — move `sync_source` out of `downloader.py` (it is orchestration, not
  downloading) and add `sync_all_sources(...)`, collapsing the loop duplicated verbatim in
  [main.py:56-64](backend/main.py:56) and [api.py:229-235](backend/routes/api.py:229).
- **`cookies.py`** — `KNOWN_BROWSERS`, `probe_browser_cookies`, `test_cookies` (the yt-dlp
  work currently sitting in the routes module).
- **`paths.py`** — `sanitize_filename`, `output_dir_for_source(settings, source)`,
  `resolve_audio_path(db, source, filename)`. This gives path resolution one home and stops
  [routes/audio.py:10](backend/routes/audio.py:10) importing a string utility from the
  download manager.

Routes then depend on services rather than wiring three collaborators each.

## Phase 6 — Backend: `downloader.py` → package

- `downloader/ffmpeg.py` — `find_ffmpeg`, `_bundled_ffmpeg_candidates`, `_clear_quarantine`,
  `_FFMPEG_SEARCH_PATHS`
- `downloader/manager.py` — `DownloadManager`
- `downloader/artwork.py` — `_embed_channel_icon` (the mutagen ID3 work). While here, drop
  the dead inner `from mutagen.id3 import ID3NoHeaderError` at
  [downloader.py:180](backend/downloader.py:180) — it's imported and never used, and
  `ID3NoHeaderError` already subclasses the `error` being caught.
- `downloader/__init__.py` — re-export `DownloadManager` and `find_ffmpeg` so existing
  imports keep working through the transition.
- `sanitize_filename` → `services/paths.py`; `sync_source` → `services/sync.py`.

**Then update `build_backend.sh`** with a `--hidden-import` for every new module from
Phases 4–6 (`backend.routes.sources`, `backend.routes.videos`, `backend.routes.sync`,
`backend.routes.status`, `backend.routes.settings`, `backend.routes.cookies`,
`backend.services.*`, `backend.downloader.*`). Skipping this is the failure mode that
passes dev and breaks the DMG.

## Phase 7 — Docs

Update the "Key files" list in [HANDOFF.md:41-56](HANDOFF.md:41) — it names `app.js`,
`style.css`, `routes/api.py`, and `downloader.py`, all of which move. Add a short
"Running tests" section.

---

## Found in passing — decide separately

These are pre-existing bugs, not refactor targets. Flagging rather than silently fixing,
since this refactor is meant to be behavior-preserving. Phase 5 is where a fix would
naturally land if you want it.

1. **Custom storage paths break audio serving.**
   [rss_generator.py:75](backend/rss_generator.py:75) emits
   `/audio/{source_id}/{video_id}.mp3`, but
   [audio.py:28-29](backend/routes/audio.py:28) resolves that against
   `settings.storage_path / sanitize_filename(source["name"])` — ignoring
   `custom_storage_path` entirely. Any source with a custom download folder serves 404s to
   podcast clients, and the containment check at `audio.py:36` would reject the custom path
   even if the lookup found it. The robust fix is to serve from the `videos.file_path`
   already stored in the DB.
2. **Python version is documented three different ways.** `HANDOFF.md:32` says 3.12,
   `pyproject.toml` says `>=3.10`, and the venv on disk is 3.11. Worth reconciling.

## Verification

After **every** phase:

```bash
source venv/bin/activate && python -m pytest tests/ -q
```

Frontend phases (2–3) additionally:

```bash
PYTHONPATH="." uvicorn backend.main:app --host 127.0.0.1 --port 8642
```

Then click the full path — add a source, sync, watch a progress bar fill, skip an episode,
delete a file, re-queue it, open Settings, detect browsers, test cookies, copy an RSS URL,
toggle enabled, delete a source, press Escape in each modal — and confirm zero console
errors (the delegated-handler conversion fails loudly in the console, which is what makes
it verifiable). Screenshot desktop and mobile widths before and after Phase 3 and compare.

Final gate — the one that catches the PyInstaller trap:

```bash
./scripts/build_app.sh
```

Launch `build/PodcastSync.app` from the menu bar, open the Web UI, and sync one source.
Dev mode passing does **not** prove the bundle works; only this does.

## Sequencing note

Phases 2–3 (frontend) and 4–6 (backend) are independent and touch disjoint files. Phases
4–6 are ordered by dependency: the route split (4) is easier once the services (5) exist,
so if you prefer, do 5 before 4. Phase 6 must come after 5, because `sanitize_filename` and
`sync_source` move into services.
