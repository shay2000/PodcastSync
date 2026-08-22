"""Source synchronization orchestration."""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


async def sync_source(
    source_id: int,
    db: Any,
    orchestrator: Any,
    download_manager: Any,
) -> tuple[int, int]:
    """Fetch new metadata for one source and process its pending downloads."""
    source = db.get_source(source_id)
    if not source:
        logger.error("Source %d not found", source_id)
        return 0, 0

    source_type = source["source_type"]
    youtube_id = source["youtube_id"]
    source_name = source["name"]

    known_ids = db.get_known_video_ids(source_id)
    max_results = min(source["max_backfill"], 50)

    db.execute(
        "UPDATE sources SET last_polled_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (source_id,),
    )

    logger.info("Syncing source %d (%s): %s %s", source_id, source_name, source_type, youtube_id)
    try:
        videos = await orchestrator.fetch_videos(source_type, youtube_id, max_results=max_results)
    except Exception:
        logger.exception("Failed to fetch videos for source %d", source_id)
        return 0, 0

    new_count = 0
    for video in videos:
        if video.video_id in known_ids:
            continue
        result = db.add_video(
            source_id=source_id,
            video_id=video.video_id,
            title=video.title,
            description=video.description[:2000] if video.description else "",
            publish_date=video.publish_date.isoformat() if video.publish_date else None,
            duration_seconds=video.duration_seconds,
            thumbnail_url=video.thumbnail_url,
        )
        if result is not None:
            new_count += 1

    logger.info("Found %d new videos for source %d", new_count, source_id)
    downloaded = await download_manager.process_pending_downloads(
        source_id,
        source_name,
        custom_storage_path=source["custom_storage_path"],
        icon_url=source["icon_url"],
        max_keep_episodes=source["max_keep_episodes"],
    )
    return new_count, downloaded


async def sync_all_sources(
    db: Any,
    orchestrator: Any,
    download_manager: Any,
    sources: Iterable[Any] | None = None,
) -> int:
    """Synchronize enabled sources, logging individual failures.

    The return value is the number of sources attempted.  The route obtains
    this count before scheduling the work; returning it here is convenient for
    the scheduler and direct callers without changing the HTTP contract.
    """
    selected_sources = list(sources) if sources is not None else db.get_enabled_sources()
    for source in selected_sources:
        try:
            await sync_source(source["id"], db, orchestrator, download_manager)
        except Exception:
            logger.exception("Sync failed for source %d", source["id"])
    return len(selected_sources)
