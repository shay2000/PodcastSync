"""Source creation and source response DTOs."""

from __future__ import annotations

from typing import Any

from backend.fetcher.url_parser import parse_youtube_url


def source_dto(db: Any, source: Any) -> dict:
    """Serialize a database source row into the public source shape."""
    return {
        **dict(source),
        "enabled": bool(source["enabled"]),
        "video_count": db.get_video_count(source["id"]),
        "completed_count": db.get_completed_count(source["id"]),
    }


def list_source_dtos(db: Any) -> list[dict]:
    """Return all sources in the same order as the API has always used."""
    return [source_dto(db, source) for source in db.get_all_sources()]


def get_source_dto(db: Any, source_id: int) -> dict | None:
    """Return one serialized source, or ``None`` when it does not exist."""
    source = db.get_source(source_id)
    return source_dto(db, source) if source else None


async def create_source(body: Any, db: Any, orchestrator: Any) -> dict:
    """Parse, resolve, enrich, and persist a source definition.

    Enrichment failures are intentionally non-fatal, matching the original
    route: uploads-playlist and artwork metadata are useful caches, not a
    requirement for creating a source.
    """
    parsed = parse_youtube_url(body.url)
    youtube_id = parsed.youtube_id
    source_type = parsed.source_type

    if parsed.needs_resolution:
        youtube_id = await orchestrator.resolve_to_channel_id(
            parsed.youtube_id, parsed.source_type
        )
        source_type = "channel"

    name = body.name or f"{source_type.title()}: {youtube_id[:20]}"

    uploads_playlist_id = None
    if source_type == "channel":
        try:
            uploads_playlist_id = await orchestrator.get_uploads_playlist_id(youtube_id)
        except Exception:
            pass

    icon_url = None
    if source_type == "channel":
        try:
            icon_url = await orchestrator.fetch_channel_icon(youtube_id)
        except Exception:
            pass

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
    return source_dto(db, source)
