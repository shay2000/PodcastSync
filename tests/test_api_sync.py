"""Characterization tests for the sync and download-control endpoints.

Note on background tasks: FastAPI runs a response's BackgroundTasks before the
ASGI call returns, and httpx.ASGITransport awaits that call, so by the time a
request here resolves the background sync has already finished. That is what lets
these tests assert on its side effects synchronously.
"""

from __future__ import annotations

from tests.conftest import CHANNEL_URL

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"


async def test_trigger_sync_is_accepted(api, source):
    resp = await api.client.post(f"/api/sources/{source['id']}/sync")
    assert resp.status_code == 202
    assert resp.json() == {"status": "started"}


async def test_trigger_sync_clears_a_previous_cancel_request(api, source):
    await api.client.post("/api/downloads/cancel-all")
    before = api.download_manager.reset_cancel_calls

    await api.client.post(f"/api/sources/{source['id']}/sync")
    assert api.download_manager.reset_cancel_calls == before + 1


async def test_trigger_sync_records_the_poll_time(api, source):
    assert source["last_polled_at"] is None

    await api.client.post(f"/api/sources/{source['id']}/sync")

    row = api.db.get_source(source["id"])
    assert row["last_polled_at"] is not None


async def test_sync_fetches_with_the_sources_backfill_limit(api, source):
    """max_results is the source's max_backfill, capped at 50."""
    await api.client.post(f"/api/sources/{source['id']}/sync")

    fetches = [c for c in api.orchestrator.calls if c[0] == "fetch_videos"]
    assert fetches == [("fetch_videos", "channel", source["youtube_id"], 5)]


async def test_sync_passes_source_settings_to_the_download_manager(api, source):
    await api.client.post(f"/api/sources/{source['id']}/sync")

    (source_id, source_name, kwargs) = api.download_manager.processed[-1]
    assert source_id == source["id"]
    assert source_name == source["name"]
    assert kwargs == {
        "custom_storage_path": source["custom_storage_path"],
        "icon_url": source["icon_url"],
        "max_keep_episodes": source["max_keep_episodes"],
    }


async def test_trigger_sync_for_unknown_source_is_404(api):
    resp = await api.client.post("/api/sources/999/sync")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found"


async def test_sync_all_queues_every_enabled_source(api):
    first = (await api.client.post("/api/sources", json={"url": CHANNEL_URL})).json()
    await api.client.post("/api/sources", json={"url": PLAYLIST_URL})

    resp = await api.client.post("/api/sync-all")
    assert resp.status_code == 202
    assert resp.json() == {"status": "started", "sources_queued": 2}

    # Disabling one removes it from the queue.
    await api.client.patch(f"/api/sources/{first['id']}", json={"enabled": False})
    resp = await api.client.post("/api/sync-all")
    assert resp.json() == {"status": "started", "sources_queued": 1}


async def test_sync_all_with_no_sources(api):
    resp = await api.client.post("/api/sync-all")
    assert resp.status_code == 202
    assert resp.json() == {"status": "started", "sources_queued": 0}


async def test_cancel_all_downloads(api):
    resp = await api.client.post("/api/downloads/cancel-all")
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}
    assert api.download_manager.cancel_all_calls == 1


async def test_download_progress_is_empty_when_idle(api):
    resp = await api.client.get("/api/downloads/progress")
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_download_progress_is_keyed_by_video_database_id(api, seeded):
    api.download_manager.progress[seeded.completed_id] = {
        "downloaded_bytes": 1024,
        "total_bytes": 4096,
        "speed": 512,
    }

    resp = await api.client.get("/api/downloads/progress")
    assert resp.status_code == 200
    # JSON object keys are strings on the wire; the frontend keys off video DB id.
    assert resp.json() == {
        str(seeded.completed_id): {
            "downloaded_bytes": 1024,
            "total_bytes": 4096,
            "speed": 512,
        }
    }
