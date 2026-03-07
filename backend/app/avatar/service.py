"""
Avatar Studio — orchestrator service.

Routes generation requests to the appropriate compute backend:
  - studio_random   → avatar-service microservice (StyleGAN)
                      Falls back to ComfyUI creative mode, then placeholder
  - studio_reference / studio_faceswap / creative → ComfyUI workflows

The backend never imports torch or any ML library.

Fallback chain for studio_random:
  1. Avatar-service (StyleGAN) — real inference if STYLEGAN_ENABLED + weights loaded
  2. ComfyUI creative mode — photorealistic diffusion-based face generation
  3. Built-in placeholder — procedural Pillow faces (last resort)
"""

from __future__ import annotations

import logging
import random
from typing import List

import httpx

from .audit import audit_event
from .config import CFG
from .availability import enabled_modes
from .licensing import LicenseDenied, enforce_license
from .placeholder import generate_placeholder_faces
from .schemas import AvatarGenerateRequest, AvatarGenerateResponse, AvatarResult
from ..services.comfyui.client import ComfyUIUnavailable
from ..services.comfyui.workflows import run_avatar_workflow

_log = logging.getLogger(__name__)


class FeatureUnavailable(Exception):
    """Raised when the requested avatar mode is disabled or unavailable."""


async def generate(req: AvatarGenerateRequest) -> AvatarGenerateResponse:
    """Generate avatar images based on the requested mode."""
    _log.info(
        "[AvatarGen] mode=%s count=%d seed=%s avatar_service_url=%s comfyui_url=%s",
        req.mode, req.count, req.seed, CFG.avatar_service_url, CFG.comfyui_url,
    )

    if not CFG.enabled:
        raise FeatureUnavailable("Avatar generator is disabled (AVATAR_ENABLED=false).")

    allowed = enabled_modes()
    _log.info("[AvatarGen] enabled_modes=%s", allowed)
    if req.mode not in allowed:
        raise FeatureUnavailable(
            f"Mode '{req.mode}' is unavailable. Enabled modes: {allowed}"
        )

    audit_event("generate_request", mode=req.mode, count=req.count, seed=req.seed)

    # ------------------------------------------------------------------
    # studio_random → StyleGAN microservice → ComfyUI fallback → placeholder
    # ------------------------------------------------------------------
    if req.mode == "studio_random":
        return await _generate_studio_random(req)

    # ------------------------------------------------------------------
    # ComfyUI-based modes
    # ------------------------------------------------------------------
    if req.mode == "studio_reference" and not req.reference_image_url:
        raise FeatureUnavailable(
            "From Reference mode requires a reference image. "
            "Upload a photo or switch to Face + Style mode."
        )

    if req.mode in ("studio_reference", "studio_faceswap", "creative"):
        try:
            results = await run_avatar_workflow(
                comfyui_base_url=CFG.comfyui_url,
                mode=req.mode,
                prompt=req.prompt or "",
                reference_image_url=req.reference_image_url,
                count=req.count,
                seed=req.seed,
                checkpoint_override=req.checkpoint_override,
                width_override=req.width,
                height_override=req.height,
                negative_prompt=req.negative_prompt,
            )
            return AvatarGenerateResponse(
                mode=req.mode,
                results=results,
                warnings=[],
            )
        except ComfyUIUnavailable as exc:
            raise FeatureUnavailable(str(exc)) from exc

    raise FeatureUnavailable(f"Unsupported mode: {req.mode}")


async def _generate_studio_random(req: AvatarGenerateRequest) -> AvatarGenerateResponse:
    """studio_random: StyleGAN → ComfyUI creative → placeholder fallback chain."""

    # ── Step 1: License check (fail fast — don't silently degrade) ──
    try:
        enforce_license(commercial_ok=False, pack_id="avatar-stylegan2")
        _log.info("[AvatarGen] License check passed for avatar-stylegan2")
    except LicenseDenied:
        _log.warning(
            "[AvatarGen] License denied for non-commercial StyleGAN. "
            "Set ALLOW_NON_COMMERCIAL_MODELS=true to enable. "
            "Skipping avatar-service, trying ComfyUI instead."
        )
        return await _fallback_comfyui_or_placeholder(req, reason="license_denied")

    # ── Step 2: Try avatar-service (StyleGAN microservice) ──
    stylegan_result = await _try_avatar_service(req)
    if stylegan_result is not None:
        return stylegan_result

    # ── Step 3: ComfyUI creative mode fallback ──
    return await _fallback_comfyui_or_placeholder(req, reason="avatar_service_unavailable")


async def _try_avatar_service(req: AvatarGenerateRequest) -> AvatarGenerateResponse | None:
    """Try the avatar-service microservice. Returns None if unavailable or placeholder-only."""
    url = f"{CFG.avatar_service_url}/v1/avatars/generate"
    seeds = _make_seeds(req.seed, req.count)
    payload = {"count": req.count, "seeds": seeds, "truncation": req.truncation}

    _log.info("[AvatarGen] Step 2: Trying avatar-service at %s", CFG.avatar_service_url)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError as exc:
        _log.warning("[AvatarGen] avatar-service connection refused: %s", exc)
        return None
    except httpx.TimeoutException as exc:
        _log.warning("[AvatarGen] avatar-service timed out (60s): %s", exc)
        return None
    except httpx.HTTPStatusError as exc:
        _log.warning("[AvatarGen] avatar-service HTTP error %s: %s", exc.response.status_code, exc)
        return None
    except Exception as exc:
        _log.warning("[AvatarGen] avatar-service unexpected error (%s): %s", type(exc).__name__, exc)
        return None

    warnings = data.get("warnings", [])
    results_raw = data.get("results", [])

    _log.info(
        "[AvatarGen] avatar-service responded: %d results, %d warnings: %s",
        len(results_raw), len(warnings), warnings,
    )

    # Check if avatar-service is running in placeholder mode.
    # If it returned placeholder warnings, skip these results and try ComfyUI
    # for real AI-generated faces instead.
    is_placeholder = any("placeholder" in w.lower() for w in warnings)
    if is_placeholder:
        _log.info(
            "[AvatarGen] avatar-service is in placeholder mode (STYLEGAN_ENABLED=false or "
            "model not loaded). Will try ComfyUI for real AI faces instead."
        )
        return None

    # Real StyleGAN results — use them
    results = [
        AvatarResult(url=x["url"], seed=x.get("seed"), metadata=x.get("metadata", {}))
        for x in results_raw
    ]
    _log.info("[AvatarGen] Using real StyleGAN results (%d faces)", len(results))
    return AvatarGenerateResponse(mode=req.mode, results=results, warnings=warnings)


async def _fallback_comfyui_or_placeholder(
    req: AvatarGenerateRequest,
    reason: str,
) -> AvatarGenerateResponse:
    """Fallback chain: ComfyUI creative mode → built-in placeholder."""
    from ..services.comfyui.client import comfyui_healthy

    comfy_ok = comfyui_healthy(CFG.comfyui_url)
    _log.info(
        "[AvatarGen] Step 3: ComfyUI fallback (reason=%s, comfyui_healthy=%s, url=%s)",
        reason, comfy_ok, CFG.comfyui_url,
    )

    if comfy_ok:
        try:
            prompt = req.prompt or (
                "Solo portrait photograph of a single real person, front-facing, "
                "looking directly at camera, RAW photo, photorealistic, "
                "ultra realistic skin texture, pores visible, fine facial detail, "
                "natural skin imperfections, DSLR, 85mm lens, f/1.8, "
                "professional studio lighting, 8k uhd"
            )
            _log.info("[AvatarGen] Generating via ComfyUI creative mode (prompt length=%d)", len(prompt))
            results = await run_avatar_workflow(
                comfyui_base_url=CFG.comfyui_url,
                mode="creative",
                prompt=prompt,
                reference_image_url=None,
                count=req.count,
                seed=req.seed,
                checkpoint_override=req.checkpoint_override,
                width_override=req.width,
                height_override=req.height,
                negative_prompt=req.negative_prompt,
            )
            _log.info("[AvatarGen] ComfyUI creative mode returned %d results", len(results))
            return AvatarGenerateResponse(
                mode=req.mode,
                results=results,
                warnings=["StyleGAN service not available. "
                          "Using ComfyUI for photorealistic face generation."],
            )
        except (ComfyUIUnavailable, Exception) as comfy_exc:
            _log.warning("[AvatarGen] ComfyUI creative mode failed: %s", comfy_exc)

    # ── Last resort: placeholder ──
    _log.warning(
        "[AvatarGen] Step 4: All AI generators unavailable. Using placeholder. "
        "To fix: start avatar-service with STYLEGAN_ENABLED=true, or start ComfyUI."
    )
    results = generate_placeholder_faces(
        count=req.count,
        seed=req.seed,
        truncation=req.truncation,
    )
    return AvatarGenerateResponse(
        mode=req.mode,
        results=results,
        warnings=["No AI generator available. Using placeholder faces. "
                   "Start ComfyUI or the avatar-service for real AI faces."],
    )

def _make_seeds(seed: int | None, count: int) -> List[int]:
    if seed is not None:
        return [seed + i for i in range(count)]
    return [random.randint(0, 2**31 - 1) for _ in range(count)]
