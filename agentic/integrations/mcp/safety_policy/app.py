from __future__ import annotations

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_RISK_TERMS = {
    "critical": {"self-harm", "suicide", "explosive", "weapon", "malware"},
    "high": {"bypass", "steal", "password", "doxx", "phish"},
    "medium": {"hack", "attack", "exploit", "jailbreak"},
}


def _score(text: str) -> tuple[float, str, list[str]]:
    q = text.lower()
    hits: list[str] = []
    score = 0.0
    for weight, terms in ((0.9, _RISK_TERMS["critical"]), (0.6, _RISK_TERMS["high"]), (0.3, _RISK_TERMS["medium"])):
        for term in terms:
            if term in q:
                hits.append(term)
                score = max(score, weight)
    label = "low"
    if score >= 0.9:
        label = "critical"
    elif score >= 0.6:
        label = "high"
    elif score >= 0.3:
        label = "medium"
    return score, label, hits


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def check_input(args: dict) -> dict:
    text = str(args.get("text", ""))
    score, label, hits = _score(text)
    return _content(f"input risk={label} score={score:.2f}", ok=True, score=score, risk=label, hits=hits)


async def check_output(args: dict) -> dict:
    text = str(args.get("text", ""))
    score, label, hits = _score(text)
    blocked = label in {"critical", "high"}
    return _content(f"output risk={label} blocked={blocked}", ok=not blocked, score=score, risk=label, hits=hits, blocked=blocked)


async def risk_score(args: dict) -> dict:
    text = str(args.get("text", ""))
    score, label, hits = _score(text)
    return _content(f"risk score={score:.2f}", ok=True, score=score, risk=label, hits=hits)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.safety.check_input", "Check prompt risk", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, check_input),
        ToolDef("hp.safety.check_output", "Check answer risk", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, check_output),
        ToolDef("hp.safety.risk_score", "Return risk score", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, risk_score),
    ]


app = create_mcp_app(server_name="mcp-safety-policy", tools=register_tools())
