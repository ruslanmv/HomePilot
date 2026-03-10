# community/shared/bundles/hello_world_greeter/mcp_server/app.py
"""
Community MCP Server: Greeter
Provides greeting, farewell, and compliment tools via JSON-RPC 2.0.

Compatible with:
  - HomePilot server_manager.py (install/uninstall lifecycle)
  - Context Forge (tool registration via POST /tools, virtual-server prefix matching)
  - MCP protocol (initialize, tools/list, tools/call via /rpc)

Install path (when deployed):
  agentic/integrations/mcp/community_greeter_server.py  (entry point)
  -> imports this module

Tool namespace: hp.community.greeter.*
  - Forge discovers tools via POST /rpc {"method": "tools/list"}
  - Forge registers each tool via POST /tools with integration_type=REST
  - Virtual servers match via include_tool_prefixes: ["hp.community.greeter."]
"""
from __future__ import annotations

import random
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app


Json = Dict[str, Any]


def _json(payload: Json) -> Json:
    """Return MCP content array wrapping a JSON payload (Forge-compatible format)."""
    return {"content": [{"type": "json", "json": payload}]}


# ── Greeting Data ─────────────────────────────────────────────────────────

GREETINGS: Dict[str, List[str]] = {
    "formal": [
        "Good day, {name}. It is a pleasure to see you.",
        "Welcome, {name}. I trust you are well.",
        "Greetings, {name}. How may I assist you today?",
    ],
    "casual": [
        "Hey {name}! Great to see you!",
        "Hi there, {name}! How's it going?",
        "What's up, {name}? Welcome back!",
    ],
    "enthusiastic": [
        "{name}!! So glad you're here! This is going to be awesome!",
        "YES! {name} is here! Let's make today incredible!",
        "Welcome welcome welcome, {name}! I've been looking forward to this!",
    ],
}

FAREWELLS: List[str] = [
    "Take care, {name}! Until next time.",
    "Goodbye, {name}. It was wonderful spending time with you.",
    "See you later, {name}! You've made today brighter.",
    "Farewell, {name}. Wishing you the very best!",
]

COMPLIMENTS: Dict[str, List[str]] = {
    "work": [
        "{name}, your dedication to your work is truly inspiring.",
        "The quality of your work speaks volumes, {name}. Outstanding effort!",
    ],
    "creativity": [
        "{name}, your creative thinking is remarkable. You see possibilities others miss.",
        "What an imagination you have, {name}! Your ideas are refreshing.",
    ],
    "kindness": [
        "{name}, your kindness makes the world a better place.",
        "The way you treat others is beautiful, {name}. Never change.",
    ],
    "general": [
        "{name}, you bring something special to every conversation.",
        "It's always a pleasure interacting with you, {name}. You're wonderful.",
    ],
}


# ── Tool Handlers ─────────────────────────────────────────────────────────

async def hp_greet(name: str, style: str = "casual", language: str = "en") -> Json:
    templates = GREETINGS.get(style, GREETINGS["casual"])
    message = random.choice(templates).format(name=name)
    return _json({"greeting": message, "style": style, "language": language})


async def hp_farewell(name: str, context: str | None = None) -> Json:
    message = random.choice(FAREWELLS).format(name=name)
    if context:
        message += f" ({context})"
    return _json({"farewell": message, "context": context})


async def hp_compliment(name: str, topic: str = "general") -> Json:
    templates = COMPLIMENTS.get(topic, COMPLIMENTS["general"])
    message = random.choice(templates).format(name=name)
    return _json({"compliment": message, "topic": topic})


# ── Tool Definitions ─────────────────────────────────────────────────────
# Naming: hp.community.greeter.<action>
# Forge registration: tools/list returns these, server_manager registers in Forge
# Virtual server matching: include_tool_prefixes: ["hp.community.greeter."]

TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.community.greeter.greet",
        description="Generate a personalized greeting for someone.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Person's name"},
                "style": {
                    "type": "string",
                    "enum": ["formal", "casual", "enthusiastic"],
                    "default": "casual",
                    "description": "Greeting style",
                },
                "language": {"type": "string", "default": "en", "description": "Language code"},
            },
            "required": ["name"],
        },
        handler=lambda args: hp_greet(**args),
    ),
    ToolDef(
        name="hp.community.greeter.farewell",
        description="Generate a thoughtful farewell message.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Person's name"},
                "context": {"type": "string", "description": "Why they are leaving (end of day, trip, etc.)"},
            },
            "required": ["name"],
        },
        handler=lambda args: hp_farewell(**args),
    ),
    ToolDef(
        name="hp.community.greeter.compliment",
        description="Generate a genuine, specific compliment.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Person's name"},
                "topic": {
                    "type": "string",
                    "description": "What to compliment (work, creativity, kindness, or general)",
                },
            },
            "required": ["name"],
        },
        handler=lambda args: hp_compliment(**args),
    ),
]


# ── FastAPI App (served by uvicorn via server_manager) ────────────────────
# Endpoints exposed:
#   GET  /health            → {"ok": true, "name": "...", "ts": ...}
#   POST /rpc               → JSON-RPC 2.0 (initialize, tools/list, tools/call)
#
# Forge registration flow:
#   1. server_manager starts uvicorn on port 9200
#   2. Waits for /health → 200
#   3. POST /rpc {"method": "tools/list"} → discovers 3 tools
#   4. Registers each tool in Forge: POST {forge_url}/tools
#   5. sync_homepilot() updates virtual servers matching hp.community.greeter.*

app = create_mcp_app(
    server_name="homepilot-community-greeter",
    tools=TOOLS,
)
