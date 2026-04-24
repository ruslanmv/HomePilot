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
    edit_recipe: Optional[Any] = None,
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
    if edit_recipe and not persona_assets:
        recipe_source = _recipe_source_image(edit_recipe)
        if recipe_source:
            persona_assets = PersonaAssets(
                persona_project_id=persona_project_id or "runtime",
                portrait_url=recipe_source,
                portrait_path=recipe_source,
            )

    if edit_recipe and persona_assets:
        workflow = _recipe_workflow_id(edit_recipe)
        variables = _build_edit_variables(
            scene_prompt=scene_prompt,
            duration_sec=duration_sec,
            persona_hint=persona_hint,
            persona_assets=persona_assets,
            recipe=edit_recipe,
        )
    elif edit_recipe and not persona_assets:
        # Persona Live action path but the portrait couldn't be resolved.
        # Falling through to txt2img here produces the "blush → empty
        # room, character gone" bug: the scene prompt renders a generic
        # backdrop without the persona anchor, and the viewport swaps to
        # a frame that has no character in it. Bail out with a clear log
        # line so the polling loop treats this as a failed render and the
        # UI keeps showing the previous frame.
        log.warning(
            "playback_render_abort reason=persona_assets_missing "
            "persona_project_id=%s recipe_workflow=%s",
            persona_project_id or "(none)",
            _recipe_workflow_id(edit_recipe),
        )
        return None
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


def _pick_available_clip_model(
    *, prefer: tuple[str, ...], fallback: str,
) -> str:
    """Pick a CLIP/T5 encoder filename that ComfyUI actually has.

    Queries the cached ``/object_info`` for ``CLIPLoader.clip_name`` and
    returns the first installed model whose lowercase name contains any
    of the ``prefer`` substrings (in order). Falls back to the provided
    default when ComfyUI is unreachable or has no matching model.

    Used to resolve ``{{t5_encoder}}`` in LTX-style video workflows so
    we submit the real installed filename instead of a literal
    ``{{t5_encoder}}`` string. Lets operators keep their model
    configuration as-is even when the env/settings don't name the
    encoder explicitly — we just use whatever's on disk.
    """
    try:
        from ...comfy import _fetch_object_info  # late import
        info = _fetch_object_info()
    except Exception:  # noqa: BLE001 — ComfyUI down / partial install
        return fallback

    clip_loader = info.get("CLIPLoader", {}) if isinstance(info, dict) else {}
    input_spec = clip_loader.get("input", {}) if isinstance(clip_loader, dict) else {}
    required = input_spec.get("required", {}) if isinstance(input_spec, dict) else {}
    clip_input = required.get("clip_name", [])
    names: List[str] = []
    if isinstance(clip_input, list) and clip_input and isinstance(clip_input[0], list):
        names = [str(n) for n in clip_input[0] if isinstance(n, str)]

    if not names:
        return fallback

    for needle in prefer:
        for n in names:
            if needle.lower() in n.lower():
                return n
    # No match by preference — return the first installed encoder rather
    # than a hardcoded name that may not exist. "Use what it has."
    return names[0]


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

    # Workflow-specific template variables that older _build_variables
    # callers never populated. When the workflow template references
    # e.g. ``{{t5_encoder}}`` and we don't provide the variable, the
    # submitted prompt contains the literal string ``{{t5_encoder}}``
    # and ComfyUI rejects it with
    #   "Value not in list: clip_name: '{{t5_encoder}}' not in [...]"
    # — even though the encoder file IS installed. The fix is to pick
    # a sensible default from what ComfyUI actually reports as
    # available (via /object_info), falling back to the standard
    # filename when the query fails.
    t5_encoder = _pick_available_clip_model(
        prefer=("t5xxl_fp16", "t5xxl_fp8_e4m3fn", "t5"),
        fallback="t5xxl_fp16.safetensors",
    )
    image_path_default = os.getenv("DEFAULT_IMG2VID_SOURCE", "").strip()

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
        # --- Workflow placeholder defaults (so _missing_ workflow vars
        #     don't submit as literal "{{...}}" and get rejected) ---
        "t5_encoder": t5_encoder,
        "image_path": image_path_default,
        "denoise": 1.0,  # img2vid defaults to full denoise on the start frame
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
    persona_assets: PersonaAssets, recipe: Any,
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
        "steps": _recipe_param_int(recipe, "steps", 30),
        "cfg": _recipe_param_float(recipe, "cfg", 5.5),
        "denoise": _recipe_param_float(recipe, "denoise", 0.45),
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
    base.update(_recipe_to_variables_any(recipe))
    return base


def _recipe_workflow_id(recipe: Any) -> str:
    if isinstance(recipe, dict):
        return str(recipe.get("workflow_id") or "edit").replace(".json", "")
    return str(getattr(recipe, "workflow_id", "") or "edit").replace(".json", "")


def _recipe_source_image(recipe: Any) -> str:
    if not isinstance(recipe, dict):
        return ""
    inputs = recipe.get("inputs") if isinstance(recipe.get("inputs"), dict) else {}
    candidates = [
        str(inputs.get("source_image") or ""),
        str(inputs.get("image_ref") or ""),
        str(inputs.get("input_image") or ""),
        str(inputs.get("image") or ""),
    ]
    for raw in candidates:
        path = raw.strip()
        if not path:
            continue
        if path.startswith("/files/"):
            upload_dir = (os.getenv("UPLOAD_DIR") or "").strip()
            if not upload_dir:
                data_dir = (os.getenv("DATA_DIR") or "").strip()
                if data_dir:
                    upload_dir = os.path.join(data_dir, "uploads")
            # Final fallback: the backend's canonical config value. Root
            # cause of the "blush → empty room, character vanished" bug —
            # when UPLOAD_DIR / DATA_DIR aren't exported as env vars in
            # the serving process, this function used to return empty,
            # which dropped persona_assets to None and forced the renderer
            # into generic txt2img with only the scene prompt.
            if not upload_dir:
                try:
                    from ... import config as _app_config  # type: ignore
                    upload_dir = str(getattr(_app_config, "UPLOAD_DIR", "") or "").strip()
                except Exception:
                    upload_dir = ""
            if upload_dir:
                local_path = os.path.join(upload_dir, path[len("/files/"):])
                if os.path.isfile(local_path):
                    return local_path
        if os.path.isfile(path):
            return path
    return ""


def _recipe_param_int(recipe: Any, key: str, default: int) -> int:
    if isinstance(recipe, dict):
        params = recipe.get("params") if isinstance(recipe.get("params"), dict) else {}
        try:
            return int(params.get(key, default))
        except (TypeError, ValueError):
            return default
    try:
        return int(getattr(recipe, key))
    except Exception:
        return default


def _recipe_param_float(recipe: Any, key: str, default: float) -> float:
    if isinstance(recipe, dict):
        params = recipe.get("params") if isinstance(recipe.get("params"), dict) else {}
        try:
            return float(params.get(key, default))
        except (TypeError, ValueError):
            return default
    try:
        return float(getattr(recipe, key))
    except Exception:
        return default


def _recipe_to_variables_any(recipe: Any) -> Dict[str, Any]:
    if not isinstance(recipe, dict):
        return recipe_to_variables(recipe)
    params = recipe.get("params") if isinstance(recipe.get("params"), dict) else {}
    locks = recipe.get("locks") if isinstance(recipe.get("locks"), list) else []
    mask_kind = ""
    if "face" in locks:
        mask_kind = "face"
    elif "background" in locks:
        mask_kind = "outfit"
    elif "subject" in locks:
        mask_kind = "bg"
    return {
        "edit_mode": str(params.get("mode") or "img2img"),
        "edit_steps": _recipe_param_int(recipe, "steps", 30),
        "edit_cfg": _recipe_param_float(recipe, "cfg", 5.5),
        "edit_denoise": _recipe_param_float(recipe, "denoise", 0.45),
        "edit_controlnet": str(recipe.get("controlnet") or ""),
        "edit_mask_kind": mask_kind,
        "edit_lora_stack": list(recipe.get("loras") or []),
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
