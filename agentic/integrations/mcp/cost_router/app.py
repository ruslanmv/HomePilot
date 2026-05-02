from __future__ import annotations

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_COST_EVENTS: list[dict] = []


MODEL_COST = {
    "cheap": 0.001,
    "balanced": 0.01,
    "premium": 0.05,
}


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def recommend_route(args: dict) -> dict:
    quality = str(args.get("quality", "balanced"))
    budget_left = float(args.get("budget_left", 10.0))
    if quality == "high" and budget_left > 1:
        route = "premium"
    elif budget_left < 0.2:
        route = "cheap"
    else:
        route = "balanced"
    return _content(f"Recommended route: {route}", ok=True, route=route, estimated_cost=MODEL_COST[route])


async def record_cost(args: dict) -> dict:
    route = str(args.get("route", "balanced"))
    units = float(args.get("units", 1.0))
    cost = float(args.get("cost", MODEL_COST.get(route, MODEL_COST["balanced"]) * units))
    _COST_EVENTS.append({"route": route, "units": units, "cost": cost})
    return _content("Cost event recorded", ok=True, total_spend=sum(item["cost"] for item in _COST_EVENTS), count=len(_COST_EVENTS))


async def monthly_budget_status(args: dict) -> dict:
    budget = float(args.get("budget", 100.0))
    spend = sum(item["cost"] for item in _COST_EVENTS)
    remaining = budget - spend
    return _content("Budget status computed", ok=remaining >= 0, budget=budget, spend=spend, remaining=remaining)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.cost.recommend_route", "Recommend route", {"type": "object", "properties": {"quality": {"type": "string"}, "budget_left": {"type": "number"}}}, recommend_route),
        ToolDef("hp.cost.record_cost", "Record cost event", {"type": "object", "properties": {"route": {"type": "string"}, "units": {"type": "number"}, "cost": {"type": "number"}}}, record_cost),
        ToolDef("hp.cost.monthly_budget_status", "Get budget status", {"type": "object", "properties": {"budget": {"type": "number"}}}, monthly_budget_status),
    ]


app = create_mcp_app(server_name="mcp-cost-router", tools=register_tools())
