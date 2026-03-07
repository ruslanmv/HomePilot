"""
Hybrid avatar service — two-stage StyleGAN face → ComfyUI full-body.

Additive module.  Does NOT modify existing generation or outfit code.

Stage A: Calls avatar-service for StyleGAN face generation (or placeholder).
Stage B: Calls ``run_avatar_workflow()`` with ``hybrid_body`` mode, which uses
         the ``avatar_body_from_face.json`` workflow — a txt2img pipeline with
         InstantID for face identity preservation.

The full-body stage generates a completely new full-body image from scratch
(EmptyLatentImage at 1024x1536 SDXL) while using InstantID to preserve the face.
This is fundamentally different from img2img — the model creates the body,
outfit, and scene from the prompt while only locking the face identity.

The ``workflow_method`` field allows switching between body generation pipelines:
  - ``default`` → hybrid_body (InstantID SDXL, balanced)
  - ``sdxl_hq`` → hybrid_sdxl_body (SDXL high-quality)
  - ``pose``    → hybrid_body_pose (InstantID + OpenPose)

  - ``identity_strength`` maps directly to the InstantID weight (0.0–1.0)
  - Full denoise (1.0) since we're generating from scratch, not editing
  - Negative prompt from the prompt builder reduces common artifacts
"""

from __future__ import annotations

import logging
import random
from typing import List, Optional

import httpx

from .config import CFG
from .availability import enabled_modes
from .hybrid_prompt import build_fullbody_prompt
from .hybrid_schemas import (
    HybridFaceRequest,
    HybridFaceResponse,
    HybridFaceResult,
    HybridFullBodyRequest,
    HybridFullBodyResponse,
    HybridFullBodyResult,
)
from ..services.comfyui.client import ComfyUIUnavailable
from ..services.comfyui.workflows import run_avatar_workflow

_log = logging.getLogger(__name__)


class HybridUnavailable(RuntimeError):
    """Raised when a hybrid pipeline stage cannot proceed."""


# ---------------------------------------------------------------------------
# Stage A — StyleGAN face generation
# ---------------------------------------------------------------------------


async def generate_faces(req: HybridFaceRequest) -> HybridFaceResponse:
    """Generate face variations via the avatar-service (StyleGAN or placeholder).

    Additive: delegates to the same avatar-service endpoint that
    ``service.generate()`` uses for ``studio_random`` mode.
    """
    seeds = _make_seeds(req.seed, req.count)
    payload = {
        "count": req.count,
        "seeds": seeds,
        "truncation": req.truncation,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{CFG.avatar_service_url}/v1/avatars/generate",
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError:
        raise HybridUnavailable(
            f"Avatar service at {CFG.avatar_service_url} is not running. "
            "Start the avatar-service or use ComfyUI modes instead."
        )
    except Exception as exc:
        raise HybridUnavailable(f"Face generation failed: {exc}") from exc

    results = [
        HybridFaceResult(
            url=x["url"],
            seed=x.get("seed"),
            metadata=x.get("metadata", {}),
        )
        for x in data.get("results", [])
    ]

    return HybridFaceResponse(
        results=results,
        warnings=data.get("warnings", []),
    )


# ---------------------------------------------------------------------------
# Stage B — ComfyUI full-body/outfit from selected face
# ---------------------------------------------------------------------------


async def generate_fullbody(req: HybridFullBodyRequest) -> HybridFullBodyResponse:
    """Generate full-body/outfit images preserving the selected face identity.

    Uses the EXISTING ``run_avatar_workflow()`` with ``studio_reference`` mode.
    The diffusion checkpoint is resolved from global settings — never from
    the per-request ``checkpoint_override`` field.

    This follows the same pattern as ``outfit.py`` but builds the prompt
    from wizard appearance fields instead of a raw outfit_prompt string.
    """
    if not CFG.enabled:
        raise HybridUnavailable("Avatar generator is disabled (AVATAR_ENABLED=false).")

    allowed = enabled_modes()
    warnings: List[str] = []

    # Build the combined prompt from wizard fields
    positive, negative = build_fullbody_prompt(
        outfit_style=req.outfit_style,
        profession=req.profession,
        body_type=req.body_type,
        posture=req.posture,
        gender=req.gender,
        age_range=req.age_range,
        background=req.background,
        lighting=req.lighting,
        prompt_extra=req.prompt_extra,
    )

    # Select body generation workflow based on workflow_method.
    # All InstantID workflows now use SDXL (ControlNet is SDXL-only).
    _METHOD_TO_MODE = {
        "default": "hybrid_body",
        "sdxl_hq": "hybrid_sdxl_body",
        "pose": "hybrid_body_pose",
    }
    method = (req.workflow_method or "default").strip().lower()
    target_mode = _METHOD_TO_MODE.get(method, "hybrid_body")

    # Resolve checkpoint from global config — but ONLY for non-SDXL workflows.
    # All body generation workflows use SDXL + InstantID, and the workflow
    # templates already specify the correct SDXL checkpoint.  Injecting an
    # SD1.5 checkpoint (e.g. DreamShaper) into an SDXL workflow causes
    # ComfyUI to crash with tensor shape mismatches.
    _SDXL_MODES = {"hybrid_body", "hybrid_sdxl_body", "hybrid_body_pose"}
    if target_mode in _SDXL_MODES:
        checkpoint = None
        _log.debug("Skipping checkpoint override for SDXL workflow %s", target_mode)
    else:
        checkpoint = _resolve_global_checkpoint()

    if not allowed:
        raise HybridUnavailable(
            "No avatar generation modes available. "
            "Ensure ComfyUI is running and avatar models are installed."
        )

    _log.info(
        "Hybrid full-body: mode=%s, identity_strength=%.2f, checkpoint=%s, count=%d",
        target_mode, req.identity_strength, checkpoint, req.count,
    )

    try:
        avatar_results = await run_avatar_workflow(
            comfyui_base_url=CFG.comfyui_url,
            mode=target_mode,
            prompt=positive,
            reference_image_url=req.face_image_url,
            count=req.count,
            seed=req.seed,
            checkpoint_override=checkpoint,
            identity_strength=req.identity_strength,
            negative_prompt=negative,
            pose_image_url=req.pose_image_url,
        )
    except (ComfyUIUnavailable, Exception) as exc:
        # If a specialized workflow fails (e.g. pose requiring OpenPose model),
        # fall back to the default body workflow before giving up.
        fallback_mode = "hybrid_body"
        if target_mode != fallback_mode:
            _log.warning(
                "Workflow %s failed (%s), falling back to %s",
                target_mode, exc, fallback_mode,
            )
            warnings.append(
                f"{method} workflow failed ({exc}). "
                f"Fell back to default body generation."
            )
            try:
                avatar_results = await run_avatar_workflow(
                    comfyui_base_url=CFG.comfyui_url,
                    mode=fallback_mode,
                    prompt=positive,
                    reference_image_url=req.face_image_url,
                    count=req.count,
                    seed=req.seed,
                    checkpoint_override=checkpoint,
                    identity_strength=req.identity_strength,
                    negative_prompt=negative,
                )
            except ComfyUIUnavailable as exc2:
                raise HybridUnavailable(str(exc2)) from exc2
            except Exception as exc2:
                raise HybridUnavailable(f"Full-body generation failed: {exc2}") from exc2
        elif isinstance(exc, ComfyUIUnavailable):
            raise HybridUnavailable(str(exc)) from exc
        else:
            raise HybridUnavailable(f"Full-body generation failed: {exc}") from exc

    results = [
        HybridFullBodyResult(
            url=r.url,
            seed=r.seed,
            metadata={
                **(r.metadata or {}),
                "engine": "comfyui",
                "pipeline": "hybrid",
                "identity_strength": req.identity_strength,
                "prompt": positive,
            },
        )
        for r in avatar_results
    ]

    return HybridFullBodyResponse(
        results=results,
        warnings=warnings,
        used_checkpoint=checkpoint,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_seeds(seed: Optional[int], count: int) -> List[int]:
    if seed is not None:
        return [seed + i for i in range(count)]
    return [random.randint(0, 2**31 - 1) for _ in range(count)]


def _resolve_global_checkpoint() -> Optional[str]:
    """Resolve the diffusion checkpoint from global settings.

    Checks the environment variable ``DEFAULT_AVATAR_DIFFUSION_CHECKPOINT``.
    If not set, returns None (the workflow template's default is used).
    """
    import os

    ckpt = os.getenv("DEFAULT_AVATAR_DIFFUSION_CHECKPOINT", "").strip()
    if ckpt:
        return ckpt

    # Fallback: check the general COMFYUI_DEFAULT_CHECKPOINT
    ckpt = os.getenv("COMFYUI_DEFAULT_CHECKPOINT", "").strip()
    if ckpt:
        return ckpt

    return None
