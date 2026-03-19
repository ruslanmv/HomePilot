"""
Persona Graph Routes — API endpoints for LangGraph persona agent + world state.

Additive router. Mounts at /v1/persona-graph.
Does NOT alter /chat, /v1/agent/chat, or any existing endpoints.

Provides:
  POST /v1/persona-graph/chat     — graph-based persona chat
  POST /v1/world-state/update     — receive VR world state
  GET  /v1/persona/{id}/motion    — get latest motion plan
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["persona-graph"])


# ── World State storage (in-memory per-session) ─────────────────────

_world_state_sessions: Dict[str, Any] = {}
_latest_motion_plans: Dict[str, Dict[str, Any]] = {}


# ── Request/Response models ──────────────────────────────────────────


class PersonaGraphChatIn(BaseModel):
    conversation_id: Optional[str] = Field(None)
    project_id: Optional[str] = Field(None)
    message: str = Field(..., description="User message")
    persona_id: str = Field("", description="Persona identifier")

    # LLM settings
    provider: str = Field("openai_compat")
    provider_base_url: Optional[str] = None
    provider_model: Optional[str] = None
    temperature: float = Field(0.7)
    max_tokens: int = Field(900)

    # Agent controls
    max_tool_calls: int = Field(4)
    history_limit: int = Field(24)


class WorldStateUpdateIn(BaseModel):
    session_id: str = Field("default", description="VR session identifier")
    user: Optional[Dict[str, Any]] = None
    avatars: Optional[Dict[str, Dict[str, Any]]] = None
    anchors: Optional[List[Dict[str, Any]]] = None


# ── POST /v1/persona-graph/chat ─────────────────────────────────────


@router.post("/v1/persona-graph/chat")
async def persona_graph_chat(inp: PersonaGraphChatIn) -> JSONResponse:
    """
    Graph-based persona chat. Uses LangGraph to run the
    perceive → think → decide → act → embody → respond pipeline.

    Falls back to direct response if the persona has no v3 profile.
    """
    from ..persona_runtime.manager import (
        PersonaRuntimeConfig,
        build_runtime_config,
    )
    from ..projects import get_project_by_id, build_persona_context
    from ..storage import get_messages
    from .graph_builder import run_persona_graph
    from .embodiment_prompt import build_embodiment_prompt
    from ..world_state.service import WorldStateService

    # Resolve persona config
    project_data = {}
    system_prompt = ""
    persona_config = PersonaRuntimeConfig()

    if inp.project_id:
        project_data = get_project_by_id(inp.project_id) or {}
        system_prompt = build_persona_context(inp.project_id) or ""

        # Try to load v3 profiles from the bundle
        try:
            from pathlib import Path
            from ..persona_runtime.manager import resolve_persona
            from ..config import UPLOAD_DIR

            bundle_dirs = [
                Path(UPLOAD_DIR) / "bundles" / inp.persona_id / "persona",
                Path(__file__).parent.parent.parent.parent
                / "community" / "shared" / "bundles" / inp.persona_id / "persona",
            ]
            for bd in bundle_dirs:
                if bd.is_dir():
                    persona_config = resolve_persona(bd)
                    break
        except Exception as e:
            logger.debug("Could not load v3 profile: %s", e)

    # Append embodiment instructions to system prompt
    embodiment_section = build_embodiment_prompt(persona_config)
    if embodiment_section:
        system_prompt = system_prompt + "\n" + embodiment_section

    # Get world state snapshot
    world_snapshot = {}
    ws_service = _world_state_sessions.get("default")
    if ws_service and hasattr(ws_service, "snapshot"):
        world_snapshot = ws_service.snapshot()
        # Compute avatar distance
        user_pos = world_snapshot.get("user", {}).get("position", {})
        avatar_data = world_snapshot.get("avatars", {}).get(inp.persona_id, {})
        if user_pos and avatar_data.get("position"):
            dx = user_pos.get("x", 0) - avatar_data["position"].get("x", 0)
            dy = user_pos.get("y", 0) - avatar_data["position"].get("y", 0)
            dz = user_pos.get("z", 0) - avatar_data["position"].get("z", 0)
            world_snapshot["avatar_distance_m"] = (dx**2 + dy**2 + dz**2) ** 0.5

    # Get conversation history
    history = []
    if inp.conversation_id:
        raw_msgs = get_messages(inp.conversation_id) or []
        for m in raw_msgs[-inp.history_limit:]:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role in ("user", "assistant", "system") and content:
                history.append({"role": role, "content": content})

    # Build initial state
    cog = persona_config.cognitive
    emb = persona_config.embodiment

    initial_state = {
        "user_message": inp.message,
        "conversation_id": inp.conversation_id or "",
        "project_id": inp.project_id or "",
        "conversation_history": history,
        "persona_id": inp.persona_id or persona_config.persona_id,
        "display_name": persona_config.display_name or "Persona",
        "reasoning_mode": cog.reasoning_mode,
        "system_prompt": system_prompt,
        "allowed_tool_categories": cog.allowed_tool_categories,
        "multi_step_planning": cog.multi_step_planning,
        "tool_chaining": cog.tool_chaining,
        "self_reflection": cog.self_reflection,
        "workflow_graphs": cog.workflow_graphs,
        "max_tool_calls": inp.max_tool_calls,
        "expression_style": emb.expression_style,
        "gesture_amplitude": emb.gesture_amplitude,
        "personal_distance_m": emb.personal_distance_m,
        "can_sit": emb.can_sit,
        "can_offer_hand": emb.can_offer_hand,
        "can_high_five": emb.can_high_five,
        "world_snapshot": world_snapshot,
        "llm_provider": inp.provider,
        "llm_base_url": inp.provider_base_url or "",
        "llm_model": inp.provider_model or "",
        "temperature": inp.temperature,
        "max_tokens": inp.max_tokens,
        "tool_calls_used": 0,
        "tool_results": [],
        "is_complete": False,
    }

    # Run the graph
    result = await run_persona_graph(
        reasoning_mode=cog.reasoning_mode,
        initial_state=initial_state,
    )

    # Store motion plan for polling
    motion_plan = result.get("motion_plan")
    persona_key = inp.persona_id or persona_config.persona_id
    if motion_plan and persona_key:
        _latest_motion_plans[persona_key] = {
            "plan": motion_plan,
            "timestamp": time.time(),
        }

    # Build response
    response: Dict[str, Any] = {
        "text": result.get("response_text", ""),
        "persona_id": persona_key,
        "reasoning_mode": cog.reasoning_mode,
    }

    # Attach x_directives for VR client
    x_directives: Dict[str, Any] = {}
    if result.get("avatar_emotion"):
        x_directives["emotion"] = result["avatar_emotion"]
    if result.get("avatar_state"):
        x_directives["state"] = result["avatar_state"]
    if motion_plan:
        x_directives["motion_plan"] = motion_plan
    if x_directives:
        response["x_directives"] = x_directives

    if result.get("response_media"):
        response["x_attachments"] = [result["response_media"]]

    return JSONResponse(status_code=200, content=response)


# ── POST /v1/world-state/update ──────────────────────────────────────


@router.post("/v1/world-state/update")
async def world_state_update(inp: WorldStateUpdateIn) -> JSONResponse:
    """
    Receive world-state updates from the VR client.
    Stores in-memory for the current session.
    """
    from ..world_state.service import WorldStateService

    session_id = inp.session_id or "default"

    if session_id not in _world_state_sessions:
        _world_state_sessions[session_id] = WorldStateService()

    ws = _world_state_sessions[session_id]

    if inp.user:
        ws.update_user(inp.user)
    if inp.avatars:
        for persona_id, avatar_data in inp.avatars.items():
            ws.update_avatar(persona_id, avatar_data)
    if inp.anchors is not None:
        ws.set_anchors(inp.anchors)

    return JSONResponse(status_code=200, content={"ok": True})


# ── GET /v1/persona/{persona_id}/motion ──────────────────────────────


@router.get("/v1/persona/{persona_id}/motion")
async def get_motion_plan(persona_id: str) -> JSONResponse:
    """
    Get the latest motion plan for a persona (polling endpoint).
    Returns null if no plan is available.
    """
    entry = _latest_motion_plans.get(persona_id)
    if not entry:
        return JSONResponse(status_code=200, content={"motion_plan": None})

    # Plans older than 30 seconds are stale
    if time.time() - entry.get("timestamp", 0) > 30:
        return JSONResponse(status_code=200, content={"motion_plan": None})

    return JSONResponse(status_code=200, content={"motion_plan": entry["plan"]})


# ── POST /world-state/update (legacy path for WorldStateBridge.js) ───


@router.post("/world-state/update")
async def world_state_update_legacy(request: Request) -> JSONResponse:
    """
    Legacy path — WorldStateBridge.js pushes to /world-state/update.
    Delegates to the v1 endpoint.
    """
    from ..world_state.service import WorldStateService

    body = await request.json()

    session_id = body.get("session_id", "default")
    if session_id not in _world_state_sessions:
        _world_state_sessions[session_id] = WorldStateService()

    ws = _world_state_sessions[session_id]

    user_data = body.get("user")
    if user_data:
        ws.update_user(user_data)

    avatars = body.get("avatars", {})
    for pid, adata in avatars.items():
        ws.update_avatar(pid, adata)

    anchors = body.get("anchors")
    if anchors is not None:
        ws.set_anchors(anchors)

    return JSONResponse(status_code=200, content={"ok": True})
