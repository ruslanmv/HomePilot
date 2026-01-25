# backend/app/studio/render_runner.py
"""
Background job runner for MP4 export.
Called from API via BackgroundTasks.
"""
import os
import time
import traceback
from typing import Optional

from .render_jobs import get_job, update_job
from .exports_repo import add_export
from .repo import (
    get_project,
    list_project_scenes,
    list_audio_tracks,
    list_captions,
)
from .mp4_renderer import render_project_to_mp4


def _file_url(abs_path: str, upload_dir: str) -> str:
    rel = os.path.relpath(abs_path, upload_dir).replace("\\", "/")
    return f"/files/{rel}"


def run_job(job_id: str, upload_dir: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    update_job(job_id, status="running", stage="loading", progress=0.05, startedAt=time.time())

    try:
        project = get_project(job.projectId)
        if not project:
            raise RuntimeError(f"Project not found: {job.projectId}")

        scenes = list_project_scenes(job.projectId)
        if not scenes:
            raise RuntimeError("No project scenes found. Create /studio/projects/{id}/scenes first.")

        audio = list_audio_tracks(job.projectId)
        captions = list_captions(job.projectId)

        # Render settings (use project.canvas if available)
        width = 1920
        height = 1080
        fps = 30

        if hasattr(project, 'canvas') and project.canvas:
            width = getattr(project.canvas, "width", 1920)
            height = getattr(project.canvas, "height", 1080)
            fps = getattr(project.canvas, "fps", 30)

        update_job(job_id, stage="rendering", progress=0.15)

        out_dir = os.path.join(upload_dir, "studio_exports", job.projectId, job.id)
        result = render_project_to_mp4(
            project_id=job.projectId,
            scenes=scenes,
            captions=captions,
            audio_tracks=audio,
            out_dir=out_dir,
            upload_dir=upload_dir,
            width=width,
            height=height,
            fps=fps,
            burn_in_captions=True,
        )

        mp4_path = result["mp4_path"]
        mp4_url = _file_url(mp4_path, upload_dir)
        add_export(job.projectId, "mp4", mp4_url, filename=os.path.basename(mp4_path), bytes_=os.path.getsize(mp4_path))

        if result.get("thumb_path"):
            tp = result["thumb_path"]
            if tp and os.path.exists(tp):
                turl = _file_url(tp, upload_dir)
                add_export(job.projectId, "thumbnail_jpg", turl, filename=os.path.basename(tp), bytes_=os.path.getsize(tp))

        if result.get("srt_path"):
            sp = result["srt_path"]
            if sp and os.path.exists(sp):
                surl = _file_url(sp, upload_dir)
                add_export(job.projectId, "captions_srt", surl, filename=os.path.basename(sp), bytes_=os.path.getsize(sp))

        lp = result.get("log_path")
        if lp and os.path.exists(lp):
            lurl = _file_url(lp, upload_dir)
            add_export(job.projectId, "render_log", lurl, filename=os.path.basename(lp), bytes_=os.path.getsize(lp))

        update_job(job_id, status="succeeded", stage="done", progress=1.0, outputUrl=mp4_url, finishedAt=time.time())

    except Exception as e:
        tb = traceback.format_exc()
        update_job(job_id, status="failed", stage="error", progress=1.0, error=f"{e}\n{tb}", finishedAt=time.time())
