from __future__ import annotations

from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


async def tool_hp_personal_search(args: Json) -> Json:
    """Search personal notes / memory (reference placeholder).

    In a real implementation, wire this to:
    * HomePilot local knowledge base
    * indexed notes
    * personal document store
    """

    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 10) or 10)
    limit = max(1, min(limit, 50))

    if not query:
        return _text("Please provide a non-empty 'query'.")

    # Placeholder results
    items = [
        {"id": "mem-1", "snippet": f"(sample) Result for '{query}'", "score": 0.82},
        {"id": "mem-2", "snippet": f"(sample) Another hit for '{query}'", "score": 0.61},
    ][:limit]

    lines = [f"Found {len(items)} items for '{query}':"] + [f"- {i['snippet']}" for i in items]
    return _text("\n".join(lines))


async def tool_hp_personal_plan_day(args: Json) -> Json:
    """Draft a day plan given a title and optional constraints."""

    title = str(args.get("title", "")).strip()
    constraints = args.get("constraints") or []
    if isinstance(constraints, str):
        constraints = [constraints]
    if not isinstance(constraints, list):
        constraints = []
    constraints = [str(c) for c in constraints if str(c).strip()]

    if not title:
        return _text("Please provide a non-empty 'title'.")

    plan: List[str] = [
        "1) Clarify your top 1–3 priorities",
        "2) Block two focus sessions (45–90m)",
        "3) Do an admin sweep (messages + calendar)",
        "4) Pick one small win for momentum",
        "5) End-of-day 5-minute review",
    ]
    if constraints:
        plan.append(f"Constraints noted: {', '.join(constraints)}")

    return _text(f"Plan for: {title}\n" + "\n".join(plan))


TOOLS = [
    ToolDef(
        name="hp.personal.search",
        description="Search personal notes / memory (reference placeholder).",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
        handler=tool_hp_personal_search,
    ),
    ToolDef(
        name="hp.personal.plan_day",
        description="Draft a simple day plan given a title and constraints.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "constraints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
        handler=tool_hp_personal_plan_day,
    ),
]


app = create_mcp_app(server_name="homepilot-personal-assistant", tools=TOOLS)

