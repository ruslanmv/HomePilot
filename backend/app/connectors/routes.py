"""Settings → Connectors: list, link and unlink accounts; Models: list a connector's models."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import CATALOG, catalog_entry, huggingface, store
from .context import current_user_id

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


def _user() -> str:
    uid = current_user_id()
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in first")
    return uid


class LinkIn(BaseModel):
    token: str = Field(..., min_length=8, max_length=4096)


@router.get("")
def list_connectors(user_id: str = Depends(_user)) -> Dict[str, Any]:
    """Every available connector, with this user's linked account if any (never its secret)."""
    linked = {c["id"]: c for c in store.linked(user_id)}
    return {
        "ok": True,
        "connectors": [
            {**c, "connected": c["id"] in linked, "account": (linked.get(c["id"]) or {}).get("account", "")}
            for c in CATALOG
        ],
    }


@router.post("/{connector_id}")
async def link(connector_id: str, body: LinkIn, user_id: str = Depends(_user)) -> Dict[str, Any]:
    if connector_id != huggingface.ID or not catalog_entry(connector_id):
        raise HTTPException(status_code=404, detail="Unknown connector")
    secret = body.token.strip()
    try:
        info = await huggingface.whoami(secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    account = str(info.get("name") or info.get("fullname") or "")
    store.save(user_id, connector_id, secret, account=account, meta={"type": info.get("type") or "user"})
    return {"ok": True, "id": connector_id, "connected": True, "account": account}


@router.delete("/{connector_id}")
def unlink(connector_id: str, user_id: str = Depends(_user)) -> Dict[str, Any]:
    store.remove(user_id, connector_id)
    return {"ok": True, "id": connector_id, "connected": False}


@router.get("/huggingface/models")
async def hf_models(
    model_type: str = Query("chat", alias="type", description="chat | multimodal | image | video"),
    user_id: Optional[str] = Depends(_user),
) -> Dict[str, Any]:
    try:
        listed = await huggingface.models(model_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — the Hub unreachable
        raise HTTPException(status_code=502, detail=f"Could not list Hugging Face models ({type(exc).__name__}).") from exc
    return {"ok": True, "type": model_type, "connected": bool(huggingface.token(user_id)), "models": listed}
