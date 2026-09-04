# WS-B — Backend data-safety & robustness (tasks B1–B11)

Files: `backend/database.py`, `backend/downloader/manager.py`, `backend/services/sync.py`, `backend/services/paths.py`, `backend/routes/audio.py`, `backend/config.py`, `backend/scheduler.py`, `backend/main.py`, `backend/downloader/artwork.py`, `backend/fetcher/rss_fetcher.py`, `backend/fetcher/api_fetcher.py`, `backend/migrations/004_*.sql` (new), and tests in `tests/` (mostly added in Phase 1; where a test is described here, add it in the same commit as the fix).

**Migration note:** this phase adds migration `004`. Because B1/B2 change the runner and rewrite 003 *in place*, apply B1+B2 together and **do not run new code against the old 003 until the rewrite lands**. Migrations must stay cumulative (001 → 002 → 003 → 004) — never edit an applied migration that shipped (003 shipped in v0.2.0). Instead:
- Fix the *runner* (B1) so it is transactional and serialized.
- Make 003’s fragile rebuild safe by *not depending on it* for fresh installs? No — fresh installs still replay 003. So **rewrite 003 in place** (B2) with an explicit-column copy. Rewriting an already-shipped migration is acceptable only because the change is semantics-preserving for the happy path and fixes corruption risk for both fresh and in-flight upgrades. State this in the commit message.

---

## B1 — Migration runner: concurrency-safe, transactional, per-migration atomicity

- **Priority:** P0 · Size: M
- **Current behaviour (verified):**
  ```python
  # database.py:26        sqlite3.connect(..., check_same_thread=False)  # no busy_timeout
  # database.py:41-55
  def initialize(self):
      current_version = self._get_schema_version()
      for mf in sorted(...):
          if version > current_version:
              self.conn.executescript(sql)     # executescript commits any pending txn first
              self._set_schema_version(version)
      self.conn.commit()
  ```
  Two processes starting together both read `schema_version=2`, both run migration 002’s `ALTER TABLE`, and the loser dies with `duplicate column name`. A crash mid-003 leaves a half-migrated DB with no recovery.
- **Required change — rewrite `DatabaseManager.initialize()` and connection setup:**

  1. In the `conn` property (`database.py:23-30`), add:
     ```python
     self._conn.execute("PRAGMA busy_timeout = 5000")
     ```
     Keep `check_same_thread=False`, `row_factory`, WAL, foreign_keys.

  2. Replace `initialize()`:
     ```python
     def initialize(self) -> None:
         """Create the DB and apply pending migrations.

         Serializes concurrent migrators with BEGIN IMMEDIATE, and applies
         each migration inside one transaction so a failure cannot leave the
         schema half-applied.
         """
         conn = self.conn
         # Serialize across processes: blocks up to busy_timeout if another
         # instance is migrating, then raises sqlite3.OperationalError
         # ("database is locked") if it still cannot acquire.
         conn.execute("BEGIN IMMEDIATE")
         try:
             current = self._get_schema_version()          # read INSIDE the lock
             for mf in sorted(MIGRATIONS_DIR.glob("*.sql")):
                 version = int(mf.stem.split("_")[0])
                 if version <= current:
                     continue
                 logger.info("Applying migration %s", mf.name)
                 self._run_migration_statements(conn, mf.read_text())
                 # Version bump is the LAST step of the same transaction.
                 conn.execute(
                     "INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', ?)",
                     (str(version),),
                 )
                 current = version
             conn.execute("COMMIT")
         except Exception:
             conn.execute("ROLLBACK")
             raise
         logger.info("Database initialized at %s (schema v%d)", self.db_path, self._get_schema_version())
     ```
  3. Add the statement executor. Python’s `executescript` implicitly commits any pending transaction, so **cannot** be used inside `BEGIN IMMEDIATE`. Split each migration file on statement boundaries and run each statement with `conn.execute` (all files in this repo are simple `;`-terminated statements with `--` comment lines — no embedded semicolons):
     ```python
     def _run_migration_statements(self, conn, sql: str) -> None:
         statements = []
         for raw in sql.split(";"):
             text = "\n".join(
                 line for line in raw.splitlines()
                 if not line.strip().startswith("--")
             ).strip()
             if text:
                 statements.append(text)
         for statement in statements:
             conn.execute(statement)
     ```
  4. `_get_schema_version()` (`database.py:57-64`): keep swallowing `OperationalError` for the *fresh-DB* case, but if the value exists and `int()` fails, fail loudly rather than pretend version 0 (re-running 002/003 against a real DB would crash confusingly):
     ```python
     def _get_schema_version(self) -> int:
         try:
             row = self.conn.execute(
                 "SELECT value FROM settings WHERE key = 'schema_version'"
             ).fetchone()
             if row is None:
                 return 0
             try:
                 return int(row["value"])
             except ValueError:
                 logger.critical("Corrupt schema_version in settings: %r", row["value"])
                 raise RuntimeError(
                     "The settings table has a corrupt schema_version; restore a backup."
                 ) from None
         except sqlite3.OperationalError:
             return 0
     ```
  5. `_set_schema_version()` (`database.py:66-71`) is now redundant — remove it or keep as a no-op wrapper used only by tests; remove the call from `initialize()` (the version is upserted inline in the transaction).
  6. Note: `conn` is created with default `isolation_level` (deferred). `BEGIN IMMEDIATE` on a fresh connection is fine. Do **not** set `isolation_level=None` here; `execute()` helpers rely on autocommit-by-commit today and we are not changing that behaviour in this task.

- **Edge cases:**
  - Fresh empty file: 001 creates `settings`; version upserts work. OK.
  - Two processes: the second blocks in `BEGIN IMMEDIATE` up to `busy_timeout` (5 s), then raises `OperationalError`. In `main.py` lifespan, let that propagate (app fails fast with a clear log) — or catch and log “another PodcastSync instance is migrating/starting”. Recommend: let it crash loudly; the packaged app’s Swift layer already reports “Failed to start”.
  - A migration that is *not* idempotent (002/003) can only be reached once because the version gate is inside the same transaction as the DDL.
- **Tests (add now, `tests/test_database.py`; full design in Phase 1):**
  - `test_fresh_install_is_schema_v3`: tmp DB → `initialize()` → version == 3, `sources` has `max_keep_episodes`, `videos` CHECK includes `deleted`.
  - `test_initialize_is_idempotent`: call `initialize()` twice → no error, version stays 3.
  - `test_concurrent_initialize_does_not_double_apply`: open two `DatabaseManager`s on the same file; run `initialize()` sequentially (second run must no-op); then run both again interleaved in threads (optional) asserting no `duplicate column` error and final version 3.
  - `test_corrupt_schema_version_fails_loudly`: set `schema_version='garbage'`, expect `RuntimeError`.

---

## B2 — Rewrite migration 003 to be column-explicit

- **Priority:** P0 · Size: S
- **Current behaviour (verified, `backend/migrations/003_rolling_delete.sql:24`):** `INSERT INTO videos SELECT * FROM videos_old;` — positional; breaks silently if column order/count ever diverges between the two `videos` definitions. It also does not re-seed `sqlite_sequence`, so after the rebuild `AUTOINCREMENT` can reissue an old id.
- **Required change:** replace the file’s copy statement with an explicit column list and re-seed the sequence. Full new content:
  ```sql
  -- Migration 003: rolling-delete keep limit + 'deleted' video status

  -- SQLite can't modify CHECK constraints in-place, so recreate the videos table.
  ALTER TABLE videos RENAME TO videos_old;

  CREATE TABLE videos (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id        INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
      video_id         TEXT    NOT NULL,
      title            TEXT    NOT NULL DEFAULT '',
      description      TEXT    NOT NULL DEFAULT '',
      publish_date     TEXT,
      duration_seconds INTEGER,
      thumbnail_url    TEXT,
      download_status  TEXT    NOT NULL DEFAULT 'pending'
                              CHECK (download_status IN ('pending','downloading','completed','failed','skipped','deleted')),
      file_path        TEXT,
      file_size        INTEGER,
      error_message    TEXT,
      created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
      UNIQUE(source_id, video_id)
  );

  INSERT INTO videos
      (id, source_id, video_id, title, description, publish_date, duration_seconds,
       thumbnail_url, download_status, file_path, file_size, error_message, created_at)
  SELECT id, source_id, video_id, title, description, publish_date, duration_seconds,
         thumbnail_url, download_status, file_path, file_size, error_message, created_at
  FROM videos_old;

  DROP TABLE videos_old;

  ALTER TABLE sources ADD COLUMN max_keep_episodes INTEGER;

  -- Keep AUTOINCREMENT monotonic across the rebuild.
  UPDATE sqlite_sequence SET seq = (SELECT COALESCE(MAX(id), 0) FROM videos) WHERE name = 'videos';

  INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '3');
  ```
  (In the new runner this file is executed statement-by-statement inside one transaction, so the whole rebuild is atomic.)
- **Tests (in `tests/test_database.py`):** upgrade fixtures:
  - Build a v1 DB by running only `001_initial.sql` statements, seed a source + a couple of videos (one `downloading`, one with every column populated), run `initialize()` → version 3; rows byte-identical; new columns NULL; `sqlite_sequence.seq >= MAX(videos.id)`.
  - Same from a v2 DB (001 + 002).
- **Verify:** `python -m pytest tests/test_database.py -q`.

---

## B3 — Crash recovery: reconcile stale `downloading` rows at startup

- **Priority:** P0 · Size: S
- **Current behaviour (verified):** `manager.py:130` sets `downloading`; the row only leaves that state via `download_video`’s final write (`:138-167`). A crash between those leaves the row `downloading` forever: excluded from `get_pending_videos` (`database.py:181-185`), excluded from feeds, never retried.
- **Required change:**
  1. Add `DatabaseManager.recover_stale_downloads() -> dict`:
     ```python
     def recover_stale_downloads(self) -> dict:
         """Reconcile rows left in 'downloading' by a crashed process.

         If a real, non-empty file exists at the recorded file_path the
         download actually finished before the crash: mark completed.
         Otherwise reset to pending so the next sync retries it.
         """
         rows = self.fetch_all(
             "SELECT * FROM videos WHERE download_status = 'downloading'"
         )
         completed = pending = 0
         for row in rows:
             fp = row["file_path"]
             if fp and Path(fp).exists() and Path(fp).stat().st_size > 0:
                 self.update_video_status(
                     row["id"], "completed",
                     file_path=fp, file_size=Path(fp).stat().st_size,
                 )
                 completed += 1
             else:
                 self.update_video_status(
                     row["id"], "pending",
                     error_message=None, file_path=None, file_size=None,
                 )
                 pending += 1
         if rows:
             logger.info("Recovered %d completed / %d pending stale downloads",
                         completed, pending)
         return {"completed": completed, "pending": pending}
     ```
     (`update_video_status` signature `(video_id, status, **fields)` already supports the extra fields; passing `None` writes NULL.)
  2. Call it in `main.py` lifespan right after `db.initialize()` and before the scheduler starts (`main.py:35-37`), and log the result.
- **Tests (`tests/test_crash_recovery.py`, added now):** seed through a pre-populated DB file (point `PODCASTSYNC_DB` at it before lifespan via the `api` fixture pattern) rows in every status; assert: stale `downloading` with a real file → `completed`; stale `downloading` without a file → `pending`; `completed`/`failed`/`skipped`/`deleted` untouched.
- **Verify:** full suite.

---

## B4 — Rolling delete: keep the newest N

- **Priority:** P1 · Size: M
- **Current behaviour (verified):** `database.py:216-224`:
  ```python
  SELECT * FROM videos
  WHERE source_id = ? AND download_status = 'completed' AND file_path IS NOT NULL
  ORDER BY publish_date ASC
  LIMIT -1 OFFSET ?
  ```
  Offsetting an *ascending* list by `max_keep` skips the **oldest** N and returns the **newest** overflow → deletes newest files and keeps oldest N. Downloads run oldest-first (`get_pending_videos` ASC + sequential `process_pending_downloads`), so during a backfill the file just downloaded is deleted immediately. Contradicts the caller comment (`manager.py:202` “Delete oldest …”) and the UI label (“keep only this many downloaded episodes”, `models.py:20`).
- **Required change:**
  1. Rewrite the query to return the **oldest** overflow rows (the ones beyond the newest N):
     ```python
     def get_overflow_completed_videos(self, source_id: int, max_keep: int) -> list[sqlite3.Row]:
         """Return completed videos beyond the keep limit, oldest first, for rolling deletion.

         The innermost query takes the NEWEST max_keep (deterministic with an
         id tiebreak); everything older than those is the overflow, returned
         oldest-first so deletion proceeds oldest → newest.
         """
         return self.fetch_all(
             """SELECT * FROM (
                    SELECT * FROM videos
                    WHERE source_id = ? AND download_status = 'completed' AND file_path IS NOT NULL
                    ORDER BY publish_date DESC, id DESC
                    LIMIT -1 OFFSET ?
                ) ORDER BY publish_date ASC, id ASC""",
             (source_id, max_keep),
         )
     ```
  2. `manager.py` `_apply_rolling_delete` (`:201-211`): also clear path/size fields on delete so the DB row no longer advertises a file:
     ```python
     self.db.update_video_status(video["id"], "deleted", file_path=None, file_size=None)
     ```
     and catch `OSError` (not just `FileNotFoundError`) so one unwritable file cannot abort the pass:
     ```python
     except OSError as exc:
         logger.warning("Rolling delete failed for %s: %s", video["file_path"], exc)
     ```
  3. `process_pending_downloads` (`:213-249`): run the trim even when nothing was newly downloaded (user raising/lowering the keep limit must take effect), and do it once at the end instead of inside the per-download callback:
     ```python
     async def process_pending_downloads(self, ...) -> int:
         pending = self.db.get_pending_videos(source_id)
         completed = 0
         if pending:
             ...gather as today (no _apply_rolling_delete call inside)...
         if max_keep_episodes:
             self._apply_rolling_delete(source_id, max_keep_episodes)
         return completed
     ```
- **Edge cases:** undated episodes sort first in ASC → become the oldest and are deleted first under the corrected semantics (they are the least valuable to keep — acceptable; document in PR). Equal `publish_date` handled deterministically by the `id DESC`/`id ASC` tiebreaks.
- **Tests (write first; land with fix):**
  - DB-level `tests/test_rolling_delete.py`: 7 completed rows dated d1..d7, `max_keep=3` → returns d1..d4 (oldest four).
  - Manager-level: real `DownloadManager` with `find_ffmpeg` monkeypatched to `None` and `download_video` faked to write a fake MP3 + mark completed; 7 pending oldest-first, `max_keep=3` → final completed set = {d5,d6,d7}.
  - `max_keep_episodes=None` → nothing deleted.
- **Verify:** `python -m pytest tests/test_rolling_delete.py -q`; full suite.

---

## B5 — Sync mutual exclusion + transactional row claiming

- **Priority:** P1 · Size: M
- **Current behaviour (verified):** three trigger paths (scheduler poll `main.py:57-64`, `POST /sources/{id}/sync`, `POST /sync-all` — `routes/sync.py:12-35`) can run concurrently; `process_pending_downloads` snapshots the pending rows and both racers run yt-dlp against the same output path. `asyncio.gather` (no `return_exceptions`) means an exception in one `_download_one` can orphan its siblings.
- **Required change:**
  1. Add one `asyncio.Lock` in `main.py` lifespan and store it: `app.state.sync_lock = asyncio.Lock()`.
  2. Give `services/sync.py` an optional lock parameter (default `None` keeps every existing call working):
     ```python
     async def sync_source(source_id, db, orchestrator, download_manager, lock=None):
         ...
         async def _run():
             ...existing body...
         if lock is None:
             return await _run()
         async with lock:
             return await _run()
     ```
     and the same for `sync_all_sources(..., lock=None)` (acquire around the per-source loop).
  3. Wire the lock in `main.py` poll closure and in `routes/sync.py` background tasks:
     ```python
     # main.py
     async def poll_all_sources():
         async with app.state.sync_lock:
             await sync_all_sources(db, orchestrator, download_manager)
     # routes/sync.py — add a small wrapper so background tasks honor the lock
     from backend.services.sync import sync_source, sync_all_sources

     async def _locked_sync_source(source_id, request):
         async with request.app.state.sync_lock:
             await sync_source(source_id, request.app.state.db,
                               request.app.state.orchestrator,
                               request.app.state.download_manager)

     background_tasks.add_task(_locked_sync_source, source_id, request)
     ```
     (For `sync-all`, use a similar `_locked_sync_all`.)
  4. Row claiming (defense in depth, cheap): in `manager.py` `_download_one`, claim before download:
     ```python
     claimed = self.db.claim_video(row["id"])
     if not claimed:
         return
     ```
     with new `DatabaseManager.claim_video`:
     ```python
     def claim_video(self, video_db_id: int) -> bool:
         cur = self.conn.execute(
             "UPDATE videos SET download_status = 'downloading' WHERE id = ? AND download_status = 'pending'",
             (video_db_id,),
         )
         self.conn.commit()
         return cur.rowcount == 1
     ```
     (`download_video` also sets `downloading` later — harmless duplicate write; keep for clarity or remove.)
  5. Gather resilience in `process_pending_downloads`:
     ```python
     results = await asyncio.gather(
         *[_download_one(row) for row in pending], return_exceptions=True
     )
     for result in results:
         if isinstance(result, Exception):
             logger.warning("A download task raised: %s", result)
     ```
- **Tests:** `tests/test_sync_concurrency.py` — (a) with the real `DownloadManager` and a stubbed slow `download_video`, call `sync_source` twice via `asyncio.gather` against the same source; assert each row was downloaded exactly once (call-count per row == 1). (b) `_apply_rolling_delete` raising `OSError` does not prevent remaining rows from processing.
- **Lockstep:** `sync_source`/`sync_all_sources` gain an *optional* trailing parameter — existing exact-tuple assertions in `test_api_sync.py` are on recorded *stub* calls, not on these signatures, so they stay green. Update `conftest.StubDownloadManager` only if you change `process_pending_downloads`’s signature (you should not need to for this task).

---

## B6 — Non-blocking fetchers with timeouts

- **Priority:** P1 · Size: M
- **Current behaviour (verified):** `rss_fetcher.py:36` calls blocking `feedparser.parse(url)` directly in an `async def`; `api_fetcher.py` calls googleapiclient `.execute()` synchronously inside async methods (e.g. pagination loop). No timeouts. A stalled upstream freezes the event loop — every feed/audio/status request and the scheduler tick stalls for the duration.
- **Required change:**
  1. `rss_fetcher.py`: wrap the network call off-loop with a scoped socket timeout:
     ```python
     import asyncio
     import socket

     def _parse_with_timeout(url: str):
         old = socket.getdefaulttimeout()
         socket.setdefaulttimeout(30)
         try:
             return feedparser.parse(url)
         finally:
             socket.setdefaulttimeout(old)

     feed = await asyncio.to_thread(_parse_with_timeout, url)
     ```
  2. `api_fetcher.py`: read the file first. Convert each blocking `.execute()` call to `await asyncio.to_thread(lambda: request.execute())` (keep the service object construction lazy). If the module builds its own `Http`, pass a timeout:
     ```python
     from googleapiclient.discovery import build
     import httplib2
     http = httplib2.Http(timeout=30)
     self._service = build("youtube", "v3", developerKey=self.api_key, http=http)
     ```
     (Confirm the actual construction site when you read the file; if `build()` is called with only `developerKey`, add the `http` argument.) Simpler and lowest-risk alternative if many call sites: make the whole `fetch_videos`/`resolve_to_channel_id` bodies run inside one `asyncio.to_thread(self._fetch_in_thread, ...)` — recommend this if the file has many `.execute()` call sites, because sharing a single googleapiclient service across threads is fine as long as calls are serialized per instance (they are, by the to_thread wrapper).
- **Tests:** `tests/test_fetchers.py` — monkeypatch `feedparser.parse` with a function that records the running thread and blocks on an `asyncio.Event`; assert the event loop stays responsive (another task ticks) while the RSS fetch is in flight; assert a socket timeout is installed during parse.
- **Verify:** `python -m pytest tests/test_fetchers.py -q`.

---

## B7 — Audio serving: per-source allow-list (fix custom storage)

- **Priority:** P1 · Size: S
- **Current behaviour (verified):** `routes/audio.py:28` calls `resolve_audio_path(db, source, filename, settings)` which (with `settings` provided, `paths.py:39-40`) returns `output_dir_for_source(...) / filename` — i.e. the **custom** directory verbatim when the source has `custom_storage_path` set. The guard at `audio.py:35-39` then requires containment under `settings.storage_path` only → any custom path outside `~/PodcastMirror` is always `403`; the custom-storage feature is broken for serving. (Serving is *supposed* to come from where the file actually is: the DB `file_path`.)
- **Required change:**
  1. In `routes/audio.py`, resolve primarily from the DB row, then fall back to the computed folder; validate against an allow-list of roots; enforce the basename shape:
     ```python
     from pathlib import Path
     from backend.services.paths import output_dir_for_source, sanitize_filename

     video_id = Path(filename).stem
     row = db.fetch_one(
         "SELECT file_path FROM videos WHERE source_id = ? AND video_id = ?",
         (source_id, video_id),
     )
     file_path = Path(row["file_path"]) if row and row["file_path"] else None
     if file_path is None:
         # Legacy/back-compat path when no DB row exists yet.
         file_path = output_dir_for_source(settings, source) / filename

     allowed = {
         settings.storage_path.resolve(),
         output_dir_for_source(settings, source).resolve(),
     }
     resolved = file_path.resolve()
     if not any(resolved == root or root in resolved.parents for root in allowed):
         raise HTTPException(status_code=403, detail="Access denied")
     # The served name must be exactly the requested <video_id>.mp3
     if Path(filename).name != filename or resolved.name != f"{video_id}.mp3":
         raise HTTPException(status_code=403, detail="Access denied")
     if not resolved.exists() or not resolved.is_file():
         raise HTTPException(status_code=404, detail="Audio file not found")
     return FileResponse(path=str(resolved), media_type="audio/mpeg", filename=Path(filename).name)
     ```
     (The DB lookup is by `video_id` derived from the stem, so a traversal filename like `../../secret.mp3` fails the lookup → falls into the computed-path branch → fails the basename/containment checks → 403.)
  2. Keep `resolve_audio_path` in `paths.py` (still used elsewhere); note it may now be bypassed by the route — leave it for tests/other callers.
- **Tests (`tests/test_custom_storage.py`, add now):**
  - Source with `custom_storage_path=tmp_path/"elsewhere"`; write the MP3 there; `GET /audio/{id}/vid.mp3` → 200 (currently 403).
  - A file outside both roots still 403; traversal strings still never leak bytes (status in (403, 404)).
  - Feed enclosure for the custom-storage source still works (base URL + path shape).
- **Verify:** `python -m pytest tests/test_custom_storage.py tests/test_audio.py -q`.

---

## B8 — Retry transient failures + structured auth classification (migration 004)

- **Priority:** P1 · Size: M
- **Current behaviour (verified):** every failure sets status `failed` (`manager.py:163-167`); only `pending` rows are ever processed, so `failed` is permanent until manual requeue. Auth/bot failures are detected by keyword sniffing (`manager.py:191-198`) and only prefixed with `[AUTH_REQUIRED]`.
- **Required change:**
  1. New migration `backend/migrations/004_download_attempts.sql`:
     ```sql
     -- Migration 004: download attempt tracking for transient retries

     ALTER TABLE videos ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;

     INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '4');
     ```
  2. `DownloadManager` failure handling in `download_video`:
     ```python
     MAX_TRANSIENT_ATTEMPTS = 3

     # classification helper
     def _classify_error(self, exc: Exception) -> str:
         message = str(exc).lower()
         if message.startswith("[auth_required]"):
             return "auth"
         if any(k in message for k in (
             "timed out", "timeout", "connection", "unreachable",
             "temporarily", "rate limit", "too many requests", "503", "429",
         )):
             return "transient"
         return "permanent"
     ```
     In the `except Exception as exc:` block (`:163-167`):
     ```python
     error_msg = str(exc)[:500]
     cls = self._classify_error(exc)
     row = self.db.fetch_one("SELECT attempts FROM videos WHERE id = ?", (video_db_id,))
     attempts = (row["attempts"] if row else 0) + 1
     if cls == "transient" and attempts < MAX_TRANSIENT_ATTEMPTS:
         # Keep it visible to the user but let the next sync retry it.
         self.db.update_video_status(
             video_db_id, "pending",
             error_message=error_msg, attempts=attempts,
         )
     else:
         self.db.update_video_status(
             video_db_id, "failed",
             error_message=error_msg, attempts=attempts,
         )
     ```
     On the success path reset attempts: `update_video_status(..., "completed", ..., attempts=0)` (include `attempts=0` in the existing success writes at `:119-124` and `:145-150`). Also increment attempts on the empty-output failure (`:156-160`).
     `update_video_status` needs `attempts` in its dynamic column string — it already builds `, {k} = ?` from `**fields`, so passing `attempts=1` works once the column exists. (B10 adds the column allow-list; include `attempts` there.)
  3. `auth` failures remain `failed` (user must add cookies via Settings); keep the `[AUTH_REQUIRED]` prefix but ensure `_classify_error` treats it as auth regardless of wording changes (check the prefix, not keywords).
- **Tests:** `tests/test_download_manager.py` (fake `yt_dlp` in `sys.modules` — see Phase 1): transient exception twice then success → row downloads on retry, `attempts` increments then resets to 0; three transient failures → `failed` with `attempts=3`; `[AUTH_REQUIRED]` failure → `failed` immediately.
- **Lockstep:** no conftest stub changes needed (the stub’s `process_pending_downloads` does not run real downloads).

---

## B9 — Settings parse hardening

- **Priority:** P2 · Size: S
- **Current behaviour (verified):** `config.py:55-70` `load_from_db` does bare `int(db_settings["poll_interval_minutes"])` etc. A corrupt row crashes startup. `_default_db_path()` runs `mkdir` as a side effect of `from_env()` even when `PODCASTSYNC_DB` is set.
- **Required change:**
  ```python
  def _db_int(key: str, value: str, default: int) -> int:
      try:
          return int(value)
      except (TypeError, ValueError):
          logger.warning("Ignoring invalid DB setting %s=%r", key, value)
          return default

  def load_from_db(self, db_settings: dict[str, str]) -> None:
      if db_settings.get("youtube_api_key"):
          self.youtube_api_key = db_settings["youtube_api_key"]
      if "poll_interval_minutes" in db_settings:
          self.poll_interval_minutes = _db_int("poll_interval_minutes", db_settings["poll_interval_minutes"], self.poll_interval_minutes)
      if "server_port" in db_settings:
          self.server_port = _db_int("server_port", db_settings["server_port"], self.server_port)
      if "storage_path" in db_settings and db_settings["storage_path"].strip():
          self.storage_path = Path(db_settings["storage_path"])
      if "max_concurrent_downloads" in db_settings:
          self.max_concurrent_downloads = _db_int("max_concurrent_downloads", db_settings["max_concurrent_downloads"], self.max_concurrent_downloads)
      if "cookies_from_browser" in db_settings:
          self.cookies_from_browser = db_settings["cookies_from_browser"]
      if "cookies_file_path" in db_settings:
          self.cookies_file_path = db_settings["cookies_file_path"]
  ```
  Add `logger = logging.getLogger(__name__)` to `config.py`.
- **Tests:** in `tests/test_database.py` or a new `tests/test_settings.py`: seed corrupt `poll_interval_minutes`/`server_port` in a DB, run lifespan → app starts with defaults; `youtube_api_key_set` reflects a real key; empty-string `storage_path` ignored.
- **Verify:** full suite.

---

## B10 — DB polish

- **Priority:** P2 · Size: M
- **Changes:**
  1. `PRAGMA busy_timeout = 5000` in the `conn` property (already added in B1).
  2. `add_video` duplicate handling (`database.py:148-167`): do a pre-check `SELECT 1 FROM videos WHERE source_id=? AND video_id=?` and return `None`; keep the `IntegrityError` catch only as a race fallback, and log a warning if the error is *not* about the unique index (inspect `str(exc)`).
  3. Column allow-lists in `update_source` (`:135-138`) and `update_video_status` (`:187-190`):
     ```python
     SOURCE_UPDATE_COLUMNS = {"name", "enabled", "max_backfill", "custom_storage_path",
                              "max_keep_episodes", "uploads_playlist_id", "icon_url"}
     VIDEO_STATUS_COLUMNS = {"file_path", "file_size", "error_message", "attempts"}

     def update_source(self, source_id: int, **fields: Any) -> None:
         fields = {k: v for k, v in fields.items() if k in SOURCE_UPDATE_COLUMNS}
         if not fields:
             return
         ...existing sql...
     ```
     Same pattern for `update_video_status` (filter `fields` to `VIDEO_STATUS_COLUMNS`).
  4. `delete_source` (`:140-142`) atomicity — execute both DELETEs in one transaction:
     ```python
     def delete_source(self, source_id: int) -> None:
         self.conn.execute("DELETE FROM videos WHERE source_id = ?", (source_id,))
         self.conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
         self.conn.commit()
     ```
     (WAL + foreign_keys make the cascade redundant but harmless; keep for older DBs without the FK pragma.)
  5. Artwork cache race (`downloader/artwork.py:16-22`): download to a temp file in the same directory, then `os.replace` to `channel_icon.jpg`, so two concurrent downloads can’t interleave a torn write:
     ```python
     tmp = cache_dir / ".channel_icon.jpg.tmp"
     urllib.request.urlretrieve(icon_url, tmp)
     os.replace(tmp, cache_dir / "channel_icon.jpg")
     ```
- **Tests:** extend `tests/test_database.py` for allow-list behaviour (unknown keys are ignored, not interpolated) and `delete_source` cascade. Artwork race is covered implicitly by manager tests (fake icon embed) — no dedicated race test required.
- **Verify:** full suite.

---

## B11 — Scheduler coalescing + bundled-trigger check

- **Priority:** P2 · Size: S
- **Changes:**
  1. `scheduler.py:17-24`: add `coalesce=True, max_instances=1, misfire_grace_time=300` to `add_job` so a hung poll can’t stack interval ticks.
  2. `scheduler.py` uses `trigger="interval"` (an APScheduler alias string resolved at runtime via import strings — PyInstaller can miss `apscheduler.triggers.interval`). Add `apscheduler.triggers.interval` (and `apscheduler.triggers.cron`, `apscheduler.triggers.date` if you extend) to the `--hidden-import` list in `scripts/build_backend.sh`, and/or rely on the Phase-1 packaged smoke test (T4) to catch it. Do both.
- **Tests:** `tests/test_scheduler.py` — `create_scheduler` job id/interval present; `reschedule_poll` changes `job.trigger.interval` (assert on the trigger object, not `next_run_time`).
- **Verify:** full suite.

---

## WS-B Phase Summary

- [ ] B1 migration runner transactional/serialized
- [ ] B2 migration 003 column-explicit
- [ ] B3 crash recovery of `downloading` rows
- [ ] B4 rolling delete keeps newest N
- [ ] B5 sync lock + row claiming
- [ ] B6 non-blocking fetchers + timeouts
- [ ] B7 audio allow-list (custom storage serving)
- [ ] B8 retry taxonomy + migration 004
- [ ] B9 settings/schema-version parse hardening
- [ ] B10 DB polish
- [ ] B11 scheduler coalescing + bundling

Full-suite gate: `python -m pytest tests/ -q` green.
