"""Audio file serving routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from backend.services.paths import resolve_audio_path

router = APIRouter()


@router.get("/audio/{source_id}/{filename}")
async def serve_audio(source_id: int, filename: str, request: Request) -> FileResponse:
    """Serve a downloaded audio file.

    URL pattern: /audio/{source_id}/{video_id}.mp3
    """
    db = request.app.state.db
    settings = request.app.state.settings

    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    file_path = resolve_audio_path(db, source, filename, settings)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Audio file not found")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Security: ensure the resolved path is within the storage directory
    try:
        file_path.resolve().relative_to(settings.storage_path.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=str(file_path),
        media_type="audio/mpeg",
        filename=filename,
    )
