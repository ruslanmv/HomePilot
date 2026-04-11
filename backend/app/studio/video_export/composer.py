from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from .fetch import materialize_remote_source
from .ffmpeg import (
    burn_subtitles,
    concat_videos,
    extract_thumbnail,
    media_duration_sec,
    mux_audio,
    normalize_video_clip,
    render_image_clip,
    write_srt,
)
from .manifest import write_manifest
from .models import ExportKind, ExportResult
from .paths import make_working_files
from .planner import build_timeline_plan
from .presets import get_preset


def _safe_stem(text: str) -> str:
    chars = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            chars.append(ch)
        elif ch.isspace():
            chars.append("_")
    return "".join(chars)[:80] or "asset"


def compose_project_export(
    project_id: str,
    project: dict[str, Any],
    export_kind: ExportKind,
    public_base_url: str,
) -> ExportResult:
    export_id = uuid.uuid4().hex
    preset = get_preset(export_kind)
    wf = make_working_files(project_id, export_id=export_id)

    plan = build_timeline_plan(project_id=project_id, project=project, export_kind=export_kind)

    rendered_clips: list[Path] = []
    for idx, scene in enumerate(plan.scenes):
        if not scene.source_url:
            continue

        source_local = materialize_remote_source(
            url=scene.source_url,
            dest_dir=wf.sources_dir,
            stem=f"{idx:03d}_{_safe_stem(scene.title)}",
        )

        clip_out = wf.renders_dir / f"{idx:03d}_clip.mp4"
        if scene.kind == "video":
            normalize_video_clip(source_local, clip_out, preset)
        else:
            render_image_clip(
                image_path=source_local,
                output_path=clip_out,
                duration_sec=scene.duration_sec,
                preset=preset,
                effect=scene.effect,
            )
        rendered_clips.append(clip_out)

    if not rendered_clips:
        raise ValueError("No renderable scenes found for export")

    wf.concat_list_path.write_text(
        "".join(f"file '{clip.resolve().as_posix()}'\n" for clip in rendered_clips),
        encoding="utf-8",
    )

    stitched_path = wf.workdir / "stitched.mp4"
    concat_videos(wf.concat_list_path, stitched_path, preset)

    voiceover_local = None
    music_local = None
    if plan.voiceover_url:
        voiceover_local = materialize_remote_source(plan.voiceover_url, wf.sources_dir, "voiceover")
    if plan.music_url:
        music_local = materialize_remote_source(plan.music_url, wf.sources_dir, "music")

    muxed_path = wf.workdir / "muxed.mp4"
    mux_audio(
        video_path=stitched_path,
        output_path=muxed_path,
        voiceover_path=voiceover_local,
        music_path=music_local,
        preset=preset,
    )

    final_path = wf.final_output_path
    if plan.subtitle_items:
        write_srt(plan.subtitle_items, wf.subtitles_path)
        burn_subtitles(muxed_path, wf.subtitles_path, final_path, preset)
    else:
        shutil.copyfile(muxed_path, final_path)

    extract_thumbnail(final_path, wf.thumbnail_path)
    duration_sec = media_duration_sec(final_path)

    output_url = f"{public_base_url.rstrip('/')}/studio/exports/{project_id}/{export_id}/final.mp4"
    thumbnail_url = f"{public_base_url.rstrip('/')}/studio/exports/{project_id}/{export_id}/thumbnail.jpg"

    write_manifest(
        wf.manifest_path,
        {
            "export_id": export_id,
            "project_id": project_id,
            "kind": export_kind,
            "preset": preset.name,
            "plan": plan.to_dict(),
            "artifacts": {
                "final_output_path": str(final_path),
                "thumbnail_path": str(wf.thumbnail_path),
            },
            "duration_sec": duration_sec,
        },
    )

    return ExportResult(
        export_id=export_id,
        project_id=project_id,
        kind=export_kind,
        status="ready",
        output_path=str(final_path),
        output_url=output_url,
        thumbnail_path=str(wf.thumbnail_path),
        thumbnail_url=thumbnail_url,
        manifest_path=str(wf.manifest_path),
        duration_sec=duration_sec,
        width=preset.width,
        height=preset.height,
        fps=preset.fps,
        message="Export completed",
    )
