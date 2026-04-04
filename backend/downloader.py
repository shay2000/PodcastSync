"""Download manager — yt-dlp wrapper for audio-only downloads."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

import yt_dlp

from backend.database import DatabaseManager
from backend.fetcher.base import VideoInfo
from backend.fetcher.orchestrator import FetcherOrchestrator

logger = logging.getLogger(__name__)

# Common ffmpeg locations on macOS
_FFMPEG_SEARCH_PATHS = ["/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"]


def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg binary on the system."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    for p in _FFMPEG_SEARCH_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def sanitize_filename(name: str, max_len: int = 64) -> str:
    """Make a string safe for use as a directory name."""
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(".")
    return name[:max_len] if name else "unnamed"


class DownloadManager:
    def __init__(
        self,
        storage_path: Path,
        db: DatabaseManager,
        max_concurrent: int = 2,
        ffmpeg_path: Optional[str] = None,
    ) -> None:
        self.storage_path = storage_path
        self.db = db
        self.max_concurrent = max_concurrent
        self.ffmpeg_path = ffmpeg_path or find_ffmpeg()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_downloads: int = 0

        if not self.ffmpeg_path:
            logger.warning(
                "ffmpeg not found! Audio downloads will fail. "
                "Install with: brew install ffmpeg"
            )

        self.storage_path.mkdir(parents=True, exist_ok=True)

    @property
    def active_downloads(self) -> int:
        return self._active_downloads

    def _make_ydl_opts(self, output_dir: Path) -> dict:
        opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ],
            "writethumbnail": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = os.path.dirname(self.ffmpeg_path)
        return opts

    async def download_video(self, video_db_id: int, video_id: str, source_name: str) -> Optional[Path]:
        """Download a single video's audio as MP3. Returns the file path on success."""
        safe_name = sanitize_filename(source_name)
        output_dir = self.storage_path / safe_name
        output_dir.mkdir(parents=True, exist_ok=True)

        expected_path = output_dir / f"{video_id}.mp3"

        # Skip if already downloaded
        if expected_path.exists():
            logger.info("Already exists: %s", expected_path)
            self.db.update_video_status(
                video_db_id, "completed",
                file_path=str(expected_path),
                file_size=expected_path.stat().st_size,
            )
            return expected_path

        self.db.update_video_status(video_db_id, "downloading")
        self._active_downloads += 1

        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._make_ydl_opts(output_dir)

            # Run yt-dlp in a thread to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_download, url, opts)

            if expected_path.exists():
                file_size = expected_path.stat().st_size
                self.db.update_video_status(
                    video_db_id, "completed",
                    file_path=str(expected_path),
                    file_size=file_size,
                )
                logger.info("Downloaded: %s (%d bytes)", expected_path, file_size)
                return expected_path
            else:
                self.db.update_video_status(
                    video_db_id, "failed",
                    error_message="Output file not found after download",
                )
                logger.error("Download appeared to succeed but output missing: %s", expected_path)
                return None

        except Exception as e:
            error_msg = str(e)[:500]
            self.db.update_video_status(video_db_id, "failed", error_message=error_msg)
            logger.error("Download failed for %s: %s", video_id, error_msg)
            return None
        finally:
            self._active_downloads -= 1

    def _sync_download(self, url: str, opts: dict) -> None:
        """Synchronous yt-dlp download (called via run_in_executor)."""
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    async def process_pending_downloads(self, source_id: int, source_name: str) -> int:
        """Download all pending videos for a source. Returns count of successful downloads."""
        pending = self.db.get_pending_videos(source_id)
        if not pending:
            return 0

        logger.info("Processing %d pending downloads for source %d", len(pending), source_id)
        completed = 0

        async def _download_one(row):
            nonlocal completed
            async with self._semaphore:
                result = await self.download_video(row["id"], row["video_id"], source_name)
                if result:
                    completed += 1

        tasks = [_download_one(row) for row in pending]
        await asyncio.gather(*tasks)

        logger.info("Completed %d/%d downloads for source %d", completed, len(pending), source_id)
        return completed


async def sync_source(
    source_id: int,
    db: DatabaseManager,
    orchestrator: FetcherOrchestrator,
    download_manager: DownloadManager,
) -> tuple[int, int]:
    """Full sync for a source: fetch new videos → insert to DB → download audio.

    Returns (new_videos_found, downloads_completed).
    """
    source = db.get_source(source_id)
    if not source:
        logger.error("Source %d not found", source_id)
        return 0, 0

    source_type = source["source_type"]
    youtube_id = source["youtube_id"]
    source_name = source["name"]

    # Determine if this is a first sync (no videos in DB yet)
    known_ids = db.get_known_video_ids(source_id)
    is_first_sync = len(known_ids) == 0
    max_results = source["max_backfill"] if is_first_sync else None

    # Fetch video metadata
    logger.info("Syncing source %d (%s): %s %s", source_id, source_name, source_type, youtube_id)
    videos = await orchestrator.fetch_videos(source_type, youtube_id, max_results=max_results)

    # Filter out already-known videos and insert new ones
    new_count = 0
    for v in videos:
        if v.video_id in known_ids:
            continue
        result = db.add_video(
            source_id=source_id,
            video_id=v.video_id,
            title=v.title,
            description=v.description[:2000] if v.description else "",
            publish_date=v.publish_date.isoformat() if v.publish_date else None,
            duration_seconds=v.duration_seconds,
            thumbnail_url=v.thumbnail_url,
        )
        if result is not None:
            new_count += 1

    # Update last polled timestamp
    db.execute("UPDATE sources SET last_polled_at = datetime('now'), updated_at = datetime('now') WHERE id = ?", (source_id,))

    logger.info("Found %d new videos for source %d", new_count, source_id)

    # Download pending videos
    downloaded = await download_manager.process_pending_downloads(source_id, source_name)

    return new_count, downloaded
