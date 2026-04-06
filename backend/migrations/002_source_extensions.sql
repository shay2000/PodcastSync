-- Migration 002: per-source custom storage path and channel icon URL

ALTER TABLE sources ADD COLUMN custom_storage_path TEXT;
ALTER TABLE sources ADD COLUMN icon_url TEXT;

-- Update schema version
INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', '2');
