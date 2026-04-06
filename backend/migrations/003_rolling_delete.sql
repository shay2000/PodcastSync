-- Migration 003: rolling-delete keep limit + 'deleted' video status

-- SQLite can't modify CHECK constraints in-place, so recreate the videos table.
ALTER TABLE videos RENAME TO videos_old;

CREATE TABLE videos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id        INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    video_id         TEXT    NOT NULL,
    title            TEXT    NOT NULL DEFAULT '',
    description      TEXT    NOT NULL DEFAULT '',
    publish_date     TEXT,
    duration_seconds INTEGER,
    thumbnail_url    TEXT,
    download_status  TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (download_status IN ('pending','downloading','completed','failed','skipped','deleted')),
    file_path        TEXT,
    file_size        INTEGER,
    error_message    TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, video_id)
);

INSERT INTO videos SELECT * FROM videos_old;
DROP TABLE videos_old;

-- Per-source rolling-delete limit (NULL = keep everything)
ALTER TABLE sources ADD COLUMN max_keep_episodes INTEGER;

INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '3');
