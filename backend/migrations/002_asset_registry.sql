-- 002_asset_registry.sql
-- Durable Asset Registry: ensures generated media is never lost.
-- Assets are the source of truth; feature tables (avatars, imagine, animate)
-- reference assets by ID. If the DB resets, reconcile rebuilds from disk.

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,                           -- uuid
    kind TEXT NOT NULL DEFAULT 'image',             -- 'image', 'video', 'mask', 'thumbnail'
    mime TEXT DEFAULT '',
    storage_backend TEXT NOT NULL DEFAULT 'local',  -- 'local' (future: 's3')
    storage_key TEXT NOT NULL,                      -- relative path inside UPLOAD_DIR
    size_bytes INTEGER DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    sha256 TEXT DEFAULT '',                         -- content hash for dedup
    origin TEXT NOT NULL DEFAULT 'unknown',         -- 'comfy', 'upload', 'editor', 'import', 'reconcile'
    source_hint TEXT DEFAULT '',                    -- e.g. comfy filename, URL, workflow name
    feature TEXT DEFAULT '',                        -- 'avatar', 'imagine', 'animate', 'outfit', 'chat', ''
    project_id TEXT DEFAULT '',                     -- associated project (if any)
    user_id TEXT DEFAULT '',                        -- owning user
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(storage_backend, storage_key)
);

CREATE INDEX IF NOT EXISTS idx_assets_sha256 ON assets(sha256);
CREATE INDEX IF NOT EXISTS idx_assets_feature ON assets(feature);
CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id);
CREATE INDEX IF NOT EXISTS idx_assets_user ON assets(user_id);
CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
CREATE INDEX IF NOT EXISTS idx_assets_last_seen ON assets(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_assets_origin ON assets(origin);
