from __future__ import annotations

from typing import Any, cast

from .adapters import (
    extract_project_type,
    list_project_scenes,
    project_music_url,
    project_voiceover_url,
    scene_duration_sec,
    scene_effect,
    scene_media_url,
    scene_subtitle_text,
    scene_title,
)
from .models import ExportKind, ProjectType, SceneSource, TimelinePlan
from .presets import get_preset


def build_timeline_plan(project_id: str, project: dict[str, Any], export_kind: ExportKind) -> TimelinePlan:
    project_type = extract_project_type(project)
    preset = get_preset(export_kind)
    raw_scenes = list_project_scenes(project)

    scenes: list[SceneSource] = []
    subtitle_items: list[dict[str, Any]] = []
    cursor = 0.0

    for i, raw in enumerate(raw_scenes):
        video_url, image_url = scene_media_url(raw)
        duration_sec = scene_duration_sec(raw, default=4.0)

        if project_type == "slides":
            kind = "image"
            source_url = image_url or video_url or ""
            effect = scene_effect(raw, fallback="ken_burns")
        else:
            if video_url:
                kind = "video"
                source_url = video_url
                effect = "none"
            else:
                kind = "image"
                source_url = image_url or ""
                effect = scene_effect(raw, fallback="ken_burns")

        scene = SceneSource(
            scene_id=str(raw.get("id") or f"scene_{i+1}"),
            title=scene_title(raw, i),
            kind=kind,
            source_url=source_url,
            duration_sec=duration_sec,
            transition_sec=float(raw.get("transition_sec") or 0.25),
            narration_url=raw.get("narration_url") or raw.get("voiceover_url"),
            music_url=raw.get("music_url"),
            subtitle_text=scene_subtitle_text(raw),
            effect=effect,
            metadata=raw,
        )
        scenes.append(scene)

        if scene.subtitle_text:
            subtitle_items.append({"start": cursor, "end": cursor + duration_sec, "text": scene.subtitle_text})
        cursor += duration_sec

    return TimelinePlan(
        project_id=project_id,
        project_type=cast(ProjectType, project_type),
        export_kind=export_kind,
        width=preset.width,
        height=preset.height,
        fps=preset.fps,
        scenes=scenes,
        voiceover_url=project_voiceover_url(project),
        music_url=project_music_url(project),
        subtitle_items=subtitle_items,
        metadata={
            "scene_count": len(scenes),
            "title": project.get("title") or project.get("name") or "Untitled Project",
        },
    )
