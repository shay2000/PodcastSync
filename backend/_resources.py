"""Resource path resolution that works in dev and PyInstaller bundles.

In a regular Python run, files like `backend/static/` and `backend/migrations/`
live next to the `backend` package on disk, so `Path(__file__).parent` works.

In a PyInstaller bundle, the entry-point script's `__file__` does not point to
a real directory, so we fall back to `sys._MEIPASS` (set by PyInstaller in both
onefile and onedir modes) and look for the resource under `backend/`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Return the absolute path to a bundled resource (e.g. 'static', 'migrations').

    `relative` is the path *within* the backend package (e.g. 'static').
    """
    if getattr(sys, "frozen", False):
        # PyInstaller: _MEIPASS is the bundle's internal file root.
        # Our build script copies backend resources to _internal/backend/<name>.
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal"))
        return base / "backend" / relative
    return Path(__file__).resolve().parent / relative
