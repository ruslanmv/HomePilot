"""
Project File Manager — reusable across all project types (persona, agent, chat).

Provides a DB-backed items/files system with metadata, categories, tags,
and asset linking.  Designed to be imported by main.py routes and by any
module that needs to attach files or items to a project.

Tables:
  project_items — semantic items (documents, photos, inventory, etc.)
                  each item can link to a file_assets row via asset_id.

All heavy file I/O is delegated to files.py (upload, storage, serving).
This module only manages the metadata layer on top.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .storage import _get_db_path


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def ensure_project_items_table() -> None:
    """Create the project_items table if it doesn't exist (idempotent)."""
    con = sqlite3.connect(_get_db_path())
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_items(
            id            TEXT PRIMARY KEY,
            project_id    TEXT NOT NULL,
            user_id       TEXT NOT NULL DEFAULT '',
            name          TEXT NOT NULL,
            description   TEXT DEFAULT '',
            category      TEXT DEFAULT 'file',
            item_type     TEXT DEFAULT 'document',
            tags          TEXT DEFAULT '[]',
            properties    TEXT DEFAULT '{}',
            asset_id      TEXT DEFAULT '',
            file_url      TEXT DEFAULT '',
            mime          TEXT DEFAULT '',
            size_bytes    INTEGER DEFAULT 0,
            original_name TEXT DEFAULT '',
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_project_items_project "
        "ON project_items(project_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_project_items_category "
        "ON project_items(project_id, category)"
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    # Deserialize JSON fields
    for field in ("tags", "properties"):
        val = d.get(field)
        if isinstance(val, str):
            try:
                d[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                d[field] = [] if field == "tags" else {}
    return d


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_item(
    project_id: str,
    name: str,
    *,
    user_id: str = "",
    description: str = "",
    category: str = "file",
    item_type: str = "document",
    tags: Optional[List[str]] = None,
    properties: Optional[Dict[str, Any]] = None,
    asset_id: str = "",
    file_url: str = "",
    mime: str = "",
    size_bytes: int = 0,
    original_name: str = "",
) -> Dict[str, Any]:
    """Insert a new item. Returns the created item dict."""
    ensure_project_items_table()
    item_id = f"item_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc).isoformat()
    con = _db()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO project_items(
            id, project_id, user_id, name, description,
            category, item_type, tags, properties,
            asset_id, file_url, mime, size_bytes, original_name,
            created_at, updated_at
        ) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?)
        """,
        (
            item_id, project_id, user_id, name, description,
            category, item_type,
            json.dumps(tags or []),
            json.dumps(properties or {}),
            asset_id, file_url, mime, int(size_bytes), original_name,
            now, now,
        ),
    )
    con.commit()
    # Fetch back
    cur.execute("SELECT * FROM project_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    con.close()
    return _row_to_dict(row) if row else {"id": item_id}


def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    """Return a single item by id, or None."""
    ensure_project_items_table()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM project_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def list_items(
    project_id: str,
    *,
    category: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List items for a project, optionally filtered by category."""
    ensure_project_items_table()
    con = _db()
    cur = con.cursor()
    if category:
        cur.execute(
            "SELECT * FROM project_items WHERE project_id = ? AND category = ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (project_id, category, limit, offset),
        )
    else:
        cur.execute(
            "SELECT * FROM project_items WHERE project_id = ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (project_id, limit, offset),
        )
    rows = cur.fetchall()
    con.close()
    return [_row_to_dict(r) for r in rows]


def update_item(item_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Update allowed fields on an item. Returns the updated item or None.
    """
    ensure_project_items_table()
    allowed = {
        "name", "description", "category", "item_type",
        "tags", "properties", "asset_id", "file_url",
        "mime", "size_bytes", "original_name",
    }
    parts = []
    vals: list = []
    for k, v in updates.items():
        if k not in allowed:
            continue
        if k in ("tags", "properties") and not isinstance(v, str):
            v = json.dumps(v)
        parts.append(f"{k} = ?")
        vals.append(v)

    if not parts:
        return get_item(item_id)

    parts.append("updated_at = ?")
    vals.append(datetime.now(timezone.utc).isoformat())
    vals.append(item_id)

    con = _db()
    cur = con.cursor()
    cur.execute(
        f"UPDATE project_items SET {', '.join(parts)} WHERE id = ?",
        vals,
    )
    con.commit()
    cur.execute("SELECT * FROM project_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def delete_item(item_id: str) -> bool:
    """Delete an item. Returns True if a row was removed."""
    ensure_project_items_table()
    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM project_items WHERE id = ?", (item_id,))
    removed = cur.rowcount > 0
    con.commit()
    con.close()
    return removed


def delete_project_items(project_id: str) -> int:
    """Delete all items for a project. Returns count removed."""
    ensure_project_items_table()
    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM project_items WHERE project_id = ?", (project_id,))
    count = cur.rowcount
    con.commit()
    con.close()
    return count


# ---------------------------------------------------------------------------
# Context builder — inject item catalog into LLM system prompt
# ---------------------------------------------------------------------------

def build_item_context(project_id: str) -> str:
    """
    Build a text block describing the project's items for injection into
    the LLM system prompt.  Returns empty string if no items.
    """
    items = list_items(project_id)
    if not items:
        return ""

    lines = ["## Project Files & Items"]
    for it in items:
        cat = it.get("category", "file")
        name = it.get("name", "Untitled")
        desc = it.get("description", "")
        tags = it.get("tags") or []
        tag_str = f"  Tags: {', '.join(tags)}" if tags else ""
        desc_str = f" — {desc}" if desc else ""
        lines.append(f"- [{cat}] **{name}**{desc_str}{tag_str}")

    return "\n".join(lines)
