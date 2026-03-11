"""
FastAPI router for /v1/teams/bridge/* endpoints.

Provides API endpoints for connecting HomePilot rooms to external
Microsoft Teams meetings via the bridge infrastructure.

All routes are additive — they do NOT modify any existing routes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .bridge.manager import bridge_manager
from .bridge.types import MeetingEvent
from . import rooms

logger = logging.getLogger("homepilot.teams.bridge_routes")

router = APIRouter(prefix="/v1/teams/bridge", tags=["teams-bridge"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class BridgeConnectRequest(BaseModel):
    room_id: str = Field(..., description="HomePilot room ID to bridge")
    join_url: str = Field(..., description="Microsoft Teams meeting join URL")
    mcp_base_url: str = Field(
        default="http://localhost:9106",
        description="URL of the teams-mcp-server",
    )
    poll_interval: float = Field(
        default=5.0,
        description="Seconds between chat polls",
    )
    voice_enabled: bool = Field(
        default=False,
        description="Enable voice detection (STT) on connect",
    )
    # ── Persona mode fields ──
    mode: str = Field(
        default="native",
        description="Connection mode: 'native' (Graph API + Azure) or 'persona' (browser guest join, no Azure)",
    )
    display_name: str = Field(
        default="",
        description="Persona display name shown in meeting (required for persona mode)",
    )
    face_image: str = Field(
        default="",
        description="Path to persona face image for virtual camera (persona mode)",
    )
    tts_voice: str = Field(
        default="en_US-amy-medium",
        description="Piper TTS voice model (persona mode)",
    )
    headless: bool = Field(
        default=True,
        description="Run browser headless (persona mode)",
    )


class BridgeVoiceToggleRequest(BaseModel):
    enabled: bool = Field(..., description="Enable or disable voice detection")


class BridgeSendRequest(BaseModel):
    sender_name: str = Field(..., description="Name of the persona sending")
    content: str = Field(..., description="Message content to send to Teams")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/health")
async def bridge_health(mcp_base_url: str = "http://localhost:9106") -> Dict[str, Any]:
    """Check if the teams-mcp-server is reachable.

    Returns ``{"available": true/false}`` so the frontend can show or
    hide Teams features without breaking when the MCP server is absent.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{mcp_base_url}/health")
            r.raise_for_status()
            return {"available": True, "tools": r.json().get("tools", [])}
    except Exception:
        return {"available": False, "tools": []}


@router.post("/connect")
async def bridge_connect(req: BridgeConnectRequest) -> Dict[str, Any]:
    """Connect a HomePilot room to a Microsoft Teams meeting.

    Paste the Teams meeting join URL and this will:
    1. Resolve the meeting chat via the teams-mcp-server
    2. Start polling for new chat messages
    3. Inject external messages into the room transcript
    4. Auto-trigger persona reactions when new messages arrive
    """
    try:
        result = await bridge_manager.connect(
            room_id=req.room_id,
            join_url=req.join_url,
            mcp_base_url=req.mcp_base_url,
            poll_interval=req.poll_interval,
            voice_enabled=req.voice_enabled,
            mode=req.mode,
            display_name=req.display_name,
            face_image=req.face_image,
            tts_voice=req.tts_voice,
            headless=req.headless,
        )

        # Wire auto-reactions: when the poller delivers new Teams messages,
        # trigger the orchestrator so personas react automatically.
        bridge_manager.set_reaction_callback(_on_bridge_messages)

        return result
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Bridge connect error: {e}", exc_info=True)
        # Provide a user-friendly message when MCP server is unreachable
        msg = str(e)
        if "connect" in msg.lower() or "timeout" in msg.lower() or "refused" in msg.lower():
            detail = (
                f"Teams MCP server at {req.mcp_base_url} is not reachable. "
                "Ensure teams-mcp-server is running before connecting."
            )
        else:
            detail = f"Bridge connection failed: {e}"
        raise HTTPException(status_code=500, detail=detail)


@router.post("/disconnect/{room_id}")
async def bridge_disconnect(room_id: str) -> Dict[str, Any]:
    """Disconnect a room from its Teams meeting."""
    return await bridge_manager.disconnect(room_id)


@router.get("/status/{room_id}")
async def bridge_status(room_id: str) -> Dict[str, Any]:
    """Get bridge connection status for a room."""
    return bridge_manager.get_status(room_id)


@router.get("/active")
async def bridge_list_active() -> list:
    """List all active bridge connections."""
    return bridge_manager.list_active()


@router.post("/voice/{room_id}")
async def bridge_voice_toggle(room_id: str, req: BridgeVoiceToggleRequest) -> Dict[str, Any]:
    """Toggle voice detection (STT) for a bridged room."""
    if not bridge_manager.is_connected(room_id):
        raise HTTPException(status_code=404, detail="No active bridge for this room")
    return await bridge_manager.toggle_voice(room_id, req.enabled)


@router.get("/voice/{room_id}")
async def bridge_voice_status(room_id: str) -> Dict[str, Any]:
    """Get voice detection status for a bridged room."""
    if not bridge_manager.is_connected(room_id):
        raise HTTPException(status_code=404, detail="No active bridge for this room")
    return await bridge_manager.get_voice_status(room_id)


@router.post("/send/{room_id}")
async def bridge_send(room_id: str, req: BridgeSendRequest) -> Dict[str, Any]:
    """Send a message from a persona to the Teams meeting chat."""
    if not bridge_manager.is_connected(room_id):
        raise HTTPException(status_code=404, detail="No active bridge for this room")
    ok = await bridge_manager.send_to_meeting(
        room_id=room_id,
        sender_name=req.sender_name,
        content=req.content,
    )
    return {"sent": ok, "room_id": room_id}


# ---------------------------------------------------------------------------
# Bridge → Orchestrator auto-reaction callback
# ---------------------------------------------------------------------------

async def _on_bridge_messages(room_id: str, events: List[MeetingEvent]) -> None:
    """Auto-trigger persona reactions when external Teams messages arrive."""
    from .orchestrator import run_reactive_step
    from .llm_adapter import llm_text
    from .participants_resolver import resolve_participants
    from .meeting_engine import run_persona_turn
    from ..projects import get_project_by_id

    room = rooms.get_room(room_id)
    if not room or not room.get("participant_ids"):
        return

    participant_projects = []
    for pid in room["participant_ids"]:
        proj = get_project_by_id(pid)
        if proj:
            participant_projects.append(proj)

    if not participant_projects:
        return

    participants = resolve_participants(room["participant_ids"])
    last_msg = events[-1].content if events else ""

    async def generate_fn(persona_id: str, rm: Dict[str, Any]) -> str:
        proj = get_project_by_id(persona_id)
        if not proj:
            return ""
        result = await run_persona_turn(proj, rm, participant_projects, llm_text)
        return result.get("content", "")

    try:
        await run_reactive_step(
            room_id=room_id,
            last_human_message=last_msg,
            participants=participants,
            generate_fn=generate_fn,
        )
    except Exception:
        logger.error(f"Auto-reaction failed for room {room_id}", exc_info=True)
