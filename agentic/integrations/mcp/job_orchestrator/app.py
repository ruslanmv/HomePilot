from __future__ import annotations

import uuid

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_JOBS: dict[str, dict] = {}


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def submit(args: dict) -> dict:
    job_id = str(uuid.uuid4())
    task = str(args.get("task", "task"))
    payload = args.get("payload") or {}
    result = {"echo": payload, "task": task}
    _JOBS[job_id] = {"job_id": job_id, "status": "completed", "task": task, "result": result}
    return _content(f"Job submitted {job_id}", ok=True, job_id=job_id, status="completed")


async def status(args: dict) -> dict:
    job_id = str(args.get("job_id", "")).strip()
    job = _JOBS.get(job_id)
    if not job:
        return _content("Job not found", ok=False, job_id=job_id)
    return _content(f"Job {job_id} status={job['status']}", ok=True, job_id=job_id, status=job["status"])


async def result(args: dict) -> dict:
    job_id = str(args.get("job_id", "")).strip()
    job = _JOBS.get(job_id)
    if not job:
        return _content("Job not found", ok=False, job_id=job_id)
    return _content("Job result ready", ok=True, job_id=job_id, result=job["result"])


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.jobs.submit", "Submit async job", {"type": "object", "properties": {"task": {"type": "string"}, "payload": {"type": "object"}}}, submit),
        ToolDef("hp.jobs.status", "Get job status", {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}, status),
        ToolDef("hp.jobs.result", "Get job result", {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}, result),
    ]


app = create_mcp_app(server_name="mcp-job-orchestrator", tools=register_tools())
