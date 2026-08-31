"""MCP server: avatar_control — speak to the avatar at turn cadence (spec v1.1 §6.14).

Nine tools, mapped onto HomePilot's three safety levels by ``avatar_director/safety.py``:

  hp.avatar.search_animations   read-only   what she can do
  hp.avatar.get_animation       read-only   one clip's record
  hp.avatar.play_animation      autonomous  one intent — Tier 1 picks the clip
  hp.avatar.queue_sequence      autonomous  several intents, in order
  hp.avatar.set_mood            autonomous  valence and energy
  hp.avatar.set_scene           autonomous  forest, ocean, meditation
  hp.avatar.vision_insight      confirm     + live client capture consent
  hp.avatar.start_capture       confirm     + live client capture consent
  hp.avatar.stop_capture        confirm     + live client capture consent

## This process holds nothing

Every tool is one HTTP call to ``POST /avatar/control`` on the backend, which owns the live
socket and enforces the safety table. This server has no state, no session, no animation
knowledge and no way to reach the avatar except through that route. That is what makes
"killing the tool server changes nothing locally" true rather than hopeful: it is a caller,
not a component. The avatar's reflexes, selector, mixer and scheduler all run on the device
and never asked this process anything.

## Tools name intents, never clips

§6.14's bridge invariant. ``play_animation`` takes an *intent* from §6.2's whitelist and the
client's Tier 1 chooses which of the thirty-one dance clips (or four waves, or…) actually
plays, against the live mood and anti-repeat. A tool that could name a clip would be a
second animation authority, and the entire point of Tier 1 is that there is one.

Start:
    uvicorn agentic.integrations.mcp.avatar_control.app:app --host 0.0.0.0 --port 9121
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

from agentic.integrations.mcp._common.server import Json, ToolDef, mcp_app

#: The backend that owns the live socket. Loopback by default, like voice_call's turn path.
BACKEND_URL = (
    os.getenv("AVATAR_CONTROL_BACKEND_URL")
    or os.getenv("HOMEPILOT_INTERNAL_BACKEND_URL")
    or "http://127.0.0.1:8000"
).rstrip("/")

#: A gesture is a short thing. A tool call that hangs for thirty seconds waiting to ask for
#: one has already failed at being a gesture.
TIMEOUT_S = float(os.getenv("AVATAR_CONTROL_TIMEOUT_S", "8"))

WHITELIST_HINT = (
    "One of: happy, sad, angry, surprised, thinking, celebrate, dance, wave, flirt, tease, "
    "shy, agree, disagree, idle, point, lean_in, nod_along, breathe, console."
)


async def _call(tool: str, args: Json, *, approved: bool = False) -> Json:
    """One tool call, forwarded. Every failure comes back named, never as a silent ok."""
    payload = {"tool": tool, "args": args, "approved": approved}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(f"{BACKEND_URL}/avatar/control", json=payload)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "backend_unreachable",
            "message": f"could not reach HomePilot at {BACKEND_URL}: {exc}",
        }

    if response.status_code >= 400:
        detail: Any = {}
        try:
            detail = (response.json() or {}).get("detail") or {}
        except ValueError:
            detail = {}
        return {
            "ok": False,
            "error": detail.get("code") or f"http_{response.status_code}",
            "message": detail.get("msg") or response.text[:200],
        }
    return response.json()


def _tool(name: str, description: str, schema: Json, *, approved: bool = False) -> ToolDef:
    async def handler(args: Json) -> Json:
        return await _call(name, args or {}, approved=approved)

    return ToolDef(name=f"hp.avatar.{name}", description=description, input_schema=schema, handler=handler)


_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "description": f"The gesture to express. {WHITELIST_HINT}"},
        "intensity": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
    },
    "required": ["intent"],
}

TOOLS: List[ToolDef] = [
    _tool(
        "search_animations",
        "Search the avatar's animation catalogue by words in its descriptions, tags and "
        "intents. Read-only. Returns records, not a choice — playing one is a separate call "
        "and names an intent rather than a clip.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to look for, e.g. 'energetic celebration'"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
    ),
    _tool(
        "get_animation",
        "Fetch one animation record by id. Read-only.",
        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    ),
    _tool(
        "play_animation",
        "Express one intent on the live avatar. The client's Tier-1 selector chooses which "
        "clip that becomes, against the current mood and what it played recently — so this "
        "asks for a feeling, not a file.",
        _INTENT_SCHEMA,
    ),
    _tool(
        "queue_sequence",
        "Express several intents in order. The client's scheduler handles the crossfades "
        "and minimum play times. At most eight.",
        {
            "type": "object",
            "properties": {
                "intents": {"type": "array", "items": _INTENT_SCHEMA, "minItems": 1, "maxItems": 8},
            },
            "required": ["intents"],
        },
    ),
    _tool(
        "set_mood",
        "Nudge the avatar's mood. Valence -1..1, energy 0..1. The mood decays back toward "
        "neutral on its own, so this is a nudge rather than a setting.",
        {
            "type": "object",
            "properties": {
                "valence": {"type": "number", "minimum": -1, "maximum": 1},
                "energy": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    ),
    _tool(
        "set_scene",
        "Enter one of the avatar's scenes: forest, ocean or meditation. Meditation silences "
        "her own initiative for its duration.",
        {"type": "object", "properties": {"id": {"type": "string", "enum": ["forest", "ocean", "meditation"]}}, "required": ["id"]},
    ),
    _tool(
        "vision_insight",
        "Ask the avatar to look at what the user is sharing and comment. Requires an "
        "operator confirmation AND a live capture consent on the user's own device — the "
        "second is not something this server can grant.",
        {"type": "object", "properties": {"prompt": {"type": "string"}}},
    ),
    _tool(
        "start_capture",
        "Ask the user's device to start sharing a screen or camera. The device's own consent "
        "machine decides; this only asks.",
        {"type": "object", "properties": {"source": {"type": "string", "enum": ["screen", "camera", "game"]}}},
    ),
    _tool(
        "stop_capture",
        "Ask the user's device to stop sharing.",
        {"type": "object", "properties": {}},
    ),
]

app = mcp_app(server_name="hp-avatar-control", tools=TOOLS)
