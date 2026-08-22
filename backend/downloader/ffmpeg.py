"""ffmpeg discovery for development and frozen macOS builds."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

_FFMPEG_SEARCH_PATHS = ["/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"]


def _bundled_ffmpeg_candidates() -> list[Path]:
    """Return likely bundled ffmpeg locations for frozen builds."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            executable_dir / "tools" / "bin" / "ffmpeg",
            executable_dir.parent / "tools" / "bin" / "ffmpeg",
            executable_dir / "_internal" / "tools" / "bin" / "ffmpeg",
        ])
    return candidates


def _clear_quarantine(path: str) -> None:
    """Remove the macOS quarantine xattr so Gatekeeper permits execution."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["/usr/bin/xattr", "-d", "com.apple.quarantine", path],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def find_ffmpeg() -> Optional[str]:
    """Locate the ffmpeg binary on the system or inside a frozen bundle."""
    bundled = os.getenv("PODCASTSYNC_FFMPEG", "").strip()
    if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    for candidate in _bundled_ffmpeg_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    path = shutil.which("ffmpeg")
    if path:
        return path
    for candidate in _FFMPEG_SEARCH_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None
