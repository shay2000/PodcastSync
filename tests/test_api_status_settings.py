"""Characterization tests for the status, settings, and cookie endpoints.

Not covered here, deliberately:

* ``POST /api/pick-directory`` shells out to osascript and opens a native folder
  picker, so it cannot run unattended.
* ``GET /api/cookies/detect`` and the yt-dlp probe inside ``POST /api/cookies/test``
  read real browser cookie stores and reach YouTube. Only the guard that runs
  before any yt-dlp work is exercised below.
"""

from __future__ import annotations

from datetime import datetime

STATUS_KEYS = {
    "server_running",
    "next_poll",
    "last_poll",
    "download_queue_size",
    "active_downloads",
}

SETTINGS_KEYS = {
    "youtube_api_key_set",
    "poll_interval_minutes",
    "storage_path",
    "server_port",
    "base_url",
    "cookies_from_browser",
    "cookies_file_path",
}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

async def test_status_shape(api):
    resp = await api.client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body) == STATUS_KEYS
    assert body["server_running"] is True
    assert body["active_downloads"] == 0
    assert body["download_queue_size"] == 0
    # No source has ever been polled on a fresh database.
    assert body["last_poll"] is None
    # The scheduler is running, so a next run time is always available.
    assert isinstance(body["next_poll"], str)
    datetime.fromisoformat(body["next_poll"])


async def test_status_counts_pending_videos_across_all_sources(api, seeded):
    assert (await api.client.get("/api/status")).json()["download_queue_size"] == 1

    api.db.update_video_status(seeded.completed_id, "pending")
    assert (await api.client.get("/api/status")).json()["download_queue_size"] == 2

    # Skipped and deleted videos are not queued work.
    api.db.skip_video(seeded.pending_id)
    assert (await api.client.get("/api/status")).json()["download_queue_size"] == 1


async def test_status_reports_the_last_poll_after_a_sync(api, source):
    await api.client.post(f"/api/sources/{source['id']}/sync")

    body = (await api.client.get("/api/status")).json()
    assert body["last_poll"] is not None


async def test_status_reflects_active_downloads(api):
    api.download_manager.active_downloads = 3
    assert (await api.client.get("/api/status")).json()["active_downloads"] == 3


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

async def test_get_settings_shape(api):
    resp = await api.client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body) == SETTINGS_KEYS
    # The key itself is never returned — only whether one is configured.
    assert body["youtube_api_key_set"] is False
    assert body["storage_path"] == str(api.storage)
    assert body["server_port"] == 8642
    assert body["poll_interval_minutes"] == 1440  # from PODCASTSYNC_POLL_INTERVAL
    assert body["cookies_from_browser"] == ""
    assert body["cookies_file_path"] == ""
    # base_url is built from a detected LAN IP, so only its shape is stable.
    assert body["base_url"].startswith("http://")
    assert body["base_url"].endswith(":8642")


async def test_patch_settings_persists_to_the_database(api):
    resp = await api.client.patch(
        "/api/settings",
        json={
            "youtube_api_key": "test-key-123",
            "poll_interval_minutes": 90,
            "cookies_from_browser": "chrome",
            "cookies_file_path": "/tmp/cookies.txt",
        },
    )
    assert resp.status_code == 200

    stored = api.db.get_all_settings()
    assert stored["youtube_api_key"] == "test-key-123"
    assert stored["poll_interval_minutes"] == "90"
    assert stored["cookies_from_browser"] == "chrome"
    assert stored["cookies_file_path"] == "/tmp/cookies.txt"


async def test_patch_settings_is_reflected_by_a_following_get(api):
    await api.client.patch(
        "/api/settings",
        json={"youtube_api_key": "test-key-123", "poll_interval_minutes": 90,
              "cookies_from_browser": "chrome"},
    )

    resp = await api.client.get("/api/settings")
    body = resp.json()
    assert body["youtube_api_key_set"] is True
    assert body["poll_interval_minutes"] == 90
    assert body["cookies_from_browser"] == "chrome"
    # Still never echoes the key back.
    assert "test-key-123" not in resp.text


async def test_patch_settings_forwards_the_api_key_to_the_orchestrator(api):
    await api.client.patch("/api/settings", json={"youtube_api_key": "test-key-123"})
    assert ("update_api_key", "test-key-123") in api.orchestrator.calls


async def test_patch_settings_only_touches_the_fields_supplied(api):
    await api.client.patch("/api/settings", json={"cookies_from_browser": "safari"})

    body = (await api.client.get("/api/settings")).json()
    assert body["cookies_from_browser"] == "safari"
    assert body["poll_interval_minutes"] == 1440
    assert body["youtube_api_key_set"] is False
    assert "youtube_api_key" not in api.db.get_all_settings()


async def test_patch_settings_reschedules_the_poll_job(api):
    before = (await api.client.get("/api/status")).json()["next_poll"]

    await api.client.patch("/api/settings", json={"poll_interval_minutes": 90})

    after = (await api.client.get("/api/status")).json()["next_poll"]
    # A shorter interval must bring the next run forward.
    assert datetime.fromisoformat(after) < datetime.fromisoformat(before)


async def test_patch_settings_rejects_an_out_of_range_poll_interval(api):
    assert (await api.client.patch(
        "/api/settings", json={"poll_interval_minutes": 0})).status_code == 422
    assert (await api.client.patch(
        "/api/settings", json={"poll_interval_minutes": 5000})).status_code == 422
    # The rejected values were not written.
    assert (await api.client.get("/api/settings")).json()["poll_interval_minutes"] == 1440


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------

async def test_cookie_test_reports_an_error_when_nothing_is_configured(api):
    """The guard that runs before any yt-dlp work — the only hermetic path here."""
    resp = await api.client.post("/api/cookies/test", json={})
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "error",
        "message": "No browser or cookie file configured",
    }
