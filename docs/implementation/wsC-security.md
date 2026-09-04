# WS-C — Security posture (tasks C1–C7)

Files: `backend/routes/videos.py`, `backend/database.py`, `backend/routes/audio.py`, `backend/static/js/format.js`, `backend/static/js/render/sources.js`, `backend/main.py`, `backend/config.py`, `backend/routes/feeds.py`, `backend/routes/cookies.py`, `backend/services/cookies.py`, `backend/models.py`, `docs/SECURITY.md` (new), plus tests.

Threat model (document in `SECURITY.md`): the app is a personal/LAN tool by design; if it is ever exposed publicly (Phase 6), the security posture below becomes mandatory, not optional. Full audit context is in the plan Appendix C. Verified non-issues you do NOT need to fix: SQL injection (all user data parameterized; interpolated column names are internal-only — but see B10 allow-lists), yt-dlp option injection (options dict, never argv), osascript injection (static script), API key never returned/logged.

---

## C1 — Scope video endpoints to their source [P0]

- **Current behaviour (verified, `routes/videos.py:27-53`):** `skip_video`, `delete_video_file`, `requeue_video` take `(source_id, video_db_id)` but only verify that *some* source exists (`_require_source`). A caller can DELETE `/api/sources/1/videos/{id}/file` for a video owned by source 2 and delete source 2’s file.
- **Required change:** fetch the video row and enforce ownership before acting:
  ```python
  def _require_video(db, source_id: int, video_db_id: int) -> sqlite3.Row:
      row = db.fetch_one("SELECT * FROM videos WHERE id = ?", (video_db_id,))
      if not row or row["source_id"] != source_id:
          raise HTTPException(status_code=404, detail="Video not found")
      return row
  ```
  Call it (after `_require_source`) in all three handlers, then pass the row/`video_db_id` to the db helpers as today. Return 404 (not 403) for both “no such video” and “video of another source” — identical observable behaviour, no existence oracle.
- **Tests (`tests/test_video_ownership.py`, write first):** with two sources each owning a video, attempt skip/delete-file/requeue of source A’s video through source B’s URL → 404 and *no change* to the owner’s row or disk file; nonexistent `video_db_id` → 404 (today it silently 204s); owner operations still succeed; deleting a completed video removes the file and sets status `deleted` with path/size cleared.
- **Verify:** `python -m pytest tests/test_video_ownership.py tests/test_api_videos.py -q`.

---

## C2 — Attribute-safe escaping + CSP [P1]

- **Current behaviour (verified):** `format.js:1-5`:
  ```js
  export function esc(value) {
      const element = document.createElement("span");
      element.textContent = value || "";
      return element.innerHTML;   // escapes & < > only — NOT double quotes
  }
  ```
  It is interpolated into double-quoted attributes at `render/sources.js:47`:
  ```js
  <img src="${esc(source.icon_url)}" alt="${esc(source.name)} artwork">
  ```
  A source name containing `"` (user-set via the add form or `PATCH /api/sources`) breaks out of the attribute; with an icon present this becomes a stored self-XSS vector reachable by any LAN/rebinding actor.
- **Required change:**
  1. Make `esc` quote-safe (safe in both text and double-quoted-attribute contexts):
     ```js
     export function esc(value) {
         const element = document.createElement("span");
         element.textContent = value || "";
         return element.innerHTML.replace(/"/g, "&quot;");
     }
     ```
     (`&quot;` renders as `"` in text nodes, so existing text usages are unaffected; `render/sources.js:132` etc. stay correct.)
  2. Belt-and-braces: validate/allow-list `source.icon_url` before rendering (hosts `i.ytimg.com`, `yt3.googleusercontent.com`, `www.youtube.com`; else treat as no icon). Add a small helper `isAllowedImageUrl(url)` in `format.js` and use it in `renderSourceArtMarkup` (`render/sources.js:44-49`).
  3. Add security headers on the FastAPI app (`main.py`). FastAPI does not have per-response middleware built in; add a lightweight `@app.middleware("http")` that sets, for all responses:
     - `Content-Security-Policy: default-src 'self'; img-src 'self' data: https://i.ytimg.com https://yt3.googleusercontent.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com`
       (Current HTML loads Syne/DM Sans from Google Fonts. If you drop the font links in the Phase-2 UI cleanup, tighten to `default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://i.ytimg.com https://yt3.googleusercontent.com`.)
     - `X-Content-Type-Options: nosniff`
     - `Referrer-Policy: no-referrer`
     - `X-Frame-Options: DENY` (until C5; harmless for this UI)
     Beware: the app inlines element `style="--tile-accent:…"` attributes, so `style-src` must allow `'unsafe-inline'` unless you migrate to a `<style>` block — keep `'unsafe-inline'` for `style-src` only, not `script-src`. Do **not** add a CSP that blocks the existing inline `style=` attributes or you will break tile colors.
- **Tests:** frontend `esc()` tests (Phase 1 T5) pinning `"` `'` `&` `<` `>` backtick; a Python test asserting the CSP header is present on `/api/status` and `/`.
- **Verify:** manual — save a source named `x" onerror="alert(1)` and reload; no handler fires; network tab shows CSP header.

---

## C3 — Host allow-list + optional API token (security baseline) [P0 if VPS; P1 otherwise]

`[DECISION]` Default recommended baseline for this handoff:
- **Always on:** `TrustedHostMiddleware`-style Host allow-list (blocks DNS rebinding and Host-header poisoning of feed URLs).
- **Optional but recommended when public (Phase 6):** a per-install bearer token required on all `/api/*` requests, sent by the web UI and the Swift menu-bar app.

**Why:** no Host validation anywhere today. A malicious website can DNS-rebind `evil.example → 192.168.x.y:8642` and, because the browser sees it as same-origin, drive every endpoint. Body-less POSTs are additionally cross-site form-CSRF-able.

**Required change — part 1 (Host allow-list):**
1. New module `backend/security.py`:
   ```python
   """Origin/host validation and optional API bearer-token enforcement."""

   from __future__ import annotations

   import secrets
   from typing import Optional

   def host_is_allowed(host: str, settings) -> bool:
       """True when the request Host header is one we serve.

       Allows localhost/127.0.0.1, the detected LAN IP, the configured
       public host (PUBLIC_URL host, see Phase 6), and anything in
       PODCASTSYNC_ALLOWED_HOSTS (comma-separated, with optional port).
       """
       import os
       host = host.split(":")[0].lower()
       allowed = {
           "localhost",
           "127.0.0.1",
           "::1",
           settings.lan_ip.lower(),
       }
       public_host = getattr(settings, "public_url_host", None)
       if public_host:
           allowed.add(public_host)
       for extra in os.getenv("PODCASTSYNC_ALLOWED_HOSTS", "").split(","):
           extra = extra.strip().lower().split(":")[0]
           if extra:
               allowed.add(extra)
       return host in allowed
   ```
2. Wire a middleware in `main.py`:
   ```python
   from starlette.middleware.trustedhost import TrustedHostMiddleware

   # After app = FastAPI(...), BEFORE include_router is not required — middleware wraps everything.
   app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])  # placeholder; see note
   ```
   `TrustedHostMiddleware` needs a static list and LAN IPs are dynamic, so instead add a small custom `@app.middleware("http")` that calls `host_is_allowed(request.headers.get("host",""), request.app.state.settings)` and returns `400 {"detail":"Invalid host"}` when false. Place it after lifespan so `settings` exists (FastAPI middleware added at import time runs before lifespan-populated state is available on first request — `request.app.state.settings` will exist for all real traffic because lifespan startup runs before the server accepts requests).

**Required change — part 2 (optional bearer token):**
1. Settings gains `api_token: str = ""`. In `from_env`, read `PODCASTSYNC_API_TOKEN`. If unset and the DB already stores one, `load_from_db` picks it up. On **first** startup when neither env nor DB has a token, generate one, store it in the settings table, and log a notice with its location — but for the LAN-only default this is **off unless enabled** (see `PODCASTSYNC_API_TOKEN`). `[DECISION]` default OFF for pure-LAN v1; ON when `PUBLIC_URL` is set (Phase 6). Implementation hint: simplest is a config flag `api_token_required: bool` derived at startup (`public_url set OR PODCASTSYNC_API_TOKEN provided`).
2. Middleware (or a FastAPI dependency applied to the `/api` router) that compares the `X-PodcastSync-Token` header to `settings.api_token`; 401 when required and absent/wrong. Apply to **all** `/api/*` methods (GETs included — they leak storage paths and cookie availability). `/feed/*`, `/audio/*`, `/` (web UI) stay open so podcast clients work; the UI page itself is public but its fetches send the token (it must be delivered to the browser).
3. Token delivery to the UI: add a tiny route `GET /api/token` that returns the token *only when the Host is allowed and the request is from the same machine* (remote-address check is unreliable behind proxies; simplest v1: the UI reads the token from a meta tag injected by a non-cached `index.html` route). Because this is a headless-agent handoff, implement the **server side** (generation, storage, header enforcement, `GET /api/settings` unaffected) and have the Swift launcher + `api.js` send the header:
   - `backend/static/js/api.js`: read `window.PODCASTSYNC_API_TOKEN` (injected via a tiny template in `index.html` served from a route, or fetched once from `/api/bootstrap` that is open on allowed hosts) and add the header when present.
   - `macos/PodcastSync/Sources/BackendProcess.swift` `triggerSyncAll()` and cookie probe: add the header by reading the token file written next to the DB (`~/.podcastsync/auth_token`) that the backend writes when it generates a token.
   This is the largest task in this spec; keep it layered so part 1 (Host allow-list) can land independently and part 2 is an incremental follow-up. **If you are implementing only the LAN v1 and not Phase 6, ship part 1 + the plumbing for part 2, with the token OFF by default.**
- **Tests:** Host allow-list — request with `Host: evil.example` → 400; `Host: localhost`/`127.0.0.1`/`lan-ip` → 200. Token — when enabled, `/api/sources` without header → 401, with header → 200; `/feed/1.xml` still 200 without a token.
- **Verify:** curl with spoofed Host; curl with/without header.

---

## C4 — Feed/enclosure origin consistency [P1]

- **Current behaviour:** `routes/feeds.py:25,41` build URLs from `request.base_url` (client-controlled Host). Combined with C3’s allow-list, a spoofed Host is rejected — but for correctness with a configured public origin, prefer an explicit configured base.
- **Required change:** add `public_url: str = ""` to `Settings` (env `PUBLIC_URL`, DB override later — see Phase 6 V1) and a helper:
  ```python
  # config.py
  @property
  def public_url_host(self) -> str:
      from urllib.parse import urlparse
      return urlparse(self.public_url).hostname or ""
  ```
  In `routes/feeds.py`, choose the base:
  ```python
  base = settings.public_url.rstrip("/") if getattr(settings, "public_url", "") else str(request.base_url).rstrip("/")
  ```
  (request.base_url remains correct for LAN since the Host allow-list guarantees a known host.) Apply the same base selection in `routes/audio.py`? No — audio URLs are constructed *in* the feed; the audio route itself serves relative to the request. Keep it as-is.
- **Tests:** with `PODCASTSYNC_PUBLIC_URL=https://pod.example.com`, feed self-link and enclosure URLs carry that origin; without it they use `http://testserver/...`.

---

## C5 — CSRF tightening for body-less mutators [P1]

- **Current behaviour (verified):** JSON mutators are CORS-preflight protected, but body-less POSTs (`/api/sync-all`, `/api/sources/{id}/sync`, `/api/downloads/cancel-all`, `/api/pick-directory`, requeue) are form-CSRF-able from any website.
- **Required change:** once C3 part 2 (token) is in, require the token header on every `/api/*` mutation regardless of body (covered automatically by the router-wide guard). Until the token ships, add a lightweight anti-CSRF header check for body-less POSTs: require header `X-PodcastSync-Requested-With: fetch` set by `api.js` on all requests (a cross-site form cannot set it). This is a stopgap; document that the token is the real control. `api.js` already centralizes fetch — add the header there.
- **Tests:** POST `/api/sync-all` without the header/token → 401/403; with it → 202. (Adjust existing sync tests to send the header.)

---

## C6 — Cookie probe hardening [P2]

- **Current behaviour:** `routes/cookies.py:14-39` exposes which of 8 browsers hold readable YouTube cookies and whether the host is signed in to any unauthenticated caller, and lets callers point `test_cookies` at an arbitrary `cookies_file` path (file-oracle).
- **Required change:** gate `/cookies/detect` and `/cookies/test` behind the token when enabled (C3); additionally reject `cookies_file` values that are not under the user’s home directory or that don’t exist (`services/cookies.py` or the route): return `{"status":"error","message":"Cookie file not found"}` rather than leaking parse distinctions. No cookie values are ever returned (verified) — do not add that.
- **Tests:** with token enabled, cookie endpoints 401 without token; a non-existent `/etc/passwd` cookie file returns a generic error (no existence oracle).

---

## C7 — Key hygiene [P2]

- **Current behaviour:** `YOUTUBE_API_KEY` is stored plaintext in the sqlite `settings` table (`routes/settings.py:60`); DB lives at `~/.podcastsync/podcastsync.db` (default perms) and WAL sidecars are not git-ignored.
- **Required change:**
  1. `database.py`/`config.py`: when creating the DB path directory, `os.chmod(dir, 0o700)` (and `0o600` on the db file after creation) if it doesn’t already have tighter perms. Best-effort (ignore OSError on filesystems without chmod).
  2. `[DECISION]` Optional: move the API key to the macOS Keychain instead of the settings table (`security add-generic-password`/`find-generic-password`), only on macOS; keep the DB row for Linux (Phase 6). If implemented: backend reads keychain first, falls back to settings row. This is a follow-up; the plan treats plaintext-in-user-owned-DB as acceptable for a single-user app provided perms are set. Implement only if time permits.
  3. `.gitignore`: add `*.db-wal`, `*.db-shm`, `*.db-journal`, `*.sqlite3` (also part of G3).
- **Tests:** unit — chmod applied when DB dir is created fresh.

---

## WS-C Phase Summary

- [ ] C1 video ownership scoping
- [ ] C2 attribute-safe escaping + CSP
- [ ] C3 Host allow-list + optional token (baseline)
- [ ] C4 feed/enclosure origin consistency
- [ ] C5 CSRF tightening
- [ ] C6 cookie probe hardening
- [ ] C7 key hygiene (+ .gitignore sidecars)

Full-suite gate: `python -m pytest tests/ -q` green; curl Host/token probes behave as specified.
