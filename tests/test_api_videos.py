"""Characterization tests for the video endpoints (list, skip, delete file, requeue)."""

from __future__ import annotations

VIDEO_KEYS = {
    "id",
    "video_id",
    "title",
    "description",
    "publish_date",
    "duration_seconds",
    "download_status",
    "file_size",
    "error_message",
    "created_at",
}


async def test_list_videos_returns_newest_first(api, seeded):
    resp = await api.client.get(f"/api/sources/{seeded.source_id}/videos")
    assert resp.status_code == 200
    body = resp.json()

    assert [v["video_id"] for v in body] == ["vid00000002", "vid00000001"]
    assert set(body[0]) == VIDEO_KEYS
    # file_path is intentionally not exposed to the client.
    assert "file_path" not in body[0]


async def test_list_videos_reports_download_status_and_size(api, seeded):
    resp = await api.client.get(f"/api/sources/{seeded.source_id}/videos")
    by_id = {v["video_id"]: v for v in resp.json()}

    assert by_id["vid00000001"]["download_status"] == "completed"
    assert by_id["vid00000001"]["file_size"] == seeded.mp3.stat().st_size
    assert by_id["vid00000002"]["download_status"] == "pending"
    assert by_id["vid00000002"]["file_size"] is None


async def test_list_videos_for_unknown_source_is_404(api):
    resp = await api.client.get("/api/sources/999/videos")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found"


async def test_skip_video_marks_it_skipped(api, seeded):
    resp = await api.client.delete(
        f"/api/sources/{seeded.source_id}/videos/{seeded.pending_id}"
    )
    assert resp.status_code == 204
    assert api.video_row(seeded.pending_id)["download_status"] == "skipped"


async def test_delete_video_file_removes_it_from_disk_and_the_database(api, seeded):
    assert seeded.mp3.exists()

    resp = await api.client.delete(
        f"/api/sources/{seeded.source_id}/videos/{seeded.completed_id}/file"
    )
    assert resp.status_code == 204

    assert not seeded.mp3.exists()
    row = api.video_row(seeded.completed_id)
    # 'deleted' rather than 'pending', so a later sync does not re-download it.
    assert row["download_status"] == "deleted"
    assert row["file_path"] is None
    assert row["file_size"] is None


async def test_delete_video_file_tolerates_an_already_missing_file(api, seeded):
    seeded.mp3.unlink()

    resp = await api.client.delete(
        f"/api/sources/{seeded.source_id}/videos/{seeded.completed_id}/file"
    )
    assert resp.status_code == 204
    assert api.video_row(seeded.completed_id)["download_status"] == "deleted"


async def test_requeue_video_resets_it_to_pending(api, seeded):
    api.db.update_video_status(
        seeded.completed_id, "failed", error_message="something went wrong"
    )

    resp = await api.client.post(
        f"/api/sources/{seeded.source_id}/videos/{seeded.completed_id}/requeue"
    )
    assert resp.status_code == 204

    row = api.video_row(seeded.completed_id)
    assert row["download_status"] == "pending"
    assert row["file_path"] is None
    assert row["file_size"] is None
    assert row["error_message"] is None


async def test_video_actions_require_a_known_source(api, seeded):
    vid = seeded.completed_id
    assert (await api.client.delete(f"/api/sources/999/videos/{vid}")).status_code == 404
    assert (await api.client.delete(f"/api/sources/999/videos/{vid}/file")).status_code == 404
    assert (await api.client.post(f"/api/sources/999/videos/{vid}/requeue")).status_code == 404

    # The video itself is untouched by any of those rejected calls.
    assert api.video_row(vid)["download_status"] == "completed"
