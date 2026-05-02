from __future__ import annotations

import uuid

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_RUNS: dict[str, dict] = {}


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def run_suite(args: dict) -> dict:
    suite = str(args.get("suite", "default"))
    cases = args.get("cases") or []
    run_id = str(uuid.uuid4())
    passed = 0
    total = 0
    details = []
    for case in cases:
        total += 1
        expected = case.get("expected")
        actual = case.get("actual")
        ok = expected == actual
        if ok:
            passed += 1
        details.append({"name": case.get("name", f"case-{total}"), "ok": ok})

    pass_rate = (passed / total) if total else 1.0
    run = {"run_id": run_id, "suite": suite, "total": total, "passed": passed, "pass_rate": pass_rate, "details": details}
    _RUNS[run_id] = run
    return _content(f"Run {run_id} completed with pass_rate={pass_rate:.2%}", ok=True, run=run)


async def report(args: dict) -> dict:
    run_id = str(args.get("run_id", "")).strip()
    run = _RUNS.get(run_id)
    if not run:
        return _content("Run not found", ok=False, run_id=run_id)
    return _content(f"Suite={run['suite']} pass_rate={run['pass_rate']:.2%}", ok=True, run=run)


async def regression_gate(args: dict) -> dict:
    run_id = str(args.get("run_id", "")).strip()
    baseline = float(args.get("baseline", 0.9))
    run = _RUNS.get(run_id)
    if not run:
        return _content("Run not found", ok=False, run_id=run_id)
    passed = run["pass_rate"] >= baseline
    return _content(f"Regression gate passed={passed}", ok=passed, run_id=run_id, baseline=baseline, pass_rate=run["pass_rate"])


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.eval.run_suite", "Run eval suite", {"type": "object", "properties": {"suite": {"type": "string"}, "cases": {"type": "array", "items": {"type": "object"}}}}, run_suite),
        ToolDef("hp.eval.report", "Get run report", {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]}, report),
        ToolDef("hp.eval.regression_gate", "Compare with baseline", {"type": "object", "properties": {"run_id": {"type": "string"}, "baseline": {"type": "number"}}, "required": ["run_id"]}, regression_gate),
    ]


app = create_mcp_app(server_name="mcp-eval-runner", tools=register_tools())
