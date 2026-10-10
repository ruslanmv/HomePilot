"""
Model Advisor routes — FitLab suggestions for the machine HomePilot runs on.

  GET  /v1/model-advisor          suggestions from the cached or bundled FitLab data; no network
  POST /v1/model-advisor/fetch    "Fetch definitions" (and the UI's optional daily check): one
                                  conditional fetch of each FitLab feed, falling back to the
                                  cached or bundled copy when offline

Both accept ``current_<kind>`` — the model the user has selected for chat, vision, image or
video — and then report an upgrade when FitLab ranks another model clearly higher for this
machine. That comparison only uses models FitLab ranks; an unknown model is never "upgraded".

Optional and additive: FITLAB_ENABLED=false turns both off (the UI then hides the card);
FITLAB_OFFLINE=true keeps the card on the bundled/cached data and never makes a request.
Nothing here installs, downloads or changes a setting — the card's Install button uses the
existing POST /models/install, and only when the user presses it.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import require_api_key
from . import feed, hardware, ranking

router = APIRouter(prefix="/v1/model-advisor", tags=["model-advisor"])

ATTRIBUTION = "Model data: FitLab (github.com/ruslanmv/fitlab), CC BY 4.0"
UPGRADE_MARGIN = 0.03   # score points: below this the "better" model is a coin flip


def _norm(model_id: str) -> str:
    m = (model_id or "").strip().lower()
    return m[: -len(":latest")] if m.endswith(":latest") else m


def _upgrade(kind: str, ranked: list, current: Optional[str]) -> Optional[Dict[str, Any]]:
    if not current or not ranked:
        return None
    pos = next((i for i, s in enumerate(ranked) if _norm(s["install"]["model_id"]) == _norm(current)), None)
    if pos is None or pos == 0:
        return None
    best, cur = ranked[0], ranked[pos]
    if best["score"] - cur["score"] < UPGRADE_MARGIN:
        return None
    return {"kind": kind, "current": {"id": cur["id"], "name": cur["name"], "model_id": current,
                                      "score": cur["score"], "rank": pos + 1},
            "better": best}


async def _installed_ollama() -> Set[str]:
    try:
        from ..model_catalog import list_models_for_provider
        models, _err = await asyncio.wait_for(list_models_for_provider("ollama"), timeout=3.0)
        return set(models)
    except Exception:
        return set()


def _installed_comfy() -> Set[str]:
    try:
        from ..providers import scan_installed_models
        return set(scan_installed_models("image")) | set(scan_installed_models("video"))
    except Exception:
        return set()


async def _build(request: Request, refresh: bool, kind: Optional[str], limit: int,
                 vram_gb: Optional[float], current: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
    if not feed.enabled():
        return {"ok": True, "enabled": False}
    llm, media = await asyncio.gather(
        asyncio.to_thread(feed.load, "llm", refresh), asyncio.to_thread(feed.load, "media", refresh))
    hw = hardware.with_override(await asyncio.to_thread(hardware.detect), vram_gb)
    ollama, comfy = await asyncio.gather(_installed_ollama(), asyncio.to_thread(_installed_comfy))

    kinds = [kind] if kind else list(ranking.KINDS)
    suggestions: Dict[str, Any] = {}
    upgrades: Dict[str, Any] = {}
    for k in kinds:
        if k in ("chat", "vision"):
            ranked = ranking.rank_llm(llm.doc, k, hw, hardware.chat_memory_gb(hw), ollama, 100) if llm.doc else []
        else:
            ranked = ranking.rank_media(media.doc, k, float(hw.get("vram_gb") or 0), comfy, 100) if media.doc else []
        suggestions[k] = ranked[:limit]
        up = _upgrade(k, ranked, (current or {}).get(k))
        if up:
            upgrades[k] = up

    errors = llm.errors + media.errors
    fetch_ok = refresh and llm.source == "live" and media.source == "live"
    return {
        "ok": True,
        "enabled": True,
        "app_version": getattr(request.app, "version", None),
        "hardware": hw,
        "feeds": {"llm": llm.info(), "media": media.info()},
        "fetch": None if not refresh else {
            "ok": fetch_ok,
            "partial": refresh and not fetch_ok and "live" in (llm.source, media.source),
            "changed": bool(llm.changed or media.changed),
            "network": feed.network_allowed(),
            "errors": errors[:6],
        },
        "suggestions": suggestions,
        "upgrades": upgrades,
        "attribution": ATTRIBUTION,
    }


def _current(chat, vision, image, video) -> Dict[str, Optional[str]]:
    return {"chat": chat, "vision": vision, "image": image, "video": video}


@router.get("")
async def suggestions(
    request: Request,
    kind: Optional[str] = Query(None, pattern="^(chat|vision|image|video)$"),
    limit: int = Query(5, ge=1, le=10),
    vram_gb: Optional[float] = Query(None, ge=0, le=256, description="Plan for this much GPU memory"),
    current_chat: Optional[str] = Query(None, max_length=200),
    current_vision: Optional[str] = Query(None, max_length=200),
    current_image: Optional[str] = Query(None, max_length=200),
    current_video: Optional[str] = Query(None, max_length=200),
) -> Dict[str, Any]:
    return await _build(request, False, kind, limit, vram_gb,
                        _current(current_chat, current_vision, current_image, current_video))


@router.post("/fetch", dependencies=[Depends(require_api_key)])
async def fetch_suggestions(
    request: Request,
    kind: Optional[str] = Query(None, pattern="^(chat|vision|image|video)$"),
    limit: int = Query(5, ge=1, le=10),
    vram_gb: Optional[float] = Query(None, ge=0, le=256),
    current_chat: Optional[str] = Query(None, max_length=200),
    current_vision: Optional[str] = Query(None, max_length=200),
    current_image: Optional[str] = Query(None, max_length=200),
    current_video: Optional[str] = Query(None, max_length=200),
) -> Dict[str, Any]:
    if not feed.enabled():
        raise HTTPException(status_code=404, detail="Model Advisor is disabled (FITLAB_ENABLED=false)")
    return await _build(request, True, kind, limit, vram_gb,
                        _current(current_chat, current_vision, current_image, current_video))
