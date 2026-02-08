from __future__ import annotations

from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app


def _json(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"content": [{"type": "json", "json": payload}]}


async def hp_decision_options(goal: str, constraints: List[str] | None = None, context: str | None = None) -> Dict[str, Any]:
    constraints = constraints or []
    # Reference implementation: deterministic placeholder options.
    options = [
      {
        "title": "Option A (Low risk)",
        "pros": ["Fast to execute", "Lowest organizational risk"],
        "cons": ["May not fully meet goal"],
        "cost": "Low",
        "risk": "Low",
        "dependencies": []
      },
      {
        "title": "Option B (Balanced)",
        "pros": ["Good tradeoff", "Scales later"],
        "cons": ["Requires coordination"],
        "cost": "Medium",
        "risk": "Medium",
        "dependencies": ["Stakeholder alignment"]
      },
      {
        "title": "Option C (High impact)",
        "pros": ["Maximizes goal attainment"],
        "cons": ["Higher complexity", "Higher execution risk"],
        "cost": "High",
        "risk": "High",
        "dependencies": ["Budget approval", "Dedicated owner"]
      }
    ]
    return _json({"goal": goal, "constraints": constraints, "context": context, "options": options})


async def hp_decision_risk_assessment(proposal: str, risk_tolerance: str = "medium") -> Dict[str, Any]:
    score = {"low": 2, "medium": 5, "high": 8}.get(risk_tolerance, 5)
    return _json({
      "proposal": proposal,
      "risk_tolerance": risk_tolerance,
      "risk_score": score,
      "risks": [
        {"risk": "Scope creep", "mitigation": "Define success criteria and stop conditions"},
        {"risk": "Stakeholder mismatch", "mitigation": "Run a 30-minute alignment review"}
      ]
    })


async def hp_decision_recommend_next(options: List[Dict[str, Any]], decision_criteria: List[str] | None = None) -> Dict[str, Any]:
    decision_criteria = decision_criteria or ["impact", "effort", "risk"]
    # Reference implementation: prefer Balanced if present.
    pick = 0
    for i, opt in enumerate(options):
        if "balanced" in (opt.get("title", "").lower()):
            pick = i
            break
    return _json({
      "decision_criteria": decision_criteria,
      "recommended_index": pick,
      "confidence": 0.62,
      "reasoning": "Picked the best tradeoff for most teams (impact vs effort vs risk)."
    })


async def hp_decision_plan_next_steps(decision: str, time_horizon: str = "this_week") -> Dict[str, Any]:
    steps = [
      {"step": 1, "title": "Confirm scope", "owner": "You", "due": "today"},
      {"step": 2, "title": "Draft plan", "owner": "You", "due": "this_week"},
      {"step": 3, "title": "Stakeholder review", "owner": "Team", "due": "this_week"},
    ]
    return _json({"decision": decision, "time_horizon": time_horizon, "steps": steps})


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.decision.options",
        description="Generate decision options with tradeoffs.",
        input_schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "context": {"type": "string"},
            },
            "required": ["goal"],
        },
        handler=lambda args: hp_decision_options(**args),
    ),
    ToolDef(
        name="hp.decision.risk_assessment",
        description="Assess risks for a proposal.",
        input_schema={
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "risk_tolerance": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
            },
            "required": ["proposal"],
        },
        handler=lambda args: hp_decision_risk_assessment(**args),
    ),
    ToolDef(
        name="hp.decision.recommend_next",
        description="Recommend a next decision from options.",
        input_schema={
            "type": "object",
            "properties": {
                "options": {"type": "array", "items": {"type": "object"}},
                "decision_criteria": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["options"],
        },
        handler=lambda args: hp_decision_recommend_next(**args),
    ),
    ToolDef(
        name="hp.decision.plan_next_steps",
        description="Turn a decision into an execution plan.",
        input_schema={
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "time_horizon": {"type": "string", "enum": ["today", "this_week", "this_month"], "default": "this_week"},
            },
            "required": ["decision"],
        },
        handler=lambda args: hp_decision_plan_next_steps(**args),
    ),
]


app = create_mcp_app(
    server_name="homepilot-decision-copilot",
    tools=TOOLS,
)
