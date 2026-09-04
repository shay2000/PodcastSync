# PodcastSync — Public-Release & Fix Plan

**Status:** Draft for owner review
**Date:** 2026-09-04
**Scope:** Fix product bugs (feed/client compatibility, backend data-safety, security, UI), add auto-update, and sanitise the repo for a public release.
**Produced by:** six parallel research agents auditing the codebase (feed spec/client research, frontend audit, backend robustness, security & git-history hygiene, packaging/CI, test strategy), followed by targeted verification (tags, branches, LICENSE, git history, `backend/scheduler.py`, `backend/rss_generator.py`, `backend/routes/feeds.py`).

> **IMPLEMENTATION:** For the code-level, handoff-ready engineering spec that expands this plan into per-task changes, exact recipes, and tests, read **`docs/IMPLEMENTATION_SPEC.md`** (plus the files under `docs/implementation/`). This file is the strategy overview; the spec is what an implementing agent executes.

> Repo note: the on-disk parent folder was renamed from `Side Projects:Hobbies` to `Side Projects and Hobbies` mid-session. Current repo root is `/Users/shayprasad/Documents/Side Projects and Hobbies/Coding/PodcastSync`. `AGENTS.md` (repo root) is the agent-facing companion to this plan.

---

## 0. Decisions the owner must make (read these first)

| # | Decision | Options | Blocks | Default recommendation |
|---|----------|---------|--------|------------------------|
| D1 | Apple Developer Program ($99/yr) for Developer ID + notarization? | (a) Stay ad-hoc, ship SHA-256 + Gatekeeper docs (b) Pay for Developer ID + notarization + stapling | Phase 5 auto-update Stage B (Sparkle), frictionless install | (a) for v1 at $0; revisit via GitHub Sponsors later |
| D2 | Auto-update mechanism | (a) Lightweight self-updater against GitHub Releases + `latest.json` (works ad-hoc) (b) Sparkle (needs notarization) (c) Both, staged a→b | Phase 4 | Staged: build (a) now, design metadata so (b) is generated from the same data later |
| D3 | Arch support | (a) Apple Silicon only (current) (b) arm64 + x86_64 matrix releases | Phase 5 v1.1 | (a) for v1, (b) as fast-follow — podcast users skew to older Macs |
| D4 | Git history rewrite to drop ~324 MB of committed build artifacts (`venv.x86_old`, `macos/PodcastSync/.build`) | (a) `git filter-repo` before going public (b) leave history | Phase 5 launch gate | (a) rewrite — repo is single-maintainer, no forks visible; also fixes machine-path disclosure and allows normalizing the `Shays-MBP.mynet` author email |
| D5 | Delete/archive remote branch `refactor/structural-cleanup` (contains stray `can-you-plan-a-partitioned-book.md`) | delete / archive | Phase 5 | Delete after merging anything needed |
| D6 | Security posture for the unauthenticated LAN server | (a) document threat model only (b) per-install token + Host allow-list + optional localhost-only mode | Phase 0 sec tasks | (b) minimum: random per-install secret + Host allow-list; firewall warning in UI |
| D7 | **Deployment target** | (a) LAN-only app (current) (b) also run the backend on a public VPS (Docker on Oracle Cloud) so Overcast and any internet podcast client work | Phases 0/3/6 | (b) is the only way to support Overcast; if chosen, the WS-C security hardening and HTTPS/proxy work become **release-blocking**, and a Docker image + `PUBLIC_URL` config are added (Phase 6) |

---

## 1. Objectives

1. **Fix real bugs** that break or degrade the product today — the most consequential being: feed items are ordered **oldest-first** (new episodes sit at the bottom), **Downcast/Overcast/LAN reachability** behaviour, rolling-delete deletes the wrong episodes, crashed downloads are unrecoverable, custom download folders make audio **403**, and cross-source video endpoints can delete another source's files.
2. **Fix the web UI** — verified bugs (attribute-injection/XSS vector, LAN clipboard copy failure, stale/blank download bar, `[object Object]` validation errors, focus loss on re-render, stale settings/auth state) plus a ranked polish list.
3. **Add auto-update** — pushing a tagged release to the repo should let installed apps detect, download, verify, and install it.
4. **Sanitise for public release** — security posture, repo history/docs hygiene, CI quality gates, packaging robustness, community/legal files, and a clean release process.

Non-goals (explicitly out of scope for v1): Mac App Store distribution, sandboxing, Homebrew cask/formula, reproducible byte-identical builds, DRM/ToS guarantees, and guaranteed silent background install without user approval. **Overcast is a non-goal only for a LAN-only feed** — if the owner picks D7(b) and runs the backend on a public VPS with HTTPS, Overcast (and any internet podcast client) works normally; that path is Phase 6 / Appendix I.

---

## 2. Problem inventory (summary; details in appendices)

### Feed / podcast-client compatibility (Appendix A)
- **P1 high:** RSS items render **oldest-first** — feedgen `add_entry()` prepends, while the DB returns newest-first, so the newest episode is last. Clients that scan until the first seen GUID, or treat item #1 as "latest", miss new episodes. (`backend/rss_generator.py:51-52`, `backend/database.py:175-179`)
- **P1:** Overcast *cannot ever* subscribe to a LAN URL — it crawls feeds server-side from the public internet (`crawl1..6.overcast.fm`). **This is only a reachability limitation**: run the backend on a public VPS with HTTPS (Phase 6, D7(b)) and Overcast works like any feed. Until then, make the feed bulletproof for on-device clients (Downcast, Apple Podcasts).
- **P2:** enclosure `length="0"` when `file_size` is missing/stale; should stat the real file.
- **P2:** no `<itunes:category>`; channel `<link>` points at the feed XML, not a website (feedgen emits the *last* link as RSS channel link); `lastBuildDate` churns every request and the route has no `ETag`/`Last-Modified`.
- **Not a bug:** bare-GUID with `isPermaLink="false"` (fine), integer `itunes:duration` (spec-recommended), RFC2822 pubDate (fine), `FileResponse` Range/HEAD support (fine on Starlette ≥ 0.39 — pin a floor and add a regression test).

### Backend robustness & data safety (Appendix B)
- **P0:** migrations are non-transactional, unlocked, and 003 is a positional table rebuild → concurrent starts crash, mid-migration crashes are unrecoverable (`backend/database.py:41-71`, `003_rolling_delete.sql`).
- **P0:** `downloading` rows orphan forever on crash — no startup reconciliation (`downloader/manager.py:104-169`, `main.py` lifespan).
- **P1:** rolling delete inverted — keeps the oldest N, deletes the newest (including just-downloaded files) (`database.py:216-224` + `manager.py:201-211`).
- **P1:** concurrent syncs double-download the same rows; one failure orphans sibling tasks (`manager.py:213-249`; no sync lock).
- **P1:** blocking network I/O (googleapiclient `.execute()`, `feedparser.parse`) runs on the event loop with no timeouts → a hung upstream freezes the whole server and skips scheduler ticks (`fetcher/api_fetcher.py`, `fetcher/rss_fetcher.py`).
- **P1:** `custom_storage_path` outside the default root is always **403** (containment checked against the wrong root) — the feature is broken (`routes/audio.py:28-39`).
- **P1:** `failed` downloads are never retried; auth failures are keyword-sniffed (`manager.py:154-167,191-198`).
- **P2:** settings parsed from DB with bare `int()`/`Path()` → corrupt row crashes startup (`config.py:55-70`); shared sync sqlite connection + per-statement commits; `add_video` swallows all `IntegrityError`; `update_*` build dynamic SQL from `**fields`; artwork `urlretrieve` cache race; `asyncio.get_event_loop()` deprecation; no coalescing/misfire settings on the scheduler job (`scheduler.py:14-26`).

### Security (Appendix C)
- **P0:** whole service unauthenticated on `0.0.0.0` with destructive endpoints + **DNS rebinding** (no Host validation anywhere) → any website can drive the API; body-less POSTs are form-CSRF-able.
- **P1:** video endpoints don't scope `video_db_id` to `source_id` → cross-source file deletion (`routes/videos.py:27-53`).
- **P1:** attribute-context stored XSS (`esc()` doesn't escape `"`, used in `src`/`alt`) (`format.js:1-5`, `render/sources.js:47`).
- **P1:** audio containment guard targets the default root, not the resolved per-source dir (`routes/audio.py:35-39`).
- **P2/P3:** no CSP, external Google Fonts, cookie probing returns host browser state to LAN callers, `pick-directory` dialog spam, plaintext API key in sqlite, key hygiene notes, host-substring check in URL parser (SSRF: verified none today — all outbound URLs are fixed-host templates).
- **Verified clean:** SQL injection (parameterized; interpolated columns are internal), yt-dlp option injection (options dict, never argv), osascript injection (static script), API key never returned/logged.

### Frontend / UI (Appendix D)
- **P1 bugs:** attribute injection (above); clipboard copy fails over LAN (not a secure context); progress bar goes blank during ffmpeg conversion; 422 errors toast `[object Object]`; full-grid re-render destroys toggle focus; optimistic timestamp races the poll; auth chip stale; add-modal never resets; API-key "set" state invisible; sync failures invisible; double-submit on primary actions.
- **UX:** skeletons, focus trap, `aria-live` regions, toast stacking, per-source "converting…"/syncing state, Retry/error states, confirmation consistency, narrow-width pass.
- **Debt:** legacy `style.css` (1,808 lines, duplicated dark blocks) shadows the modular CSS split (recommendation: formally retire modular CSS, keep `style.css` canonical); manual `?v=` cache-busting only versions 2 URLs (submodules unversioned); dead code list; no JS tests.

### Packaging / CI (Appendix E)
- **P0:** ffmpeg presence check is dead code (`build_app.sh:100-107`); nested codesign failures swallowed via `|| true`; `build/PodcastSync-launcher` fallback can silently ship yesterday's binary; workflow only tests on tag push; no packaged smoke test.
- **P1:** trigger-`"interval"` alias in `scheduler.py:19` is resolved dynamically by APScheduler → verify bundled scheduler works in the packaged binary (add smoke test; add hidden import if needed).
- **P1:** version coupling pyproject ↔ git tag ↔ Info.plist with no guard; stale `release_tag` default `v0.2.0` (`build-release.yml:12`); hidden-import/resource drift is manual discipline only.
- **P2:** arm64-only (no Intel build); no PR CI; no dependabot; no lint/format/type tooling.

### Repo hygiene (Appendix G)
- **P0:** ~324 MB of build artifacts in pushed history (`venv.x86_old/` + `macos/PodcastSync/.build/`, incl. `~/.pyvenv`/shebangs disclosing the owner's real path); still present in tag `v0.1.0`; machine-derived author email on 7 commits.
- Stray planning doc on remote branch; stale docs paths/badges/version defaults; missing WAL-sidecar ignores; no `CONTRIBUTING`/`SECURITY`/`CHANGELOG`/issue templates/dependabot.

### Testing gaps (Appendix F)
- Video-ingestion loop, fetcher layer, real DownloadManager (yt-dlp/ffmpeg), cookie probes, migrations/upgrades, crash recovery, rolling-delete semantics, custom-storage serving, RSS spec pinning, `Range` support, settings corruption, scheduler trigger, packaging-inventory drift guard — all untested today.

---

## 3. Phased execution plan

Task tags: **P0/P1/P2** priority, **S/M/L** effort (S ≤ ½ day, M ≤ 2 days, L ≤ 5 days). Each phase ends with acceptance criteria. Land each fix **with its locking test** (Appendix F) in the same commit; the test suite must stay green (characterization-first where noted).

### Phase 0 — Correctness & security fixes (the "make it right" phase)

P0 bug fixes land first because everything else (tests, UI, release) builds on them.

#### WS-A Feed compatibility (`backend/rss_generator.py`, `backend/routes/feeds.py`)
| # | Task | Ref | Size |
|---|------|-----|------|
| A1 | Emit items **newest-first**: `fg.add_entry(order="append")` (or iterate reversed). Pin: two-item feed asserts GUID order newest-first. | `rss_generator.py:51-52` | S |
| A2 | Real enclosure length: stat `row["file_path"]` at render; fall back to stored `file_size`; skip/guard missing. Pin: completed video with `file_size=None` → length equals on-disk bytes. | `rss_generator.py:74-76` | S |
| A3 | Emit `<itunes:category>` (default "Technology" or per-source later). Pin valid category present. | `rss_generator.py:31-49` | S |
| A4 | Channel `<link>` = source's YouTube URL (add `rel="self"` first, then `rel="alternate"`). Pin `<channel><link>` and `<atom:link rel="self">`. | `rss_generator.py:37-38` | S |
| A5 | Stable `lastBuildDate` from newest item pubDate; add `ETag`/`Last-Modified` on the feed route. Pin headers + changeless body between requests. | `rss_generator.py`, `feeds.py:29-33` | S |
| A6 | Log (don't silently drop) unparseable `publish_date`. | `rss_generator.py:60-68` | S |
| A7 | Exclude completed videos with no file from feeds (they point at 404s). Pin. | `database.py:175-179` + `feeds.py:26` | S |
| A8 | Pin `starlette>=0.39` floor (Range/HEAD support) + regression test: `Range: bytes=0-99` → 206 + `Content-Range`, HEAD → 200 + `Content-Length`. | `requirements.txt`, `pyproject.toml`, `tests/test_audio_guard_and_ranges.py` | S |
| A9 | Doc fix: README Overcast note says exactly why (server-side crawling of a LAN URL) and states Downcast/Apple Podcasts fetch on-device. Also add "grant Local Network permission on iOS 14+" to usage docs. | `README.md:78-79,137` | S |

#### WS-B Backend data-safety
| # | Task | Ref | Size |
|---|------|-----|------|
| B1 | **Migration runner hardening:** open connection with `isolation_level=None` + `PRAGMA busy_timeout=5000`; wrap the whole upgrade in `BEGIN IMMEDIATE` (serialize concurrent migrators; clear error if busy); re-read version inside the lock; one transaction per migration with version bump last and ROLLBACK on failure; defensive `ADD COLUMN` guards via `PRAGMA table_info`. | `database.py:41-71` | M |
| B2 | **Rewrite migration 003** as a column-explicit rebuild (`INSERT INTO videos_new (cols…) SELECT cols…`), drop/rename, and re-seed `sqlite_sequence`; add `tests/test_database.py` upgrade fixtures (v1→v3, v2→v3) that would have caught the fragility. | `003_rolling_delete.sql` | S |
| B3 | **Crash recovery:** startup reconciliation in lifespan (after `initialize()`, before scheduler start): requeue stale `downloading` rows (`→ pending`); if a valid file exists, mark `completed`. Pin with `tests/test_crash_recovery.py`. | `main.py:29-77` | S |
| B4 | **Rolling delete fix:** `get_overflow_completed_videos` must return the *oldest* overflow (ORDER BY `publish_date DESC, id DESC … OFFSET max_keep`, then re-sort ASC) so keep-N retains the newest N; deterministic tiebreak by `id`; run trim also when nothing new downloaded; clear `file_path`/`file_size` on deletion. Pin both DB-level and manager-level tests. | `database.py:216-224`, `manager.py:201-211` | M |
| B5 | **Sync mutual exclusion + row claiming:** one global `asyncio.Lock` on `app.state` shared by scheduler job + all manual sync paths; claim each row transactionally (`UPDATE … SET download_status='downloading' WHERE id=? AND status='pending'`, proceed only on rowcount 1); `gather(return_exceptions=True)` + per-video try/except so one failure can't orphan siblings. | `main.py`, `services/sync.py`, `manager.py:213-249`, `routes/sync.py` | M |
| B6 | **Event-loop non-blocking fetchers:** run googleapiclient calls and `feedparser.parse` via `asyncio.to_thread`; set explicit timeouts (google Http timeout ~30s, socket timeout around RSS parse). Pin with a thread-identity unit test. | `fetcher/api_fetcher.py:137-158`, `rss_fetcher.py:36` | M |
| B7 | **Audio serving fix:** resolve from the DB row's `file_path`; validate containment against allow-list = default storage root ∪ this source's resolved output dir; require basename `== <video_id>.mp3`. Pin: custom-storage source serves 200; out-of-tree paths still 403. | `routes/audio.py:28-39`, `services/paths.py:26-40` | S |
| B8 | **Retry + failure taxonomy:** add `attempts`/`last_attempt_at`; auto-requeue transient failures (network/unavailable) on next sync up to N attempts; keep `[AUTH_REQUIRED]` as a distinct terminal-ish class with a UI hint; structured classification instead of raw keyword sniff where cheap. | `manager.py:154-199`, DB migration | M |
| B9 | **Settings hardening:** guarded parse in `load_from_db` (invalid → log + keep env/default); tolerate corrupt `schema_version`. Pin crash-then-fix tests. | `config.py:55-70`, `database.py:57-64` | S |
| B10 | **DB polish:** add `busy_timeout`; stop swallowing non-duplicate `IntegrityError` in `add_video` (distinguish via constraint message or pre-check); column-name allow-lists in `update_source`/`update_video_status`; wrap `delete_source` steps in one transaction; art cache write to a temp file + rename to avoid races. | `database.py`, `downloader/artwork.py:16-22` | M |
| B11 | **Scheduler:** `coalesce=True`, `max_instances=1`, `misfire_grace_time` sane default so polls don't pile up after a hang; add APScheduler trigger modules to PyInstaller hidden imports or confirm via smoke test. | `scheduler.py:14-26`, `build_backend.sh` | S |

#### WS-C Security
| # | Task | Ref | Size |
|---|------|-----|------|
| C1 | **Ownership checks:** load the video and require `source_id == path source_id` before skip/delete-file/requeue; 404 otherwise (incl. nonexistent video). Pin `tests/test_video_ownership.py`. | `routes/videos.py:27-53`, `database.py:192-214` | S |
| C2 | **Attribute-safe escaping:** `escAttr()` (escape `"`, `'`, backtick) or render attributes via DOM APIs; use it for `src`/`alt`; optionally validate `icon_url` hosts. Add CSP header (`default-src 'self'`; allowlist Google Fonts or drop them). Pin esc tests + dispatch/format tests. | `format.js:1-5`, `render/sources.js:47`, `main.py` (headers/middleware) | S |
| C3 | **Origin/Host validation + auth posture decision (D6):** implement (i) `TrustedHostMiddleware`/explicit allow-list (localhost, LAN IP, configured host), (ii) a per-install random secret generated on first run, stored in the settings table, required as a header (`X-PodcastSync-Token`) for `/api/*` mutations and injected by the Swift launcher + web UI bootstrap, (iii) UI firewall/“sharing on your network” warning banner, (iv) explicit opt-out/“LAN sharing” toggle later. At minimum ship the Host allow-list + SECURITY.md threat model. | `main.py`, `config.py`, `routes/*` (guard dependency), `macos/…/BackendProcess.swift`, frontend `api.js` | L |
| C4 | **Feed/enclosure host consistency:** build feed/audio URLs from the allow-listed origin only (never a spoofed `Host`); keep request-based derivation only when host is allowed. | `feeds.py:23-25`, `routes/audio.py` | S |
| C5 | **CSRF tightening:** require the token header on body-less mutators; exempt only if C3 header present. | `routes/sync.py`, `routes/settings.py` (pick-directory) | S |
| C6 | **Cookie probe scope:** require token; do not return per-browser availability to unauthenticated callers; restrict `cookies_file` testing to paths that exist under the user's home dir. | `routes/cookies.py`, `services/cookies.py` | S |
| C7 | **Key hygiene:** optionally move API key to macOS Keychain (backend reads via `security` CLI); tighten DB file perms (`chmod 600` on `~/.podcastsync`). Document. | `config.py`, `database.py` | M |

**Phase 0 acceptance:** full test suite green incl. new locking tests; feeds render newest-first and validate against the RSS spec checklist; `python -m pytest tests/ -q` passes; manual QA: add a channel with and without an API key, sync backfill, custom storage folder, rolling keep-N, kill mid-download then relaunch → episode recovers, feed loads in Apple Podcasts and Downcast on the same LAN, `curl` traversal/ownership probes return 403/404.

### Phase 1 — Verification & quality gates (lock Phase 0 in)

| # | Task | Size |
|---|------|------|
| T1 | Add all locking tests per Appendix F: rolling delete, ownership, custom storage, sync ingest, database/migrations, download manager (fake `yt_dlp` via `sys.modules`), feed golden, crash recovery, fetcher layer (`tests/fakes.py`), scheduler, cookies probe, packaging inventory. | L |
| T2 | New `.github/workflows/ci.yml` on every push/PR (ubuntu, py3.12): `pytest tests/ -q`, `ruff check` + `ruff format --check`, optional macOS `swift build` job; keep release workflow as the only write-token job. | M |
| T3 | Add `ruff` config + dev extra; run one cleanup pass over `backend/` + `tests/`. | S |
| T4 | Package smoke test in release workflow: launch the PyInstaller binary on the runner with temp `PODCASTSYNC_DB`/`STORAGE`/`PORT`, poll `/api/status`, `GET /`, exercise one feed render — catches hidden-import/resource drift incl. the APScheduler alias. | M |
| T5 | JS tests via `node:test` (no deps) under `backend/static`: dispatch-table sync test (extract `ACTION_HANDLERS` map), `esc`/`escAttr`, `format.js` boundaries, DOM-id cross-check, `api.js` with stub fetch. | M |
| T6 | Rework brittle tests (audio traversal tolerant union → deterministic symlink case; exact-kwargs assertions → required-subset; scheduler reschedule compare trigger interval not next_run strings; BackgroundTasks timing note). | S |

### Phase 2 — Frontend / UI fixes (Appendix D, ordered)

| # | Task | Size |
|---|------|------|
| U1 | Copy fallback for non-secure contexts (hidden textarea + `execCommand`); surface the existing in-detail URL row on failure. | S |
| U2 | Indeterminate "Converting…" bar when status `downloading` but no progress entry (belt-and-braces) + backend pops progress only after final status. | S |
| U3 | Normalize 422 detail arrays in `api.js` (`detail.map(d=>d.msg)`); client-side numeric clamping/validation. | S |
| U4 | Focus preservation: single-tile patch render (re-render one tile, refocus its toggle); never full-grid re-render on a toggle. | M |
| U5 | Fix optimistic `last_polled_at` (copy-and-replace or drop optimistic write); gate 1s progress poll on active downloads; sequence-guard `loadDetailVideos`. | M |
| U6 | Modal hygiene: reset add-source modal + clear `displayNameManuallyEdited` on open; derive/clear auth chip on settings open; "Key set/Not set" pill next to API-key field. | S |
| U7 | Persist + surface `last_sync_error` (backend models/DTO + tile/detail banner); disable primary actions in flight; per-source syncing state. | M |
| U8 | Initial-load skeletons + error/Retry empty state (replace wrong "no sources" flash). | S |
| U9 | a11y pass: focus trap in modals, return focus, `role=status`/`aria-live`, `role=alert` on error toasts, aria labels on tiles, remove blanket `outline: none`. | M |
| U10 | Toast system: container + stacking + dismiss + duration by severity. | S |
| U11 | Confirmation consistency (file delete → inline confirm); "No enabled sources" sync-all message; clearer copy for Stop/cancel & empty states. | S |
| U12 | CSS: **formally retire the modular CSS split** — keep `style.css` as the only sheet (`main.css` just imports it), delete `css/overrides.css` + component/token/base/layout files after confirming no unique rules, merge the two duplicated dark-mode blocks into one at end of file. Then stop bumping `?v=` for css/main.css in two places. | M |
| U13 | Cache-busting: serve `index.html` from a tiny route injecting `?v=` derived from asset mtimes/hashes, or add `Cache-Control: no-cache` to `/js/*` + `/css/*`; apply to the whole module graph. | M |
| U14 | Dead code removal (precise list in Appendix D): no-op `stopPropagation`, redundant dynamic `import("./api.js")`, unused exports (`setSelectedSource`, `syncDetailTabUi`/`updateDetailFeedUrl`, `buildSourceSummary`), unused DOM ids, decide `/feeds` route fate. | S |

**Phase 2 acceptance:** manual pass on Chrome + Safari over `127.0.0.1` and LAN IP: add/edit/delete source, sync, toggle, copy feed URL, settings incl. API key + cookies, cancel downloads, narrow window; no console errors; keyboard-only flows work; node:test suite passes.

### Phase 3 — Packaging & release engineering (Appendix E)

| # | Task | Size |
|---|------|------|
| R1 | `build_app.sh` hardening: real ffmpeg/ffprobe presence check (drop the `\|\| echo` default); strict nested codesign (drop `\|\| true`, add `codesign --verify --deep --strict` + `spctl` assess); launcher fallback opt-in via env, never in CI; `hdiutil attach` parsing via `-plist`; trap to detach RW image on failure. | M |
| R2 | Version single-sourcing: version lives in `pyproject.toml`; workflow guard asserts tag == pyproject version; remove `release_tag` default (make it required, only for rebuild); add `retention-days` on artifacts. | S |
| R3 | Add hidden-import/resource drift guards (test) + packaged smoke test (T4). Verify scheduler `"interval"` alias is bundled. | S |
| R4 | Info.plist polish: distinguish `CFBundleShortVersionString` (semver) vs `CFBundleVersion` (build number); add `NSHumanReadableCopyright`, category. | S |
| R5 | Dependabot config; README dynamic badges (release + downloads), arch-annotated once matrix exists. | S |
| R6 | (v1.1) arm64 + x86_64 release matrix (`macos-14` + `macos-13`), per-arch asset names. | L |
| R7 | (v1.1, budget-permitting, D1) notarization pipeline: identity indirection `PODCASTSYNC_SIGNING_IDENTITY`, `--options runtime --timestamp` on outer sign, entitlements only if needed, `xcrun notarytool` + `stapler` with the listed GitHub secrets, gates `codesign`/`spctl`/`stapler validate`. | L |

### Phase 4 — Auto-update feature (new; requested)

**Goal:** owner pushes tag `vX.Y.Z` → GitHub Actions builds/publishes → every installed PodcastSync menu bar app checks in, offers, downloads, verifies, and installs the update with one click, then relaunches.

Design constraints from the audit:
- The `.app` is usually in `/Applications` (admin-owned) — direct overwrite needs privileges; handle two install locations.
- The Python backend is embedded in the `.app`; updating the app updates everything. User data (`~/.podcastsync`, `~/PodcastMirror`, per-source custom folders) lives outside the bundle — never touched by an update.
- Fully silent installs are only frictionless with notarization (D1). Stage A keeps the Gatekeeper caveat but removes the “check GitHub manually” step.

**Stage A — lightweight updater (works with ad-hoc signing, $0):**
| # | Task | Size |
|---|------|------|
| AU1 | Publish update metadata in the release workflow: attach per-arch `PodcastSync-<ver>-<arch>.zip` (containing `.app`) + `.dmg` + `.sha256`, plus a generated `latest.json`: `{version, build, date, minOSVersion, notes_url, assets:[{arch, url, sha256, size}]}` (commit a small template; CI fills fields). | M |
| AU2 | Swift `Updater` service (`macos/PodcastSync/Sources/Updater.swift`): on launch + every 6h + manual “Check for Updates…” menu item, `GET latest.json` (GitHub Releases/raw or Pages URL), compare semver against `CFBundleShortVersionString`; publish `updateAvailable(version)`; `URLSession` with 20s timeout, TLS only. | M |
| AU3 | Menu bar UX: badge + “Update available — vX.Y.Z” row (blue dot, opens update panel), “Release Notes” deep link, “What’s New” via notes_url. | S |
| AU4 | Download & verify: stream asset to `~/Library/Caches/com.podcastsync.app/`, verify SHA-256 against `latest.json`, size check; show progress in the panel; on mismatch abort with error. | M |
| AU5 | Install & relaunch flow: if bundle is user-writable (`~/Applications`, user-owned `/Applications` copy) → quit backend + app, swap bundles atomically (staged copy in a temp dir, then `replaceItemAt`/`rename`), relaunch via `open`. If not writable → fallback: reveal the downloaded DMG in Finder with clear “drag to Applications” instructions (the honest option without privileges), or use `AuthorizationExecuteWithPrivileges`-style helper only as a later enhancement. Never run as root automatically in v1. | M |
| AU6 | Offline/hermetic tests for the updater state machine (fake manifest + stubbed URLSession), version-compare unit tests, sha256 mismatch handling. Wire into CI where macOS runner is used. | S |
| AU7 | Guard rails: never auto-install without explicit user click (menu-bar app); require macOS ≥ 13; skip when backend is mid-sync (defer prompt); ignore prerelease tags (or add explicit beta channel later); keep last-good fallback (don't delete the current bundle until the new one verifies). | S |

**Stage B — Sparkle migration (later, gated on D1/notarization):**
| # | Task | Size |
|---|------|------|
| AU8 | Embed Sparkle; generate EdDSA keypair; generate `appcast.xml` from the same release metadata that feeds `latest.json` (single source of truth in CI); per-arch feed items; Sparkle handles privilege elevation, delta updates, scheduled checks, relaunch. Requires signed+notarized builds (R7). | L |

**Phase 4 acceptance:** install the DMG build, then push a new tag → within one manual check the app reports the newer version; clicking Update downloads, verifies sha256, installs, relaunches with data intact (DB + episodes + settings preserved); a corrupted download aborts safely; "Check for Updates" finds "up to date" at latest.

### Phase 5 — Public-release sanitisation & launch

| # | Task | Size |
|---|------|------|
| G1 | **History rewrite (D4):** `git filter-repo` removing `venv.x86_old/` and `macos/PodcastSync/.build/`; re-create tag `v0.1.0` at its rewritten commit (or drop it); normalize author email to `shayprasad@gmail.com`; coordinate force-push timing (single-maintainer). Verify `git count-objects`/clone size and that no secrets/DBs ever appear (`git log --all -p` scan was clean). | L |
| G2 | Delete or archive remote branch `refactor/structural-cleanup` (D5) after merging anything still wanted from the planning doc. | S |
| G3 | Docs sanitisation: `HANDOFF.md` generic path example; `debug_app.sh` parametrize app path + fix Python checks; `backend/test_fetch.py` docstring "manual CLI test script" (drop “for M1”); `.gitignore` add `*.db-wal/shm/journal`, remove obsolete `venv.x86_old/`, add `.pytest_cache/`; README dynamic badges + Security section + real clone URL + current Gatekeeper (“Open Anyway”) instructions (ad-hoc path) + accurate HANDOFF/README Overcast wording (A9). | S |
| G4 | Community/legal files: `SECURITY.md` (threat model incl. DNS rebinding, LAN-only disclaimer, reporting policy, current mitigations per D6), `CONTRIBUTING.md` (dev setup, tests, conventions from `AGENTS.md`), `CHANGELOG.md` (Keep a Changelog; release notes derived from it), issue templates (bug/feature), PR template checklist, `dependabot.yml`, optional `CODEOWNERS`. Confirm GitHub repo license = MIT and `LICENSE` matches. | M |
| G5 | GitHub settings (manual): branch protection on `main` (PR + required CI checks), tag protection for `v*`, secret scanning + push protection, delete/archive stale branch, enable discussions/security overview as wanted. | S |
| G6 | Final QA sweep on a clean clone: fresh `git clone` → dev run → full suite → `build_app.sh` → smoke DMG on a second Mac if available; verify `build/` never tracked; verify packaged app boots, polls, serves feeds, updates (Phase 4). | M |
| G7 | Cut **v0.3.0**: bump `pyproject.toml` + CHANGELOG in one commit; tag `v0.3.0`; release workflow builds, tests, publishes DMG + sha256 + `latest.json` + zip assets; update `AGENTS.md` (remove fixed gotchas, document updater + manifest, keep cross-file contracts accurate). | S |

**Phase 5 acceptance:** repo clone is small and clean; `git log` shows no machine paths/artifacts/secrets; CI green on the tag; release page has DMG + sha256 + zips + `latest.json`; README/HANDOFF/SECURITY are accurate for strangers; fresh-clone dev + build follow the documented commands without any personal paths.

### Phase 6 — Public VPS / Docker deployment (optional; D7(b) — unlocks Overcast)

**Goal:** run the PodcastSync backend on an Oracle Cloud (or any) Linux VPS in Docker behind HTTPS so Overcast and all internet podcast clients can subscribe. The macOS menu bar app remains the local-control surface (optionally pointed at the remote server later); the backend itself is pure Python and fully cross-platform.

| # | Task | Size |
|---|------|------|
| V1 | **`PUBLIC_URL` configuration:** add a `PUBLIC_URL` env/setting (e.g. `https://podcast.yourdomain.com`). Feed self-links, enclosure URLs, `/feeds` list, and the web UI's copy-feed-URL logic (`settings.base_url` in `api.js:26-42`, `config.py:72-74`) must honour it when set, instead of the LAN-IP/request-derived values. Request-derived `base_url` stays only for LAN access. | M |
| V2 | **Proxy-awareness:** run uvicorn with `--proxy-headers` (or FastAPI `ProxyHeadersMiddleware`) so `request.base_url` is correct behind a reverse proxy; document required headers (`X-Forwarded-Proto/Host`). | S |
| V3 | **Docker packaging:** add a `Dockerfile` (multi-stage: python:3.12-slim + `apt-get install ffmpeg`, `pip install` from a pinned `requirements.lock`, non-root user) + `docker-compose.yml` with named volumes for `PODCASTSYNC_DB` (`~/.podcastsync` equivalent) and `PODCASTSYNC_STORAGE`; document `PODCASTSYNC_PORT`, `PODCASTSYNC_POLL_INTERVAL`, `YOUTUBE_API_KEY`, cookie settings. Add `scripts/docker-entrypoint.sh` running migrations via normal startup. | M |
| V4 | **Public security hardening (this becomes P0 when D7(b) is chosen):** the WS-C token/Host-allow-list work must ship *before* any public exposure; additionally restrict with a firewall (Oracle Cloud Security List / `ufw`) to 80/443 only and bind the app to an internal port; terminate TLS with Caddy or nginx + Let's Encrypt; optional HTTP Basic Auth or per-install token for the web UI. DNS-rebinding is irrelevant on a public IP but arbitrary-internet access replaces the "trusted LAN" model — see SECURITY.md. | M |
| V5 | **Cookies on a headless server:** browser-cookie extraction (`cookies_from_browser`) cannot work on Linux — document that server deployments must use a Netscape `cookies_file` (`PATCH /api/settings` cookie file path or volume-mounted) when YouTube requires sign-in; confirm the downloader already prefers `cookies_file_path` when `cookies_from_browser` is empty (`manager.py:89-95`). | S |
| V6 | **Operational docs:** README "Run on a server (Docker)" section — Oracle Cloud specifics (free-tier Ampere A1 ARM or AMD micro instance; Ubuntu 22.04/24.04; open ports in the VCN Security List; attach a public IP; ~10 TB/mo egress is ample for podcast audio; a domain + Let's Encrypt recommended because podcast clients strongly prefer HTTPS). | S |
| V7 | **Feed URL ergonomics:** when `PUBLIC_URL` is set, the web UI should present the public feed URL even when opened via localhost/SSH-tunnel; per-source copy-feed-URL and RSS/audio paths all render the public origin (ties into A4/feeds work). | S |

**Phase 6 acceptance:** `docker compose up` on an Oracle VPS with a domain → subscribe to `https://<domain>/feed/<id>.xml` in Overcast and Apple Podcasts and episodes download; `curl` to port 8642 from the internet is blocked; only 80/443 open; unauthenticated `/api/*` mutators reject without the token (per D6(b)); feed/audio URLs all carry the public HTTPS origin.

---

## 4. Suggested execution order & batching (commits/PRs)

1. **PR set 1 (Phase 0, backend):** B3, B4, B7, C1, B1+B2 (+ tests) — data-safety cluster.
2. **PR set 2 (Phase 0, backend):** B5, B6, B8, B9-B11 + A1-A8 (+ feed tests) — behavior cluster.
3. **PR set 3 (Phase 0, security):** C2-C7 + C3 baseline (Host allow-list + token) (+ tests).
4. **PR set 4 (Phase 1):** T1-T6 (CI split, ruff, node tests).
5. **PR set 5 (Phase 2):** U1-U14 (frontend bugs → UX → CSS/cache-bust cleanup).
6. **PR set 6 (Phase 3):** R1-R5.
7. **PR set 7 (Phase 4):** AU1-AU7 (auto-update).
8. **PR set 8 (Phase 5):** G1-G5, then cut v0.3.0 (G6-G7).
9. **PR set 9 (Phase 6, if D7(b)):** V1, V2, V4 first (config + security), then V3/V5-V7 (Docker + docs). This can land before or after the macOS release; it depends only on Phases 0-1.

Batches 1-2 swap cleanly if feed fixes (A1) are wanted first — A1 alone is the single highest-impact *perceived* fix for podcast clients.

---

## 5. Open questions to resolve during implementation

1. Overcast: is D7(b) (public VPS deployment) in scope for v1? If not, README keeps an explicit "Overcast is unsupported on a LAN-only feed (server-side crawling); it works if the server is publicly reachable" line.
2. Rolling delete: confirm keep-N means “keep the N newest episodes by publish date” (undated episodes count as oldest → first deleted). OK?
3. Auth (D6): accept the per-install token + Host allow-list as the v1 posture, with LAN-only binding retained?
4. Auto-update (AU5): is “reveal DMG in Finder when the app isn't user-writable” acceptable for v1, or should the privilege-helper path be scoped into Stage A?
5. Update channel: latest-stable only for v1 (prereleases ignored)?
6. `GET /feeds` route and `/feeds` list API: unused by the client — remove or keep for API consumers?

---

## Appendices (condensed findings driving the tasks above)

### Appendix A — Feed/client research (source: feed-audit agent)
- Overcast crawls feeds server-side (`crawl1..6.overcast.fm`); a `http://192.168.x.x` feed is unreachable from the internet → unsupported regardless of XML. Downcast and Apple Podcasts fetch on-device, hence the README claim. No XML fix exists; document + harden everything else.
- Order bug verified against feedgen 1.0.0 (`add_entry` defaults `order='prepend'`; DB already newest-first → output oldest-first).
- `itunes:duration` as integer seconds is spec-recommended — do not convert to `HH:MM:SS`.
- `FileResponse` Range/HEAD/Content-Length/ETag support landed in Starlette 0.39 → pin floor + test.
- Feed route has only `Cache-Control: max-age=300`; no `ETag`/`Last-Modified`; `lastBuildDate` churns per request.
- spec checklist in Section 3 / WS-A acceptance.

### Appendix B — Backend findings (source: robustness agent; verified)
- B1/B2 migration issues, B3 crash orphans, B4 inverted rolling delete, B5 concurrency double-download + gather leak, B6 blocking I/O, B7 custom-storage 403, B8 no retry + keyword sniffing, B9 settings parse crash, B10 sqlite/dynamic-SQL/art races, B11 scheduler aliasing — full mechanisms + exact fix recipes (including replacement SQL for rolling delete and column-explicit migration 003) in the agent report; recipes are encoded in WS-B above.

### Appendix C — Security findings (source: security agent; verified)
- S1 unauth + DNS rebinding; S2 cross-source deletion; S3 attribute XSS (needs API key + icon to fire, but trivial); S4 wrong containment root; S5 Host-poisoned feed URLs; S6 cookie probing disclosure (no cookie values leak); S7 pick-directory spam/path disclosure; S8 no arbitrary-host SSRF (host substring check sloppy only); S9 key stored plaintext in sqlite, never returned/logged (verified); S10 no exploitable SQLi; S11 dependency drift (`yt-dlp>=2026.01.01` in requirements.txt vs `>=2024.01.01` in pyproject; `mutagen`/`pyinstaller` only in requirements.txt); S12 no CSP + Google Fonts.
- Dependency remediation is folded into R2/R5 + a Phase 0 task: unify `requirements.txt` and `pyproject.toml`, add exact pins / `requirements.lock` with hashes for the bundled runtime, drive bumps via dependabot and rebuild releases.

### Appendix D — Frontend findings (source: frontend agent)
- Dispatch table / DOM ids / API shapes all consistent (no orphans) — the audit's top-line structural check passed.
- Verified bugs U1-U7 above with exact file refs; UX list U8-U11; debt U12-U14 incl. precise dead-code list and the CSS retirement recommendation (no modular rule ever wins — they're a shadowed snapshot; “finishing” the split needs a visual-diff harness that doesn't exist; retire instead).
- `?v=9` cache-bust only versions `index.html`-linked assets; ES-module imports and CSS `@import`s are unversioned (rely on ETag revalidation) — U13.

### Appendix E — Packaging/CI findings (source: packaging agent; scheduler alias verified in `backend/scheduler.py:19`)
- ffmpeg check dead code; `|| true` swallows nested sign failures; stale-launcher fallback can ship old binary; awk-based hdiutil parsing; no PR CI; no smoke test; no dependabot; arch = arm64-only; version coupling w/o guard; stale workflow default.
- Notarization path documented (Developer ID cert + hardened runtime + timestamp; `xcrun notarytool` with App Store Connect API key `.p8` + key-id + issuer, or apple-id + app-specific password + team-id; notarize DMG (nested files covered) + `stapler staple`; paid program only, ~$99/yr; required for Developer ID apps to launch without override; ad-hoc path still works on current macOS via “Open Anyway”, reset per release). Ad-hoc runtime quarantine stripping stays until real signing exists.

### Appendix F — Test strategy (source: tests agent)
- New modules: `test_rolling_delete.py`, `test_video_ownership.py`, `test_custom_storage.py`, `test_sync_ingest.py`, `test_database.py` (+ migration upgrades), `test_download_manager.py` (fake `yt_dlp` injected into `sys.modules`; real class, no app state), `test_feed_golden.py`, `test_crash_recovery.py`, `test_fetchers.py` (+ `tests/fakes.py`), `test_scheduler.py`, `test_cookies_probe.py`, `test_audio_guard_and_ranges.py`, `test_packaging_inventory.py`.
- Lockstep warnings: `StubOrchestrator`/`StubDownloadManager` in `tests/conftest.py` mirror call signatures asserted as exact tuples — any signature change updates both; extend rather than break.
- Brittle tests to rework listed in T6.

### Appendix G — Release-hygiene checklist (source: security agent + verification)
- History blobs ~324 MB in `v0.1.0` (commit `4d245bc` added, `f612da6` removed; still in pushed history); 7 commits with `shayprasad@Shays-MBP.mynet`; remote branch holds `can-you-plan-a-partitioned-book.md`.
- Clean today: no secrets/DBs/apps/DMGs ever tracked; `git ls-files` = 91 source/docs files; `LICENSE` (MIT) present; tags `v0.1.0`/`v0.2.0` exist; releases already wired via `gh`.
- Full file-by-file stale-reference fix list in Section 3 / G3 (debug_app.sh, test_fetch.py docstring, HANDOFF path example, `.gitignore` WAL sidecars, workflow default, README badges incl. fake “downloads 68.7MB” and static `v0.2.0`, Overcast dedupe).

### Appendix H — Auto-update detail
See Phase 4. `latest.json` schema (draft):
```json
{
  "version": "0.3.0",
  "build": 30,
  "minOSVersion": "13.0",
  "date": "2026-09-04",
  "notes_url": "https://github.com/shay2000/PodcastSync/releases/tag/v0.3.0",
  "assets": [
    {"arch": "arm64", "kind": "app-zip", "url": "https://github.com/shay2000/PodcastSync/releases/download/v0.3.0/PodcastSync-0.3.0-arm64.zip", "sha256": "…", "size": 123456789},
    {"arch": "arm64", "kind": "dmg", "url": "…/PodcastSync.dmg", "sha256": "…", "size": …}
  ]
}
```
Generated by a small CI step (template in `scripts/`), uploaded as a release asset and mirrored to `https://raw.githubusercontent.com/shay2000/PodcastSync/main/release/latest.json`-style path or GitHub Pages for fetching without the API rate limit.

### Appendix I — Overcast reachability & public deployment (D7(b), requested)

- **Overcast works the moment the feed is publicly reachable.** Overcast fetches every subscription from its own crawlers on the public internet; a `http://192.168.x.x:8642` feed is unreachable, but `https://podcast.example.com/feed/1.xml` on a VPS is fetched like any normal podcast. Downcast and Apple Podcasts additionally fetch on-device, so they work both on the LAN and against the VPS. No XML change is required to "enable Overcast" — the fix is deployment reachability (public IP/domain + HTTPS) plus the code changes in V1/V2 so advertised URLs carry the public origin.
- **Oracle Cloud specifics (researched):** the Always Free tier offers Ampere A1 (ARM, up to 4 OCPU/24 GB) and AMD micro (1/8 OCPU, 1 GB) instances — either comfortably runs this single-process FastAPI backend (yt-dlp downloads + ffmpeg conversion are the only heavy moments; a 1-2 vCPU ARM instance handles a few concurrent downloads at 192 kbps). Ubuntu 22.04/24.04 arm64 images work; the Docker image is arch-agnostic (python:3.12-slim has arm64 variants). Free-tier egress (~10 TB/month on A1) is far beyond podcast-audio needs. Networking: the VCN Security List and instance firewall must open 80/443 (and SSH); the backend itself should stay on an internal port reachable only via the reverse proxy or the Docker network.
- **Consequences of going public (why D7(b) changes priorities):** the "trusted LAN, unauthenticated" model becomes "internet-facing"; WS-C (token/Host allow-list), TLS, and firewall rules become release-blocking rather than optional; browser-cookie auth doesn't exist on Linux (V5); and `PUBLIC_URL`/proxy handling (V1/V2) must be correct or podcast clients get enclosure URLs pointing at the wrong host/origin.
- macOS app interplay: the menu bar app currently assumes a local backend on 8642. For v1 of the VPS path, keep the web UI as the management surface for the remote server (optionally document an SSH-tunnel or future "server URL" setting in the app).

---

*Plan artifacts: this document is the owner-facing plan. `AGENTS.md` will be updated at G7 (and opportunistically as cross-file contracts change) to remove fixed gotchas and document the updater manifest, token auth, and new invariants.*
