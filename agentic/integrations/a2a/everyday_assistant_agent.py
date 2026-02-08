from __future__ import annotations

from typing import Any, Dict

from agentic.integrations.a2a._common.server import AgentDef, Json, create_a2a_app


async def handle_message(text: str, meta: Json) -> Json:
    """A small read-only, advisory reference agent.

    The goal is to provide an A2A target that:
    * can be registered in Context Forge
    * shows up in HomePilot's wizard
    * returns a predictable output (useful for integration tests)
    """

    persona = str(meta.get("persona") or "friendly")
    prefix = {
        "friendly": "Sure —",
        "neutral": "Okay.",
        "focused": "Got it.",
    }.get(persona, "Sure —")

    return {
        "agent": "everyday-assistant",
        "text": f"{prefix} here is a simple next step: write down the 1–3 outcomes you want today.\n\nYou said: {text}",
        "policy": {
            "can_act": False,
            "needs_confirmation": True,
        },
    }


app = create_a2a_app(
    agent=AgentDef(
        name="everyday-assistant",
        description="Friendly helper that summarizes and plans. Read-only + advisory.",
    ),
    handle_message=handle_message,
)
