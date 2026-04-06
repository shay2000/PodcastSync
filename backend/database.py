"""SQLite database manager with migration support."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

from backend._resources import resource_path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = resource_path("migrations")


class DatabaseManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Migration runner
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create the database and apply pending migrations."""
        current_version = self._get_schema_version()
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        for mf in migration_files:
            version = int(mf.stem.split("_")[0])
            if version > current_version:
                logger.info("Applying migration %s", mf.name)
                sql = mf.read_text()
                self.conn.executescript(sql)
                self._set_schema_version(version)

        self.conn.commit()
        logger.info("Database initialized at %s (schema v%d)", self.db_path, self._get_schema_version())

    def _get_schema_version(self) -> int:
        try:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key = 'schema_version'"
            ).fetchone()
            return int(row["value"]) if row else 0
        except sqlite3.OperationalError:
            return 0

    def _set_schema_version(self, version: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchone()

    def fetch_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def get_all_settings(self) -> dict[str, str]:
        rows = self.fetch_all("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in rows}

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    # ------------------------------------------------------------------
    # Source helpers
    # ------------------------------------------------------------------

    def add_source(
        self,
        name: str,
        source_type: str,
        youtube_id: str,
        url: str,
        max_backfill: int = 15,
        uploads_playlist_id: str | None = None,
        custom_storage_path: str | None = None,
        icon_url: str | None = None,
        max_keep_episodes: int | None = None,
    ) -> int:
        cur = self.execute(
            """INSERT INTO sources
               (name, source_type, youtube_id, url, max_backfill, uploads_playlist_id, custom_storage_path, icon_url, max_keep_episodes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, source_type, youtube_id, url, max_backfill, uploads_playlist_id, custom_storage_path, icon_url, max_keep_episodes),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def get_source(self, source_id: int) -> Optional[sqlite3.Row]:
        return self.fetch_one("SELECT * FROM sources WHERE id = ?", (source_id,))

    def get_all_sources(self) -> list[sqlite3.Row]:
        return self.fetch_all("SELECT * FROM sources ORDER BY created_at DESC")

    def get_enabled_sources(self) -> list[sqlite3.Row]:
        return self.fetch_all("SELECT * FROM sources WHERE enabled = 1 ORDER BY created_at DESC")

    def update_source(self, source_id: int, **fields: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [source_id]
        self.execute(f"UPDATE sources SET {sets}, updated_at = datetime('now') WHERE id = ?", tuple(vals))

    def delete_source(self, source_id: int) -> None:
        self.execute("DELETE FROM videos WHERE source_id = ?", (source_id,))
        self.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    # ------------------------------------------------------------------
    # Video helpers
    # ------------------------------------------------------------------

    def add_video(
        self,
        source_id: int,
        video_id: str,
        title: str = "",
        description: str = "",
        publish_date: str | None = None,
        duration_seconds: int | None = None,
        thumbnail_url: str | None = None,
    ) -> int | None:
        """Insert a video if it doesn't already exist for this source. Returns row id or None if duplicate."""
        try:
            cur = self.execute(
                """INSERT INTO videos (source_id, video_id, title, description, publish_date, duration_seconds, thumbnail_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source_id, video_id, title, description, publish_date, duration_seconds, thumbnail_url),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def get_videos_for_source(self, source_id: int, limit: int = 200) -> list[sqlite3.Row]:
        return self.fetch_all(
            "SELECT * FROM videos WHERE source_id = ? ORDER BY publish_date DESC LIMIT ?",
            (source_id, limit),
        )

    def get_completed_videos_for_source(self, source_id: int) -> list[sqlite3.Row]:
        return self.fetch_all(
            "SELECT * FROM videos WHERE source_id = ? AND download_status = 'completed' ORDER BY publish_date DESC",
            (source_id,),
        )

    def get_pending_videos(self, source_id: int) -> list[sqlite3.Row]:
        return self.fetch_all(
            "SELECT * FROM videos WHERE source_id = ? AND download_status = 'pending' ORDER BY publish_date ASC",
            (source_id,),
        )

    def update_video_status(self, video_id: int, status: str, **fields: Any) -> None:
        extra = "".join(f", {k} = ?" for k in fields)
        vals = [status] + list(fields.values()) + [video_id]
        self.execute(f"UPDATE videos SET download_status = ?{extra} WHERE id = ?", tuple(vals))

    def skip_video(self, video_db_id: int) -> None:
        """Mark a video as skipped so it is never downloaded."""
        self.execute(
            "UPDATE videos SET download_status = 'skipped' WHERE id = ?",
            (video_db_id,),
        )

    def delete_downloaded_file(self, video_db_id: int) -> Optional[str]:
        """Return the file_path and mark the video as 'deleted' (won't auto-re-download)."""
        row = self.fetch_one("SELECT file_path FROM videos WHERE id = ?", (video_db_id,))
        file_path = row["file_path"] if row else None
        self.execute(
            "UPDATE videos SET download_status = 'deleted', file_path = NULL, file_size = NULL WHERE id = ?",
            (video_db_id,),
        )
        return file_path

    def requeue_video(self, video_db_id: int) -> None:
        """Reset a deleted/failed video to pending so it will be downloaded on next sync."""
        self.execute(
            "UPDATE videos SET download_status = 'pending', file_path = NULL, file_size = NULL, error_message = NULL WHERE id = ?",
            (video_db_id,),
        )

    def get_overflow_completed_videos(self, source_id: int, max_keep: int) -> list[sqlite3.Row]:
        """Return completed videos beyond the keep limit, oldest first (to be rolling-deleted)."""
        return self.fetch_all(
            """SELECT * FROM videos
               WHERE source_id = ? AND download_status = 'completed' AND file_path IS NOT NULL
               ORDER BY publish_date ASC
               LIMIT -1 OFFSET ?""",
            (source_id, max_keep),
        )

    def get_known_video_ids(self, source_id: int) -> set[str]:
        rows = self.fetch_all("SELECT video_id FROM videos WHERE source_id = ?", (source_id,))
        return {row["video_id"] for row in rows}

    def get_video_count(self, source_id: int) -> int:
        row = self.fetch_one("SELECT COUNT(*) as cnt FROM videos WHERE source_id = ?", (source_id,))
        return row["cnt"] if row else 0

    def get_completed_count(self, source_id: int) -> int:
        row = self.fetch_one(
            "SELECT COUNT(*) as cnt FROM videos WHERE source_id = ? AND download_status = 'completed'",
            (source_id,),
        )
        return row["cnt"] if row else 0
