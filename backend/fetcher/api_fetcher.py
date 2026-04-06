"""YouTube Data API v3 fetcher implementation."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from backend.fetcher.base import QuotaExceededError, VideoInfo, YouTubeSourceFetcher

logger = logging.getLogger(__name__)


def _parse_iso8601_duration(duration: str) -> int:
    """Parse ISO 8601 duration (e.g. 'PT1H2M3S') to total seconds."""
    import re
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class YouTubeApiFetcher(YouTubeSourceFetcher):
    def __init__(self, api_key: str) -> None:
        from googleapiclient.discovery import build  # Lazy import — google client is slow

        self.api_key = api_key
        self._service = build("youtube", "v3", developerKey=api_key)
        self._uploads_cache: dict[str, str] = {}  # channel_id -> uploads_playlist_id

    def _handle_http_error(self, e) -> None:
        from googleapiclient.errors import HttpError  # Lazy import
        if not isinstance(e, HttpError):
            raise
        if e.resp.status == 403:
            error_reason = ""
            if e.error_details:
                for detail in e.error_details:
                    if isinstance(detail, dict):
                        error_reason = detail.get("reason", "")
            if "quotaExceeded" in str(e.content) or error_reason == "quotaExceeded":
                raise QuotaExceededError(f"YouTube API quota exceeded: {e}") from e
        raise

    async def resolve_to_channel_id(self, identifier: str, id_type: str) -> str:
        """Resolve a handle, custom URL, or username to a channel ID."""
        try:
            if id_type == "handle":
                resp = self._service.channels().list(
                    part="id", forHandle=identifier, maxResults=1
                ).execute()
            elif id_type == "user":
                resp = self._service.channels().list(
                    part="id", forUsername=identifier, maxResults=1
                ).execute()
            elif id_type == "custom":
                # Try searching for the custom URL
                resp = self._service.search().list(
                    part="id", q=identifier, type="channel", maxResults=1
                ).execute()
                items = resp.get("items", [])
                if items:
                    return items[0]["id"]["channelId"]
                raise ValueError(f"Could not resolve custom URL: {identifier}")
            else:
                raise ValueError(f"Unknown id_type: {id_type}")

            items = resp.get("items", [])
            if not items:
                raise ValueError(f"No channel found for {id_type}: {identifier}")
            return items[0]["id"]

        except Exception as e:
            self._handle_http_error(e)
            raise

    async def get_uploads_playlist_id(self, channel_id: str) -> str:
        """Get the uploads playlist ID via the API, with caching."""
        if channel_id in self._uploads_cache:
            return self._uploads_cache[channel_id]

        try:
            resp = self._service.channels().list(
                part="contentDetails", id=channel_id
            ).execute()
            items = resp.get("items", [])
            if not items:
                raise ValueError(f"Channel not found: {channel_id}")

            playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
            self._uploads_cache[channel_id] = playlist_id
            return playlist_id

        except Exception as e:
            self._handle_http_error(e)
            raise

    async def get_channel_icon_url(self, channel_id: str) -> Optional[str]:
        """Return the highest-resolution channel avatar URL, or None on failure."""
        try:
            resp = self._service.channels().list(
                part="snippet", id=channel_id
            ).execute()
            items = resp.get("items", [])
            if not items:
                return None
            thumbs = items[0].get("snippet", {}).get("thumbnails", {})
            for quality in ("high", "medium", "default"):
                url = thumbs.get(quality, {}).get("url")
                if url:
                    return url
        except Exception:
            logger.warning("Could not fetch channel icon for %s", channel_id)
        return None

    async def fetch_videos(
        self,
        source_type: str,
        youtube_id: str,
        max_results: Optional[int] = None,
    ) -> list[VideoInfo]:
        """Fetch videos using the YouTube Data API v3."""
        if source_type == "channel":
            playlist_id = await self.get_uploads_playlist_id(youtube_id)
        else:
            playlist_id = youtube_id

        videos: list[VideoInfo] = []
        page_token: Optional[str] = None
        remaining = max_results

        try:
            while True:
                page_size = min(50, remaining) if remaining else 50
                resp = self._service.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=playlist_id,
                    maxResults=page_size,
                    pageToken=page_token,
                ).execute()

                video_ids = []
                snippet_map = {}

                for item in resp.get("items", []):
                    vid = item["contentDetails"]["videoId"]
                    video_ids.append(vid)
                    snippet_map[vid] = item["snippet"]

                # Batch fetch durations via videos.list
                if video_ids:
                    details_resp = self._service.videos().list(
                        part="contentDetails",
                        id=",".join(video_ids),
                    ).execute()
                    duration_map = {}
                    for d_item in details_resp.get("items", []):
                        raw = d_item["contentDetails"].get("duration", "PT0S")
                        duration_map[d_item["id"]] = _parse_iso8601_duration(raw)
                else:
                    duration_map = {}

                for vid in video_ids:
                    snippet = snippet_map[vid]
                    pub_str = snippet.get("publishedAt", "")
                    pub_date = None
                    if pub_str:
                        try:
                            pub_date = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                        except ValueError:
                            pass

                    thumbs = snippet.get("thumbnails", {})
                    thumb_url = (
                        thumbs.get("maxres", {}).get("url")
                        or thumbs.get("high", {}).get("url")
                        or thumbs.get("default", {}).get("url")
                    )

                    videos.append(VideoInfo(
                        video_id=vid,
                        title=snippet.get("title", ""),
                        description=snippet.get("description", ""),
                        publish_date=pub_date,
                        duration_seconds=duration_map.get(vid),
                        thumbnail_url=thumb_url,
                        channel_name=snippet.get("channelTitle", ""),
                    ))

                if remaining is not None:
                    remaining -= len(resp.get("items", []))
                    if remaining <= 0:
                        break

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

        except Exception as e:
            self._handle_http_error(e)

        logger.info("API fetched %d videos for %s %s", len(videos), source_type, youtube_id)
        return videos
