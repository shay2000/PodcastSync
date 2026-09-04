# Phase 1 — Verification & quality gates (T1–T6)

Files: many new under `tests/`, `tests/conftest.py`, `tests/fakes.py` (new), `.github/workflows/ci.yml` (new), `pyproject.toml`, `backend/static/package.json` (new, for node:test).

Goal: lock every Phase-0 fix with offline tests, add CI on every PR, add ruff + JS tests, and rework the brittle existing tests. Run this phase *before* starting frontend/packaging/auto-update work so every later phase is lint-clean and CI-protected.

---

## T1 — Locking tests (write with the fixes; several already specified in WS-A/B/C files)

Add all of the following files. Every test stays hermetic: per-test `tmp_path` DB/storage, `httpx.ASGITransport` + the `api` fixture (lifespan_context + app.state stub swap), no network, no real yt-dlp/google clients.

### `tests/test_database.py` (pure DB; new `raw_db` fixture in conftest)
```python
@pytest_asyncio.fixture
def raw_db(tmp_path):
    """A DatabaseManager on a fresh temp DB, initialized, closed on teardown."""
    from backend.database import DatabaseManager
    mgr = DatabaseManager(tmp_path / "raw.db")
    mgr.initialize()
    yield mgr
    mgr.close()
```
Tests: fresh install schema v3/v4 (`sources` has `max_keep_episodes`; `videos` CHECK includes `deleted`; new `attempts` column after migration 004); `initialize()` idempotent; concurrent initialize (two managers, same file, sequential + threaded) no double-ALTER; corrupt `schema_version` → `RuntimeError`; v1→latest and v2→latest upgrade fixtures with byte-identical rows (build old DBs by executing `001` / `001+002` statement files); helper semantics (`add_video` dedupe → None; `get_pending_videos` oldest-first; `get_overflow_completed_videos` keep-newest after B4; `delete_source` cascade; `requeue_video` clears error fields; allow-listed update columns ignore unknown keys; `claim_video` only claims `pending`).

### `tests/test_rolling_delete.py` (fix-first, with B4)
Fixtures: `raw_db` or `api` + real `DownloadManager` with `find_ffmpeg` monkeypatched to return `None` (constructor then skips quarantine/ffmpeg_location) and `DownloadManager.download_video` monkeypatched on the instance to write a fake MP3 + call `update_video_status(..., "completed", file_path=..., file_size=...)`. Pin the scenarios listed in WS-B B4.

### `tests/test_video_ownership.py` (fix-first, with C1)
Extend conftest with a `seed_video(api, source_id, ...)` helper (extracted from the `seeded` fixture body) and add a second source+video. Pin the C1 scenarios.

### `tests/test_custom_storage.py` (fix-first, with B7)
Pin the custom-storage serving scenarios in WS-B B7.

### `tests/test_sync_ingest.py`
Exercises the never-run ingest loop (`services/sync.py:42-57`):
- Extend `StubOrchestrator` with a `videos` list already present (`conftest.py:45`) — add a `make_video(**overrides)` factory in `tests/fakes.py` that builds `backend.fetcher.base.VideoInfo`.
- Pin: N videos → N rows with correct field mapping (publish_date `.isoformat()`, description sliced to 2000); second sync adds 0 (dedupe); partial overlap adds only unknowns; `max_backfill>50` is capped to 50 (assert the recorded `("fetch_videos", ...)` tuple has `50`); `fetch_videos` raising → no new rows, `last_polled_at` still stamped (pin current semantics), no 500; `fetch_videos` returning `[]` → `process_pending_downloads` still invoked with correct kwargs.
- Lockstep: assertions in `test_api_sync.py:39-57` use exact tuples; if you change `fetch_videos`/`process_pending_downloads` signatures, update both.

### `tests/test_download_manager.py` (real class, hermetic)
Construct a real `DownloadManager` + real `DatabaseManager` (`raw_db`), `find_ffmpeg`→None, `settings` a lightweight namespace with empty cookie fields.
- Fake `yt_dlp` without installing it: an autouse module fixture inserts a fake module into `sys.modules["yt_dlp"]` whose `YoutubeDL(opts)` captures opts, fires `progress_hooks` with canned dicts, and `.download()` optionally raises or writes `<outtmpl-dir>/<video_id>.mp3` (parse `opts["outtmpl"]`). Scope it to this module and remove in teardown so the `api`-fixture tests (which never import yt_dlp) are unaffected.
- Pin: happy path (`downloading`→`completed`, size recorded, progress popped on finished, `active_downloads` decremented in finally); pre-existing non-empty file skips yt-dlp; pre-existing empty file is deleted and re-downloaded; failure taxonomy — `[AUTH_REQUIRED]` prefix on sign-in/bot messages → `failed`; generic network exception → `failed` with ≤500-char message; fake leaving no file → “Audio conversion failed …” message; transient retry logic per B8 (attempts increments, 3rd failure → `failed`); `cancel_all` semantics (queued-but-not-started skip, in-flight completes — use an `asyncio.Event`-blocking fake); semaphore honors `max_concurrent` (peak concurrency ≤2); cookie opts mapping (`cookiesfrombrowser` tuple vs `cookiefile` only when file exists); icon embed invoked and a raising `_embed_channel_icon` (monkeypatch `backend.downloader.manager._embed_channel_icon`) still completes the download; `ffmpeg_location` present when `ffmpeg_path` set.

### `tests/test_feed_golden.py`
Extend `test_feeds.py` with richer builders (durations 600/3661/None, tz-aware and absent dates, `&`/`<` titles, thumbnails present/absent). Assert structure with `xml.etree` **and** validate pubDate via `email.utils.parsedate_to_datetime`. Pin the A1–A8 items (order, enclosure length, category, channel link, self atom link, `isPermaLink="false"` on bare guids — characterize current feedgen output first, then fix if it renders `isPermaLink` default-true), stable body between requests, headers (`application/rss+xml`, `Cache-Control`, `ETag`, 304). Normalize/delete `lastBuildDate` before structural compare where needed.

### `tests/test_crash_recovery.py` (fix-first, with B3)
See WS-B B3. Must run through lifespan with a pre-seeded DB file so the recovery point in `main.py` is exercised.

### `tests/test_fetchers.py` (+ `tests/fakes.py`)
- `rss_fetcher`: monkeypatch `feedparser.parse`; canned feeds via a `feed_entries(...)` builder in `tests/fakes.py`. Pin extraction/fallbacks per the audit list: `yt_videoid`, link-split fallback, entries with neither skipped, malformed `published_parsed` → None, thumbnail fallback to `https://i.ytimg.com/vi/<id>/hqdefault.jpg`, `duration_seconds=None`, `max_results` slicing, bozo-with-entries tolerated / bozo-and-empty → `[]`. Plus the B6 to_thread/timeout test.
- `api_fetcher`: build with `YouTubeApiFetcher.__new__` + a `FakeService` returning canned paginated pages (never construct the real google client). Pin pagination via `nextPageToken`, `max_results` mid-pagination halting, duration batch map + `_parse_iso8601_duration` table, `publishedAt` Z-parse, thumbnail preference maxres→high→default→absent, uploads-playlist caching (second call hits service zero times), quota → `QuotaExceededError` (fake `googleapiclient.errors.HttpError`-shaped exception, monkeypatching `sys.modules["googleapiclient"]` if needed for the lazy import), resolve handle/user/custom + no-results → `ValueError`.
- `orchestrator`: construct with no key (RSS-only), assign fake `api_fetcher`/`rss_fetcher` post-construction. Pin API-first, fallback on `QuotaExceededError`, fallback on generic API exception, no-key → RSS, both-fail → `[]`, `fetch_channel_icon` None without API, UC→UU fallback for uploads id without key.

### `tests/test_scheduler.py`
`create_scheduler` job id/interval; `reschedule_poll` changes `job.trigger.interval` (assert on the trigger, never on `next_run_time` strings); startup/DB-override test: seed settings rows before lifespan → `GET /api/settings` reflects DB over env and scheduler interval matches DB; status `next_poll` when scheduler has no jobs.

### `tests/test_cookies_probe.py`
`probe_browser_cookies` taxonomy via the `sys.modules["yt_dlp"]` fake (cookiejar with youtube cookies → available; “Operation not permitted”/`PermissionError` → `needs_permission`; other → unavailable). `test_cookies` route happy/error via monkeypatching `backend.services.cookies.test_cookies`. `pick-directory` by monkeypatching `subprocess.run` in `routes/settings.py` → `{"path": "/Users/x/Music"}` / `{"path": None}`.

### `tests/test_audio_guard_and_ranges.py`
A8 Range/HEAD tests + the deterministic symlink containment case (a symlink inside the source folder pointing outside storage → `resolve()` follows → real 403) to replace the tolerant `(403, 404)` union in `test_audio.py:47-58`. Keep the existing traversal-string tests asserting no byte leak.

### `tests/test_packaging_inventory.py`
Pure stdlib. Read `scripts/build_backend.sh` text; extract `--hidden-import backend\.(\S+)` tokens. Walk `backend/`; assert (1) every listed module still exists, (2) every `.py` under `routes/ services/ downloader/ fetcher/` plus top-level modules is either whitelisted or in an explicit “statically reachable from main.py” exception set, (3) `--collect-all feedgen` present and the script still copies `backend/static` and `backend/migrations`. Failing message: “add to --hidden-import list in build_backend.sh”. Runs in ms.

### Lockstep summary
| Change | Impact |
|---|---|
| Additive stub surface (`make_video`, `seed_video`) | None (additive) |
| `fetch_videos`/`process_pending_downloads` param changes | Break exact-tuple tests → update stubs+tests together |
| `sync_source`/`sync_all_sources` optional trailing `lock` | None (optional param) |
| `update_video_status`/`update_source` column filtering | None to stubs |

---

## T2 — PR CI workflow (`.github/workflows/ci.yml`)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]   # floor + current
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
          cache-dependency-path: requirements.txt
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -e ".[dev]"
          pip install ruff
      - name: Lint
        run: ruff check backend tests && ruff format --check backend tests
      - name: Test
        run: python -m pytest tests/ -q

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: JS tests
        working-directory: backend/static
        run: node --test
```
Notes: tests are fully offline, so ubuntu is fine and fast. The matrix floor (3.10) guards `requires-python`. If `backend/static/package.json` doesn’t exist yet (T5), drop the `frontend` job until it does. Release workflow (`build-release.yml`) keeps `contents: write`; `ci.yml` never runs with write tokens.

---

## T3 — Ruff

`pyproject.toml`:
```toml
[tool.ruff]
line-length = 100
target-version = "py310"
src = ["backend", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
```
Add `ruff>=0.6` to `[project.optional-dependencies].dev`. Run one cleanup pass over `backend/` and `tests/` (import sorting `I` will reorder many files — keep the diff mechanical). Do not add `mypy`/`pyright` in this phase. CI runs `ruff check` + `ruff format --check` (format with `ruff format backend tests` once and commit).

---

## T4 — Packaged-backend smoke test (macOS CI only)

Add to `build-release.yml` after “Build app and DMG” (or as a separate job gated on `build_backend.sh`):
```yaml
- name: Smoke test packaged backend
  env:
    PODCASTSYNC_DB: /tmp/smoke/podcastsync.db
    PODCASTSYNC_STORAGE: /tmp/smoke/storage
    PODCASTSYNC_PORT: "8643"
    YOUTUBE_API_KEY: ""
  run: |
    build/backend-dist/podcastsync-backend/podcastsync-backend &
    PID=$!
    for i in $(seq 1 60); do
      curl -sf http://127.0.0.1:8643/api/status >/dev/null 2>&1 && break
      sleep 1
    done
    curl -fsS http://127.0.0.1:8643/api/status
    curl -fsS http://127.0.0.1:8643/ | grep -q "PodcastSync"
    curl -fsS http://127.0.0.1:8643/app-icon.svg -o /dev/null
    kill $PID
```
This catches missing hidden imports (incl. the APScheduler `trigger="interval"` runtime import), missing static/migration resources, and scheduler boot failures — the only true end-to-end guarantee.

---

## T5 — JS tests (node:test, zero deps)

Under `backend/static/`, add `package.json` with `{"type":"module","scripts":{"test":"node --test"}}`. First-test list (pure-logic only — no jsdom in this phase):
1. **Dispatch-table sync:** refactor `main.js` — extract the switch body into an exported `ACTION_HANDLERS` map (e.g. into a new `js/dispatch.js`), then statically parse `index.html` and every `render/*.js` template for `data-action="…"` literals and assert each key exists in `ACTION_HANDLERS`. (Also removes the dead `default: break` path.)
2. **`esc`/`escAttr`:** pin the full escape table incl. `"`, `'`, backtick (C2). Requires DOM (`document`) — keep `esc` pure by accepting an element factory, or use the lightest DOM shim (skip jsdom; simplest: refactor `esc` to a pure string escaper `escapeHtml(value)` and make `esc` delegate).
3. **`format.js`:** `parseAppDate` (space-separated `YYYY-MM-DD HH:MM:SS` parsed as UTC via the `"Z"` append — pin), `timeAgo`/`formatSyncAge` thresholds, `normalizeDownloadStatus` aliases, `deriveDisplayNameFromUrl` handle edges.
4. **DOM-id cross-check:** parse `index.html` ids and assert every `getElementById`/`querySelector("#…")` in `js/` exists (static scan).
5. **`api.js`:** stub `fetch`; pin method/headers/body construction, error normalization (`detail` array → joined `msg`s; object → `msg`), 204 → null.
Defer `render/*`/`actions/*` DOM tests to a future jsdom/vitest step. Wire into CI (T2 frontend job).

---

## T6 — Rework brittle existing tests

1. `tests/test_audio.py:47-58` traversal union `(403, 404)` → deterministic symlink 403 (see T1 audio file) + keep 404 assertions only for encoded-slash strings.
2. `tests/test_api_sync.py` exact-kwargs assertions (`test_sync_passes_source_settings_to_the_download_manager`) → loosen to a required-subset assertion so future kwarg additions don’t churn.
3. `tests/test_api_status_settings.py:150-157` `test_patch_settings_reschedules_the_poll_job` → assert `api.scheduler.get_job(POLL_JOB_ID).trigger.interval == timedelta(minutes=90)` instead of comparing `next_poll` strings.
4. BackgroundTasks timing assumption: keep the module docstring note; add one belt-and-braces poll of `last_polled_at`/`processed` rather than assuming instant completion.
5. `tests/test_feeds.py` `test_feed_only_lists_completed_videos` fakes completion with a nonexistent path — give that video a real temp file (A7 changes feed filtering).
6. `tests/conftest.py` docstring/comment updates where behaviour is pinned by the fixes.

---

## Phase 1 Summary

- [ ] T1 locking tests (all files listed)
- [ ] T2 `ci.yml`
- [ ] T3 ruff config + cleanup
- [ ] T4 packaged-backend smoke test
- [ ] T5 JS tests
- [ ] T6 brittle-test rework

Gate: `python -m pytest tests/ -q`, `ruff check backend tests`, `ruff format --check backend tests` all green locally; `ci.yml` green on a PR.
