"""REST API routes for source management and app status."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from backend.downloader import sync_source
from backend.fetcher.url_parser import parse_youtube_url
from backend.models import (
    SettingsResponse,
    SettingsUpdate,
    SourceCreate,
    SourceResponse,
    SourceUpdate,
    StatusResponse,
    VideoResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Sources CRUD
# ---------------------------------------------------------------------------

@router.get("/sources", response_model=list[SourceResponse])
async def list_sources(request: Request) -> list[dict]:
    db = request.app.state.db
    sources = db.get_all_sources()
    result = []
    for s in sources:
        result.append({
            **dict(s),
            "enabled": bool(s["enabled"]),
            "video_count": db.get_video_count(s["id"]),
            "completed_count": db.get_completed_count(s["id"]),
        })
    return result


@router.post("/sources", response_model=SourceResponse, status_code=201)
async def add_source(body: SourceCreate, request: Request) -> dict:
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator

    # Parse URL
    try:
        parsed = parse_youtube_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    youtube_id = parsed.youtube_id
    source_type = parsed.source_type

    # Resolve handles/custom URLs to channel IDs
    if parsed.needs_resolution:
        try:
            youtube_id = await orchestrator.resolve_to_channel_id(
                parsed.youtube_id, parsed.source_type
            )
            source_type = "channel"
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Auto-generate name if not provided
    name = body.name or f"{source_type.title()}: {youtube_id[:20]}"

    # Cache uploads playlist ID for channels
    uploads_playlist_id = None
    if source_type == "channel":
        try:
            uploads_playlist_id = await orchestrator.get_uploads_playlist_id(youtube_id)
        except Exception:
            pass  # Non-critical, will be fetched on first sync

    # Fetch channel icon (only available when API key is set)
    icon_url = None
    if source_type == "channel":
        try:
            icon_url = await orchestrator.fetch_channel_icon(youtube_id)
        except Exception:
            pass  # Non-critical

    source_id = db.add_source(
        name=name,
        source_type=source_type,
        youtube_id=youtube_id,
        url=body.url,
        max_backfill=body.max_backfill,
        uploads_playlist_id=uploads_playlist_id,
        custom_storage_path=body.custom_storage_path or None,
        icon_url=icon_url,
        max_keep_episodes=body.max_keep_episodes,
    )

    source = db.get_source(source_id)
    return {
        **dict(source),
        "enabled": bool(source["enabled"]),
        "video_count": 0,
        "completed_count": 0,
    }


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source(source_id: int, request: Request) -> dict:
    db = request.app.state.db
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return {
        **dict(source),
        "enabled": bool(source["enabled"]),
        "video_count": db.get_video_count(source_id),
        "completed_count": db.get_completed_count(source_id),
    }


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def update_source(source_id: int, body: SourceUpdate, request: Request) -> dict:
    db = request.app.state.db
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    updates = body.model_dump(exclude_unset=True)
    if updates:
        db.update_source(source_id, **updates)

    source = db.get_source(source_id)
    return {
        **dict(source),
        "enabled": bool(source["enabled"]),
        "video_count": db.get_video_count(source_id),
        "completed_count": db.get_completed_count(source_id),
    }


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: int, request: Request) -> None:
    db = request.app.state.db
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete_source(source_id)


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------

@router.get("/sources/{source_id}/videos", response_model=list[VideoResponse])
async def list_videos(source_id: int, request: Request) -> list[dict]:
    db = request.app.state.db
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    rows = db.get_videos_for_source(source_id)
    return [dict(r) for r in rows]


@router.delete("/sources/{source_id}/videos/{video_db_id}", status_code=204)
async def skip_video(source_id: int, video_db_id: int, request: Request) -> None:
    """Mark a video as skipped so it won't be downloaded."""
    db = request.app.state.db
    if not db.get_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    db.skip_video(video_db_id)


@router.delete("/sources/{source_id}/videos/{video_db_id}/file", status_code=204)
async def delete_video_file(source_id: int, video_db_id: int, request: Request) -> None:
    """Delete the downloaded MP3 from disk and mark the video as 'deleted' (won't auto-re-download)."""
    import os
    db = request.app.state.db
    if not db.get_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    file_path = db.delete_downloaded_file(video_db_id)
    if file_path:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass  # File already gone — that's fine


@router.post("/sources/{source_id}/videos/{video_db_id}/requeue", status_code=204)
async def requeue_video(source_id: int, video_db_id: int, request: Request) -> None:
    """Re-queue a deleted or failed video so it will be downloaded on the next sync."""
    db = request.app.state.db
    if not db.get_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    db.requeue_video(video_db_id)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@router.post("/sources/{source_id}/sync", status_code=202)
async def trigger_sync(source_id: int, request: Request, background_tasks: BackgroundTasks) -> dict:
    """Manually trigger a sync for one source. Returns immediately; sync runs in background."""
    db = request.app.state.db
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    orchestrator = request.app.state.orchestrator
    download_manager = request.app.state.download_manager
    download_manager.reset_cancel()

    background_tasks.add_task(sync_source, source_id, db, orchestrator, download_manager)
    return {"status": "started"}


@router.post("/sync-all", status_code=202)
async def trigger_sync_all(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Trigger sync for all enabled sources. Returns immediately; syncs run in background."""
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator
    download_manager = request.app.state.download_manager

    sources = db.get_enabled_sources()
    download_manager.reset_cancel()

    async def _run_all():
        for source in sources:
            try:
                await sync_source(source["id"], db, orchestrator, download_manager)
            except Exception:
                logger.exception("Sync failed for source %d", source["id"])

    background_tasks.add_task(_run_all)
    return {"status": "started", "sources_queued": len(sources)}


# ---------------------------------------------------------------------------
# Status & Settings
# ---------------------------------------------------------------------------

@router.post("/downloads/cancel-all")
async def cancel_all_downloads(request: Request) -> dict:
    """Stop any queued downloads from starting. In-flight downloads finish normally."""
    request.app.state.download_manager.cancel_all()
    return {"cancelled": True}


@router.get("/downloads/progress")
async def get_download_progress(request: Request) -> dict:
    """Return live download progress for all active downloads, keyed by video DB id."""
    return request.app.state.download_manager.get_progress()


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> dict:
    download_manager = request.app.state.download_manager
    scheduler = getattr(request.app.state, "scheduler", None)

    next_poll = None
    last_poll = None
    if scheduler and scheduler.running:
        jobs = scheduler.get_jobs()
        if jobs:
            next_run = jobs[0].next_run_time
            next_poll = next_run.isoformat() if next_run else None

    # Get last poll from any source
    db = request.app.state.db
    row = db.fetch_one("SELECT MAX(last_polled_at) as lp FROM sources")
    if row and row["lp"]:
        last_poll = row["lp"]

    pending_row = db.fetch_one("SELECT COUNT(*) as cnt FROM videos WHERE download_status = 'pending'")
    queue_size = pending_row["cnt"] if pending_row else 0

    return {
        "server_running": True,
        "next_poll": next_poll,
        "last_poll": last_poll,
        "download_queue_size": queue_size,
        "active_downloads": download_manager.active_downloads,
    }


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "youtube_api_key_set": bool(settings.youtube_api_key),
        "poll_interval_minutes": settings.poll_interval_minutes,
        "storage_path": str(settings.storage_path),
        "server_port": settings.server_port,
        "base_url": settings.base_url,
        "cookies_from_browser": settings.cookies_from_browser,
        "cookies_file_path": settings.cookies_file_path,
    }


@router.post("/pick-directory")
async def pick_directory() -> dict:
    """Open a native macOS folder picker and return the selected path."""
    import subprocess
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'POSIX path of (choose folder with prompt "Select download folder")'],
            capture_output=True, text=True, timeout=60,
        )
        path = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        path = None
    return {"path": path}


@router.patch("/settings", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdate, request: Request) -> dict:
    db = request.app.state.db
    settings = request.app.state.settings
    orchestrator = request.app.state.orchestrator

    if body.youtube_api_key is not None:
        settings.youtube_api_key = body.youtube_api_key
        db.set_setting("youtube_api_key", body.youtube_api_key)
        orchestrator.update_api_key(body.youtube_api_key)

    if body.poll_interval_minutes is not None:
        settings.poll_interval_minutes = body.poll_interval_minutes
        db.set_setting("poll_interval_minutes", str(body.poll_interval_minutes))
        # Reschedule if scheduler is running
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler and scheduler.running:
            from backend.scheduler import reschedule_poll
            reschedule_poll(scheduler, settings.poll_interval_minutes)

    if body.cookies_from_browser is not None:
        settings.cookies_from_browser = body.cookies_from_browser
        db.set_setting("cookies_from_browser", body.cookies_from_browser)

    if body.cookies_file_path is not None:
        settings.cookies_file_path = body.cookies_file_path
        db.set_setting("cookies_file_path", body.cookies_file_path)

    return {
        "youtube_api_key_set": bool(settings.youtube_api_key),
        "poll_interval_minutes": settings.poll_interval_minutes,
        "storage_path": str(settings.storage_path),
        "server_port": settings.server_port,
        "base_url": settings.base_url,
        "cookies_from_browser": settings.cookies_from_browser,
        "cookies_file_path": settings.cookies_file_path,
    }


# ---------------------------------------------------------------------------
# Cookie detection & validation
# ---------------------------------------------------------------------------

_KNOWN_BROWSERS = ["chrome", "safari", "firefox", "brave", "chromium", "edge", "opera", "vivaldi"]

# A stable, always-public YouTube video used for cookie validation probes
_PROBE_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _probe_browser_cookies(browser: str) -> dict:
    """Synchronous: try to read cookies for `browser` via yt-dlp. Returns a status dict."""
    import yt_dlp

    try:
        opts = {
            "cookiesfrombrowser": (browser,),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            jar = ydl.cookiejar
            yt_cookies = [c for c in jar if "youtube" in c.domain or "google" in c.domain]
            return {
                "name": browser,
                "available": True,
                "needs_permission": False,
                "has_youtube_cookies": len(yt_cookies) > 0,
            }
    except Exception as e:
        err = str(e)
        if "Operation not permitted" in err or "PermissionError" in err:
            return {"name": browser, "available": True, "needs_permission": True, "has_youtube_cookies": False}
        return {"name": browser, "available": False, "needs_permission": False, "has_youtube_cookies": False}


@router.get("/cookies/detect")
async def detect_cookies() -> dict:
    """Detect which browsers are installed and have YouTube cookies accessible."""
    loop = asyncio.get_event_loop()
    results = []
    for browser in _KNOWN_BROWSERS:
        result = await loop.run_in_executor(None, _probe_browser_cookies, browser)
        results.append(result)
    return {"browsers": results}


def _test_cookies_sync(browser: str | None, cookies_file: str | None) -> dict:
    """Synchronous: probe YouTube with the configured cookies to verify they work."""
    import yt_dlp

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": 15,
    }
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    elif cookies_file:
        opts["cookiefile"] = cookies_file

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(_PROBE_VIDEO_URL, download=False)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)[:300]}


@router.post("/cookies/test")
async def test_cookies(request: Request) -> dict:
    """Test whether the configured (or specified) cookies work for YouTube downloads."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    settings = request.app.state.settings

    browser = body.get("browser", settings.cookies_from_browser) or None
    cookies_file = body.get("cookies_file", settings.cookies_file_path) or None

    if not browser and not cookies_file:
        return {"status": "error", "message": "No browser or cookie file configured"}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _test_cookies_sync, browser, cookies_file)
    return result
