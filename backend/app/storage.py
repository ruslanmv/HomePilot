from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from .config import SQLITE_PATH

_RESOLVED_DB_PATH = None

def _get_db_path() -> str:
    global _RESOLVED_DB_PATH
    if _RESOLVED_DB_PATH:
        return _RESOLVED_DB_PATH

    candidate = SQLITE_PATH
    directory = os.path.dirname(candidate) or "."

    try:
        os.makedirs(directory, exist_ok=True)
        test_file = os.path.join(directory, f".perm_check_{os.getpid()}")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        _RESOLVED_DB_PATH = candidate
        return candidate
    except (OSError, PermissionError):
        fallback_dir = Path(__file__).resolve().parents[1] / "data"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = str(fallback_dir / "db.sqlite")
        print(f"WARNING: Permission denied for '{SQLITE_PATH}'. Using local fallback: {fallback_path}")
        _RESOLVED_DB_PATH = fallback_path
        return fallback_path


def init_db():
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            role TEXT,
            content TEXT,
            media TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Add media column to existing tables (migration)
    try:
        cur.execute("ALTER TABLE messages ADD COLUMN media TEXT")
        con.commit()
    except sqlite3.OperationalError:
        # Column already exists
        pass
    # Add project_id column to existing tables (migration)
    try:
        cur.execute("ALTER TABLE messages ADD COLUMN project_id TEXT")
        con.commit()
    except sqlite3.OperationalError:
        # Column already exists
        pass

    # -----------------------------------------------------------------------
    # Companion-grade persona tables (additive — zero changes to existing)
    # -----------------------------------------------------------------------

    # Sessions: threads within a persona project (voice or text)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_sessions(
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL UNIQUE,
            mode TEXT DEFAULT 'text',
            title TEXT,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            ended_at DATETIME,
            message_count INTEGER DEFAULT 0,
            summary TEXT,
            UNIQUE(conversation_id)
        )
        """
    )
    # Indexes for fast session lookups
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_project ON persona_sessions(project_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_active ON persona_sessions(project_id, ended_at)"
    )

    # Long-term memory: persistent per-persona facts that survive across sessions
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_memory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            source_session TEXT,
            source_type TEXT DEFAULT 'inferred',
            visibility TEXT DEFAULT 'private',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, category, key)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_project ON persona_memory(project_id)"
    )

    # Additive: extend persona_memory schema for Memory V2 (safe ALTER TABLEs)
    from .memory_v2 import ensure_v2_columns
    ensure_v2_columns()

    # Additive: extend persona_memory schema for V1 hardening (is_pinned, expires_at)
    from .ltm_v1_maintenance import ensure_v1_hardening_columns
    ensure_v1_hardening_columns()

    # Durable async jobs: survives restarts, processes lazily
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            session_id TEXT,
            job_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            payload TEXT,
            result TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_pending ON persona_jobs(status, created_at)"
    )

    # Additive: Multi-user accounts tables
    from .users import ensure_users_tables
    ensure_users_tables()

    con.commit()
    con.close()


def add_message(conversation_id: str, role: str, content: str, media: Optional[Dict[str, Any]] = None, project_id: Optional[str] = None):
    """
    Add a message to the database with optional media attachments.

    Args:
        conversation_id: Unique conversation identifier
        role: Message role (user/assistant)
        content: Message text content
        media: Optional dict containing images/videos, e.g.:
               {"images": ["url1", "url2"], "video_url": "url"}
        project_id: Optional project ID this conversation belongs to
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    # Serialize media to JSON if provided
    media_json = json.dumps(media) if media else None

    cur.execute(
        "INSERT INTO messages(conversation_id, role, content, media, project_id) VALUES (?,?,?,?,?)",
        (conversation_id, role, content, media_json, project_id),
    )
    con.commit()
    con.close()


def get_recent(conversation_id: str, limit: int = 24) -> List[Tuple[str, str]]:
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT role, content FROM messages
        WHERE conversation_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (conversation_id, limit),
    )
    rows = cur.fetchall()
    con.close()
    return list(reversed(rows))


def list_conversations(limit: int = 50, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns most recent conversations, with last message preview.
    If project_id is given, only returns conversations belonging to that project.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    if project_id:
        cur.execute(
            """
            SELECT m.conversation_id,
                   MAX(m.id) as max_id
            FROM messages m
            WHERE m.project_id = ?
            GROUP BY m.conversation_id
            ORDER BY max_id DESC
            LIMIT ?
            """,
            (project_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT m.conversation_id,
                   MAX(m.id) as max_id
            FROM messages m
            GROUP BY m.conversation_id
            ORDER BY max_id DESC
            LIMIT ?
            """,
            (limit,),
        )
    convs = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for conversation_id, max_id in convs:
        cur.execute(
            "SELECT role, content, created_at FROM messages WHERE id=?",
            (max_id,),
        )
        row = cur.fetchone()
        if row:
            role, content, created_at = row
            out.append(
                {
                    "conversation_id": conversation_id,
                    "last_role": role,
                    "last_content": content,
                    "updated_at": created_at,
                }
            )
    con.close()
    return out


def get_messages(conversation_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Retrieve messages for a conversation, including media attachments.

    Returns:
        List of dicts with keys: role, content, created_at, media
        media is None or a dict like {"images": [...], "video_url": "..."}
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT role, content, created_at, media
        FROM messages
        WHERE conversation_id=?
        ORDER BY id ASC
        LIMIT ?
        """,
        (conversation_id, limit),
    )
    rows = cur.fetchall()
    con.close()

    result = []
    for row in rows:
        r, c, t, media_json = row
        # Deserialize media from JSON
        media = None
        if media_json:
            try:
                media = json.loads(media_json)
            except (json.JSONDecodeError, TypeError):
                media = None

        result.append({
            "role": r,
            "content": c,
            "created_at": t,
            "media": media
        })

    return result


def delete_image_url(image_url: str) -> int:
    """
    Delete a specific image URL from all messages in the database.

    Args:
        image_url: The image URL to remove

    Returns:
        Number of messages updated
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    # Get all messages with media
    cur.execute("SELECT id, media FROM messages WHERE media IS NOT NULL")
    rows = cur.fetchall()

    updated_count = 0
    for msg_id, media_json in rows:
        if not media_json:
            continue

        try:
            media = json.loads(media_json)
            if not isinstance(media, dict):
                continue

            images = media.get("images", [])
            if not isinstance(images, list):
                continue

            # Remove the image URL if it exists
            if image_url in images:
                images.remove(image_url)

                # Update or clear media field
                if images or media.get("video_url"):
                    # Still have media, update with filtered list
                    media["images"] = images
                    new_media_json = json.dumps(media)
                    cur.execute("UPDATE messages SET media = ? WHERE id = ?", (new_media_json, msg_id))
                else:
                    # No media left, clear field
                    cur.execute("UPDATE messages SET media = NULL WHERE id = ?", (msg_id,))

                updated_count += 1

        except (json.JSONDecodeError, TypeError):
            continue

    con.commit()
    con.close()
    return updated_count


def delete_conversation(conversation_id: str) -> int:
    """
    Delete all messages from a specific conversation.

    Args:
        conversation_id: The conversation ID to delete

    Returns:
        Number of messages deleted
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    # Count messages before deletion
    cur.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,))
    count = cur.fetchone()[0]

    # Delete all messages for this conversation
    cur.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))

    con.commit()
    con.close()
    return count
