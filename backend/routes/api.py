"""REST API routes for source management and app status."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

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
    """Delete the downloaded MP3 from disk and reset the video status to pending."""
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


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@router.post("/sources/{source_id}/sync")
async def trigger_sync(source_id: int, request: Request) -> dict:
    """Manually trigger a sync for one source."""
    db = request.app.state.db
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    orchestrator = request.app.state.orchestrator
    download_manager = request.app.state.download_manager

    new_videos, downloaded = await sync_source(source_id, db, orchestrator, download_manager)
    return {"new_videos": new_videos, "downloaded": downloaded}


@router.post("/sync-all")
async def trigger_sync_all(request: Request) -> dict:
    """Trigger sync for all enabled sources."""
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator
    download_manager = request.app.state.download_manager

    sources = db.get_enabled_sources()
    total_new = 0
    total_downloaded = 0

    for source in sources:
        try:
            new_v, dl = await sync_source(source["id"], db, orchestrator, download_manager)
            total_new += new_v
            total_downloaded += dl
        except Exception:
            logger.exception("Sync failed for source %d", source["id"])

    return {"sources_synced": len(sources), "new_videos": total_new, "downloaded": total_downloaded}


# ---------------------------------------------------------------------------
# Status & Settings
# ---------------------------------------------------------------------------

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

    return {
        "youtube_api_key_set": bool(settings.youtube_api_key),
        "poll_interval_minutes": settings.poll_interval_minutes,
        "storage_path": str(settings.storage_path),
        "server_port": settings.server_port,
        "base_url": settings.base_url,
    }
