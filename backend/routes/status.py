"""Application status API route."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.models import StatusResponse

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> dict:
    download_manager = request.app.state.download_manager
    scheduler = getattr(request.app.state, "scheduler", None)

    next_poll = None
    if scheduler and scheduler.running:
        jobs = scheduler.get_jobs()
        if jobs:
            next_run = jobs[0].next_run_time
            next_poll = next_run.isoformat() if next_run else None

    db = request.app.state.db
    return {
        "server_running": True,
        "next_poll": next_poll,
        "last_poll": db.get_last_poll_time(),
        "download_queue_size": db.count_pending_videos(),
        "active_downloads": download_manager.active_downloads,
    }
