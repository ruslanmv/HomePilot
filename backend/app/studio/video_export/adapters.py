from __future__ import annotations

from typing import Any


def normalize_project_type(raw: str | None) -> str:
    raw = (raw or "").strip().lower()
    mapping = {
        "video": "youtube_video",
        "slideshow": "slides",
        "video_series": "youtube_video",
    }
    return mapping.get(raw, raw or "youtube_video")


def extract_project_type(project: dict[str, Any]) -> str:
    for key in ("projectType", "type", "project_type", "kind", "content_type"):
        if key in project and project[key]:
            return normalize_project_type(str(project[key]))
    return "youtube_video"


def list_project_scenes(project: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("scenes", "outline_scenes", "storyboard", "items"):
        value = project.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def project_voiceover_url(project: dict[str, Any]) -> str | None:
    for key in ("voiceover_url", "narration_url", "audio_url"):
        val = project.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def project_music_url(project: dict[str, Any]) -> str | None:
    for key in ("music_url", "bg_music_url", "background_music_url"):
        val = project.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def scene_media_url(scene: dict[str, Any]) -> tuple[str | None, str | None]:
    video_keys = ("video_url", "videoUrl", "clip_url", "media_url")
    image_keys = ("image_url", "imageUrl", "poster_url", "thumbnail_url")

    video_url = next((scene.get(k) for k in video_keys if isinstance(scene.get(k), str) and scene.get(k)), None)
    image_url = next((scene.get(k) for k in image_keys if isinstance(scene.get(k), str) and scene.get(k)), None)
    return video_url, image_url


def scene_duration_sec(scene: dict[str, Any], default: float = 4.0) -> float:
    for key in ("durationSec", "duration_sec", "duration", "seconds", "clip_seconds"):
        val = scene.get(key)
        try:
            if val is not None:
                return max(0.5, float(val))
        except Exception:
            pass
    return default


def scene_title(scene: dict[str, Any], index: int) -> str:
    return str(scene.get("title") or scene.get("name") or f"Scene {index + 1}")


def scene_effect(scene: dict[str, Any], fallback: str = "ken_burns") -> str:
    val = str(scene.get("effect") or scene.get("motion_effect") or fallback).strip().lower()
    return "ken_burns" if val in {"ken_burns", "kenburns", "pan_zoom"} else "none"


def scene_subtitle_text(scene: dict[str, Any]) -> str:
    for key in ("subtitle_text", "caption", "text", "narration", "voiceover_text"):
        val = scene.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""
