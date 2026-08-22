"""Filesystem naming and audio path helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def sanitize_filename(name: str, max_len: int = 64) -> str:
    """Make a string safe for use as a directory name."""
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(".")
    return name[:max_len] if name else "unnamed"


def output_dir_for_source(settings: Any, source: Any) -> Path:
    """Return the directory where a source's downloads are written."""
    custom_storage_path = source["custom_storage_path"]
    if custom_storage_path:
        return Path(custom_storage_path)
    return settings.storage_path / sanitize_filename(source["name"])


def resolve_audio_path(
    db: Any,
    source: Any,
    filename: str,
    settings: Any | None = None,
) -> Path | None:
    """Resolve an audio filename under a source's configured download folder.

    ``settings`` is accepted by the HTTP route so the legacy default-folder
    behaviour remains explicit.  When it is omitted, a stored video path is
    used when available, which also makes this helper useful to callers that
    already have a database row but no application settings object.
    """
    if settings is not None:
        return output_dir_for_source(settings, source) / filename

    video_id = Path(filename).stem
    row = db.fetch_one(
        "SELECT file_path FROM videos WHERE source_id = ? AND video_id = ?",
        (source["id"], video_id),
    )
    if row and row["file_path"]:
        return Path(row["file_path"])
    return None
