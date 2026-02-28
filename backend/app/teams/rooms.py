# backend/app/teams/rooms.py
"""
JSON-file-based storage for meeting rooms (same pattern as projects.py).

Each room is a dict persisted in DATA_DIR/teams/<room_id>.json.
Uses the same canonical DATA_DIR as the rest of HomePilot (config.py).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("homepilot.teams.rooms")


def _resolve_data_dir() -> Path:
    """Resolve the teams data directory using the same logic as config.py.

    Priority:
      1. Import UPLOAD_DIR from config → parent is the canonical data root
      2. DATA_DIR env var
      3. /app/data (Docker) or backend/data (local)
    Always appends /teams to the resolved root.
    """
    # Try importing the canonical data root from config
    try:
        from ..config import UPLOAD_DIR
        return Path(UPLOAD_DIR).parent / "teams"
    except Exception:
        pass

    # Fallback: replicate config.py resolution
    data_dir_env = os.getenv("DATA_DIR", "").strip()
    if data_dir_env:
        return Path(data_dir_env) / "teams"

    # Docker detection
    if os.path.isfile("/.dockerenv") or os.environ.get("CONTAINER", "") == "1":
        return Path("/app/data/teams")

    # Local development
    backend_dir = Path(__file__).resolve().parent.parent.parent  # backend/
    return backend_dir / "data" / "teams"


_DATA_DIR = _resolve_data_dir()
_DOCS_DIR = _DATA_DIR / "docs"

_MAX_UPLOAD_BYTES = int(os.environ.get("HOMEPILOT_TEAMS_MAX_DOC_BYTES", str(10 * 1024 * 1024)))  # 10 MB
_PREVIEW_CHARS = int(os.environ.get("HOMEPILOT_TEAMS_DOC_PREVIEW_CHARS", "4000"))

# ── Auto-migration: move rooms from old location if needed ────────────────

_OLD_DIRS = [
    Path("data") / "teams",              # old HOMEPILOT_DATA_DIR default
    Path("data/teams"),                   # relative CWD variant
]


def _migrate_old_rooms() -> None:
    """One-time migration: copy room files from old data/ location to canonical path."""
    for old_dir in _OLD_DIRS:
        old_dir = old_dir.resolve()
        canonical = _DATA_DIR.resolve()
        if old_dir == canonical or not old_dir.is_dir():
            continue
        migrated = 0
        for f in old_dir.glob("*.json"):
            dest = canonical / f.name
            if not dest.exists():
                canonical.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(f), str(dest))
                migrated += 1
        if migrated:
            logger.info(
                "Migrated %d room(s) from %s → %s", migrated, old_dir, canonical,
            )


# Run migration on import (idempotent, fast no-op when nothing to move)
try:
    _migrate_old_rooms()
except Exception as exc:
    logger.debug("Room migration check skipped: %s", exc)


def _ensure_dir() -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR


def _room_path(room_id: str) -> Path:
    return _ensure_dir() / f"{room_id}.json"


def _read(room_id: str) -> Optional[Dict[str, Any]]:
    p = _room_path(room_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read room %s: %s", room_id, exc)
        return None


def _write(room: Dict[str, Any]) -> None:
    p = _room_path(room["id"])
    p.write_text(json.dumps(room, indent=2), encoding="utf-8")


# ── CRUD ──────────────────────────────────────────────────────────────────


def create_room(
    name: str,
    description: str = "",
    participant_ids: Optional[List[str]] = None,
    turn_mode: str = "round-robin",
    agenda: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new meeting room and return it."""
    room: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "participant_ids": participant_ids or [],
        "turn_mode": turn_mode,
        "agenda": agenda or [],
        "messages": [],
        "documents": [],
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "active",
    }
    _write(room)
    logger.info("Created room %s: %s (%d personas)", room["id"], name, len(room["participant_ids"]))
    return room


def get_room(room_id: str) -> Optional[Dict[str, Any]]:
    return _read(room_id)


def list_rooms() -> List[Dict[str, Any]]:
    """Return all rooms sorted by updated_at descending.

    Each room includes computed summary fields for the landing page:
      - message_count: total messages in transcript
      - last_activity: timestamp of most recent message (or updated_at)
      - participant_count: number of persona participants
    """
    rooms: List[Dict[str, Any]] = []
    d = _ensure_dir()
    for f in d.glob("*.json"):
        try:
            room = json.loads(f.read_text(encoding="utf-8"))
            # Inject computed summary fields
            msgs = room.get("messages") or []
            room["message_count"] = len(msgs)
            room["participant_count"] = len(room.get("participant_ids") or [])
            room["last_activity"] = (
                msgs[-1]["timestamp"] if msgs else room.get("updated_at", 0)
            )
            rooms.append(room)
        except Exception:
            pass
    rooms.sort(key=lambda r: r.get("last_activity", 0), reverse=True)
    return rooms


def update_room(room_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    room = _read(room_id)
    if not room:
        return None
    room.update(updates)
    room["updated_at"] = time.time()
    _write(room)
    return room


def add_participant(room_id: str, persona_id: str) -> Optional[Dict[str, Any]]:
    room = _read(room_id)
    if not room:
        return None
    if persona_id not in room["participant_ids"]:
        room["participant_ids"].append(persona_id)
        room["updated_at"] = time.time()
        _write(room)
    return room


def remove_participant(room_id: str, persona_id: str) -> Optional[Dict[str, Any]]:
    room = _read(room_id)
    if not room:
        return None
    if persona_id in room["participant_ids"]:
        room["participant_ids"].remove(persona_id)
        room["updated_at"] = time.time()
        _write(room)
    return room


def add_message(
    room_id: str,
    sender_id: str,
    sender_name: str,
    content: str,
    role: str = "user",
    tools_used: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Append a message to the room transcript."""
    room = _read(room_id)
    if not room:
        return None
    msg = {
        "id": str(uuid.uuid4()),
        "sender_id": sender_id,
        "sender_name": sender_name,
        "content": content,
        "role": role,
        "tools_used": tools_used or [],
        "timestamp": time.time(),
    }
    room.setdefault("messages", []).append(msg)
    room["updated_at"] = time.time()
    _write(room)
    return room


def delete_room(room_id: str) -> bool:
    p = _room_path(room_id)
    if p.exists():
        p.unlink()
        logger.info("Deleted room %s", room_id)
    # Clean up docs folder
    docs_dir = _DOCS_DIR / room_id
    if docs_dir.is_dir():
        shutil.rmtree(str(docs_dir), ignore_errors=True)
    return True


# ── Documents (Additive) ──────────────────────────────────────────────────


def _ensure_docs_dir(room_id: str) -> Path:
    p = _DOCS_DIR / room_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_filename(name: str) -> str:
    name = name.strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^a-zA-Z0-9.\-_() ]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] if name else "document"


def _infer_doc_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith((".md", ".markdown")):
        return "md"
    if lower.endswith(".txt"):
        return "txt"
    return "file"


def list_documents(room_id: str) -> Optional[List[Dict[str, Any]]]:
    room = _read(room_id)
    if not room:
        return None
    return room.get("documents") or []


def get_document(room_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    room = _read(room_id)
    if not room:
        return None
    for d in room.get("documents") or []:
        if d.get("id") == doc_id:
            return d
    return None


def add_document_upload(
    room_id: str,
    filename: str,
    content_bytes: bytes,
    uploaded_by: str = "You",
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Upload a file and attach it to a room. Returns (room, doc)."""
    room = _read(room_id)
    if not room:
        return None
    if len(content_bytes) > _MAX_UPLOAD_BYTES:
        raise ValueError(f"File too large (max {_MAX_UPLOAD_BYTES} bytes)")

    safe = _safe_filename(filename)
    doc_id = str(uuid.uuid4())
    doc_type = _infer_doc_type(safe)

    docs_dir = _ensure_docs_dir(room_id)
    stored_name = f"{doc_id}__{safe}"
    (docs_dir / stored_name).write_bytes(content_bytes)

    doc: Dict[str, Any] = {
        "id": doc_id,
        "name": safe,
        "type": doc_type,
        "kind": "file",
        "uploaded_by": uploaded_by,
        "size_bytes": len(content_bytes),
        "stored_filename": stored_name,
        "created_at": time.time(),
    }
    room.setdefault("documents", []).append(doc)
    room["updated_at"] = time.time()
    _write(room)
    return room, doc


def add_document_url(
    room_id: str,
    url: str,
    title: str = "",
    uploaded_by: str = "You",
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Attach a URL reference to a room. Returns (room, doc)."""
    room = _read(room_id)
    if not room:
        return None
    doc_id = str(uuid.uuid4())
    doc: Dict[str, Any] = {
        "id": doc_id,
        "name": title.strip() or url.strip(),
        "type": "url",
        "kind": "url",
        "url": url.strip(),
        "uploaded_by": uploaded_by,
        "created_at": time.time(),
    }
    room.setdefault("documents", []).append(doc)
    room["updated_at"] = time.time()
    _write(room)
    return room, doc


def delete_document(room_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    room = _read(room_id)
    if not room:
        return None
    docs = room.get("documents") or []
    keep: List[Dict[str, Any]] = []
    removed: Optional[Dict[str, Any]] = None
    for d in docs:
        if d.get("id") == doc_id:
            removed = d
        else:
            keep.append(d)
    if not removed:
        return room
    # Delete backing file
    if removed.get("kind") == "file" and removed.get("stored_filename"):
        p = _DOCS_DIR / room_id / removed["stored_filename"]
        if p.exists():
            p.unlink(missing_ok=True)
    room["documents"] = keep
    room["updated_at"] = time.time()
    _write(room)
    return room


def get_document_file_path(room_id: str, doc_id: str) -> Optional[Path]:
    d = get_document(room_id, doc_id)
    if not d or d.get("kind") != "file":
        return None
    stored = d.get("stored_filename")
    if not stored:
        return None
    p = _DOCS_DIR / room_id / stored
    return p if p.exists() else None


def get_document_preview(room_id: str, doc_id: str) -> Optional[str]:
    d = get_document(room_id, doc_id)
    if not d:
        return None
    if d.get("kind") == "url":
        return d.get("url") or ""
    if d.get("kind") == "file":
        doc_type = d.get("type")
        if doc_type not in ("txt", "md"):
            return f"[{(doc_type or 'file').upper()} uploaded — preview not available for this format]"
        p = get_document_file_path(room_id, doc_id)
        if not p:
            return None
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            if len(text) > _PREVIEW_CHARS:
                return text[:_PREVIEW_CHARS] + "\n\n...(truncated)..."
            return text
        except Exception:
            return "[Unable to read preview]"
    return ""
