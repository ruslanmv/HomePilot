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

from .edit_recipes import EditRecipe, recipe_to_variables
from .persona_assets import PersonaAssets, resolve_persona_assets
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
    edit_recipe: Optional[EditRecipe] = None,
    persona_project_id: str = "",
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

    # Persona Live Play edit path — when the composer returned an
    # edit recipe AND we can resolve the persona's canonical
    # portrait on disk, route through the matching edit workflow
    # (avatar_body_pose / avatar_inpaint_outfit / …) with the
    # portrait as the source image. This swaps txt2img for img2img
    # on a fixed anchor, which keeps identity locked across turns.
    # Any failure (no persona, no portrait committed, unknown
    # workflow file) falls back to the existing txt2img pipeline
    # so standard projects and degraded personas still render.
    persona_assets: Optional[PersonaAssets] = None
    if edit_recipe and persona_project_id:
        persona_assets = resolve_persona_assets(persona_project_id)

    if edit_recipe and persona_assets:
        workflow = edit_recipe.workflow_id
        variables = _build_edit_variables(
            scene_prompt=scene_prompt,
            duration_sec=duration_sec,
            persona_hint=persona_hint,
            persona_assets=persona_assets,
            recipe=edit_recipe,
        )
    else:
        # Pick the workflow by model ARCHITECTURE (sd15/sdxl/flux/svd/
        # ltx/wan/...) — same dispatch Imagine + Animate already use,
        # so we inherit their battle-tested workflow JSON filenames
        # instead of the hard-coded ``animate`` / ``avatar_txt2img``
        # that never matched files on disk. See _resolve_workflow().
        workflow = _resolve_workflow(cfg, media_type)
        variables = _build_variables(
            scene_prompt, duration_sec, persona_hint,
            media_type=media_type,
        )
    log.info(
        "playback_render_submit workflow=%s media_type=%s",
        workflow, media_type,
        extra={"session_id": session_id},
    )
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

# Architecture → image txt2img workflow.  Mirrors the mapping
# ``app.orchestrator`` (Imagine) already uses, so we submit the
# same JSON files that Imagine is known to render correctly.
_IMAGE_WORKFLOW_BY_ARCH: Dict[str, str] = {
    "sd15":            "txt2img-sd15-uncensored",
    "sdxl":            "txt2img",
    "flux_schnell":    "txt2img-flux-schnell",
    "flux_dev":        "txt2img-flux-dev",
    "noobai_xl":       "txt2img",
    "noobai_xl_vpred": "txt2img",
    "pony_xl":         "txt2img-pony-xl",
}

# Substring in the video model filename → img2vid workflow.
# Same dispatch Animate uses (orchestrator lines ~995-1015).
_VIDEO_WORKFLOW_BY_MODEL: List[tuple[str, str]] = [
    ("ltx",      "img2vid-ltx"),
    ("wan",      "img2vid-wan"),
    ("mochi",    "img2vid-mochi"),
    ("hunyuan",  "img2vid-hunyuan"),
    ("cogvideo", "img2vid-cogvideo"),
    ("svd",      "img2vid"),
]


def _resolve_workflow(cfg: PlaybackConfig, media_type: str) -> str:
    """Pick the ComfyUI workflow filename from the live-resolved
    model name the same way Imagine + Animate do.

    Image mode:  model filename → architecture (via
    ``model_config.get_architecture``) → workflow from the
    table above.

    Video mode:  substring match on the video model name (``svd``
    → ``img2vid``, ``ltx`` → ``img2vid-ltx``, …).

    When no match is found we fall back to the ``PlaybackConfig``
    value so operators can still override via env — but the log
    line above tells us exactly what ran either way.
    """
    from ..media_router import resolve_current_providers  # late import
    from ...model_config import detect_architecture_from_filename

    providers = resolve_current_providers()
    kind = (media_type or "").strip().lower()

    if kind == "image":
        arch = detect_architecture_from_filename(providers.image_model)
        wf = _IMAGE_WORKFLOW_BY_ARCH.get(arch)
        if wf:
            # Pony override matches Imagine's special-case (an SDXL
            # finetune with its own workflow).
            if "pony" in (providers.image_model or "").lower():
                return "txt2img-pony-xl"
            return wf
        return cfg.image_workflow  # env override / "avatar_txt2img" default

    # Video path (default).
    model_lc = (providers.video_model or "").lower()
    for needle, workflow in _VIDEO_WORKFLOW_BY_MODEL:
        if needle in model_lc:
            return workflow
    return cfg.render_workflow  # env override / "animate" default


def _build_variables(
    scene_prompt: str, duration_sec: int, persona_hint: str,
    *, media_type: str = "video",
) -> Dict[str, Any]:
    """Bundle a generic variable set accepted by typical Animate /
    ComfyUI video templates. Unknown keys are harmless — workflow
    engines ignore variables they don't reference.

    PIPE-1: includes the live-resolved image + video model names
    under several aliases (``image_model``, ``video_model``,
    ``model``, ``checkpoint``, ``ckpt_name``) so a workflow author
    can reference whichever placeholder style matches their JSON.
    ``model`` in particular is set to the ACTIVE model for the
    requested media_type, which matches the most common template
    convention in public ComfyUI workflow snippets.
    """
    import random as _random
    from ..media_router import resolve_current_providers  # late import
    from ...model_config import detect_architecture_from_filename, get_model_settings

    positive = ", ".join(p for p in (persona_hint.strip(), scene_prompt.strip()) if p)
    safe_duration = max(2, min(int(duration_sec or 5), 15))
    fps = 8

    providers = resolve_current_providers()
    kind = (media_type or "").lower()
    active_model = (
        providers.image_model if kind == "image" else providers.video_model
    )

    # Resolve safe width/height/steps/cfg the same way Imagine
    # does, so the workflow template substitution never produces
    # the "two heads" resolution mismatch SD 1.5 is famous for.
    # Defaults match Imagine's "med" preset at 1:1 when the model
    # is unknown.
    width, height, steps, cfg_scale = 512, 512, 25, 7.0
    if kind == "image":
        try:
            settings = get_model_settings(
                providers.image_model, "1:1", "med",
            )
            width = int(settings["width"])
            height = int(settings["height"])
            steps = int(settings["steps"])
            cfg_scale = float(settings["cfg"])
        except Exception:  # noqa: BLE001 — unknown model → defaults
            pass

    return {
        "prompt": positive,
        "positive_prompt": positive,
        "negative_prompt": os.getenv("DEFAULT_NEGATIVE_PROMPT", _DEFAULT_NEGATIVE),
        "seconds": safe_duration,
        "duration_sec": safe_duration,
        "frames": safe_duration * fps,
        "fps": fps,
        # --- Render tuning (required by Imagine-style workflows) ---
        "width": width,
        "height": height,
        "steps": steps,
        "cfg": cfg_scale,
        "seed": _random.randint(1, 2_147_483_646),
        "aspect_ratio": "1:1",
        "style": "photorealistic",
        # --- PIPE-1: model + endpoint bindings ---
        "image_model": providers.image_model,
        "video_model": providers.video_model,
        "model": active_model,
        "checkpoint": active_model,
        "ckpt_name": active_model,
        "comfy_base_url": providers.comfy_base_url,
    }


def _build_edit_variables(
    *, scene_prompt: str, duration_sec: int, persona_hint: str,
    persona_assets: PersonaAssets, recipe: EditRecipe,
) -> Dict[str, Any]:
    """Variables for a Persona Live Play edit run.

    Reuses the same "aliased model/checkpoint" shape the txt2img
    path emits (so a workflow author can reference whichever name
    fits their JSON) but overlays the edit-specific fields:
    source image paths, per-recipe denoise/cfg/steps, the LoRA
    stack (safety-filtered upstream), and the mask / ControlNet
    hints. Every key the workflow doesn't reference is ignored,
    so we can send a union of inputs without per-workflow code.
    """
    import random as _random
    from ..media_router import resolve_current_providers  # late import

    positive_bits: List[str] = []
    for bit in (persona_hint.strip(), persona_assets.character_prompt,
                persona_assets.outfit_prompt, scene_prompt.strip()):
        if bit and bit not in positive_bits:
            positive_bits.append(bit)
    positive = ", ".join(positive_bits)

    providers = resolve_current_providers()
    safe_duration = max(2, min(int(duration_sec or 5), 15))

    base: Dict[str, Any] = {
        "prompt": positive,
        "positive_prompt": positive,
        "negative_prompt": os.getenv("DEFAULT_NEGATIVE_PROMPT", _DEFAULT_NEGATIVE),
        "seconds": safe_duration,
        "duration_sec": safe_duration,
        "width": 1024,
        "height": 1024,
        "steps": recipe.steps,
        "cfg": recipe.cfg,
        "denoise": recipe.denoise,
        "seed": _random.randint(1, 2_147_483_646),
        "aspect_ratio": "1:1",
        "style": "photorealistic",
        # Source image for img2img / inpaint — multiple aliases so
        # a workflow LoadImage node can pick whichever placeholder
        # its JSON uses.
        "source_image": persona_assets.portrait_path,
        "input_image": persona_assets.portrait_path,
        "image": persona_assets.portrait_path,
        "reference_image": persona_assets.portrait_path,
        "persona_portrait_url": persona_assets.portrait_url,
        # Model bindings (same shape txt2img path uses).
        "image_model": providers.image_model,
        "video_model": providers.video_model,
        "model": providers.image_model,
        "checkpoint": providers.image_model,
        "ckpt_name": providers.image_model,
        "comfy_base_url": providers.comfy_base_url,
    }
    base.update(recipe_to_variables(recipe))
    return base


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
