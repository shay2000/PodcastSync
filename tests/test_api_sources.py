"""Characterization tests for the sources CRUD endpoints."""

from __future__ import annotations

from tests.conftest import CHANNEL_ID, CHANNEL_URL, HANDLE_URL, RESOLVED_CHANNEL_ID, STUB_ICON_URL

SOURCE_KEYS = {
    "id",
    "name",
    "source_type",
    "youtube_id",
    "url",
    "enabled",
    "max_backfill",
    "last_polled_at",
    "video_count",
    "completed_count",
    "created_at",
    "custom_storage_path",
    "icon_url",
    "max_keep_episodes",
}


async def test_list_sources_is_empty_on_a_fresh_database(api):
    resp = await api.client.get("/api/sources")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_source_from_channel_url(api):
    resp = await api.client.post(
        "/api/sources", json={"url": CHANNEL_URL, "name": "Linus Tech Tips", "max_backfill": 5}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert set(body) == SOURCE_KEYS
    assert body["name"] == "Linus Tech Tips"
    assert body["source_type"] == "channel"
    assert body["youtube_id"] == CHANNEL_ID
    assert body["url"] == CHANNEL_URL
    assert body["max_backfill"] == 5
    assert body["last_polled_at"] is None
    assert body["video_count"] == 0
    assert body["completed_count"] == 0
    # SQLite stores this as an integer; the API must surface a real boolean.
    assert body["enabled"] is True
    # Fetched from the orchestrator during creation.
    assert body["icon_url"] == STUB_ICON_URL


async def test_create_source_does_not_consult_the_orchestrator_for_resolution(api):
    """A direct /channel/UC… URL needs no lookup, so no resolve call is made."""
    await api.client.post("/api/sources", json={"url": CHANNEL_URL})
    resolve_calls = [c for c in api.orchestrator.calls if c[0] == "resolve_to_channel_id"]
    assert resolve_calls == []


async def test_create_source_resolves_a_handle_to_a_channel_id(api):
    resp = await api.client.post("/api/sources", json={"url": HANDLE_URL})
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["youtube_id"] == RESOLVED_CHANNEL_ID
    # A resolved handle is recorded as a channel, not as a handle.
    assert body["source_type"] == "channel"
    # The original URL the user typed is preserved.
    assert body["url"] == HANDLE_URL
    assert ("resolve_to_channel_id", "someHandle", "handle") in api.orchestrator.calls


async def test_create_source_auto_generates_a_name_when_blank(api):
    resp = await api.client.post("/api/sources", json={"url": CHANNEL_URL})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Channel: UCXuqSBlHAE6Xw-yeJA0"


async def test_create_source_rejects_a_non_youtube_url(api):
    resp = await api.client.post("/api/sources", json={"url": "https://example.com/not-youtube"})
    assert resp.status_code == 400
    assert "Not a YouTube URL" in resp.json()["detail"]
    assert await _source_count(api) == 0


async def test_create_source_rejects_an_unrecognised_youtube_url(api):
    resp = await api.client.post("/api/sources", json={"url": "https://www.youtube.com/nonsense/thing"})
    assert resp.status_code == 400
    assert "Could not extract" in resp.json()["detail"]
    assert await _source_count(api) == 0


async def test_create_source_validates_max_backfill_range(api):
    """max_backfill is bounded 1..50 by the request model."""
    too_big = await api.client.post("/api/sources", json={"url": CHANNEL_URL, "max_backfill": 999})
    too_small = await api.client.post("/api/sources", json={"url": CHANNEL_URL, "max_backfill": 0})
    assert too_big.status_code == 422
    assert too_small.status_code == 422


async def test_create_source_stores_optional_fields(api):
    resp = await api.client.post(
        "/api/sources",
        json={
            "url": CHANNEL_URL,
            "name": "Custom",
            "custom_storage_path": "/tmp/somewhere",
            "max_keep_episodes": 3,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["custom_storage_path"] == "/tmp/somewhere"
    assert body["max_keep_episodes"] == 3


async def test_get_source(api, source):
    resp = await api.client.get(f"/api/sources/{source['id']}")
    assert resp.status_code == 200
    assert resp.json() == source


async def test_get_unknown_source_is_404(api):
    resp = await api.client.get("/api/sources/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found"


async def test_patch_source_updates_fields(api, source):
    resp = await api.client.patch(
        f"/api/sources/{source['id']}", json={"name": "Renamed", "enabled": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["enabled"] is False
    # Untouched fields survive.
    assert body["youtube_id"] == source["youtube_id"]
    assert body["max_backfill"] == source["max_backfill"]


async def test_patch_source_with_no_fields_changes_nothing(api, source):
    resp = await api.client.patch(f"/api/sources/{source['id']}", json={})
    assert resp.status_code == 200
    assert resp.json() == source


async def test_patch_unknown_source_is_404(api):
    resp = await api.client.patch("/api/sources/999", json={"name": "x"})
    assert resp.status_code == 404


async def test_delete_source(api, source):
    resp = await api.client.delete(f"/api/sources/{source['id']}")
    assert resp.status_code == 204

    assert (await api.client.get(f"/api/sources/{source['id']}")).status_code == 404
    assert (await api.client.get("/api/sources")).json() == []


async def test_delete_unknown_source_is_404(api):
    resp = await api.client.delete("/api/sources/999")
    assert resp.status_code == 404


async def test_delete_source_also_deletes_its_videos(api, seeded):
    assert len(api.db.get_videos_for_source(seeded.source_id)) == 2

    resp = await api.client.delete(f"/api/sources/{seeded.source_id}")
    assert resp.status_code == 204
    assert api.db.get_videos_for_source(seeded.source_id) == []


async def test_list_sources_reports_video_counts(api, seeded):
    resp = await api.client.get("/api/sources")
    assert resp.status_code == 200
    (body,) = resp.json()
    assert body["video_count"] == 2
    assert body["completed_count"] == 1


async def _source_count(api) -> int:
    resp = await api.client.get("/api/sources")
    return len(resp.json())
