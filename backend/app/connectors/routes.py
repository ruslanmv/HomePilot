"""Settings → Connectors: list, link and unlink accounts; Models: list a connector's models."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import CATALOG, catalog_entry, huggingface, oauth, store
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
    return {"ok": True, "connectors": [_public(c, linked.get(c["id"])) for c in CATALOG]}


def _public(entry: Dict[str, Any], row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A catalog entry plus what this user may see of their link: account, avatar, how it was
    linked, whether it expired. Never the secret."""
    meta = (row or {}).get("meta") or {}
    out = {
        **entry,
        "oauth": entry["id"] == huggingface.ID and oauth.enabled(),
        "manage_url": oauth.MANAGE_URL if entry["id"] == huggingface.ID else "",
        "connected": bool(row) and not row.get("expired"),
        "expired": bool(row and row.get("expired")),
        "account": (row or {}).get("account", ""),
        "avatar": meta.get("avatar", ""),
        "via": meta.get("via", "token") if row else "",
        "connected_at": (row or {}).get("connected_at"),
    }
    return out


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


@router.post("/huggingface/oauth/start")
def hf_oauth_start(request: Request, user_id: str = Depends(_user)) -> Dict[str, Any]:
    """A one-use "Sign in with Hugging Face" URL for this user, to open in a new window."""
    if not oauth.enabled():
        raise HTTPException(status_code=404, detail="Sign in with Hugging Face is not set up on this server.")
    origin = (request.headers.get("origin") or "").strip()
    return {"ok": True, "url": oauth.start(user_id, str(request.base_url), origin=origin)}


@router.get("/huggingface/oauth/callback", response_class=HTMLResponse)
async def hf_oauth_callback(code: str = "", state: str = "", error: str = "",
                            error_description: str = "") -> HTMLResponse:
    """Where Hugging Face sends the sign-in window back. Links the account, then closes."""
    pending = oauth.take(state)
    origin = (pending or {}).get("origin", "")
    if error:
        reason = "You cancelled the sign-in." if error == "access_denied" else (error_description or error)
        return HTMLResponse(oauth.finish_page(False, error=reason, origin=origin))
    if not pending:
        return HTMLResponse(oauth.finish_page(False, error="This sign-in link expired. Please try again."), status_code=400)
    try:
        got = await oauth.exchange(code, pending)
    except ValueError as exc:
        return HTMLResponse(oauth.finish_page(False, error=str(exc), origin=origin), status_code=400)
    except Exception as exc:  # noqa: BLE001 — Hugging Face unreachable
        return HTMLResponse(oauth.finish_page(False, error=f"Could not reach Hugging Face ({type(exc).__name__}).",
                                              origin=origin), status_code=502)
    store.save(pending["user_id"], huggingface.ID, got["token"], account=got["account"], meta=got["meta"])
    return HTMLResponse(oauth.finish_page(True, account=got["account"], origin=origin))


@router.delete("/{connector_id}")
def unlink(connector_id: str, user_id: str = Depends(_user)) -> Dict[str, Any]:
    store.remove(user_id, connector_id)
    return {"ok": True, "id": connector_id, "connected": False}


@router.get("/huggingface/models")
async def hf_models(
    model_type: str = Query("chat", alias="type", description="chat | multimodal | image | video"),
    sort: str = Query("popular", description="popular | likes | trending | newest | rising"),
    user_id: Optional[str] = Depends(_user),
) -> Dict[str, Any]:
    """Models Inference Providers serve live for a type, ranked (FitLab's inference lane):
    ``popular`` weighs likes, downloads, trend and freshness; ``likes`` is ranked by the people."""
    try:
        listed, source = await huggingface.ranked(model_type, sort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — the Hub unreachable
        raise HTTPException(status_code=502, detail=f"Could not list Hugging Face models ({type(exc).__name__}).") from exc
    return {"ok": True, "type": model_type, "sort": sort, "orders": list(huggingface.ORDERS),
            "source": source, "connected": bool(huggingface.token(user_id)), "models": listed,
            "note": "Ranked by popularity on Hugging Face. Popular is not always best for your task."}
