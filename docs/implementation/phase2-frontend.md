# Phase 2 — Frontend / UI fixes & polish (U1–U14)

Files: `backend/static/index.html`, `backend/static/js/*.js` (main.js, store.js, api.js, poll.js, format.js), `backend/static/js/actions/*.js`, `backend/static/js/render/*.js`, `backend/static/js/ui/*.js`, `backend/static/css/` (main.css, style.css, overrides.css, components/*), `backend/services/sources.py`, `backend/models.py`, `backend/database.py` (for U7).

Verified integrity baseline: the audit found **no** orphaned DOM ids, unknown `data-action` names, or API field mismatches. Preserve that.

Work top-down: bugs (U1–U7) → UX (U8–U11) → debt (U12–U14). Each is small and independent.

---

## U1 — Clipboard copy fallback for non-secure contexts

- **Problem (verified):** `actions/sources.js:56-69` uses `navigator.clipboard.writeText`, which only exists in secure contexts. The app is explicitly LAN/http-oriented (`api.js:26-42`), so copying the RSS URL over the LAN always throws → “Failed to copy RSS feed”.
- **Change (`actions/sources.js`):** add a fallback:
  ```js
  export async function copyText(text) {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
          await navigator.clipboard.writeText(text);
          return;
      }
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
          document.execCommand("copy");
      } finally {
          document.body.removeChild(ta);
      }
  }
  ```
  Use it in `copyFeedUrl`. On failure, **surface** the existing in-detail URL row (`#detail-feed-url`, `index.html:153-160` — set by `actions/sources.js:62-64`) with a toast “Copy failed — select the URL below”, and also `window.prompt("Copy this feed URL:", url)` as a last resort (works everywhere, user-initiated).
- **Verify:** open the UI over `http://<lan-ip>:8642`, click RSS — toast confirms copy (or prompt shows the URL). Re-check over `http://127.0.0.1:8642`.

---

## U2 — “Converting…” state during ffmpeg post-processing

- **Problem (verified):** `downloader/manager.py:175-183` removes the progress entry on yt-dlp `finished`, but ffmpeg conversion still runs before the DB row flips to `completed`. `poll.js:132-135` sees the id vanish, re-renders the list, and `render/episodes.js` renders a fresh static “Downloading…” bar that never advances.
- **Changes:**
  1. Frontend (belt-and-braces, `render/episodes.js`): when a row’s status is `downloading` but there is no live progress entry, render an **indeterminate** bar + “Converting…” text. (The episodes renderer is fed from `state.detailVideos`; progress is not in that list — simplest: keep a module-level `activeProgressIds` set updated by `poll.js`, or read `state.prevProgressIds`.) 
  2. Backend (preferred, so the transition is honest): only pop `_progress[video_db_id]` when the whole `download_video` finishes (move the pop from the `finished`/`error` hook to a `finally` in `download_video`, `manager.py:138-168`), or add a phase flag (`downloading` → `converting`) written to the progress dict so the UI can show “Converting…”.
- **Verify:** during a real download (VPS with ffmpeg + network) the row shows a moving bar while yt-dlp runs and “Converting…” during post-processing, then flips to Completed without a frozen empty bar.

---

## U3 — Normalize FastAPI 422 errors (`[object Object]`)

- **Problem (verified):** FastAPI 422 `detail` is an array of `{loc,msg,type}` objects. `api.js:14-17` throws `new Error(error.detail)`; `String(array)` → `[object Object]`.
- **Change (`api.js`):**
  ```js
  function detailToString(detail) {
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      if (detail && typeof detail === "object") return detail.msg || detail.detail || JSON.stringify(detail);
      return "Request failed";
  }
  ...
  throw new Error(detailToString(error.detail));
  ```
  Optionally clamp numerics client-side before sending (add form validation in `main.js:203-206` and `actions/settings.js` so `parseInt("")` never sends `null` where `ge=1` is required).
- **Verify:** clear the backfill input in the Add modal and submit → readable message, not `[object Object]`.

---

## U4 — Preserve focus: per-tile patch render instead of full-grid re-render

- **Problem (verified):** every enabled toggle re-renders the entire grid (`render/sources.js:98-173`) via `replaceSource`→notify→subscriber (`main.js:59-66`); the toggled checkbox is destroyed/recreated, dropping keyboard focus and any SR announcement.
- **Change:** add `renderSourceTile(source)` that re-renders just that tile’s `<article>` (replace its outerHTML), then re-focus the new checkbox if the old one had focus. Have the subscriber call the full grid only when the source *list* changed (add a `gridChanged`/`sourcesListSignature` guard in `store.js` like `sourceSignature` but including only identity+enabled fields), and use the per-tile patch for `replaceSource`.
- **Verify:** keyboard: focus a toggle, press Space repeatedly — focus stays on the control and state toggles each time.

---

## U5 — Optimistic-timestamp race + polling jank + stale-list race

- **Problem (verified):**
  1. `actions/sources.js:34-37` mutates `source.last_polled_at` on the live store object; the in-flight `GET /api/sources` (stamped only when the background task runs, `services/sync.py:30-33`) can return the old value and the next poll visually reverts “Just now”.
  2. `poll.js:174-189` unconditionally polls `/api/downloads/progress` every 1 s even when idle, and any progress transition triggers full `loadDetailVideos` + `loadSources`.
  3. Two overlapping `GET /videos` calls can resolve out of order (guarded only by `state.selectedSourceId`, `poll.js:20-22`).
- **Changes:**
  1. `syncSource`: drop the optimistic write (server stamps within ms of the 202) OR copy-then-`replaceSource`. Simplest correct: remove lines `34-37`; the next status/sources poll shows the new timestamp.
  2. `startPolling`: run `refreshProgress` only when `state.currentStatus?.active_downloads > 0` (re-arm it whenever `loadStatus` sees active downloads). Keep the 5 s status/sources poll.
  3. `loadDetailVideos`: add a monotonically increasing request id; ignore responses whose id is older than the latest issued for that source.
  4. `refreshProgress`: when the only change is progress add/remove for a *different* source than the selected one, skip the `loadDetailVideos` re-render.
- **Verify:** rapid Sync clicks and fast source switching show no flicker of stale timestamps/lists; network tab shows the progress poll only while downloads are active.

---

## U6 — Modal hygiene (add-source reset, auth chip, API-key “set” state)

- **Problem (verified):**
  1. `openAddSource` (`modals.js:9-14`) never resets the form; `state.displayNameManuallyEdited` stays `true` after a cancelled manual edit, so auto-derivation is permanently suppressed.
  2. `#auth-global-status` / `#test-cookies-result` are written only by `testCookies`; reopening settings shows a stale chip.
  3. API-key field gives no “is set” signal except the footer line (`poll.js:106-107`).
- **Changes:**
  1. `openAddSource`: `document.getElementById("add-source-form").reset(); document.getElementById("source-backfill").value = "15"; state.displayNameManuallyEdited = false;` then re-derive the name from any URL present.
  2. In `actions/settings.js` `detectBrowserCookies`: after re-rendering rows, derive the global chip from `state.currentBrowserSelection` + that row’s `has_youtube_cookies`/`needs_permission`, and call `clearTestResult()`; also call it from `openSettings` (`modals.js`).
  3. On `openSettings`, read cached settings (`getSettings()` from `api.js:30-38`) and render a “Key set” / “Not set” pill next to the key field; clear the password field on open.
- **Verify:** cancel/reopen the add modal with a different URL → name re-derives; reopen settings after a test → chip reflects current config; key pill shows state without waiting for the poll.

---

## U7 — Surface per-source sync errors (`last_sync_error`)

- **Problem (verified):** fetch failures in `sync_source` are logged and swallowed (`services/sync.py:36-40`) while `last_polled_at` is stamped first — the UI shows “Checked just now” with no error.
- **Changes (backend + frontend):**
  1. Migration `005_source_sync_error.sql`? No — do it in migration **004** if B8 hasn’t shipped, else **005**:
     ```sql
     ALTER TABLE sources ADD COLUMN last_sync_error TEXT;
     INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '5');
     ```
     (Match the next free number against what B8 added; keep migrations cumulative.)
  2. `services/sync.py`: on fetch/download failure set `last_sync_error` (and clear it on success: `UPDATE sources SET last_sync_error = NULL ...`). Wrap the whole `sync_source` body: `except Exception as exc: db.execute("UPDATE sources SET last_sync_error = ? WHERE id = ?", (str(exc)[:500], source_id))`.
  3. `services/sources.py` `source_dto` + `models.py` `SourceResponse`: add `last_sync_error: Optional[str]`.
  4. Frontend: render an error banner in the tile (`render/sources.js` summary area) and the detail header when `last_sync_error` is set (reuse the error styling used by `render/episodes.js:46-56`); clear on next successful sync.
- **Verify:** point a source at an unreachable host (or stub `fetch_videos` to raise), sync, and confirm the UI shows the error while the server keeps running; a later successful sync clears it.

---

## U8 — Initial-load skeleton + error/Retry state

- **Problem (verified):** the “No podcasts yet” empty state (`index.html:79-92`) and “No sources attached yet” subtitle flash before the first `loadSources` resolves even when sources exist; a failed first load silently shows the wrong empty state.
- **Change:** add `state.initialLoading = true` (reset after first `loadSources`) and `state.initialLoadFailed`. In `render/sources.js`: while loading, render 3 skeleton tiles; when `initialLoadFailed && !sources.length`, show an error panel with a Retry button (`data-action="retry-initial-load"` → re-run `loadSources`); only show the real empty state after a successful load with zero sources. `loadSources` catch (`poll.js:65-67`) sets `initialLoadFailed`.
- **Verify:** throttle the network (DevTools) and reload — skeletons, then grid; force a failure and confirm Retry.

---

## U9 — Accessibility pass

1. Remove the blanket `outline: none` on `.source-tile` (`css/components/source-tile.css:13` — note this file is shadowed by `style.css` until U12; the real rule is in `style.css`; fix whichever file is canonical after U12) and keep `:focus-visible` rings.
2. Modal focus trap + return focus on close (`ui/modals.js`): on open, store `document.activeElement`; trap Tab within the modal (cycle focusables); on close, restore focus. Add `inert`/`aria-hidden` on `<main>` while a modal is open (fall back to a class + `visibility` if inert is unsupported).
3. `role="status"`/`aria-live="polite"` on `#status-text` and `#next-poll` (`index.html:31-33`); `role="alert"` on error toasts (`ui/toast.js`).
4. Source tiles are focusable `<article tabindex="0">` (`render/sources.js:115-120`) activated by Enter/Space (`main.js:259-267`) — add `role="button"` semantics carefully (an `<article>` with interactive children shouldn’t be a button; instead keep tiles focusable but announce the source name via `aria-label` on the article including `source.name`) and add `aria-pressed`-style state to the enable toggle (a real checkbox already gives that — keep the checkbox, remove the `data-action="ignore-tile"` wrapper weirdness in U14).
5. Add visible focus rings and `aria-label`s to icon buttons (Sync/RSS) with the source name.
- **Verify:** full keyboard run-through: Tab order sane, modals trap + return focus, SR announces status changes and toasts.

---

## U10 — Toast system

- **Change (`ui/toast.js` + canonical CSS):** maintain a `#toast-container` (create lazily, `position: fixed; bottom/right`), stack new toasts above older ones (offset each), each with `role` (alert for errors, status otherwise), a dismiss button, and duration by severity (errors 6 s, others 3 s), pause-on-hover. Keep the existing `.toast` styling in `style.css` but move layout to the container.
- **Verify:** trigger several toasts rapidly → stacked, individually dismissible, no overlap.

---

## U11 — Confirmation consistency + copy + sync-all message

1. Convert the native `confirm()` in `actions/videos.js:18` (delete downloaded file) to the same inline-confirm pattern used for source deletion (or a reusable `ui/confirm.js` promise-based helper).
2. `sync-all` with zero enabled sources: read the `sources_queued` response (`routes/sync.py:35`); toast “No enabled sources to sync” instead of “Sync started for all sources” (`main.js:247-257`).
3. Cancel copy: `poll.js:164-172` toast should say “Queued downloads cancelled — in-flight downloads will finish” (matching `routes/sync.py:38-42` semantics).
4. Empty states: the Add modal should hint “first sync backfills up to N (default 15, max 50)” and the per-video auth-required banner (`render/episodes.js:48-53`) should include one line of guidance (“Add YouTube cookies in Settings”).
- **Verify:** manual UI pass.

---

## U12 — Retire the shadowed modular CSS; keep `style.css` canonical

- **Problem (verified):** `css/main.css` imports tokens/base/layout/components then `overrides.css`, which re-imports the monolithic `style.css` **last**. `style.css` (1,808 lines, with duplicated dark-mode blocks at `:62-164` and `:1676-1808`) wins every specificity tie, so the modular files are dead scaffolding and editing them silently does nothing.
- **Change:**
  1. `index.html:11`: link `/css/style.css` directly (drop `main.css`) — or keep `main.css` containing only `@import url("style.css");` so the `?v=` URL stays stable.
  2. Delete `css/overrides.css`, `css/tokens.css`, `css/base.css`, `css/layout.css`, and `css/components/*.css` (8 files) after confirming (grep) no rule unique to them (the audit found none that win).
  3. Merge `style.css`’s two dark-mode `@media (prefers-color-scheme: dark)` blocks into a single block appended at the end of the file, resolving duplicates (keep the union of selectors).
  4. `?v=` bump: from U13 onward one query string on `style.css` suffices (U13 removes the need to bump by hand).
- **Verify:** visual diff of every screen (light + dark) before/after using screenshots; no regressions. If you cannot screenshot, at least verify computed styles on representative elements match before/after via devtools.

---

## U13 — Cache-busting that actually covers the module graph

- **Problem (verified):** `?v=9` only versions `main.css`/`main.js`/`app-icon.svg` in `index.html`. The ES-module import graph and CSS `@import`s are unversioned and rely on server ETag revalidation.
- **Change (no-build recommendation):** serve `index.html` through a small FastAPI route instead of the static mount (keep the mount for the rest), and compute one version string from the mtimes/hashes of `index.html`, `main.css` (or `style.css`), `main.js`, and every transitively imported JS/CSS file (glob `backend/static/js/**` and `css/**`, hash contents, combine), then inject `?v=<hash>` into `index.html` and into every `import "./x.js"` specifier + CSS `@import` at serve time (string replace on the served HTML/CSS/JS). Simpler acceptable alternative: set `Cache-Control: no-cache` (must revalidate) on `/js/*` and `/css/*` via a tiny `StaticFiles` subclass overriding `get_response_headers` or a middleware, and drop the query strings entirely.
- **Verify:** deploy new JS, hard-refresh once, and confirm the new code loads (no stale module); second load is 304s/conditional.
- **Note:** whichever route is chosen, keep the `index.html` served at `/` and ensure it is NOT cached longer than a refresh (this also matters for Phase 4/6 token bootstrap).

---

## U14 — Dead code removal (precise list from the audit)

- `main.js:87,91,96` — remove no-op `event.stopPropagation()` in `sync-source`/`copy-feed-url`/`ignore-tile`+`toggle-enabled` (single delegated listener already targets the innermost `[data-action]`; dropping them is safe). Remove the `ignore-tile` case (or leave an empty case with a comment) since `toggle-enabled` is handled by the `change` listener.
- `main.js:209` and `main.js:249` — replace `await import("./api.js")` with the static `import { api } from "./api.js"` (already imported transitively by `poll.js:1`).
- `store.js:89-92` — delete unused export `setSelectedSource` (never imported).
- `render/detail.js:16-34` `syncDetailTabUi` and `:36-56` `updateDetailFeedUrl` — remove the `export` keyword (internal use only).
- `render/sources.js:26-38` `buildSourceSummary` — remove `export` (internal).
- `index.html` ids never referenced by JS: `#browse-source-path`, `#save-api-key`, `#save-poll-interval`, `#test-cookies-btn`, `#refresh-detect-btn`, `#save-cookies-file` — remove only if you confirm no CSS/test relies on them (grep first).
- `routes/feeds.py:36-55` `GET /feeds` — unused by the client. `[DECISION]` Remove it, or keep and document as a public API. Recommend keep for v1 (cheap, may help power users/scripts) but note it in README.
- After U12: the whole modular CSS directory removal.

---

## Phase 2 Summary

- [ ] U1 clipboard fallback
- [ ] U2 “Converting…” state
- [ ] U3 422 error normalization
- [ ] U4 per-tile focus-preserving render
- [ ] U5 optimistic/polling/race fixes
- [ ] U6 modal + settings chip + key pill
- [ ] U7 `last_sync_error` surfacing
- [ ] U8 skeleton + error/Retry state
- [ ] U9 accessibility pass
- [ ] U10 toast container
- [ ] U11 confirmations/copy/messages
- [ ] U12 retire shadowed modular CSS
- [ ] U13 real cache-busting
- [ ] U14 dead-code removal

Gate: `node --test` (T5) green where applicable; full pytest green; manual browser pass on 127.0.0.1 and LAN IP in light + dark, narrow + wide.
