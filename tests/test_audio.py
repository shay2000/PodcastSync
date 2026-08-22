"""Characterization tests for audio file serving."""

from __future__ import annotations

from tests.conftest import SOURCE_NAME


async def test_serves_a_downloaded_file(api, seeded):
    resp = await api.client.get(f"/audio/{seeded.source_id}/vid00000001.mp3")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == seeded.mp3.read_bytes()


async def test_missing_file_is_404(api, seeded):
    resp = await api.client.get(f"/audio/{seeded.source_id}/nope.mp3")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Audio file not found"


async def test_unknown_source_is_404(api):
    resp = await api.client.get("/audio/999/anything.mp3")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found"


async def test_a_deleted_file_stops_being_served(api, seeded):
    assert (await api.client.get(f"/audio/{seeded.source_id}/vid00000001.mp3")).status_code == 200

    await api.client.delete(f"/api/sources/{seeded.source_id}/videos/{seeded.completed_id}/file")

    resp = await api.client.get(f"/audio/{seeded.source_id}/vid00000001.mp3")
    assert resp.status_code == 404


async def test_files_are_looked_up_under_the_source_name_folder(api, seeded):
    """The route resolves storage_path / <sanitized source name> / <filename>."""
    assert seeded.mp3.parent == api.storage / SOURCE_NAME

    # A file sitting directly in the storage root is therefore not reachable.
    stray = api.storage / "stray.mp3"
    stray.write_bytes(b"not in the source folder")
    resp = await api.client.get(f"/audio/{seeded.source_id}/stray.mp3")
    assert resp.status_code == 404


async def test_path_traversal_does_not_escape_the_storage_directory(api, seeded, tmp_path):
    secret = tmp_path / "secret.mp3"
    secret.write_bytes(b"SECRET-OUTSIDE-STORAGE")

    for attempt in (
        "..%2F..%2Fsecret.mp3",
        "../../secret.mp3",
        "..%252F..%252Fsecret.mp3",
    ):
        resp = await api.client.get(f"/audio/{seeded.source_id}/{attempt}")
        # Rejected either by path routing (404) or by the containment check (403).
        assert resp.status_code in (403, 404), attempt
        assert b"SECRET-OUTSIDE-STORAGE" not in resp.content, attempt
