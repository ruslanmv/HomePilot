"""
Scene-video job pipeline.

PLAY-3/8. Thin, swappable bridge between the scene planner and
whichever renderer is in front of us today. Public API:

  submit_scene_job(session_id, turn_id, plan) -> SceneJob
  list_jobs(session_id, *, since_id=None) -> List[SceneJob]
  get_job(job_id) -> Optional[SceneJob]
  mark_rendering(job_id, backend_job_id)
  mark_ready(job_id, asset_id)
  mark_failed(job_id, error)

Phase-1 behaviour: ``submit_scene_job`` writes the row as
``pending`` and returns immediately. An in-process ``render_now``
helper completes jobs synchronously with a deterministic
placeholder asset id so the HTTP routes + tests can exercise the
full end-to-end flow today, without a real Animate / ComfyUI
roundtrip. Phase-2 will swap ``render_now`` for an async worker
that hits the Animate pipeline and writes the real asset id back.

No existing module is edited — the table is created defensively
on first use via ``ensure_playback_schema()``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, List, Optional

from .. import store
from .scene_planner import ScenePlan
from .schema import ensure_playback_schema


@dataclass(frozen=True)
class SceneJob:
    """One row of ``ix_scene_queue``."""

    id: str
    session_id: str
    turn_id: str
    status: str          # 'pending' | 'rendering' | 'ready' | 'failed'
    job_id: str
    asset_id: str
    prompt: str
    duration_sec: int
    error: str
    created_at: str
    updated_at: str


# ── Public surface ──────────────────────────────────────────────

def submit_scene_job(
    session_id: str, turn_id: str, plan: ScenePlan,
) -> SceneJob:
    """Enqueue a render job and return its row.

    Does not render anything — callers are expected to call
    ``render_now(job.id)`` synchronously in phase-1, or enqueue to
    an async worker in phase-2. This split keeps the write-path
    fast (single INSERT) and lets the route return a job id
    immediately before any heavy work runs.
    """
    ensure_playback_schema()
    jid = store.new_id("ixj")
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_scene_queue (
                id, session_id, turn_id, status, prompt, duration_sec
            ) VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (jid, session_id, turn_id, plan.scene_prompt, int(plan.duration_sec or 5)),
        )
        con.commit()
        row = con.execute("SELECT * FROM ix_scene_queue WHERE id = ?", (jid,)).fetchone()
    return _row_to_job(row)


def list_jobs(
    session_id: str, *, since_id: Optional[str] = None, limit: int = 50,
) -> List[SceneJob]:
    """Return jobs for a session in creation order.

    ``since_id`` acts as a cursor — rows are filtered to only those
    whose ``rowid`` is greater than the referenced job. SSE / poll
    endpoints use this to stream only new events on reconnect.
    """
    ensure_playback_schema()
    with store._conn() as con:
        if since_id:
            row = con.execute(
                "SELECT rowid FROM ix_scene_queue WHERE id = ?", (since_id,),
            ).fetchone()
            cursor_rowid = int(row["rowid"]) if row else 0
            rows = con.execute(
                "SELECT * FROM ix_scene_queue WHERE session_id = ? AND rowid > ? "
                "ORDER BY rowid ASC LIMIT ?",
                (session_id, cursor_rowid, max(1, min(limit, 500))),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM ix_scene_queue WHERE session_id = ? "
                "ORDER BY rowid ASC LIMIT ?",
                (session_id, max(1, min(limit, 500))),
            ).fetchall()
    return [_row_to_job(r) for r in rows]


def get_job(job_id: str) -> Optional[SceneJob]:
    ensure_playback_schema()
    with store._conn() as con:
        row = con.execute(
            "SELECT * FROM ix_scene_queue WHERE id = ?", (job_id,),
        ).fetchone()
    return _row_to_job(row) if row else None


def mark_rendering(job_id: str, backend_job_id: str = "") -> Optional[SceneJob]:
    return _update_status(job_id, "rendering", job_id_value=backend_job_id)


def mark_ready(job_id: str, asset_id: str) -> Optional[SceneJob]:
    return _update_status(job_id, "ready", asset_id_value=asset_id)


def mark_failed(job_id: str, error: str) -> Optional[SceneJob]:
    return _update_status(job_id, "failed", error_value=error)


# ── Phase-1 synchronous renderer ───────────────────────────────

def render_now(job_id: str, *, delay_ms: int = 0) -> Optional[SceneJob]:
    """Complete a job synchronously with a deterministic stub asset.

    This is the seam the async worker will replace in phase-2. Tests
    and the HTTP route can call this right after ``submit_scene_job``
    to drive the full state machine end-to-end without real video
    generation.

    The placeholder asset id is derived from the job id so replay
    debugging can tie a playback stream back to a specific job.
    """
    job = get_job(job_id)
    if not job:
        return None
    mark_rendering(job_id, backend_job_id=f"stub-{job_id[-8:]}")
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)
    placeholder = f"ixa_stub_{job_id[-12:]}"
    return mark_ready(job_id, asset_id=placeholder)


# ── Internals ───────────────────────────────────────────────────

def _row_to_job(row: Any) -> SceneJob:
    d = dict(row)
    return SceneJob(
        id=str(d.get("id") or ""),
        session_id=str(d.get("session_id") or ""),
        turn_id=str(d.get("turn_id") or ""),
        status=str(d.get("status") or "pending"),
        job_id=str(d.get("job_id") or ""),
        asset_id=str(d.get("asset_id") or ""),
        prompt=str(d.get("prompt") or ""),
        duration_sec=int(d.get("duration_sec") or 5),
        error=str(d.get("error") or ""),
        created_at=str(d.get("created_at") or ""),
        updated_at=str(d.get("updated_at") or ""),
    )


def _update_status(
    job_id: str, status: str, *,
    job_id_value: Optional[str] = None,
    asset_id_value: Optional[str] = None,
    error_value: Optional[str] = None,
) -> Optional[SceneJob]:
    ensure_playback_schema()
    sets: List[str] = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    args: List[Any] = [status]
    if job_id_value is not None:
        sets.append("job_id = ?"); args.append(job_id_value)
    if asset_id_value is not None:
        sets.append("asset_id = ?"); args.append(asset_id_value)
    if error_value is not None:
        sets.append("error = ?"); args.append(error_value)
    args.append(job_id)
    with store._conn() as con:
        con.execute(f"UPDATE ix_scene_queue SET {', '.join(sets)} WHERE id = ?", tuple(args))
        con.commit()
    return get_job(job_id)
