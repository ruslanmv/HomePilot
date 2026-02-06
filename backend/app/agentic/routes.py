"""FastAPI router — /v1/agentic/*

Phase 1–4 endpoints (additive, non-destructive):
  GET  /v1/agentic/status        → health / feature-flag check
  GET  /v1/agentic/admin         → admin UI redirect URL
  GET  /v1/agentic/capabilities  → dynamic discovery from Context Forge + built-ins
  POST /v1/agentic/invoke        → execute a capability (local orchestrator + Context Forge)

Phase 4 additions:
  - capabilities returns source="forge"|"built_in"|"mixed" field
  - generate_images uses model-config preset system (not hard-coded dims)
  - generate_videos routed to local animate pipeline
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_api_key
from ..defaults import DEFAULT_NEGATIVE_PROMPT
from ..orchestrator import handle_request
from .capabilities import discover_capabilities
from .client import ContextForgeClient
from .policy import apply_policy, is_allowed, resolve_profile
from .types import (
    AgenticAdminOut,
    AgenticStatusOut,
    CapabilitiesOut,
    InvokeIn,
    InvokeOut,
)

logger = logging.getLogger("homepilot.agentic.routes")

router = APIRouter(prefix="/v1/agentic", tags=["agentic"])

# ── Configuration (read once at import, overridable via env) ──────────────────

_ENABLED = os.getenv("AGENTIC_ENABLED", "true").lower() in ("1", "true", "yes")
_FORGE_URL = os.getenv("CONTEXT_FORGE_URL", "http://localhost:4444").rstrip("/")
_ADMIN_URL = os.getenv("CONTEXT_FORGE_ADMIN_URL", "http://localhost:4444/admin").rstrip("/")
_TOKEN = os.getenv("CONTEXT_FORGE_TOKEN", "")
_AUTH_USER = os.getenv("CONTEXT_FORGE_AUTH_USER", "admin")
_AUTH_PASS = os.getenv("CONTEXT_FORGE_AUTH_PASS", "changeme")


def _client() -> ContextForgeClient:
    return ContextForgeClient(
        base_url=_FORGE_URL,
        token=_TOKEN,
        auth_user=_AUTH_USER,
        auth_pass=_AUTH_PASS,
    )


# ── GET /v1/agentic/status ───────────────────────────────────────────────────

@router.get("/status", response_model=AgenticStatusOut)
async def agentic_status(_key: str = Depends(require_api_key)):
    configured = bool(_FORGE_URL)
    reachable = False
    if _ENABLED and configured:
        try:
            reachable = await _client().ping()
        except Exception:
            pass
    return AgenticStatusOut(
        enabled=_ENABLED,
        configured=configured,
        reachable=reachable,
        admin_configured=bool(_ADMIN_URL),
    )


# ── GET /v1/agentic/admin ────────────────────────────────────────────────────

@router.get("/admin", response_model=AgenticAdminOut)
async def agentic_admin(_key: str = Depends(require_api_key)):
    if not _ADMIN_URL:
        raise HTTPException(status_code=404, detail="Admin URL not configured")
    return AgenticAdminOut(admin_url=_ADMIN_URL)


# ── GET /v1/agentic/capabilities ─────────────────────────────────────────────

@router.get("/capabilities", response_model=CapabilitiesOut)
async def agentic_capabilities(_key: str = Depends(require_api_key)):
    if not _ENABLED:
        return CapabilitiesOut(capabilities=[], source="built_in")
    try:
        caps, source = await discover_capabilities(_client())
    except Exception as exc:
        logger.warning("capability discovery failed: %s", exc)
        caps, source = [], "built_in"
    return CapabilitiesOut(capabilities=caps, source=source)


# ── POST /v1/agentic/invoke ──────────────────────────────────────────────────
# Phase 3: built-in intents route to the local HomePilot orchestrator.
# Other intents fall through to Context Forge tool invocation.

async def _invoke_local_imagine(body: InvokeIn, defaults: Dict[str, Any]) -> InvokeOut:
    """Route generate_images through the existing HomePilot imagine pipeline."""
    prompt = (body.args.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing args.prompt")

    # Let the orchestrator's preset system compute width/height/steps/cfg
    # based on model architecture (SDXL bucketed resolutions, Pony-specific
    # steps, Flux CFG, etc.) instead of hard-coding dimensions here.
    payload: Dict[str, Any] = {
        "message": prompt,
        "conversation_id": body.conversation_id,
        "project_id": body.project_id,
        "mode": "imagine",
        "imgPreset": defaults.get("img_preset", "med"),
        "imgSeed": 0,
        "imgModel": body.args.get("model", "pony-xl"),
        "promptRefinement": True,
        "nsfwMode": body.nsfwMode,
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    }

    result = await handle_request("imagine", payload)
    return InvokeOut(
        ok=True,
        conversation_id=result.get("conversation_id", body.conversation_id or ""),
        assistant_text="Here you go.",
        media=result.get("media"),
        meta={"intent": "generate_images", "profile": body.profile},
    )


async def _invoke_local_animate(body: InvokeIn, defaults: Dict[str, Any]) -> InvokeOut:
    """Route generate_videos through the existing HomePilot animate pipeline."""
    prompt = (body.args.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing args.prompt")

    payload: Dict[str, Any] = {
        "message": prompt,
        "conversation_id": body.conversation_id,
        "project_id": body.project_id,
        "mode": "animate",
        "vidSteps": defaults.get("vid_steps", 20),
        "vidCfg": defaults.get("vid_cfg", 3.5),
        "vidFrames": defaults.get("vid_frames", 25),
        "nsfwMode": body.nsfwMode,
    }

    result = await handle_request("animate", payload)
    return InvokeOut(
        ok=True,
        conversation_id=result.get("conversation_id", body.conversation_id or ""),
        assistant_text="Here is your video.",
        media=result.get("media"),
        meta={"intent": "generate_videos", "profile": body.profile},
    )


@router.post("/invoke", response_model=InvokeOut)
async def agentic_invoke(body: InvokeIn, _key: str = Depends(require_api_key)):
    """Execute a capability.

    Phase 3 strategy:
    - Built-in intents (generate_images, generate_videos) → local orchestrator
    - Other intents → Context Forge tool invocation (with graceful error)
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    if not is_allowed(body.intent):
        raise HTTPException(status_code=403, detail=f"Capability '{body.intent}' is not allowed")

    defaults = resolve_profile(body.profile)

    # ── Built-in intents (use local HomePilot pipelines) ──────────────────
    try:
        if body.intent == "generate_images":
            return await _invoke_local_imagine(body, defaults)

        if body.intent == "generate_videos":
            return await _invoke_local_animate(body, defaults)
    except HTTPException:
        raise  # re-raise 400s etc.
    except Exception as exc:
        logger.error("Built-in intent '%s' failed: %s", body.intent, exc, exc_info=True)
        return InvokeOut(
            ok=False,
            conversation_id=body.conversation_id or "",
            assistant_text=f"Generation failed: {exc}",
            media=None,
            meta={"intent": body.intent, "error": str(exc)},
        )

    # ── All other intents → Context Forge ─────────────────────────────────
    try:
        merged_args = apply_policy(body.intent, body.args, body.profile)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    client = _client()
    result = await client.invoke_tool(body.intent, merged_args)

    if "error" in result:
        return InvokeOut(
            ok=False,
            conversation_id=body.conversation_id or "",
            assistant_text=result["error"],
            meta=result,
        )

    return InvokeOut(
        ok=True,
        conversation_id=body.conversation_id or "",
        assistant_text=result.get("result", result.get("text", "")),
        media=result.get("media"),
        meta={k: v for k, v in result.items() if k not in ("result", "text", "media")},
    )
