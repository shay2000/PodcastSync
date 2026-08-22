"""Application settings API routes."""

from __future__ import annotations

import subprocess

from fastapi import APIRouter, Request

from backend.models import SettingsResponse, SettingsUpdate

router = APIRouter()


def settings_to_response(settings) -> dict:
    """Serialize settings without exposing the YouTube API key."""
    return {
        "youtube_api_key_set": bool(settings.youtube_api_key),
        "poll_interval_minutes": settings.poll_interval_minutes,
        "storage_path": str(settings.storage_path),
        "server_port": settings.server_port,
        "base_url": settings.base_url,
        "cookies_from_browser": settings.cookies_from_browser,
        "cookies_file_path": settings.cookies_file_path,
    }


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(request: Request) -> dict:
    return settings_to_response(request.app.state.settings)


@router.post("/pick-directory")
async def pick_directory() -> dict:
    """Open a native macOS folder picker and return its selected path."""
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'POSIX path of (choose folder with prompt "Select download folder")',
            ],
            capture_output=True,
            text=True,
            timeout=60,
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

    return settings_to_response(settings)
