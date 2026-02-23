"""
Persona Attachments — lightweight mapping from a persona project to project_items.

Enterprise pattern:
  - store files once (file_assets)
  - represent them as inventory items (project_items)
  - attach/detach to personas with policy (persona_attachments)

Modes:
  - indexed  -> included in RAG retrieval
  - pinned   -> included + always top-weighted in retrieval
  - excluded -> explicitly excluded from retrieval
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .storage import _get_db_path
from .project_files import ensure_project_items_table, get_item


ALLOWED_MODES = {"indexed", "pinned", "excluded"}


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def ensure_persona_attachments_table() -> None:
    """Create the persona_attachments table if it doesn't exist (idempotent)."""
    con = _db()
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_attachments(
            id         TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            item_id    TEXT NOT NULL,
            mode       TEXT NOT NULL DEFAULT 'indexed',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_persona_attach_unique "
        "ON persona_attachments(project_id, item_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_persona_attach_project "
        "ON persona_attachments(project_id)"
    )
    con.commit()
    con.close()


def attach_item_to_persona(
    project_id: str,
    item_id: str,
    mode: str = "indexed",
) -> Dict[str, Any]:
    """
    Attach a project_item to the persona with a mode.
    Idempotent: if already attached, updates mode.
    """
    ensure_project_items_table()
    ensure_persona_attachments_table()

    mode = (mode or "indexed").strip().lower()
    if mode not in ALLOWED_MODES:
        mode = "indexed"

    it = get_item(item_id)
    if not it or it.get("project_id") != project_id:
        raise ValueError("Item not found in this project")

    attach_id = f"pa_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc).isoformat()

    con = _db()
    cur = con.cursor()

    # Upsert by unique (project_id, item_id)
    cur.execute(
        "SELECT id FROM persona_attachments WHERE project_id = ? AND item_id = ?",
        (project_id, item_id),
    )
    row = cur.fetchone()

    if row:
        cur.execute(
            "UPDATE persona_attachments SET mode = ?, updated_at = ? "
            "WHERE project_id = ? AND item_id = ?",
            (mode, now, project_id, item_id),
        )
        attach_id = str(row["id"])
    else:
        cur.execute(
            "INSERT INTO persona_attachments(id, project_id, item_id, mode, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (attach_id, project_id, item_id, mode, now, now),
        )

    con.commit()
    con.close()

    return {
        "id": attach_id,
        "project_id": project_id,
        "item_id": item_id,
        "mode": mode,
        "updated_at": now,
    }


def detach_item_from_persona(project_id: str, item_id: str) -> bool:
    """Detach an item from a persona (does NOT delete the file)."""
    ensure_persona_attachments_table()
    con = _db()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM persona_attachments WHERE project_id = ? AND item_id = ?",
        (project_id, item_id),
    )
    removed = cur.rowcount > 0
    con.commit()
    con.close()
    return removed


def set_attachment_mode(
    project_id: str, item_id: str, mode: str
) -> Optional[Dict[str, Any]]:
    """Update mode on an existing attachment."""
    ensure_persona_attachments_table()
    mode = (mode or "").strip().lower()
    if mode not in ALLOWED_MODES:
        raise ValueError(f"Invalid mode. Allowed: {sorted(ALLOWED_MODES)}")

    now = datetime.now(timezone.utc).isoformat()

    con = _db()
    cur = con.cursor()
    cur.execute(
        "UPDATE persona_attachments SET mode = ?, updated_at = ? "
        "WHERE project_id = ? AND item_id = ?",
        (mode, now, project_id, item_id),
    )
    con.commit()

    cur.execute(
        "SELECT * FROM persona_attachments WHERE project_id = ? AND item_id = ?",
        (project_id, item_id),
    )
    row = cur.fetchone()
    con.close()

    return dict(row) if row else None


def list_persona_attachments(project_id: str) -> List[Dict[str, Any]]:
    """Returns attachment rows only (no item data joined)."""
    ensure_persona_attachments_table()
    con = _db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM persona_attachments WHERE project_id = ? ORDER BY updated_at DESC",
        (project_id,),
    )
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_persona_documents(project_id: str) -> List[Dict[str, Any]]:
    """
    Returns attached items joined with project_items so UI can show:
    - name, mime, size, properties.index_status, etc.

    Defensively deduplicates by asset_id (preferred), then by
    (original_name, size_bytes) so the same physical file never
    appears more than once — even if multiple project_items rows
    or attachment rows reference it.
    """
    ensure_project_items_table()
    ensure_persona_attachments_table()

    con = _db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT
            pa.id as attachment_id,
            pa.mode as mode,
            pa.updated_at as attachment_updated_at,
            pi.*
        FROM persona_attachments pa
        JOIN project_items pi ON pi.id = pa.item_id
        WHERE pa.project_id = ?
        ORDER BY pa.updated_at DESC
        """,
        (project_id,),
    )
    rows = cur.fetchall()
    con.close()

    out: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for r in rows:
        d = dict(r)
        for field in ("tags", "properties"):
            if isinstance(d.get(field), str):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    d[field] = [] if field == "tags" else {}

        # Deduplicate: prefer asset_id, fall back to (name, size)
        asset_id = d.get("asset_id") or ""
        if asset_id:
            dedup_key = f"asset:{asset_id}"
        else:
            name = d.get("original_name") or d.get("name") or ""
            size = d.get("size_bytes") or 0
            dedup_key = f"file:{name}:{size}"

        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        out.append(d)
    return out


def get_allowed_document_item_ids_for_chat(project_id: str) -> List[str]:
    """
    Returns only item_ids that should be used for RAG retrieval in chat.
    - indexed + pinned included
    - excluded removed
    """
    ensure_persona_attachments_table()
    con = _db()
    cur = con.cursor()
    cur.execute(
        "SELECT item_id, mode FROM persona_attachments WHERE project_id = ?",
        (project_id,),
    )
    rows = cur.fetchall()
    con.close()

    allowed: List[str] = []
    for r in rows:
        mode = str(r["mode"] or "indexed").lower()
        item_id = str(r["item_id"])
        if mode in ("indexed", "pinned"):
            allowed.append(item_id)
    return allowed
