"""
In-process job tracker for asynchronous Creator Studio MP4 renders.

A render can take tens of seconds to several minutes, far longer than the
client should wait synchronously. This module:

  - Spawns a worker thread per submitted render.
  - Stores job state in memory (id, owner, status, progress, output path).
  - Lets the HTTP layer poll status and stream the finished MP4 when done.

Scope intentionally minimal — no broker, no database. A single backend
process serves the jobs it created. For multi-process deployments swap this
out for a Redis / SQS / Celery backend without touching the renderer.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .render_mp4 import (
    RenderKind,
    PlatformPreset,
    SceneInput,
    render_scenes,
)

logger = logging.getLogger(__name__)


JobStatus = str  # Literal["queued", "running", "done", "error"]


@dataclass
class RenderJob:
    """In-memory record of a single render job."""
    id: str
    user_id: str
    video_id: str
    kind: RenderKind
    preset: PlatformPreset
    status: JobStatus = "queued"
    progress: float = 0.0
    output_path: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Never leak the absolute filesystem path to the client.
        d.pop("output_path", None)
        return d


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_jobs_lock = threading.RLock()
_jobs: Dict[str, RenderJob] = {}


def _new_job_id() -> str:
    return "rj_" + secrets.token_urlsafe(16)


def _store(job: RenderJob) -> None:
    with _jobs_lock:
        _jobs[job.id] = job


def get_job(job_id: str) -> Optional[RenderJob]:
    with _jobs_lock:
        return _jobs.get(job_id)


def get_job_for_owner(job_id: str, user_id: str) -> Optional[RenderJob]:
    """Return the job only if it is owned by ``user_id``. Otherwise None.

    Callers should treat None as "not found" — we deliberately do not
    differentiate "exists but not yours" from "doesn't exist" so that
    foreign job ids cannot be probed.
    """
    job = get_job(job_id)
    if job and job.user_id == user_id:
        return job
    return None


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def _exports_dir() -> Path:
    """Resolve <UPLOAD_DIR>/studio/exports, creating it if needed."""
    from ..config import UPLOAD_DIR
    p = Path(UPLOAD_DIR) / "studio" / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def submit_render(
    *,
    user_id: str,
    video_id: str,
    kind: RenderKind,
    preset: PlatformPreset,
    scenes: List[SceneInput],
) -> RenderJob:
    """Queue a render and return its job record. Worker thread starts immediately."""
    job_id = _new_job_id()
    output_path = str(_exports_dir() / f"{job_id}.mp4")

    job = RenderJob(
        id=job_id,
        user_id=user_id,
        video_id=video_id,
        kind=kind,
        preset=preset,
        status="queued",
        output_path=output_path,
    )
    _store(job)

    t = threading.Thread(
        target=_run_job,
        args=(job_id, scenes),
        name=f"render-{job_id}",
        daemon=True,
    )
    t.start()
    return job


def _update(job_id: str, **changes: Any) -> None:
    with _jobs_lock:
        j = _jobs.get(job_id)
        if not j:
            return
        for k, v in changes.items():
            setattr(j, k, v)
        j.updated_at = time.time()


def _run_job(job_id: str, scenes: List[SceneInput]) -> None:
    """Worker entry point — invoked once per submitted render."""
    job = get_job(job_id)
    if not job:
        return

    _update(job_id, status="running", progress=0.0)

    def _on_progress(pct: float) -> None:
        _update(job_id, progress=max(0.0, min(100.0, pct)))

    try:
        result = render_scenes(
            scenes,
            preset=job.preset,
            kind=job.kind,
            output_path=job.output_path or "",
            on_progress=_on_progress,
        )
        _update(
            job_id,
            status="done",
            progress=100.0,
            duration_sec=result.duration_sec,
            width=result.width,
            height=result.height,
        )
    except Exception as exc:  # noqa: BLE001  (we want the message in the job)
        logger.exception("render job %s failed", job_id)
        _update(job_id, status="error", error=str(exc))


# ---------------------------------------------------------------------------
# Test / cleanup helpers
# ---------------------------------------------------------------------------

def _reset_for_tests() -> None:
    """Clear the in-memory registry. Tests only — never call from prod code."""
    with _jobs_lock:
        _jobs.clear()


def cleanup_finished_files(max_age_sec: float = 24 * 3600) -> int:
    """Best-effort cleanup of finished MP4 outputs older than ``max_age_sec``.

    Removes both the file on disk and the in-memory job record. Returns the
    number of files removed.
    """
    removed = 0
    cutoff = time.time() - max_age_sec
    with _jobs_lock:
        stale = [
            j for j in _jobs.values()
            if j.status in ("done", "error") and j.updated_at < cutoff
        ]
    for j in stale:
        try:
            if j.output_path and os.path.exists(j.output_path):
                os.remove(j.output_path)
                removed += 1
        except OSError:
            pass
        with _jobs_lock:
            _jobs.pop(j.id, None)
    return removed
