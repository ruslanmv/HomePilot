from __future__ import annotations

from datetime import datetime, timezone

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_MEMORY: dict[str, list[dict]] = {}


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def append_memory(args: dict) -> dict:
    scope = str(args.get("scope", "default"))
    value = str(args.get("value", "")).strip()
    if not value:
        return _content("Missing required field: value", ok=False)

    entry = {"value": value, "ts": datetime.now(timezone.utc).isoformat()}
    _MEMORY.setdefault(scope, []).append(entry)
    return _content("Memory appended.", ok=True, scope=scope, size=len(_MEMORY[scope]))


async def recall_memory(args: dict) -> dict:
    scope = str(args.get("scope", "default"))
    limit = max(1, min(int(args.get("limit", 10) or 10), 100))
    items = _MEMORY.get(scope, [])[-limit:]
    lines = [f"Memory scope={scope}, entries={len(items)}"] + [f"- {item['value']}" for item in items]
    return _content("\n".join(lines), ok=True, items=items, scope=scope)


async def forget_memory(args: dict) -> dict:
    scope = str(args.get("scope", "default"))
    deleted = len(_MEMORY.pop(scope, []))
    return _content(f"Deleted {deleted} entries.", ok=True, scope=scope, deleted=deleted)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.memory.append", "Append memory row", {"type": "object", "properties": {"scope": {"type": "string"}, "value": {"type": "string"}}, "required": ["value"]}, append_memory),
        ToolDef("hp.memory.recall", "Recall memories", {"type": "object", "properties": {"scope": {"type": "string"}, "limit": {"type": "integer"}}}, recall_memory),
        ToolDef("hp.memory.forget", "Delete memory scope", {"type": "object", "properties": {"scope": {"type": "string"}}}, forget_memory),
    ]


app = create_mcp_app(server_name="mcp-memory-store", tools=register_tools())
