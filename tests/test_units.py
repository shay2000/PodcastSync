"""Unit tests for the two pure helpers the rest of the system leans on.

These are the cheapest possible guard on the refactor: ``sanitize_filename``
decides on-disk folder names (so changing it orphans existing downloads) and
``parse_youtube_url`` decides what counts as a valid source.
"""

from __future__ import annotations

import pytest

from backend.downloader import sanitize_filename
from backend.fetcher.url_parser import parse_youtube_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Normal Name", "Normal Name"),
        # The characters that are illegal or awkward in a path segment.
        ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
        # Runs of whitespace collapse, and the result is stripped.
        ("  spaced   out  ", "spaced out"),
        # Trailing dots break on some filesystems.
        ("trailing...", "trailing"),
        # Non-ASCII is left alone.
        ("Ünïcødé Ok", "Ünïcødé Ok"),
        # Nothing usable left over.
        ("", "unnamed"),
        ("   ", "unnamed"),
        ("...", "unnamed"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_to_64_characters_by_default():
    assert sanitize_filename("x" * 100) == "x" * 64


def test_sanitize_filename_honours_a_custom_length():
    assert sanitize_filename("abcdefghijklmno", max_len=10) == "abcdefghij"


@pytest.mark.parametrize(
    ("url", "source_type", "youtube_id", "needs_resolution"),
    [
        # Direct channel ID — usable immediately.
        (
            "https://www.youtube.com/channel/UCXuqSBlHAE6Xw-yeJA0Tunw",
            "channel",
            "UCXuqSBlHAE6Xw-yeJA0Tunw",
            False,
        ),
        ("UCXuqSBlHAE6Xw-yeJA0Tunw", "channel", "UCXuqSBlHAE6Xw-yeJA0Tunw", False),
        # Handles, custom names and legacy user URLs all need an API lookup.
        ("https://youtube.com/@mkbhd", "handle", "mkbhd", True),
        ("@mkbhd", "handle", "mkbhd", True),
        ("https://www.youtube.com/c/SomeCustom", "custom", "SomeCustom", True),
        ("https://www.youtube.com/user/SomeUser", "user", "SomeUser", True),
        # Playlists, in every accepted form.
        (
            "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
            "playlist",
            "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
            False,
        ),
        (
            "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
            "playlist",
            "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
            False,
        ),
        # A watch URL that carries a list= parameter resolves to that playlist.
        (
            "https://m.youtube.com/watch?v=abc&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
            "playlist",
            "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
            False,
        ),
    ],
)
def test_parse_youtube_url(url, source_type, youtube_id, needs_resolution):
    result = parse_youtube_url(url)
    assert result.source_type == source_type
    assert result.youtube_id == youtube_id
    assert result.needs_resolution is needs_resolution


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x",
        "https://vimeo.com/12345",
        "not a url",
        "",
    ],
)
def test_parse_youtube_url_rejects_non_youtube_hosts(url):
    with pytest.raises(ValueError, match="Not a YouTube URL"):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/nonsense/thing",
        # A bare watch URL has no channel or playlist to sync.
        "https://youtu.be/dQw4w9WgXcQ",
    ],
)
def test_parse_youtube_url_rejects_youtube_urls_with_nothing_to_sync(url):
    with pytest.raises(ValueError, match="Could not extract"):
        parse_youtube_url(url)
