from __future__ import annotations

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_LINEAGE: dict[str, list[dict]] = {}


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def attach_claim(args: dict) -> dict:
    response_id = str(args.get("response_id", "")).strip()
    claim = str(args.get("claim", "")).strip()
    citations = args.get("citations") or []
    if not response_id or not claim:
        return _content("Missing required fields: response_id and claim", ok=False)
    entry = {"claim": claim, "citations": citations}
    _LINEAGE.setdefault(response_id, []).append(entry)
    return _content("Claim attached", ok=True, response_id=response_id, entry=entry)


async def verify_citations(args: dict) -> dict:
    response_text = str(args.get("response_text", "")).strip()
    citation_count = response_text.count("[")
    ok = citation_count > 0
    return _content(
        "Citation verification completed.",
        ok=ok,
        citation_count=citation_count,
        message="No bracket-style citations were detected." if not ok else "Citations detected.",
    )


async def get_lineage(args: dict) -> dict:
    response_id = str(args.get("response_id", "")).strip()
    entries = _LINEAGE.get(response_id, [])
    return _content(f"Lineage entries: {len(entries)}", ok=True, response_id=response_id, entries=entries)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.citation.attach_claim", "Attach claim lineage", {"type": "object", "properties": {"response_id": {"type": "string"}, "claim": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}}}, "required": ["response_id", "claim"]}, attach_claim),
        ToolDef("hp.citation.verify_citations", "Verify citation coverage", {"type": "object", "properties": {"response_text": {"type": "string"}}, "required": ["response_text"]}, verify_citations),
        ToolDef("hp.citation.verify", "Verify citation coverage (alias)", {"type": "object", "properties": {"response_text": {"type": "string"}}, "required": ["response_text"]}, verify_citations),
        ToolDef("hp.citation.get_lineage", "Get response lineage", {"type": "object", "properties": {"response_id": {"type": "string"}}, "required": ["response_id"]}, get_lineage),
    ]


app = create_mcp_app(server_name="mcp-citation-provenance", tools=register_tools())
