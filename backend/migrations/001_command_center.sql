-- Migration 001: Command Center - Projects and Conversations
-- Adds support for project-scoped context and conversation management

-- Projects table: Stores user projects with metadata
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived INTEGER DEFAULT 0  -- 0 = active, 1 = archived
);

-- Conversations table: Links conversations to projects (optional)
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT,  -- NULL means no project association (ephemeral chat)
    mode TEXT NOT NULL DEFAULT 'chat',  -- chat, voice, search, project, imagine, edit, animate
    title TEXT,  -- Auto-generated from first message
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived INTEGER DEFAULT 0,  -- 0 = active, 1 = archived
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);

-- Index for fast project lookups
CREATE INDEX IF NOT EXISTS idx_conversations_project_id ON conversations(project_id);

-- Index for filtering by mode
CREATE INDEX IF NOT EXISTS idx_conversations_mode ON conversations(mode);

-- Index for filtering by archived status
CREATE INDEX IF NOT EXISTS idx_conversations_archived ON conversations(archived);
CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects(archived);

-- Default project (for demonstration)
INSERT OR IGNORE INTO projects (id, name, description)
VALUES ('default', 'Default Project', 'Default project for general conversations');
