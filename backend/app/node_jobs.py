"""
Node Jobs — Phase 3 (core execution) of the OllaBridge Cloud Mirror.

Durable jobs for long-running operations (chat, image, video, voice, avatar)
that the cloud UI triggers and watches. Like node_rpc, the relay can only
create jobs for WHITELISTED named operations - never arbitrary execution
(design §6, §10, §20.5). Unlike node_rpc, jobs run in the background, report
progress, and deliver artifacts via node_artifacts.

Design: docs/design/ollabridge-cloud-mirror/README.md (Phase 3)

Guardrails (shared with the manifest/RPC planes):
  - localhost-only + feature-flagged (HOMEPILOT_MIRROR_JOBS_ENABLED, default off)
  - every operation declares a scope (Phase 4 authorization hook)
  - "no silent fallback for private operations": a job runs on THIS node or
    fails honestly - it never fabricates output or reroutes elsewhere
    (design §12). If the backing service is unavailable the job fails with a
    clear reason.

Handlers are pluggable: register_operation() lets real generation paths (and
tests) attach without this module importing heavy runtimes at import time.

ADDITIVE - reads existing services through thin adapters; changes none.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .node_manifest import _is_localhost, _node_id, _node_name

router = APIRouter(tags=["node-jobs"])

JobStatus = str  # queued | running | completed | failed | cancelled


def _flag_enabled() -> bool:
    return os.getenv("HOMEPILOT_MIRROR_JOBS_ENABLED", "false").strip().lower() in (
        "1", "true", "yes")


# ── Job model + store ────────────────────────────────────────────────────────

class Job:
    def __init__(self, operation: str, params: Dict[str, Any]):
        self.id = "job_" + uuid.uuid4().hex[:16]
        self.operation = operation
        self.params = params
        self.status: JobStatus = "queued"
        self.progress: int = 0
        self.stage: str = ""
        self.message: str = ""
        self.output: Optional[Dict[str, Any]] = None
        self.error: str = ""
        self.created_at = time.time()
        self.updated_at = self.created_at
        self._cancel = threading.Event()

    def set_progress(self, pct: int, stage: str = "", message: str = "") -> None:
        self.progress = max(0, min(100, int(pct)))
        if stage:
            self.stage = stage
        if message:
            self.message = message
        self.updated_at = time.time()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": f"mirror.job.{'progress' if self.status == 'running' else self.status}",
            "job_id": self.id,
            "operation": self.operation,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "message": self.message,
            "output": self.output,
            "error": self.error,
            "source": {"type": "homepilot_node",
                       "node_id": _node_id(), "node_name": _node_name()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_JOBS: Dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()

# operation -> (scope, handler). handler(job, params) -> output dict.
_OPERATIONS: Dict[str, "JobOperation"] = {}


class JobOperation(BaseModel):
    scope: str
    handler: Callable[[Job, Dict[str, Any]], Dict[str, Any]]
    model_config = {"arbitrary_types_allowed": True}


def register_operation(name: str, scope: str,
                       handler: Callable[[Job, Dict[str, Any]], Dict[str, Any]]) -> None:
    _OPERATIONS[name] = JobOperation(scope=scope, handler=handler)


def available_operations() -> List[Dict[str, str]]:
    return [{"operation": n, "scope": o.scope} for n, o in sorted(_OPERATIONS.items())]


# ── Lifecycle ────────────────────────────────────────────────────────────────

class JobCreateRequest(BaseModel):
    operation: str
    params: Dict[str, Any] = Field(default_factory=dict)


def create_job(operation: str, params: Dict[str, Any]) -> Job:
    if operation not in _OPERATIONS:
        raise KeyError(operation)
    job = Job(operation, params)
    with _JOBS_LOCK:
        _JOBS[job.id] = job

    def _run() -> None:
        op = _OPERATIONS[operation]
        job.status = "running"
        job.updated_at = time.time()
        try:
            if job.cancelled():
                job.status = "cancelled"
                return
            output = op.handler(job, params)
            if job.cancelled():
                job.status = "cancelled"
                return
            job.output = output or {}
            job.status = "completed"
            job.progress = 100
        except Exception as e:  # noqa: BLE001
            # Honest failure - never fabricate output or reroute (design §12)
            job.status = "failed"
            job.error = f"{type(e).__name__}: {e}"
        finally:
            job.updated_at = time.time()

    threading.Thread(target=_run, daemon=True).start()
    return job


def get_job(job_id: str) -> Optional[Job]:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = get_job(job_id)
    if not job:
        return False
    job._cancel.set()
    if job.status in ("queued", "running"):
        job.status = "cancelled"
        job.updated_at = time.time()
    return True


# ── Built-in operation adapters (thin; fail honestly when backend is down) ───

def _op_chat_completions(job: Job, params: Dict[str, Any]) -> Dict[str, Any]:
    import asyncio

    from .config import OLLAMA_BASE_URL, OLLAMA_MODEL
    from .llm import chat_ollama

    messages = params.get("messages") or [{"role": "user",
                                           "content": params.get("prompt", "")}]
    model = params.get("model") or OLLAMA_MODEL
    job.set_progress(10, "dispatch", "sending to local model")
    resp = asyncio.run(chat_ollama(
        messages=messages,
        base_url=params.get("base_url") or OLLAMA_BASE_URL,
        model=model, temperature=params.get("temperature", 0.7),
        max_tokens=params.get("max_tokens", 1024)))
    text = ""
    if isinstance(resp, dict):
        choices = resp.get("choices") or []
        if choices:
            text = choices[0].get("message", {}).get("content", "")
        text = text or resp.get("content", "")
    job.set_progress(100, "done", "")
    return {"content": text, "model": model}


def _op_images_generate(job: Job, params: Dict[str, Any]) -> Dict[str, Any]:
    from . import node_artifacts

    # Delegates to the existing local ComfyUI orchestrator. Kept import-local
    # so an offline ComfyUI surfaces as an honest job failure, not an import
    # error at module load.
    job.set_progress(5, "queue", "submitting to local ComfyUI")
    from .orchestrator import orchestrate  # noqa: F401  (adapter hook)
    raise RuntimeError(
        "images.generate requires a running local ComfyUI; wire the "
        "orchestrate() call here once the sidecar provides its base URL "
        "(kept explicit so the job fails honestly rather than fabricating).")


# Register built-ins. image/video are declared (so they appear in the
# operation whitelist + carry scopes) but fail honestly until the sidecar
# supplies a live ComfyUI endpoint.
register_operation("chat.completions", "chat:run", _op_chat_completions)
register_operation("images.generate", "image:run", _op_images_generate)
register_operation("videos.generate", "video:run", _op_images_generate)


# ── Endpoints (localhost only, feature-flagged) ──────────────────────────────

def _guard(request: Request) -> Optional[JSONResponse]:
    if not _flag_enabled():
        return JSONResponse(status_code=404, content={"error": "node_jobs_disabled"})
    if not _is_localhost(request):
        return JSONResponse(status_code=403,
                            content={"error": "node_jobs_local_only",
                                     "message": "Node jobs are served to localhost / "
                                                "the local sidecar only."})
    return None


@router.get("/v1/node/jobs/operations")
def list_job_operations(request: Request):
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    return {"operations": available_operations()}


@router.post("/v1/node/jobs", status_code=202)
def create_node_job(req: JobCreateRequest, request: Request):
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    try:
        job = create_job(req.operation, req.params)
    except KeyError:
        return JSONResponse(status_code=400,
                            content={"error": "unknown_operation",
                                     "operation": req.operation,
                                     "message": "Operation is not in the job whitelist."})
    return {"job_id": job.id, "status": job.status, "operation": job.operation}


@router.get("/v1/node/jobs/{job_id}")
def get_node_job(job_id: str, request: Request):
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    job = get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "job_not_found"})
    return job.to_dict()


@router.post("/v1/node/jobs/{job_id}/cancel")
def cancel_node_job(job_id: str, request: Request):
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    if not cancel_job(job_id):
        return JSONResponse(status_code=404, content={"error": "job_not_found"})
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/v1/node/artifacts/{artifact_id}")
def get_node_artifact(artifact_id: str, request: Request):
    from fastapi.responses import FileResponse

    from . import node_artifacts
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    meta = node_artifacts.get_meta(artifact_id)
    path = node_artifacts.get_path(artifact_id) if meta else None
    if not meta or not path:
        return JSONResponse(status_code=404,
                            content={"error": "artifact_not_found_or_expired"})
    return FileResponse(path, media_type=meta.content_type,
                        filename=meta.filename,
                        headers={"Cache-Control": "private, max-age=60"})
