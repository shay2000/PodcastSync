# PodcastSync — Implementation Spec (Handoff Edition)

**Handoff target:** an autonomous engineering agent (or human) implementing + testing the public-release hardening of PodcastSync, primarily on a Linux VPS (Docker-capable), with optional macOS for packaging steps.
**Source repo (as of handoff):** `github.com/shay2000/PodcastSync`, branch `public-release-hardening` (created 2026-09-04). Commit `a9ff853` contains this plan and `AGENTS.md`.
**Read first:** `AGENTS.md` (repo root) = living codebase guide. This file + its sub-documents = the change spec. `docs/PUBLIC_RELEASE_PLAN.md` = the shorter strategy/overview this spec expands.

---

## 0. How to use this spec

1. Work **one phase at a time**, in the order below. Every phase has its own file with numbered tasks (e.g. `B1`). Tasks are small enough for one commit each, and **each task says exactly which tests to write and how to verify**.
2. Create a branch for each phase off the handoff branch:
   ```bash
   git checkout -b public-release-hardening origin/public-release-hardening   # or clone fresh
   git checkout -b implementation/phase0-feed
   ```
   Never commit to `main` or to the handoff branch directly. Squash-merge/PR when a phase is green.
3. **Test-first discipline:** the suite is an *offline characterization suite*. For every bug fix, write the failing test first (or keep a `pytest.mark.xfail`/characterization test), then make it pass. **Lockstep warning:** `tests/conftest.py` swaps `app.state.orchestrator` / `app.state.download_manager` with stubs and several tests assert *exact recorded call tuples*. If you change a method signature (`fetch_videos`, `process_pending_downloads`, `resolve_to_channel_id`, …), update the stubs and the asserting tests **in the same commit**.
4. **Run the suite after every task:**
   ```bash
   source venv/bin/activate && python -m pytest tests/ -q
   ```
5. Mark progress by updating the Phase Summary table at the end of each phase file (`[ ]` → `[x]`).
6. When you change anything the `AGENTS.md` "Known gotchas & risks" section describes, update `AGENTS.md` in the same PR.

### File tree of this spec

| File | Covers |
|---|---|
| `docs/IMPLEMENTATION_SPEC.md` (this file) | Handoff guide, environment, conventions, platform matrix, global invariants, overall Definition of Done |
| `docs/implementation/wsA-feeds.md` | Podcast-client/RSS compatibility fixes (tasks A1–A9) |
| `docs/implementation/wsB-backend.md` | Backend data-safety + robustness (tasks B1–B11, incl. new migration 004) |
| `docs/implementation/wsC-security.md` | Security posture (tasks C1–C7) |
| `docs/implementation/phase1-gates.md` | Test expansion + CI/quality gates (T1–T6) |
| `docs/implementation/phase2-frontend.md` | Frontend/UI fixes + polish (U1–U14) |
| `docs/implementation/phase3-packaging.md` | macOS packaging + release engineering (R1–R7) |
| `docs/implementation/phase4-autoupdate.md` | Auto-update feature (AU1–AU8) |
| `docs/implementation/phase5-hygiene.md` | Repo sanitisation + docs + GitHub settings (G1–G7) |
| `docs/implementation/phase6-vps.md` | Public VPS/Docker deployment, unlocks Overcast (V1–V7) |

---

## 1. Environment

### Linux VPS (this is the primary implement-and-test environment)

The backend, the whole test suite, the packaging-inventory test, ruff, and the Docker phase run on Linux. No macOS needed for phases 0–2 and 6.

```bash
# Ubuntu 22.04/24.04 arm64 or amd64
sudo apt-get update
sudo apt-get install -y ffmpeg python3.12-venv git   # python3.12 via deadsnakes PPA if not present
git clone https://github.com/shay2000/PodcastSync.git
cd PodcastSync && git fetch origin public-release-hardening && git checkout public-release-hardening
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"          # dev extras = pytest, pytest-asyncio, httpx
python -m pytest tests/ -q       # must be green before you change anything
```

Notes:
- Tests are fully offline (temp DB/storage per test, fetcher/downloader stubbed) — **no network, no yt-dlp, no API key** needed to run the suite.
- `ffmpeg` is required only to boot a real `DownloadManager`; the suite stubs it out. Manual E2E of downloads on the VPS needs real ffmpeg + YouTube access (install it: `sudo apt-get install -y ffmpeg`).
- **Do not** run `backend/test_fetch.py` against a live DB; it is a manual CLI that writes to the real settings DB path. It is excluded from pytest by `testpaths`.

### macOS (only for tasks flagged `[macOS]`)

Phases 3 and parts of 5 (Swift build, PyInstaller bundle, DMG, codesign). Phase 1’s Swift lint step also needs macOS. These tasks must be run on an Apple machine (or skipped with a `SKIPPED_ON_LINUX` note if out of scope for this handoff).

### Platform matrix

| Phase | Linux-testable | macOS-only |
|---|---|---|
| Phase 0 (A/B/C) | Yes (all of it) | — |
| Phase 1 (T) | Yes except T2 Swift job, T4 package smoke | T2’s `swift build` job, T4 (runs on `macos-14` in CI) |
| Phase 2 (U) | Yes (backend static UI served locally; use browser/curl) | — |
| Phase 3 (R) | R2/R5 partial (version guards, dependabot, badges); R1/R3/R4/R6/R7 need macOS/CI | R1, R3 (script-level), R4, R6, R7 |
| Phase 4 (AU) | AU2–AU7 logic can be built + unit-tested on Linux (Swift does not run; use CI macOS job to compile) | AU1/AU8 (workflow), compile checks |
| Phase 5 (G) | G1–G5 yes | G6 final .dmg QA |
| Phase 6 (V) | Yes (this is the point) | — |

---

## 2. Conventions and global invariants (apply everywhere)

1. **Backend routing:** routes pull collaborators off `request.app.state.*` per request. Never cache them at module import. The test suite depends on swapping `app.state.orchestrator`/`download_manager` after lifespan startup. Preserve this pattern.
2. **Imports:** absolute `backend.`-prefixed. `from __future__ import annotations` first in every module you touch.
3. **Lazy heavy imports stay lazy:** `yt_dlp`, `googleapiclient`, `feedgen`, `lxml` are imported inside functions to keep startup fast. Do not promote them to module scope.
4. **Every new module that PyInstaller might miss must be added to the `--hidden-import` list in `scripts/build_backend.sh`** (cross-file contract; T3’s `test_packaging_inventory.py` enforces it).
5. **New non-Python resources** (directories/data files read via `backend/_resources.py`) must be copied by `scripts/build_backend.sh` and must live under `backend/`.
6. **Migration numbering:** the runner applies `backend/migrations/NNN_*.sql` sorted lexically; the numeric prefix is the version. Next free number is `004`.
7. **DB access:** `backend/database.py` owns all SQL. Routes/services never hand-write SQL except `services/sync.py:30` and `conftest` (documented exceptions).
8. **Feeds are public XML** (no `/api` prefix, mounted at root). `/api/*` is JSON. The static UI mount at `/` must stay last in `main.py`.
9. **Python floor 3.10** (modern builtin generics OK). Ruff config to be added targets `py310`.
10. **Commit hygiene:** one logical change per commit; include its tests; never commit `build/`, DBs, venvs, `.DS_Store`, or secrets (see `.gitignore`).

---

## 3. Task summary (id — title — priority — size — phase file)

Phase 0 — Feed/client compatibility (`wsA-feeds.md`):
- A1 RSS items newest-first · P1 · S
- A2 Real enclosure length from disk · P2 · S
- A3 Channel `itunes:category` · P2 · S
- A4 Channel `<link>` = source website · P2 · S
- A5 Stable `lastBuildDate` + ETag/304 on feed route · P2 · S
- A6 Log unparseable publish dates · P3 · S
- A7 Exclude completed-but-fileness videos from feed · P1 · S
- A8 Pin `starlette>=0.39` + Range/HEAD regression test · P2 · S
- A9 Docs: Overcast/LAN + Local Network permission · P2 · S

Phase 0 — Backend data-safety (`wsB-backend.md`):
- B1 Migration runner concurrency + atomicity · P0 · M
- B2 Rewrite migration 003 column-explicit · P0 · S
- B3 Crash recovery of `downloading` rows · P0 · S
- B4 Rolling-delete keep-newest fix · P1 · M
- B5 Sync mutual exclusion + row claiming · P1 · M
- B6 Non-blocking fetchers + timeouts · P1 · M
- B7 Audio serving allow-list fix (custom storage) · P1 · S
- B8 Retry + failure taxonomy (migration 004) · P1 · M
- B9 Settings/`schema_version` parse hardening · P2 · S
- B10 DB polish (busy_timeout, whitelists, atomic delete) · P2 · M
- B11 Scheduler coalescing + bundling check · P2 · S

Phase 0 — Security (`wsC-security.md`):
- C1 Video ownership scoping · P0 · S
- C2 Attribute-safe escaping + CSP · P1 · S
- C3 Host allow-list + optional API token (pick baseline) · P0 if VPS · M
- C4 Feed/enclosure origin consistency · P1 · S
- C5 CSRF tightening for body-less mutators · P1 · S
- C6 Cookie probe hardening · P2 · S
- C7 Key hygiene (Keychain optional, DB perms) · P2 · M

Phase 1 — Gates (`phase1-gates.md`): T1 locking tests (A–F module list) · T2 `ci.yml` · T3 ruff · T4 package smoke · T5 JS tests · T6 brittle-test rework.

Phase 2 — Frontend (`phase2-frontend.md`): U1–U14 per the plan table.

Phase 3 — Packaging (`phase3-packaging.md`): R1 build script hardening · R2 version single-sourcing · R3 hidden-import/resource guards + scheduler bundle check · R4 Info.plist · R5 dependabot/badges · R6 arch matrix · R7 notarization pipeline.

Phase 4 — Auto-update (`phase4-autoupdate.md`): AU1 manifest/CI · AU2 Swift Updater · AU3 menu UX · AU4 download+verify · AU5 install/relaunch · AU6 tests · AU7 guard rails · AU8 Sparkle migration (staged).

Phase 5 — Hygiene (`phase5-hygiene.md`): G1 history rewrite · G2 branch cleanup · G3 docs/.gitignore fixes · G4 community files · G5 GitHub settings · G6 QA · G7 v0.3.0 cut.

Phase 6 — Public VPS/Docker (`phase6-vps.md`): V1 PUBLIC_URL config · V2 proxy headers · V3 Dockerfile/compose · V4 public security hardening · V5 cookies on headless · V6 operational docs (Oracle) · V7 feed-URL ergonomics.

---

## 4. Global Definition of Done

Run on the Linux VPS after each phase:

```bash
source venv/bin/activate
python -m pytest tests/ -q                       # all green
ruff check backend tests && ruff format --check backend tests   # from Phase 1 on
```

Then, for the whole program (at least once, on a Linux host):

1. `git clone` the handoff branch cleanly; the above commands succeed with zero personal paths.
2. Start the backend (`uvicorn backend.main:app --host 127.0.0.1 --port 8642` or `./scripts/dev.sh`) with temp env vars and confirm:
   - `curl -s http://127.0.0.1:8642/api/status` returns JSON with `server_running: true`.
   - `curl -s http://127.0.0.1:8642/` returns the web UI HTML.
   - Adding a source via `POST /api/sources` with a **direct channel URL** works offline-testable only with stubbed fetcher; with a real (public) YouTube URL and network available it should return 201.
3. Generate a feed via a seeded DB (see `tests` recipes) and validate: newest-first order, RFC822 pubDate, enclosure url+length+type, `isPermaLink="false"` guid, `itunes:category`, channel `<link>` = YouTube URL, `ETag` present, conditional GET → 304.
4. `curl -I -H "Range: bytes=0-99"` against an audio file returns `206 Partial Content` + `Content-Range`.
5. Cross-source deletion attempts return 404 (see C1 test).
6. Security posture (per D6 baseline chosen in C3): requests with disallowed Host or (if enabled) missing token are rejected; plain GETs still work on LAN.
7. Docker phase: `docker compose up -d` on a public VPS → feed reachable over HTTPS behind Caddy; Overcast subscribes (public reachability). HTTP direct-to-app port is closed externally.
8. All phases’ per-file Phase Summaries are `[x]`.

---

## 5. Sequencing and batching

Recommended commit/PR batches (also in the plan doc §4):

1. `implementation/phase0-feed` — A1–A9 (+ A1 has its own locking test; A7 modifies a DB query used by feeds and A8 adds a route test).
2. `implementation/phase0-backend-1` — B3, B4, B7, B2, B1 (data-safety core) with their tests.
3. `implementation/phase0-backend-2` — B5, B6, B8, B9, B10, B11 with tests.
4. `implementation/phase0-security` — C1–C7 with tests.
5. `implementation/phase1-gates` — T1–T6 (this is where ruff + ci.yml land; run it before later phases so every later phase is lint-clean).
6. `implementation/phase2-frontend` — U1–U14.
7. `implementation/phase3-packaging` — R1–R5 (macOS or CI), R6/R7 deferred.
8. `implementation/phase4-autoupdate` — AU1–AU7.
9. `implementation/phase5-hygiene` — G1–G5, then G7 (v0.3.0) once QA passes.
10. `implementation/phase6-vps` — V1–V7 (can start as soon as phase 0/1 are green — it is the deployment the handoff VPS exists for).

Where a task needs a decision from the owner, the spec says **`[DECISION]`** and recommends a default. Proceed with the default unless told otherwise; record the decision in the PR description.
