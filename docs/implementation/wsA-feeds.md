# WS-A — Feed / podcast-client compatibility (tasks A1–A9)

Files: `backend/rss_generator.py`, `backend/routes/feeds.py`, `backend/database.py`, `backend/routes/audio.py` (test only), `requirements.txt`, `pyproject.toml`, `README.md`, `tests/test_feeds.py`, `tests/conftest.py`.

Why this exists (verified): feedgen’s `FeedGenerator.add_entry()` **defaults to `order='prepend'`**, so while `db.get_completed_videos_for_source()` returns rows **newest-first**, the generated XML ends up **oldest-first**. The newest episode is the last item in the feed. Clients that scan until the first already-seen GUID will never see new episodes; any client that treats item #1 as “latest” picks the oldest episode. This is the single highest-impact feed bug.

Overcast: verified unreachable on a LAN feed by design (server-side crawling from the public internet). **No XML fix exists.** If the service is publicly reachable (Phase 6 / decision D7(b)), Overcast works. The README wording must say this precisely (A9).

---

## A1 — Emit items newest-first

- **Priority:** P1 · Size: S
- **Current behaviour (verified):** `backend/rss_generator.py:51-52`:
  ```python
  for row in videos:
      fe = fg.add_entry()
  ```
  `videos` comes from `db.get_completed_videos_for_source()` (`database.py:175-179`) with `ORDER BY publish_date DESC` (newest first). `add_entry()` prepends, so output order is reversed → oldest-first.
- **Required change:** append instead of prepend:
  ```python
  for row in videos:
      fe = fg.add_entry(order="append")
  ```
  (Equivalent alternative: `for row in reversed(videos):` with the default prepend. Prefer `order="append"`.)
- **Edge cases:** `publish_date` is `NULL` for some rows. SQLite sorts `NULL`s last under `DESC`, so undated items already land at the end of `videos`; after the fix they are the last feed items (acceptable, deterministic). If you later want undated-at-bottom always, sort `publish_date IS NULL, publish_date DESC` in the DB query (do not do this in this task).
- **Test (write first):** extend `tests/test_feeds.py` with `test_feed_items_are_newest_first`. Fixture `seeded` provides `vid00000001` (completed, dated 2026-01-01) and `vid00000002` (pending, dated 2026-02-01). Complete the pending video first (reuse the seeded folder pattern), then GET `/feed/{id}.xml`, parse with `xml.etree.ElementTree`, collect item GUIDs in document order, assert `["vid00000002", "vid00000001"]`.
- **Also pin (existing weakness):** `test_feed_only_lists_completed_videos` (`tests/test_feeds.py:77-89`) asserts set membership only — strengthen it to assert order as above when both items are completed.
- **Verify:** `python -m pytest tests/test_feeds.py -q`.

---

## A2 — Enclosure length from disk

- **Priority:** P2 · Size: S
- **Current behaviour:** `backend/rss_generator.py:74-76`:
  ```python
  file_size = row["file_size"] or 0
  ...
  fe.enclosure(audio_url, str(file_size), "audio/mpeg")
  ```
  A completed row with `file_size IS NULL` (or a file replaced after the size was recorded) emits `length="0"`. Apple’s validator and several clients compare `length` with the real `Content-Length` (byte-range checks).
- **Required change:** stat the actual file at render time; fall back gracefully:
  ```python
  import os  # module level in rss_generator.py (stdlib, cheap)

  file_size = row["file_size"]
  if not file_size and row["file_path"]:
      try:
          file_size = os.path.getsize(row["file_path"])
      except OSError:
          file_size = 0
  audio_url = f"{base_url}/audio/{source_id}/{video_id}.mp3"
  fe.enclosure(audio_url, str(file_size or 0), "audio/mpeg")
  ```
  (The query is `SELECT *`, so `file_path` is already present in `row`.)
- **Test:** `test_feed_enclosure_length_matches_file_on_disk` in `tests/test_feeds.py` — seed a completed video via `db.add_video` + `db.update_video_status(id, "completed", file_path=mp3, file_size=None)` (leave size unset), then assert the parsed enclosure `length` equals `mp3.stat().st_size`.
- **Verify:** `python -m pytest tests/test_feeds.py -q`.

---

## A3 — Channel `<itunes:category>`

- **Priority:** P2 · Size: S
- **Current behaviour:** no `fg.podcast.itunes_category(...)` call anywhere in `rss_generator.py` (channel metadata block `:31-49`).
- **Required change:** after `fg.podcast.itunes_explicit("no")` (`:43`):
  ```python
  fg.podcast.itunes_category("Technology")
  ```
  feedgen maps this to `<itunes:category text="Technology">`. Use valid Apple category casing. **Do not invent subcategories.**
- **Note:** `[DECISION]` add a per-source category later? Default `"Technology"` for now.
- **Test:** `test_feed_has_itunes_category` — parse the feed and assert `itunes:category` `text="Technology"` exists under the channel (namespace `http://www.itunes.com/dtds/podcast-1.0.dtd`).
- **Verify:** `python -m pytest tests/test_feeds.py -q`.

---

## A4 — Channel `<link>` points at the source website

- **Priority:** P2 · Size: S
- **Current behaviour:** `backend/rss_generator.py:36-38`:
  ```python
  feed_url = f"{base_url}/feed/{source_id}.xml"
  fg.link(href=source["url"], rel="alternate")
  fg.link(href=feed_url, rel="self")
  ```
  feedgen’s RSS serializer uses the **last** link as the RSS 2.0 `<channel><link>`, and emits `rel="self"` only as `<atom:link>`. Net result (verified): `<channel><link>` = the feed XML itself and the YouTube link is dropped entirely. RSS 2.0 says `<link>` is the HTML website of the channel.
- **Required change:** swap the order so the alternate (website) link is added last:
  ```python
  fg.link(href=feed_url, rel="self")
  fg.link(href=source["url"], rel="alternate")
  ```
- **Test:** `test_feed_channel_link_is_the_youtube_url` — assert the plain `<channel><link>` text equals the source’s YouTube `url` and `<atom:link rel="self">` equals `http://testserver/feed/{id}.xml`.
- **Verify:** `python -m pytest tests/test_feeds.py -q`.

---

## A5 — Stable `lastBuildDate` + `ETag`/`Last-Modified` on the feed route

- **Priority:** P2 · Size: S
- **Current behaviour:** feedgen stamps `lastBuildDate = now` on every render; `routes/feeds.py:29-33` returns a plain `Response` with only `Cache-Control: max-age=300`, so every request produces byte-different XML and clients/crawlers cannot do conditional GETs.
- **Required changes:**
  1. `rss_generator.py`: after building all entries, compute the newest parseable item pubDate and pin it:
     ```python
     # inside generate_feed, after the loop
     newest = None
     for row in videos:
         if row["publish_date"]:
             try:
                 d = datetime.fromisoformat(row["publish_date"])
                 if d.tzinfo is None:
                     d = d.replace(tzinfo=timezone.utc)
                 if newest is None or d > newest:
                     newest = d
             except ValueError:
                 continue
     if newest is not None:
         fg.lastBuildDate(newest)
     ```
     (Do not call `fg.lastBuildDate` when there are no items — omit so clients don’t see a made-up timestamp.)
  2. `routes/feeds.py`: add validators. After generating `xml`:
     ```python
     import hashlib

     etag = f'"{hashlib.sha1(xml.encode("utf-8")).hexdigest()}"'
     if request.headers.get("If-None-Match") == etag:
         return Response(status_code=304)
     headers = {
         "Cache-Control": "max-age=300",
         "ETag": etag,
     }
     return Response(content=xml, media_type="application/rss+xml", headers=headers)
     ```
     (Optional: compute `Last-Modified` from the newest item date as HTTP-date. ETag alone satisfies conditional GET for all practical clients.)
- **Test:** `test_feed_is_stable_and_conditional_get_returns_304` — GET twice, assert bodies equal; capture the `ETag`; GET with `If-None-Match` = that ETag → assert `304` and empty body; assert `ETag` header present on the first response.
- **Verify:** `python -m pytest tests/test_feeds.py -q`.

---

## A6 — Log unparseable publish dates

- **Priority:** P3 · Size: S
- **Current behaviour:** `rss_generator.py:60-68` silently `pass`es on `ValueError` when a stored `publish_date` cannot be parsed, so a corrupt date quietly drops the item’s pubDate.
- **Required change:** add a module-level `logger = logging.getLogger(__name__)` and in the `except ValueError:` block log a warning including `source_id`/`video_id`.
- **Verify:** unit-level via manual run or a `caplog` assertion in `test_feeds.py` (`test_unparseable_publish_date_is_logged`).

---

## A7 — Exclude completed videos with no file from feeds

- **Priority:** P1 · Size: S
- **Current behaviour:** `database.py:175-179` `get_completed_videos_for_source` selects `download_status = 'completed'` with **no `file_path` filter**. A row completed without a stored path (or whose file was removed but status not updated) is advertised with an enclosure that 404s.
- **Required change:** add `AND file_path IS NOT NULL` to the WHERE clause of `get_completed_videos_for_source`.
- **Related:** `delete_downloaded_file` sets status `deleted` and clears the path, so normal deletion is already excluded; this catches the stale cases.
- **Test:** `test_feed_excludes_completed_videos_without_a_file` — seed a second completed video with `file_path=None`; assert only the real-file item appears in the feed.
- **Verify:** `python -m pytest tests/test_feeds.py -q`.

---

## A8 — Pin Starlette floor + Range/HEAD regression test

- **Priority:** P2 · Size: S
- **Why:** `FileResponse` HTTP Range support (206/Content-Range/Accept-Ranges + HEAD) landed in Starlette 0.39.0. Current pins are `fastapi>=0.104.0` with no Starlette floor; a fresh install today resolves a modern Starlette, but nothing enforces it. Podcast clients (incl. Apple) expect byte-range and HEAD support on enclosures.
- **Required changes:**
  1. `requirements.txt` and `pyproject.toml`: add `starlette>=0.39.0`.
  2. `tests/test_audio_guard_and_ranges.py` (new; see Phase-1 T1 for full file) — add now (this task is its own test):
     ```python
     async def test_audio_supports_range_requests(api, seeded):
         r = await api.client.get(f"/audio/{seeded.source_id}/vid00000001.mp3",
                                  headers={"Range": "bytes=0-3"})
         assert r.status_code == 206
         assert r.headers["content-range"] == f"bytes 0-3/{seeded.mp3.stat().st_size}"
         assert r.content == b"ID3 "   # first 4 bytes of the seeded fake file
     ```
     plus `test_audio_supports_head(api, seeded)` asserting `HEAD` returns 200 with a `content-length` equal to the file size and an empty body.
- **Verify:** `python -m pytest tests/test_audio_guard_and_ranges.py -q` and full suite.

---

## A9 — Documentation of client behaviour

- **Priority:** P2 · Size: S
- **Required changes (README.md):**
  1. Replace the “Overcast disclaimer” block (`README.md:78-79` and again near the end) with precise wording:
     > **Overcast:** Overcast fetches every feed from its own servers on the public internet, so it cannot reach a feed hosted only on your local network. Overcast will work if PodcastSync is hosted at a publicly reachable HTTPS address (see “Run on a server”). Apple Podcasts and Downcast fetch feeds on the device, so they work with LAN feeds.
  2. Add a note in the “Subscribing in a podcast app” section: on iOS 14+, podcast clients need the **Local Network** permission granted to reach `192.168.x.x` addresses.
  3. (Phase 6 will add the “Run on a server (Docker)” section.)
- **Verify:** doc change; nothing to run. Keep `HANDOFF.md` in sync by removing its duplicate Overcast paragraph or pointing to README (task G3).

---

## WS-A Phase Summary

- [ ] A1 newest-first items
- [ ] A2 enclosure length from disk
- [ ] A3 itunes:category
- [ ] A4 channel link = website
- [ ] A5 stable lastBuildDate + ETag/304
- [ ] A6 log unparseable dates
- [ ] A7 exclude completed-without-file
- [ ] A8 starlette floor + Range/HEAD tests
- [ ] A9 docs (Overcast / Local Network)

Full-suite gate: `python -m pytest tests/ -q` green.
