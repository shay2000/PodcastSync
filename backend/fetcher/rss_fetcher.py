"""YouTube RSS/Atom feed fetcher implementation (fallback)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import feedparser

from backend.fetcher.base import VideoInfo, YouTubeSourceFetcher

logger = logging.getLogger(__name__)

YOUTUBE_RSS_BASE = "https://www.youtube.com/feeds/videos.xml"


class YouTubeRssFetcher(YouTubeSourceFetcher):
    async def fetch_videos(
        self,
        source_type: str,
        youtube_id: str,
        max_results: Optional[int] = None,
    ) -> list[VideoInfo]:
        """Fetch videos from YouTube's public Atom XML feed.

        Note: This typically returns only the ~15 most recent videos.
        Duration metadata is not available via RSS.
        """
        if source_type == "channel":
            url = f"{YOUTUBE_RSS_BASE}?channel_id={youtube_id}"
        else:
            url = f"{YOUTUBE_RSS_BASE}?playlist_id={youtube_id}"

        logger.info("RSS fetching from %s", url)
        feed = feedparser.parse(url)

        if feed.bozo and not feed.entries:
            logger.error("RSS feed parse error for %s: %s", url, feed.bozo_exception)
            return []

        videos: list[VideoInfo] = []
        for entry in feed.entries:
            video_id = entry.get("yt_videoid", "")
            if not video_id:
                # Try extracting from link
                link = entry.get("link", "")
                if "watch?v=" in link:
                    video_id = link.split("watch?v=")[1].split("&")[0]
                if not video_id:
                    continue

            pub_date = None
            if entry.get("published_parsed"):
                try:
                    pub_date = datetime(*entry.published_parsed[:6])
                except (TypeError, ValueError):
                    pass

            # Thumbnail from media:group
            thumbnail_url = None
            media_group = entry.get("media_thumbnail", [])
            if media_group:
                thumbnail_url = media_group[0].get("url")
            if not thumbnail_url:
                thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

            videos.append(VideoInfo(
                video_id=video_id,
                title=entry.get("title", ""),
                description=entry.get("summary", ""),
                publish_date=pub_date,
                duration_seconds=None,  # Not available via RSS
                thumbnail_url=thumbnail_url,
                channel_name=entry.get("author", ""),
            ))

        if max_results and len(videos) > max_results:
            videos = videos[:max_results]

        logger.info("RSS fetched %d videos for %s %s", len(videos), source_type, youtube_id)
        return videos
