"""
User Memory API — additive module (v1).

Explicit, user-managed memory vault.  The user can add facts they want the AI
to remember and can "forget" (delete) them at any time.

Storage: local JSON file (user_memory.json) next to the DB.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import require_api_key
from .config import DATA_DIR, SQLITE_PATH

router = APIRouter(prefix="/v1/memory", tags=["memory"])

MEMORY_FILE = "user_memory.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_root() -> Path:
    if DATA_DIR:
        return Path(DATA_DIR)
    return Path(SQLITE_PATH).parent


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _read() -> Dict[str, Any]:
    path = _data_root() / MEMORY_FILE
    if not path.exists():
        return {"items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def _write(data: Dict[str, Any]) -> None:
    path = _data_root() / MEMORY_FILE
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MemoryItem(BaseModel):
    id: str = Field(..., min_length=6, max_length=64)
    text: str = Field(..., min_length=1, max_length=500)
    category: str = "general"  # general | likes | dislikes | relationship | work | health | other
    importance: int = 2        # 1..5
    last_confirmed_iso: str = ""
    source: str = "user"       # user | inferred
    pinned: bool = False


class MemoryUpsert(BaseModel):
    items: List[MemoryItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", dependencies=[Depends(require_api_key)])
def get_memory():
    return {"ok": True, "memory": _read()}


@router.put("", dependencies=[Depends(require_api_key)])
def put_memory(body: MemoryUpsert):
    ids = [x.id for x in body.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="Duplicate memory item id")
    data = {"items": [x.model_dump() for x in body.items]}
    _write(data)
    return {"ok": True}


@router.delete("/{item_id}", dependencies=[Depends(require_api_key)])
def delete_memory(item_id: str):
    data = _read()
    items = [x for x in data.get("items", []) if x.get("id") != item_id]
    data["items"] = items
    _write(data)
    return {"ok": True}
