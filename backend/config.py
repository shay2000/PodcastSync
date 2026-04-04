"""Application settings — loaded from environment variables with sensible defaults."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path


def _default_storage_path() -> Path:
    return Path.home() / "PodcastMirror"


def _default_db_path() -> Path:
    p = Path.home() / ".podcastsync"
    p.mkdir(parents=True, exist_ok=True)
    return p / "podcastsync.db"


def _get_lan_ip() -> str:
    """Best-effort LAN IP detection."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@dataclass
class Settings:
    youtube_api_key: str = ""
    storage_path: Path = field(default_factory=_default_storage_path)
    db_path: Path = field(default_factory=_default_db_path)
    server_port: int = 8642
    poll_interval_minutes: int = 30
    max_concurrent_downloads: int = 2
    lan_ip: str = field(default_factory=_get_lan_ip)

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from environment variables. DB-stored settings override later."""
        return cls(
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
            storage_path=Path(os.getenv("PODCASTSYNC_STORAGE", str(_default_storage_path()))),
            db_path=Path(os.getenv("PODCASTSYNC_DB", str(_default_db_path()))),
            server_port=int(os.getenv("PODCASTSYNC_PORT", "8642")),
            poll_interval_minutes=int(os.getenv("PODCASTSYNC_POLL_INTERVAL", "30")),
            max_concurrent_downloads=int(os.getenv("PODCASTSYNC_MAX_DOWNLOADS", "2")),
        )

    def load_from_db(self, db_settings: dict[str, str]) -> None:
        """Override settings with values stored in the database."""
        if "youtube_api_key" in db_settings and db_settings["youtube_api_key"]:
            self.youtube_api_key = db_settings["youtube_api_key"]
        if "poll_interval_minutes" in db_settings:
            self.poll_interval_minutes = int(db_settings["poll_interval_minutes"])
        if "server_port" in db_settings:
            self.server_port = int(db_settings["server_port"])
        if "storage_path" in db_settings:
            self.storage_path = Path(db_settings["storage_path"])
        if "max_concurrent_downloads" in db_settings:
            self.max_concurrent_downloads = int(db_settings["max_concurrent_downloads"])

    @property
    def base_url(self) -> str:
        return f"http://{self.lan_ip}:{self.server_port}"
