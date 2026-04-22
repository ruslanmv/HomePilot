from __future__ import annotations

from datetime import datetime, timezone

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_METRICS: list[dict] = []
_TRACES: list[dict] = []
_EVENTS: list[dict] = []


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def emit_metric(args: dict) -> dict:
    item = {"name": str(args.get("name", "metric")), "value": float(args.get("value", 1)), "labels": args.get("labels") or {}, "ts": _now()}
    _METRICS.append(item)
    return _content("Metric recorded", ok=True, metric=item, total=len(_METRICS))


async def emit_trace(args: dict) -> dict:
    item = {"trace_id": str(args.get("trace_id", "trace")), "span": str(args.get("span", "root")), "attrs": args.get("attrs") or {}, "ts": _now()}
    _TRACES.append(item)
    return _content("Trace recorded", ok=True, trace=item, total=len(_TRACES))


async def emit_event(args: dict) -> dict:
    item = {"event": str(args.get("event", "event")), "payload": args.get("payload") or {}, "ts": _now()}
    _EVENTS.append(item)
    return _content("Event recorded", ok=True, event=item, total=len(_EVENTS))


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.obs.emit_metric", "Emit metric", {"type": "object", "properties": {"name": {"type": "string"}, "value": {"type": "number"}, "labels": {"type": "object"}}}, emit_metric),
        ToolDef("hp.obs.emit_trace", "Emit trace", {"type": "object", "properties": {"trace_id": {"type": "string"}, "span": {"type": "string"}, "attrs": {"type": "object"}}}, emit_trace),
        ToolDef("hp.obs.emit_event", "Emit event", {"type": "object", "properties": {"event": {"type": "string"}, "payload": {"type": "object"}}}, emit_event),
    ]


app = create_mcp_app(server_name="mcp-observability", tools=register_tools())
