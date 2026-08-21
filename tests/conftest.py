"""Shared fixtures for the PodcastSync characterization tests.

These tests pin *current* behaviour so the structural refactor can be verified
rather than hoped about. They assert on API shape and database/disk effects, not
on internal structure, so they should survive modules moving around.

Everything runs offline. `Settings.from_env()` already honours PODCASTSYNC_DB and
PODCASTSYNC_STORAGE, so a temp directory is enough to isolate a test run without
touching production code. The two collaborators that would leave the machine —
the fetcher orchestrator (YouTube API / RSS) and the download manager (yt-dlp and
ffmpeg) — are swapped for stubs once startup has finished.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio

# A real channel URL in the direct /channel/UC… form, so parse_youtube_url
# resolves it without the orchestrator being consulted.
CHANNEL_URL = "https://www.youtube.com/channel/UCXuqSBlHAE6Xw-yeJA0Tunw"
CHANNEL_ID = "UCXuqSBlHAE6Xw-yeJA0Tunw"

# A handle URL, which *does* need the orchestrator to resolve it.
HANDLE_URL = "https://www.youtube.com/@someHandle"

# What StubOrchestrator resolves handles to.
RESOLVED_CHANNEL_ID = "UCstubresolved00000000"
STUB_ICON_URL = "https://example.invalid/icon.jpg"

# sanitize_filename() leaves this untouched, so tests can build the on-disk
# folder path without importing that helper (which moves during the refactor).
SOURCE_NAME = "Test Channel"


class StubOrchestrator:
    """Stands in for FetcherOrchestrator. Records calls, never reaches YouTube."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.videos: list[Any] = []
        self.api_key = ""

    async def resolve_to_channel_id(self, identifier: str, source_type: str) -> str:
        self.calls.append(("resolve_to_channel_id", identifier, source_type))
        return RESOLVED_CHANNEL_ID

    async def get_uploads_playlist_id(self, channel_id: str) -> str:
        self.calls.append(("get_uploads_playlist_id", channel_id))
        return "UUstubuploads00000000"

    async def fetch_channel_icon(self, channel_id: str) -> str:
        self.calls.append(("fetch_channel_icon", channel_id))
        return STUB_ICON_URL

    async def fetch_videos(self, source_type: str, youtube_id: str, max_results: int | None = None):
        self.calls.append(("fetch_videos", source_type, youtube_id, max_results))
        return list(self.videos)

    def update_api_key(self, api_key: str) -> None:
        self.calls.append(("update_api_key", api_key))
        self.api_key = api_key


class StubDownloadManager:
    """Stands in for DownloadManager. No yt-dlp, no ffmpeg, no downloads."""

    def __init__(self) -> None:
        self.active_downloads = 0
        self.cancel_all_calls = 0
        self.reset_cancel_calls = 0
        self.progress: dict[int, dict] = {}
        self.processed: list[tuple] = []

    def get_progress(self) -> dict:
        return dict(self.progress)

    def cancel_all(self) -> None:
        self.cancel_all_calls += 1

    def reset_cancel(self) -> None:
        self.reset_cancel_calls += 1

    async def process_pending_downloads(self, source_id: int, source_name: str, **kwargs) -> int:
        self.processed.append((source_id, source_name, kwargs))
        return 0


@dataclass
class AppUnderTest:
    """Bundles the HTTP client with the live app state the tests need to inspect."""

    client: httpx.AsyncClient
    app: Any

    @property
    def db(self):
        return self.app.state.db

    @property
    def settings(self):
        return self.app.state.settings

    @property
    def orchestrator(self) -> StubOrchestrator:
        return self.app.state.orchestrator

    @property
    def download_manager(self) -> StubDownloadManager:
        return self.app.state.download_manager

    @property
    def scheduler(self):
        return self.app.state.scheduler

    @property
    def storage(self) -> Path:
        return self.app.state.settings.storage_path

    def video_row(self, video_db_id: int) -> dict:
        row = self.db.fetch_one("SELECT * FROM videos WHERE id = ?", (video_db_id,))
        return dict(row) if row else {}


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    """A started app with a fresh temp database, storage dir, and stubbed collaborators."""
    monkeypatch.setenv("PODCASTSYNC_DB", str(tmp_path / "db" / "podcastsync.db"))
    monkeypatch.setenv("PODCASTSYNC_STORAGE", str(tmp_path / "storage"))
    # Far enough out that the scheduler never fires during a test.
    monkeypatch.setenv("PODCASTSYNC_POLL_INTERVAL", "1440")
    monkeypatch.setenv("YOUTUBE_API_KEY", "")

    from backend.main import app

    # httpx.ASGITransport does not run the lifespan, so drive it explicitly:
    # startup applies migrations and populates app.state.
    async with app.router.lifespan_context(app):
        # Replace the outbound collaborators *after* startup built the real ones.
        app.state.orchestrator = StubOrchestrator()
        app.state.download_manager = StubDownloadManager()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield AppUnderTest(client=client, app=app)


@pytest_asyncio.fixture
async def source(api) -> dict:
    """One source created through the API, as a response dict."""
    resp = await api.client.post(
        "/api/sources",
        json={"url": CHANNEL_URL, "name": SOURCE_NAME, "max_backfill": 5},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@dataclass
class Seeded:
    """A source with two videos: one completed with a real file, one pending."""

    source: dict
    completed_id: int
    pending_id: int
    mp3: Path

    @property
    def source_id(self) -> int:
        return self.source["id"]


@pytest_asyncio.fixture
async def seeded(api, source) -> Seeded:
    folder = api.storage / SOURCE_NAME
    folder.mkdir(parents=True, exist_ok=True)
    mp3 = folder / "vid00000001.mp3"
    mp3.write_bytes(b"ID3 fake audio bytes")

    db = api.db
    completed_id = db.add_video(
        source_id=source["id"],
        video_id="vid00000001",
        title="First Episode",
        description="Description one",
        publish_date="2026-01-01T00:00:00",
        duration_seconds=1800,
        thumbnail_url="https://example.invalid/thumb1.jpg",
    )
    pending_id = db.add_video(
        source_id=source["id"],
        video_id="vid00000002",
        title="Second Episode",
        description="",
        publish_date="2026-02-01T00:00:00",
        duration_seconds=600,
    )
    db.update_video_status(
        completed_id, "completed", file_path=str(mp3), file_size=mp3.stat().st_size
    )
    return Seeded(source=source, completed_id=completed_id, pending_id=pending_id, mp3=mp3)
