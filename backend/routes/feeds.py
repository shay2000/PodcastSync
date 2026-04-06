"""RSS feed routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from backend.rss_generator import generate_feed

router = APIRouter()


@router.get("/feed/{source_id}.xml")
async def get_feed(source_id: int, request: Request) -> Response:
    """Serve the podcast RSS feed for a specific source."""
    db = request.app.state.db
    settings = request.app.state.settings

    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Use the request's own base URL so that audio links in the feed always
    # point back to whichever address the client used to reach this server.
    base_url = str(request.base_url).rstrip("/")
    videos = db.get_completed_videos_for_source(source_id)
    xml = generate_feed(source, videos, base_url)

    return Response(
        content=xml,
        media_type="application/rss+xml",
        headers={"Cache-Control": "max-age=300"},
    )


@router.get("/feeds")
async def list_feeds(request: Request) -> list[dict]:
    """List all available feeds with their URLs."""
    db = request.app.state.db
    settings = request.app.state.settings

    base_url = str(request.base_url).rstrip("/")
    sources = db.get_all_sources()
    feeds = []
    for s in sources:
        feeds.append({
            "id": s["id"],
            "name": s["name"],
            "source_type": s["source_type"],
            "enabled": bool(s["enabled"]),
            "feed_url": f"{base_url}/feed/{s['id']}.xml",
            "video_count": db.get_video_count(s["id"]),
            "completed_count": db.get_completed_count(s["id"]),
        })
    return feeds
