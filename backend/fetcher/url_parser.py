"""Parse YouTube URLs to extract source type and ID."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


@dataclass
class ParseResult:
    source_type: str  # "channel", "playlist", "handle", "custom", "user"
    youtube_id: str   # channel ID, playlist ID, handle, or custom name
    original_url: str

    @property
    def needs_resolution(self) -> bool:
        """Whether this ID needs API resolution to get a channel ID."""
        return self.source_type in ("handle", "custom", "user")


def parse_youtube_url(url: str) -> ParseResult:
    """Parse a YouTube URL and extract the source type and identifier.

    Supported formats:
        https://www.youtube.com/channel/UCxxxxxxx
        https://www.youtube.com/@username
        https://www.youtube.com/c/CustomName
        https://www.youtube.com/user/Username
        https://www.youtube.com/playlist?list=PLxxxxxxx
        https://youtube.com/channel/UCxxxxxxx  (no www)
        UCxxxxxxx  (bare channel ID)
        PLxxxxxxx  (bare playlist ID)
        @username  (bare handle)

    Returns:
        ParseResult with source_type, youtube_id, and original_url.

    Raises:
        ValueError: If the URL format is not recognized.
    """
    url = url.strip()

    # Bare handle: @username
    if url.startswith("@"):
        return ParseResult(source_type="handle", youtube_id=url.lstrip("@"), original_url=url)

    # Bare channel ID: UCxxxxxxx
    if re.match(r"^UC[\w-]{20,}$", url):
        return ParseResult(source_type="channel", youtube_id=url, original_url=url)

    # Bare playlist ID: PLxxxxxxx or other prefixes (FL, OL, etc.)
    if re.match(r"^(PL|FL|OL|UU)[\w-]{10,}$", url):
        return ParseResult(source_type="playlist", youtube_id=url, original_url=url)

    # Ensure URL has a scheme for urlparse
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    host = parsed.hostname or ""

    if "youtube.com" not in host and "youtu.be" not in host:
        raise ValueError(f"Not a YouTube URL: {url}")

    path = parsed.path.rstrip("/")

    # /channel/UCxxxxxxx
    match = re.match(r"/channel/(UC[\w-]+)", path)
    if match:
        return ParseResult(source_type="channel", youtube_id=match.group(1), original_url=url)

    # /@username
    match = re.match(r"/@([\w.-]+)", path)
    if match:
        return ParseResult(source_type="handle", youtube_id=match.group(1), original_url=url)

    # /c/CustomName
    match = re.match(r"/c/([\w.-]+)", path)
    if match:
        return ParseResult(source_type="custom", youtube_id=match.group(1), original_url=url)

    # /user/Username
    match = re.match(r"/user/([\w.-]+)", path)
    if match:
        return ParseResult(source_type="user", youtube_id=match.group(1), original_url=url)

    # /playlist?list=PLxxxxxxx
    if "/playlist" in path:
        qs = parse_qs(parsed.query)
        if "list" in qs:
            return ParseResult(source_type="playlist", youtube_id=qs["list"][0], original_url=url)

    # Fallback: check query params for list= (some URLs embed it differently)
    qs = parse_qs(parsed.query)
    if "list" in qs:
        return ParseResult(source_type="playlist", youtube_id=qs["list"][0], original_url=url)

    raise ValueError(
        f"Could not extract a channel or playlist ID from: {url}\n"
        "Supported formats: channel URL, @handle, playlist URL, or bare channel/playlist ID."
    )
