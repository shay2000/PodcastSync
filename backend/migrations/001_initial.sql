-- Initial schema for PodcastSync

CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    source_type     TEXT    NOT NULL CHECK (source_type IN ('channel', 'playlist')),
    youtube_id      TEXT    NOT NULL,
    url             TEXT    NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    max_backfill    INTEGER NOT NULL DEFAULT 15,
    uploads_playlist_id TEXT,
    last_polled_at  TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    video_id        TEXT    NOT NULL,
    title           TEXT    NOT NULL DEFAULT '',
    description     TEXT    NOT NULL DEFAULT '',
    publish_date    TEXT,
    duration_seconds INTEGER,
    thumbnail_url   TEXT,
    download_status TEXT    NOT NULL DEFAULT 'pending'
                           CHECK (download_status IN ('pending','downloading','completed','failed','skipped')),
    file_path       TEXT,
    file_size       INTEGER,
    error_message   TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, video_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Seed schema version
INSERT OR IGNORE INTO settings (key, value) VALUES ('schema_version', '1');
