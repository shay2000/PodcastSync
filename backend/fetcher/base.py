"""Abstract base class for YouTube source fetchers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class VideoInfo:
    """Metadata for a single YouTube video, returned by fetchers."""
    video_id: str
    title: str
    description: str
    publish_date: Optional[datetime]
    duration_seconds: Optional[int]
    thumbnail_url: Optional[str]
    channel_name: str = ""


class QuotaExceededError(Exception):
    """Raised when the YouTube Data API quota is exhausted."""


class YouTubeSourceFetcher(ABC):
    @abstractmethod
    async def fetch_videos(
        self,
        source_type: str,
        youtube_id: str,
        max_results: Optional[int] = None,
    ) -> list[VideoInfo]:
        """Fetch video metadata for a channel or playlist.

        Args:
            source_type: "channel" or "playlist"
            youtube_id: The channel ID or playlist ID
            max_results: Maximum number of videos to return (None = all available)

        Returns:
            List of VideoInfo, newest first.
        """

    async def resolve_to_channel_id(self, identifier: str, id_type: str) -> str:
        """Resolve a handle or custom URL to a channel ID.

        Default implementation raises NotImplementedError — only the API fetcher supports this.
        """
        raise NotImplementedError(f"Cannot resolve {id_type} without YouTube API key")

    async def get_uploads_playlist_id(self, channel_id: str) -> str:
        """Get the uploads playlist ID for a channel.

        Default implementation uses the UC→UU prefix substitution.
        """
        if channel_id.startswith("UC"):
            return "UU" + channel_id[2:]
        raise ValueError(f"Cannot derive uploads playlist from channel ID: {channel_id}")
