from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

from agentic.integrations.a2a._common.server import AgentDef, Json, create_a2a_app


FORGE_BASE_URL = os.environ.get("MCPGATEWAY_URL", "http://localhost:4444").rstrip("/")
FORGE_AUTH_USER = os.environ.get("BASIC_AUTH_USER", "admin")
FORGE_AUTH_PASS = os.environ.get("BASIC_AUTH_PASSWORD", "changeme")


async def _try_invoke(tool_name: str, args: Dict[str, Any]) -> str:
    """Best-effort tool invocation against Context Forge.

    This is only for the **reference implementation** so you can verify end-to-end wiring.
    In production, HomePilot's backend should invoke tools and enforce allow-lists.
    """

    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as c:
            r = await c.post(
                f"{FORGE_BASE_URL}/rpc",
                json=body,
                auth=(FORGE_AUTH_USER, FORGE_AUTH_PASS),
                headers={"Content-Type": "application/json"},
            )
            data = r.json()
            content = (((data.get("result") or {}).get("content")) or [])
            # Look for a text chunk
            for ch in content:
                if ch.get("type") == "text":
                    return str(ch.get("text") or "")
            return ""
    except Exception:
        return ""


#: Words that make a question a question about meetings. Deliberately short: the cost of a
#: miss is a briefing without a citation, and the cost of a false positive is a tool call that
#: returns nothing — so this leans towards asking.
_MEETING_WORDS = (
    "meeting", "meetings", "call", "calls", "standup", "stand-up", "sync", "retro",
    "we decide", "we decided", "we agreed", "discussed", "last week", "this week",
)


def _asks_about_meetings(text: str) -> bool:
    """Whether to spend a tool call on `ms.search`.

    A cheap keyword test rather than a model call: the enrichment is best-effort and the
    briefing has to come back inside a turn, so a second round trip to decide whether to make
    a round trip is the wrong trade.
    """
    lowered = (text or "").lower()
    return any(word in lowered for word in _MEETING_WORDS)


async def handle_message(text: str, meta: Json) -> Json:
    """Chief of Staff orchestrator (safe v1).

    Output is intentionally structured and conservative:
    * No external side effects
    * Clear separation of facts/assumptions/recommendations
    """

    mode = str(meta.get("mode") or "auto").lower()

    # Optional best-effort enrichment if seeded tools exist
    enrichment = ""
    if mode in ("auto", "knowledge", "decision"):
        enrichment = await _try_invoke("hp.search_workspace", {"query": text, "limit": 3})

    # MS22. "What did we decide about pricing?" is a question about meetings, and a chief of
    # staff that could not answer it would be one nobody asks twice. Best-effort like the
    # workspace search above: `ms.search` returns nothing when MeetingSense is not seeded, and
    # the briefing reads the same as it did before this batch.
    meetings = ""
    if mode in ("auto", "knowledge", "decision") and _asks_about_meetings(text):
        meetings = await _try_invoke("hp.ms.search", {"query": text, "k": 4})

    response_lines: List[str] = []
    response_lines.append("**What I know**")
    if enrichment:
        response_lines.append(f"- Workspace search hints:\n{enrichment}")
    if meetings:
        # Kept as its own bullet rather than folded into the workspace hints: these carry a
        # `meeting · hh:mm:ss` citation and the workspace ones do not, and a reader who cannot
        # tell them apart cannot check either.
        response_lines.append(f"- From your meetings (cited):\n{meetings}")
    if not enrichment and not meetings:
        response_lines.append("- I don't have workspace facts yet (or tools are not seeded).")

    response_lines.append("")
    response_lines.append("**What I assume**")
    response_lines.append("- You want a practical next step, not a long essay.")

    response_lines.append("")
    response_lines.append("**Options**")
    response_lines.append("1) Quick win: define success criteria in one sentence.")
    response_lines.append("2) Safe plan: list risks + mitigations, then pick an owner.")
    response_lines.append("3) Deep dive: gather sources, then decide with a scorecard.")

    response_lines.append("")
    response_lines.append("**Recommendation (with confidence)**")
    response_lines.append("- Start with option 1 today, then option 2 this week. (confidence: 0.65)")

    response_lines.append("")
    response_lines.append("**Question for you**")
    response_lines.append("- What's the deadline and what does 'good' look like?")

    return {
        "agent": "chief-of-staff",
        "text": "\n".join(response_lines),
        "policy": {"can_act": False, "needs_confirmation": True},
    }


app = create_a2a_app(
    agent=AgentDef(
        name="chief-of-staff",
        description="Orchestrates: gather facts → structure options → produce briefing (safe v1).",
    ),
    handle_message=handle_message,
)
