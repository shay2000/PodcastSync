"""Video listing and lifecycle API routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from backend.models import VideoResponse

router = APIRouter()


def _require_source(request: Request, source_id: int):
    source = request.app.state.db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.get("/sources/{source_id}/videos", response_model=list[VideoResponse])
async def list_videos(source_id: int, request: Request) -> list[dict]:
    _require_source(request, source_id)
    return [dict(row) for row in request.app.state.db.get_videos_for_source(source_id)]


@router.delete("/sources/{source_id}/videos/{video_db_id}", status_code=204)
async def skip_video(source_id: int, video_db_id: int, request: Request) -> None:
    """Mark a video as skipped so it will not be downloaded."""
    db = request.app.state.db
    _require_source(request, source_id)
    db.skip_video(video_db_id)


@router.delete("/sources/{source_id}/videos/{video_db_id}/file", status_code=204)
async def delete_video_file(source_id: int, video_db_id: int, request: Request) -> None:
    """Delete the downloaded MP3 and mark the video as deleted."""
    db = request.app.state.db
    _require_source(request, source_id)
    file_path = db.delete_downloaded_file(video_db_id)
    if file_path:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass


@router.post("/sources/{source_id}/videos/{video_db_id}/requeue", status_code=204)
async def requeue_video(source_id: int, video_db_id: int, request: Request) -> None:
    """Re-queue a deleted or failed video for the next sync."""
    db = request.app.state.db
    _require_source(request, source_id)
    db.requeue_video(video_db_id)
