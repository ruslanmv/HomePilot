from __future__ import annotations

import contextlib
import io
import uuid

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_RUNS: dict[str, dict] = {}
_ALLOWED_BUILTINS = {"print": print, "len": len, "sum": sum, "min": min, "max": max, "range": range}


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def code_run(args: dict) -> dict:
    language = str(args.get("language", "python")).lower()
    code = str(args.get("code", ""))
    if language != "python":
        return _content("Only python is supported in this MCP sandbox implementation.", ok=False)

    run_id = str(uuid.uuid4())
    stdout = io.StringIO()
    error = None
    status = "completed"
    try:
        with contextlib.redirect_stdout(stdout):
            exec(code, {"__builtins__": _ALLOWED_BUILTINS}, {})
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        status = "failed"

    _RUNS[run_id] = {"run_id": run_id, "status": status, "stdout": stdout.getvalue(), "error": error}
    return _content(f"Run {run_id} status={status}", ok=status == "completed", run_id=run_id)


async def code_status(args: dict) -> dict:
    run_id = str(args.get("run_id", "")).strip()
    run = _RUNS.get(run_id)
    if not run:
        return _content("Run not found", ok=False, run_id=run_id)
    return _content(f"Run {run_id} status={run['status']}", ok=True, run_id=run_id, status=run["status"])


async def code_result(args: dict) -> dict:
    run_id = str(args.get("run_id", "")).strip()
    run = _RUNS.get(run_id)
    if not run:
        return _content("Run not found", ok=False, run_id=run_id)
    text = run["stdout"] or "<no output>"
    if run["error"]:
        text += f"\nERROR: {run['error']}"
    return _content(text, ok=run["status"] == "completed", **run)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.code.run", "Execute code safely", {"type": "object", "properties": {"language": {"type": "string"}, "code": {"type": "string"}}, "required": ["code"]}, code_run),
        ToolDef("hp.code.status", "Execution status", {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]}, code_status),
        ToolDef("hp.code.result", "Execution result", {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]}, code_result),
    ]


app = create_mcp_app(server_name="mcp-code-sandbox", tools=register_tools())
