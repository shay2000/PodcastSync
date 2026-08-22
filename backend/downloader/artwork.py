"""MP3 artwork helpers."""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def _embed_channel_icon(mp3_path: Path, icon_url: str, cache_dir: Path) -> None:
    """Download and embed a channel icon as the MP3's cover art."""
    from mutagen.id3 import APIC, ID3, error as ID3Error

    icon_path = cache_dir / "channel_icon.jpg"
    if not icon_path.exists():
        try:
            urllib.request.urlretrieve(icon_url, str(icon_path))
        except Exception as exc:
            logger.warning("Could not download channel icon: %s", exc)
            return

    try:
        tags = ID3(str(mp3_path))
    except ID3Error:
        tags = ID3()

    tags.delall("APIC")
    tags.add(APIC(
        encoding=3,
        mime="image/jpeg",
        type=3,
        desc="Cover",
        data=icon_path.read_bytes(),
    ))
    tags.save(str(mp3_path))
