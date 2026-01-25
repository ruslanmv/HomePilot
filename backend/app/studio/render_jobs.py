# backend/app/studio/render_jobs.py
"""
Render job management for MP4 export.
Stores job state in-memory (can be swapped for DB/Redis later).
"""
import time
import threading
from typing import Dict, Optional, List, Any

from .models import RenderJob

_LOCK = threading.Lock()
_JOBS: Dict[str, RenderJob] = {}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def create_job(project_id: str, meta: Optional[Dict[str, Any]] = None) -> RenderJob:
    now = time.time()
    job = RenderJob(
        id=_new_id("job"),
        projectId=project_id,
        kind="mp4",
        status="queued",
        progress=0.0,
        stage="queued",
        createdAt=now,
        updatedAt=now,
        meta=meta or {},
    )
    with _LOCK:
        _JOBS[job.id] = job
    return job


def get_job(job_id: str) -> Optional[RenderJob]:
    with _LOCK:
        return _JOBS.get(job_id)


def list_jobs(project_id: str) -> List[RenderJob]:
    with _LOCK:
        return [j for j in _JOBS.values() if j.projectId == project_id]


def update_job(job_id: str, **fields) -> Optional[RenderJob]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        data = job.model_dump()
        data.update(fields)
        data["updatedAt"] = time.time()
        _JOBS[job_id] = RenderJob(**data)
        return _JOBS[job_id]
