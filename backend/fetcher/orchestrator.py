"""Fetcher orchestrator — tries API first, falls back to RSS."""

from __future__ import annotations

import logging
from typing import Optional

from backend.fetcher.base import QuotaExceededError, VideoInfo, YouTubeSourceFetcher
from backend.fetcher.rss_fetcher import YouTubeRssFetcher

logger = logging.getLogger(__name__)


class FetcherOrchestrator:
    def __init__(self, api_key: str = "") -> None:
        self.api_fetcher: Optional[YouTubeSourceFetcher] = None
        self.rss_fetcher = YouTubeRssFetcher()

        if api_key:
            from backend.fetcher.api_fetcher import YouTubeApiFetcher  # Lazy — google client is heavy
            self.api_fetcher = YouTubeApiFetcher(api_key)
            logger.info("Orchestrator initialized with API + RSS fetchers")
        else:
            logger.info("Orchestrator initialized with RSS fetcher only (no API key)")

    @property
    def has_api(self) -> bool:
        return self.api_fetcher is not None

    def update_api_key(self, api_key: str) -> None:
        """Update the API key at runtime (e.g. when set via web UI)."""
        if api_key:
            self.api_fetcher = YouTubeApiFetcher(api_key)
            logger.info("API fetcher updated with new key")
        else:
            self.api_fetcher = None
            logger.info("API fetcher disabled (key removed)")

    async def resolve_to_channel_id(self, identifier: str, id_type: str) -> str:
        """Resolve a handle/custom/user identifier to a channel ID. Requires API."""
        if not self.api_fetcher:
            raise ValueError(
                f"Cannot resolve YouTube {id_type} '{identifier}' without an API key. "
                "Please set your YouTube API key in Settings, or use a direct channel/playlist URL."
            )
        return await self.api_fetcher.resolve_to_channel_id(identifier, id_type)

    async def get_uploads_playlist_id(self, channel_id: str) -> str:
        """Get the uploads playlist ID, preferring API over UC→UU fallback."""
        if self.api_fetcher:
            return await self.api_fetcher.get_uploads_playlist_id(channel_id)
        return await self.rss_fetcher.get_uploads_playlist_id(channel_id)

    async def fetch_videos(
        self,
        source_type: str,
        youtube_id: str,
        max_results: Optional[int] = None,
    ) -> list[VideoInfo]:
        """Fetch videos, trying API first then falling back to RSS.

        The fallback triggers on:
        - No API key configured
        - QuotaExceededError from the API
        - Any other API error (after logging)
        """
        if self.api_fetcher:
            try:
                videos = await self.api_fetcher.fetch_videos(source_type, youtube_id, max_results)
                logger.info("Fetched %d videos via API", len(videos))
                return videos
            except QuotaExceededError:
                logger.warning("API quota exceeded, falling back to RSS for %s %s", source_type, youtube_id)
            except Exception:
                logger.exception("API fetch failed, falling back to RSS for %s %s", source_type, youtube_id)

        # Fallback to RSS
        try:
            videos = await self.rss_fetcher.fetch_videos(source_type, youtube_id, max_results)
            logger.info("Fetched %d videos via RSS (fallback)", len(videos))
            return videos
        except Exception:
            logger.exception("RSS fetch also failed for %s %s", source_type, youtube_id)
            return []
