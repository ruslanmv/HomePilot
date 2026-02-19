"""MCP server: local-notes — persistent human-readable memory for personas.

Tools:
  notes.search(query, limit=20)
  notes.read(note_id)
  notes.create(title, content, tags=[])       [write-gated]
  notes.append(note_id, content)               [write-gated]
  notes.update(note_id, content)               [write-gated]
  notes.delete(note_id)                        [write-gated]
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# In-memory store (placeholder — production would use sqlite or filesystem)
_NOTES: Dict[str, Dict[str, Any]] = {}


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _write_gate(action: str) -> Json | None:
    """Return an error response if writes are disabled."""
    if not WRITE_ENABLED:
        msg = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
        if DRY_RUN:
            msg += " (DRY_RUN mode — no changes made)"
        return _text(msg)
    return None


async def notes_search(args: Json) -> Json:
    query = str(args.get("query", "")).strip().lower()
    limit = max(1, min(int(args.get("limit", 20) or 20), 100))
    if not query:
        return _text("Please provide a non-empty 'query'.")

    matches = []
    for nid, note in _NOTES.items():
        if query in note["title"].lower() or query in note["content"].lower() or any(query in t.lower() for t in note.get("tags", [])):
            matches.append({"note_id": nid, "title": note["title"], "tags": note.get("tags", []), "snippet": note["content"][:120]})
        if len(matches) >= limit:
            break

    if not matches:
        return _text(f"No notes found for '{query}'. (store has {len(_NOTES)} notes)")
    return {"results": matches, "total": len(matches)}


async def notes_read(args: Json) -> Json:
    note_id = str(args.get("note_id", "")).strip()
    if not note_id:
        return _text("Please provide a 'note_id'.")
    note = _NOTES.get(note_id)
    if not note:
        return _text(f"Note '{note_id}' not found.")
    return {"note_id": note_id, **note}


async def notes_create(args: Json) -> Json:
    gate = _write_gate("notes.create")
    if gate:
        return gate
    title = str(args.get("title", "")).strip()
    content = str(args.get("content", "")).strip()
    tags = args.get("tags") or []
    if not title:
        return _text("Please provide a 'title'.")
    note_id = f"note-{uuid.uuid4().hex[:8]}"
    _NOTES[note_id] = {"title": title, "content": content, "tags": tags, "created_at": time.time(), "updated_at": time.time()}
    return _text(f"Created note '{note_id}': {title}")


async def notes_append(args: Json) -> Json:
    gate = _write_gate("notes.append")
    if gate:
        return gate
    note_id = str(args.get("note_id", "")).strip()
    content = str(args.get("content", "")).strip()
    if not note_id or not content:
        return _text("Please provide 'note_id' and 'content'.")
    note = _NOTES.get(note_id)
    if not note:
        return _text(f"Note '{note_id}' not found.")
    note["content"] += "\n" + content
    note["updated_at"] = time.time()
    return _text(f"Appended to note '{note_id}'.")


async def notes_update(args: Json) -> Json:
    gate = _write_gate("notes.update")
    if gate:
        return gate
    note_id = str(args.get("note_id", "")).strip()
    content = str(args.get("content", "")).strip()
    if not note_id or not content:
        return _text("Please provide 'note_id' and 'content'.")
    note = _NOTES.get(note_id)
    if not note:
        return _text(f"Note '{note_id}' not found.")
    note["content"] = content
    note["updated_at"] = time.time()
    return _text(f"Updated note '{note_id}'.")


async def notes_delete(args: Json) -> Json:
    gate = _write_gate("notes.delete")
    if gate:
        return gate
    note_id = str(args.get("note_id", "")).strip()
    if not note_id:
        return _text("Please provide a 'note_id'.")
    if note_id not in _NOTES:
        return _text(f"Note '{note_id}' not found.")
    del _NOTES[note_id]
    return _text(f"Deleted note '{note_id}'.")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.notes.search",
        description="Search notes by query across titles, content, and tags.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
        handler=notes_search,
    ),
    ToolDef(
        name="hp.notes.read",
        description="Read a note by its ID.",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note ID"},
            },
            "required": ["note_id"],
        },
        handler=notes_read,
    ),
    ToolDef(
        name="hp.notes.create",
        description="Create a new note with title, content, and optional tags. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["title", "content"],
        },
        handler=notes_create,
    ),
    ToolDef(
        name="hp.notes.append",
        description="Append content to an existing note. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["note_id", "content"],
        },
        handler=notes_append,
    ),
    ToolDef(
        name="hp.notes.update",
        description="Replace the content of an existing note. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["note_id", "content"],
        },
        handler=notes_update,
    ),
    ToolDef(
        name="hp.notes.delete",
        description="Delete a note by ID. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
            },
            "required": ["note_id"],
        },
        handler=notes_delete,
    ),
]

app = create_mcp_app(server_name="homepilot-local-notes", tools=TOOLS)
