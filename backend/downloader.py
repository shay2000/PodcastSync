"""Download manager — yt-dlp wrapper for audio-only downloads."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

from backend.database import DatabaseManager
from backend.fetcher.base import VideoInfo
from backend.fetcher.orchestrator import FetcherOrchestrator

logger = logging.getLogger(__name__)

# Common ffmpeg locations on macOS
_FFMPEG_SEARCH_PATHS = ["/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"]


def _bundled_ffmpeg_candidates() -> list[Path]:
    """Return likely bundled ffmpeg locations for frozen builds."""
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            executable_dir / "tools" / "bin" / "ffmpeg",
            executable_dir.parent / "tools" / "bin" / "ffmpeg",
            executable_dir / "_internal" / "tools" / "bin" / "ffmpeg",
        ])

    return candidates


def _clear_quarantine(path: str) -> None:
    """Remove the macOS quarantine xattr so Gatekeeper won't block execution."""
    if sys.platform != "darwin":
        return
    try:
        import subprocess
        subprocess.run(
            ["/usr/bin/xattr", "-d", "com.apple.quarantine", path],
            check=False, capture_output=True, timeout=5,
        )
    except Exception:
        pass


def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg binary on the system."""
    bundled = os.getenv("PODCASTSYNC_FFMPEG", "").strip()
    if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    for candidate in _bundled_ffmpeg_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
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
        settings=None,
    ) -> None:
        self.storage_path = storage_path
        self.db = db
        self.max_concurrent = max_concurrent
        self.ffmpeg_path = ffmpeg_path or find_ffmpeg()
        self._settings = settings  # live reference so cookie setting changes take effect

        # Clear macOS quarantine so the OS doesn't block ffmpeg/ffprobe when
        # yt-dlp tries to execute them (happens after installing from a DMG).
        if self.ffmpeg_path:
            _clear_quarantine(self.ffmpeg_path)
            ffprobe = os.path.join(os.path.dirname(self.ffmpeg_path), "ffprobe")
            if os.path.isfile(ffprobe):
                _clear_quarantine(ffprobe)

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_downloads: int = 0
        self._progress: dict[int, dict] = {}  # video_db_id -> progress info
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
        """Return a snapshot of current download progress keyed by video_db_id."""
        return dict(self._progress)

    def cancel_all(self) -> None:
        """Stop any pending downloads from starting. In-flight downloads finish normally."""
        self._cancel_requested = True
        self._progress.clear()

    def reset_cancel(self) -> None:
        """Clear the cancel flag so the next sync proceeds normally."""
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
        if custom_storage_path:
            return Path(custom_storage_path)
        return self.storage_path / sanitize_filename(source_name)

    def _embed_channel_icon(self, mp3_path: Path, icon_url: str, cache_dir: Path) -> None:
        """Download the channel icon once and embed it as album art in the MP3."""
        import urllib.request
        from mutagen.id3 import ID3, APIC, error as ID3Error

        icon_path = cache_dir / "channel_icon.jpg"
        if not icon_path.exists():
            try:
                urllib.request.urlretrieve(icon_url, str(icon_path))
            except Exception as e:
                logger.warning("Could not download channel icon: %s", e)
                return

        try:
            tags = ID3(str(mp3_path))
        except ID3Error:
            from mutagen.id3 import ID3NoHeaderError
            tags = ID3()

        tags.delall("APIC")
        tags.add(APIC(
            encoding=3,       # UTF-8
            mime="image/jpeg",
            type=3,           # Cover (front)
            desc="Cover",
            data=icon_path.read_bytes(),
        ))
        tags.save(str(mp3_path))

    async def download_video(
        self,
        video_db_id: int,
        video_id: str,
        source_name: str,
        custom_storage_path: Optional[str] = None,
        icon_url: Optional[str] = None,
    ) -> Optional[Path]:
        """Download a single video's audio as MP3. Returns the file path on success."""
        output_dir = self._get_output_dir(source_name, custom_storage_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        expected_path = output_dir / f"{video_id}.mp3"

        # Skip if already downloaded (and non-empty)
        if expected_path.exists() and expected_path.stat().st_size > 0:
            logger.info("Already exists: %s", expected_path)
            self.db.update_video_status(
                video_db_id, "completed",
                file_path=str(expected_path),
                file_size=expected_path.stat().st_size,
            )
            return expected_path
        elif expected_path.exists():
            # Stale 0-byte file from a previous failed conversion — remove it and retry
            logger.warning("Removing empty output file, will re-download: %s", expected_path)
            expected_path.unlink()

        self.db.update_video_status(video_db_id, "downloading")
        self._active_downloads += 1

        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._make_ydl_opts(output_dir)

            # Run yt-dlp in a thread to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_download, url, opts, video_db_id)

            if expected_path.exists() and expected_path.stat().st_size > 0:
                # Embed channel icon as album art (instead of per-video thumbnail)
                if icon_url:
                    try:
                        self._embed_channel_icon(expected_path, icon_url, output_dir)
                    except Exception as e:
                        logger.warning("Failed to embed channel icon: %s", e)

                file_size = expected_path.stat().st_size
                self.db.update_video_status(
                    video_db_id, "completed",
                    file_path=str(expected_path),
                    file_size=file_size,
                )
                logger.info("Downloaded: %s (%d bytes)", expected_path, file_size)
                return expected_path
            else:
                # Empty file means ffmpeg conversion failed — clean up and report
                if expected_path.exists():
                    expected_path.unlink()
                self.db.update_video_status(
                    video_db_id, "failed",
                    error_message="Audio conversion failed (ffmpeg produced empty output). Check ffmpeg is installed.",
                )
                logger.error("ffmpeg produced empty output for %s — is ffmpeg working?", video_id)
                return None

        except Exception as e:
            error_msg = str(e)[:500]
            self.db.update_video_status(video_db_id, "failed", error_message=error_msg)
            logger.error("Download failed for %s: %s", video_id, error_msg)
            return None
        finally:
            self._active_downloads -= 1

    def _sync_download(self, url: str, opts: dict, video_db_id: int) -> None:
        """Synchronous yt-dlp download (called via run_in_executor)."""
        import yt_dlp  # Lazy import — yt-dlp takes ~60s to load

        def _progress_hook(d: dict) -> None:
            if d.get("status") == "downloading":
                self._progress[video_db_id] = {
                    "downloaded_bytes": d.get("downloaded_bytes", 0),
                    "total_bytes": d.get("total_bytes") or d.get("total_bytes_estimate", 0),
                    "speed": d.get("speed", 0),
                }
            elif d.get("status") in ("finished", "error"):
                self._progress.pop(video_db_id, None)

        opts = {**opts, "progress_hooks": [_progress_hook]}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            msg = str(exc)
            _auth_keywords = ("Sign in to confirm", "confirm you're not a bot", "login required", "LOGIN_REQUIRED")
            if any(kw.lower() in msg.lower() for kw in _auth_keywords):
                raise Exception(f"[AUTH_REQUIRED] {msg}") from exc
            raise

    def _apply_rolling_delete(self, source_id: int, max_keep: int) -> None:
        """Delete oldest completed files if the source is over its keep limit."""
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
        """Download all pending videos for a source. Returns count of successful downloads."""
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
                    row["id"], row["video_id"], source_name,
                    custom_storage_path=custom_storage_path,
                    icon_url=icon_url,
                )
                if result:
                    completed += 1
                    if max_keep_episodes:
                        self._apply_rolling_delete(source_id, max_keep_episodes)

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
    max_backfill = source["max_backfill"]
    # Cap at 50 to prevent accidentally fetching hundreds; use max_backfill as the limit
    max_results = min(max_backfill, 50)

    # Record the check at the start of the sync attempt so the UI reflects
    # that a manual sync was actually triggered even if fetching finds nothing
    # or later steps fail.
    db.execute(
        "UPDATE sources SET last_polled_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (source_id,),
    )

    # Fetch video metadata
    logger.info("Syncing source %d (%s): %s %s", source_id, source_name, source_type, youtube_id)
    try:
        videos = await orchestrator.fetch_videos(source_type, youtube_id, max_results=max_results)
    except Exception:
        logger.exception("Failed to fetch videos for source %d", source_id)
        return 0, 0

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

    logger.info("Found %d new videos for source %d", new_count, source_id)

    # Download pending videos
    downloaded = await download_manager.process_pending_downloads(
        source_id, source_name,
        custom_storage_path=source["custom_storage_path"],
        icon_url=source["icon_url"],
        max_keep_episodes=source["max_keep_episodes"],
    )

    return new_count, downloaded
