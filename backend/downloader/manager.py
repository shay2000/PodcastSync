"""yt-dlp-backed audio download manager."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from backend.database import DatabaseManager
from backend.downloader.artwork import _embed_channel_icon
from backend.downloader.ffmpeg import _clear_quarantine, find_ffmpeg
from backend.services.paths import output_dir_for_source

logger = logging.getLogger(__name__)


class DownloadManager:
    def __init__(
        self,
        storage_path: Path,
        db: DatabaseManager,
        max_concurrent: int = 2,
        ffmpeg_path: Optional[str] = None,
        settings=None,
    ) -> None:
        self.storage_path = storage_path
        self.db = db
        self.max_concurrent = max_concurrent
        self.ffmpeg_path = ffmpeg_path or find_ffmpeg()
        self._settings = settings

        if self.ffmpeg_path:
            _clear_quarantine(self.ffmpeg_path)
            ffprobe = os.path.join(os.path.dirname(self.ffmpeg_path), "ffprobe")
            if os.path.isfile(ffprobe):
                _clear_quarantine(ffprobe)

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_downloads: int = 0
        self._progress: dict[int, dict] = {}
        self._cancel_requested: bool = False

        if not self.ffmpeg_path:
            logger.warning(
                "ffmpeg not found! Audio downloads will fail. "
                "Packaged builds should bundle ffmpeg automatically. "
                "Development mode still requires it on the host machine."
            )

        self.storage_path.mkdir(parents=True, exist_ok=True)

    @property
    def active_downloads(self) -> int:
        return self._active_downloads

    def get_progress(self) -> dict:
        """Return a snapshot of active progress keyed by video database id."""
        return dict(self._progress)

    def cancel_all(self) -> None:
        """Stop pending downloads from starting; in-flight downloads finish."""
        self._cancel_requested = True
        self._progress.clear()

    def reset_cancel(self) -> None:
        """Clear the cancellation flag for the next sync."""
        self._cancel_requested = False

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
            ],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = os.path.dirname(self.ffmpeg_path)
        browser = (self._settings.cookies_from_browser if self._settings else "").strip()
        if browser:
            opts["cookiesfrombrowser"] = (browser,)
        else:
            cookie_file = (self._settings.cookies_file_path if self._settings else "").strip()
            if cookie_file and os.path.isfile(cookie_file):
                opts["cookiefile"] = cookie_file
        return opts

    def _get_output_dir(self, source_name: str, custom_storage_path: Optional[str]) -> Path:
        return output_dir_for_source(
            self,
            {"name": source_name, "custom_storage_path": custom_storage_path},
        )

    async def download_video(
        self,
        video_db_id: int,
        video_id: str,
        source_name: str,
        custom_storage_path: Optional[str] = None,
        icon_url: Optional[str] = None,
    ) -> Optional[Path]:
        """Download one video's audio as MP3."""
        output_dir = self._get_output_dir(source_name, custom_storage_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        expected_path = output_dir / f"{video_id}.mp3"

        if expected_path.exists() and expected_path.stat().st_size > 0:
            logger.info("Already exists: %s", expected_path)
            self.db.update_video_status(
                video_db_id,
                "completed",
                file_path=str(expected_path),
                file_size=expected_path.stat().st_size,
            )
            return expected_path
        if expected_path.exists():
            logger.warning("Removing empty output file, will re-download: %s", expected_path)
            expected_path.unlink()

        self.db.update_video_status(video_db_id, "downloading")
        self._active_downloads += 1
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._make_ydl_opts(output_dir)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_download, url, opts, video_db_id)

            if expected_path.exists() and expected_path.stat().st_size > 0:
                if icon_url:
                    try:
                        _embed_channel_icon(expected_path, icon_url, output_dir)
                    except Exception as exc:
                        logger.warning("Failed to embed channel icon: %s", exc)
                file_size = expected_path.stat().st_size
                self.db.update_video_status(
                    video_db_id,
                    "completed",
                    file_path=str(expected_path),
                    file_size=file_size,
                )
                logger.info("Downloaded: %s (%d bytes)", expected_path, file_size)
                return expected_path

            if expected_path.exists():
                expected_path.unlink()
            self.db.update_video_status(
                video_db_id,
                "failed",
                error_message="Audio conversion failed (ffmpeg produced empty output). Check ffmpeg is installed.",
            )
            logger.error("ffmpeg produced empty output for %s — is ffmpeg working?", video_id)
            return None
        except Exception as exc:
            error_msg = str(exc)[:500]
            self.db.update_video_status(video_db_id, "failed", error_message=error_msg)
            logger.error("Download failed for %s: %s", video_id, error_msg)
            return None
        finally:
            self._active_downloads -= 1

    def _sync_download(self, url: str, opts: dict, video_db_id: int) -> None:
        """Run yt-dlp synchronously in the executor thread."""
        import yt_dlp  # Lazy import — yt-dlp takes ~60s to load

        def _progress_hook(data: dict) -> None:
            if data.get("status") == "downloading":
                self._progress[video_db_id] = {
                    "downloaded_bytes": data.get("downloaded_bytes", 0),
                    "total_bytes": data.get("total_bytes") or data.get("total_bytes_estimate", 0),
                    "speed": data.get("speed", 0),
                }
            elif data.get("status") in ("finished", "error"):
                self._progress.pop(video_db_id, None)

        opts = {**opts, "progress_hooks": [_progress_hook]}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            message = str(exc)
            auth_keywords = (
                "Sign in to confirm",
                "confirm you're not a bot",
                "login required",
                "LOGIN_REQUIRED",
            )
            if any(keyword.lower() in message.lower() for keyword in auth_keywords):
                raise Exception(f"[AUTH_REQUIRED] {message}") from exc
            raise

    def _apply_rolling_delete(self, source_id: int, max_keep: int) -> None:
        """Delete oldest completed files beyond the source keep limit."""
        to_delete = self.db.get_overflow_completed_videos(source_id, max_keep)
        for video in to_delete:
            if video["file_path"]:
                try:
                    os.remove(video["file_path"])
                    logger.info("Rolling delete: removed %s", video["file_path"])
                except FileNotFoundError:
                    pass
            self.db.update_video_status(video["id"], "deleted")

    async def process_pending_downloads(
        self,
        source_id: int,
        source_name: str,
        custom_storage_path: Optional[str] = None,
        icon_url: Optional[str] = None,
        max_keep_episodes: Optional[int] = None,
    ) -> int:
        """Download all pending videos for a source."""
        pending = self.db.get_pending_videos(source_id)
        if not pending:
            return 0

        logger.info("Processing %d pending downloads for source %d", len(pending), source_id)
        completed = 0

        async def _download_one(row):
            nonlocal completed
            if self._cancel_requested:
                return
            async with self._semaphore:
                if self._cancel_requested:
                    return
                result = await self.download_video(
                    row["id"],
                    row["video_id"],
                    source_name,
                    custom_storage_path=custom_storage_path,
                    icon_url=icon_url,
                )
                if result:
                    completed += 1
                    if max_keep_episodes:
                        self._apply_rolling_delete(source_id, max_keep_episodes)

        await asyncio.gather(*[_download_one(row) for row in pending])
        logger.info("Completed %d/%d downloads for source %d", completed, len(pending), source_id)
        return completed
