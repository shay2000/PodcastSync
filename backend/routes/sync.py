"""Sync and download-control API routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from backend.services.sync import sync_all_sources, sync_source

router = APIRouter()


@router.post("/sources/{source_id}/sync", status_code=202)
async def trigger_sync(source_id: int, request: Request, background_tasks: BackgroundTasks) -> dict:
    """Start a sync for one source in the background."""
    db = request.app.state.db
    if not db.get_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")

    orchestrator = request.app.state.orchestrator
    download_manager = request.app.state.download_manager
    download_manager.reset_cancel()
    background_tasks.add_task(sync_source, source_id, db, orchestrator, download_manager)
    return {"status": "started"}


@router.post("/sync-all", status_code=202)
async def trigger_sync_all(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Start syncs for all enabled sources in the background."""
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator
    download_manager = request.app.state.download_manager
    sources = db.get_enabled_sources()
    download_manager.reset_cancel()
    background_tasks.add_task(sync_all_sources, db, orchestrator, download_manager, sources)
    return {"status": "started", "sources_queued": len(sources)}


@router.post("/downloads/cancel-all")
async def cancel_all_downloads(request: Request) -> dict:
    """Stop queued downloads from starting; in-flight downloads finish."""
    request.app.state.download_manager.cancel_all()
    return {"cancelled": True}


@router.get("/downloads/progress")
async def get_download_progress(request: Request) -> dict:
    """Return live download progress keyed by video database id."""
    return request.app.state.download_manager.get_progress()
