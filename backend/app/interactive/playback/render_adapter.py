"""
Scene render adapter (phase-2 swap for video_job.render_now).

Thin, asyncio-friendly wrapper over the existing ComfyUI /
Animate pipeline at ``app.comfy.run_workflow`` + the shared
``app.asset_registry``. No new pipeline logic — just the glue
that turns a (scene_prompt, duration_sec) pair into a registered
asset id.

Every failure path returns ``None`` so the caller (video_job.
render_now) can gracefully fall back to the stub path and keep
the player's polling loop alive.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from .playback_config import PlaybackConfig, load_playback_config


log = logging.getLogger(__name__)


_DEFAULT_NEGATIVE = (
    "blurry, low quality, watermark, extra fingers, deformed, mutated, "
    "distorted face, low-res, jpeg artifacts"
)

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")
_VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".avi")


async def render_scene_async(
    *,
    scene_prompt: str,
    duration_sec: int,
    session_id: str,
    persona_hint: str = "",
    media_type: str = "video",
    config: Optional[PlaybackConfig] = None,
) -> Optional[str]:
    """Submit a workflow, extract the first usable media URL, and
    register it as a durable asset. Returns the asset id or
    ``None`` on any failure / when the render flag is off.

    ``media_type='image'`` swaps to the still-image workflow
    (``PlaybackConfig.image_workflow``) — a fast GPU-friendly path
    for operators without the VRAM budget for full video clips. The
    player already picks ``<img>`` vs ``<video>`` by file extension,
    so the change is transparent to the frontend.
    """
    cfg = config or load_playback_config()
    if not cfg.render_enabled:
        return None
    if not scene_prompt.strip():
        return None

    workflow = cfg.workflow_for(media_type)
    variables = _build_variables(scene_prompt, duration_sec, persona_hint)
    try:
        result = await asyncio.wait_for(
            _run_workflow_off_thread(workflow, variables),
            timeout=cfg.render_timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning(
            "playback_render_timeout after %.1fs (workflow=%s)",
            cfg.render_timeout_s, workflow,
            extra={"session_id": session_id},
        )
        return None
    except Exception as exc:  # noqa: BLE001 — any pipeline failure → fallback
        log.warning(
            "playback_render_error (workflow=%s): %s",
            workflow, str(exc)[:400],
            extra={"session_id": session_id},
        )
        return None

    media_url, media_kind = _select_best_media(result, prefer=media_type)
    if not media_url:
        keys = list(result.keys()) if isinstance(result, dict) else []
        log.warning(
            "playback_render_no_output — run_workflow returned keys %s but no videos/images",
            keys,
            extra={"session_id": session_id},
        )
        return None

    try:
        asset_id = _register(
            storage_key=media_url, kind=media_kind,
            session_id=session_id, scene_prompt=scene_prompt,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "playback_asset_register_failed: %s", str(exc)[:200],
            extra={"session_id": session_id},
        )
        return None
    return asset_id


# ── Internals ───────────────────────────────────────────────────

def _build_variables(
    scene_prompt: str, duration_sec: int, persona_hint: str,
) -> Dict[str, Any]:
    """Bundle a generic variable set accepted by typical Animate /
    ComfyUI video templates. Unknown keys are harmless — workflow
    engines ignore variables they don't reference.
    """
    positive = ", ".join(p for p in (persona_hint.strip(), scene_prompt.strip()) if p)
    safe_duration = max(2, min(int(duration_sec or 5), 15))
    fps = 8
    return {
        "prompt": positive,
        "positive_prompt": positive,
        "negative_prompt": os.getenv("DEFAULT_NEGATIVE_PROMPT", _DEFAULT_NEGATIVE),
        "seconds": safe_duration,
        "duration_sec": safe_duration,
        "frames": safe_duration * fps,
        "fps": fps,
    }


async def _run_workflow_off_thread(
    workflow: str, variables: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the sync, blocking run_workflow() on a worker thread
    so the asyncio event loop stays responsive. A late import
    keeps the phase-1 stub path free of the heavy comfy import.
    """
    loop = asyncio.get_running_loop()

    def _go() -> Dict[str, Any]:
        from ...comfy import run_workflow  # late import
        return run_workflow(workflow, variables) or {}

    result = await loop.run_in_executor(None, _go)
    return result if isinstance(result, dict) else {}


def _select_best_media(
    result: Dict[str, Any], *, prefer: str = "video",
) -> tuple[str, str]:
    """Pick the best output URL from a ComfyUI result.

    ``prefer='video'`` (default) grabs a clip first and falls back to
    an image — the legacy order for full video workflows that only
    occasionally produce stills. ``prefer='image'`` flips the
    priority so operators using the image-only workflow (for
    GPU-constrained feasibility tests) don't accidentally get an
    unexpected clip if the workflow also emits one. Returns
    ``(url, kind)``; both empty when nothing usable is present.
    """
    videos = _first_urls(result.get("videos"))
    images = _first_urls(result.get("images"))
    if (prefer or "").strip().lower() == "image":
        if images:
            return images[0], "image"
        if videos:
            return videos[0], "video"
        return "", ""
    if videos:
        return videos[0], "video"
    if images:
        return images[0], "image"
    return "", ""


def _first_urls(candidate: Any) -> List[str]:
    if not isinstance(candidate, list):
        return []
    out: List[str] = []
    for item in candidate:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _register(
    *, storage_key: str, kind: str,
    session_id: str, scene_prompt: str,
) -> str:
    """Register the produced asset so operators can find it later
    via the same registry that the studio + animate tabs use.
    Late import so the phase-1 stub path never pulls sqlite in.
    """
    from ...asset_registry import register_asset  # late import

    mime = _guess_mime(storage_key, kind)
    return register_asset(
        storage_key=storage_key,
        kind=kind,
        mime=mime,
        origin="interactive_playback",
        feature="animate",
        project_id=session_id,
        source_hint=_short_hint(scene_prompt),
    )


def _guess_mime(url: str, kind: str) -> str:
    lower = url.lower()
    if kind == "video":
        for ext in _VIDEO_SUFFIXES:
            if lower.endswith(ext):
                return f"video/{ext.lstrip('.')}"
        return "video/mp4"
    for ext in _IMAGE_SUFFIXES:
        if lower.endswith(ext):
            ext_name = ext.lstrip(".")
            if ext_name == "jpg":
                ext_name = "jpeg"
            return f"image/{ext_name}"
    return "image/png"


def _short_hint(text: str, *, limit: int = 120) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"
