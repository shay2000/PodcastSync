"""CLI test script for M1 — fetch video metadata from a YouTube URL."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from backend.config import Settings
from backend.database import DatabaseManager
from backend.fetcher.orchestrator import FetcherOrchestrator
from backend.fetcher.url_parser import parse_youtube_url

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m backend.test_fetch <YouTube URL>")
        print("  Set YOUTUBE_API_KEY env var for API-based fetching.")
        print()
        print("Examples:")
        print("  python -m backend.test_fetch https://www.youtube.com/@mkbhd")
        print("  python -m backend.test_fetch https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf")
        print("  python -m backend.test_fetch UCBJycsmduvYEL83R_U4JriQ")
        sys.exit(1)

    url = sys.argv[1]
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    # Parse URL
    print(f"\n--- Parsing URL: {url}")
    parsed = parse_youtube_url(url)
    print(f"  Type: {parsed.source_type}")
    print(f"  ID:   {parsed.youtube_id}")
    print(f"  Needs resolution: {parsed.needs_resolution}")

    # Initialize
    settings = Settings.from_env()
    orchestrator = FetcherOrchestrator(api_key=settings.youtube_api_key)
    print(f"\n--- API available: {orchestrator.has_api}")

    # Resolve handle if needed
    youtube_id = parsed.youtube_id
    source_type = parsed.source_type

    if parsed.needs_resolution:
        print(f"  Resolving {parsed.source_type} '{parsed.youtube_id}'...")
        youtube_id = await orchestrator.resolve_to_channel_id(parsed.youtube_id, parsed.source_type)
        source_type = "channel"
        print(f"  Resolved to channel ID: {youtube_id}")

    # Fetch videos
    print(f"\n--- Fetching up to {max_results} videos...")
    videos = await orchestrator.fetch_videos(source_type, youtube_id, max_results=max_results)

    print(f"\n--- Found {len(videos)} videos:\n")
    for i, v in enumerate(videos, 1):
        duration = f"{v.duration_seconds // 60}:{v.duration_seconds % 60:02d}" if v.duration_seconds else "N/A"
        date = v.publish_date.strftime("%Y-%m-%d") if v.publish_date else "N/A"
        print(f"  {i:3d}. [{date}] ({duration}) {v.title}")
        print(f"       ID: {v.video_id}  Channel: {v.channel_name}")

    # Test database integration
    print("\n--- Testing database integration...")
    db = DatabaseManager(settings.db_path)
    db.initialize()

    source_name = videos[0].channel_name if videos else "Test Source"
    source_id = db.add_source(
        name=source_name,
        source_type=source_type,
        youtube_id=youtube_id,
        url=url,
        max_backfill=max_results,
    )
    print(f"  Created source #{source_id}: {source_name}")

    inserted = 0
    for v in videos:
        result = db.add_video(
            source_id=source_id,
            video_id=v.video_id,
            title=v.title,
            description=v.description[:500],
            publish_date=v.publish_date.isoformat() if v.publish_date else None,
            duration_seconds=v.duration_seconds,
            thumbnail_url=v.thumbnail_url,
        )
        if result is not None:
            inserted += 1

    print(f"  Inserted {inserted} new videos (skipped {len(videos) - inserted} duplicates)")
    print(f"  Total videos in DB for this source: {db.get_video_count(source_id)}")

    db.close()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
