"""
Outfit Variations — generate wardrobe changes for an existing avatar.

Additive module — does NOT modify any existing avatar or generation code.

Uses the same generation pipeline as /v1/avatars/generate but with the
reference image always passed as the identity anchor and the outfit_prompt
injected into the generation prompt.

Falls back to standard text-to-image if identity models aren't installed.
"""

from __future__ import annotations

import io
import logging
import random
import tempfile
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import CFG
from .availability import enabled_modes
from .schemas import AvatarResult
from .service import FeatureUnavailable
from ..services.comfyui.client import ComfyUIUnavailable
from ..services.comfyui.workflows import run_avatar_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/avatars", tags=["avatars"])


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------


class OutfitRequest(BaseModel):
    """Request to generate outfit variations for an existing avatar."""
    reference_image_url: str = Field(
        ..., description="Avatar face/identity image URL to preserve"
    )
    outfit_prompt: str = Field(
        ..., description="Clothing/setting description for the new outfit"
    )
    character_prompt: Optional[str] = Field(
        None, description="Face/body/hair description override"
    )
    negative_prompt: Optional[str] = Field(
        None,
        description="Combined negative prompt (framing + style negatives from preset)",
    )
    count: int = Field(4, ge=1, le=8)
    seed: Optional[int] = None
    generation_mode: str = Field(
        "identity",
        description="'identity' (face-preserving via InstantID), "
                    "'standard' (text-only, no reference), or "
                    "'reference' (img2img with reference colors, no face ControlNet)",
    )
    checkpoint_override: Optional[str] = Field(
        default=None,
        description="Override the workflow checkpoint (model filename).",
    )
    denoise_override: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override denoise strength. Higher values (0.95-1.0) allow "
                    "the text prompt to fully control pose/angle instead of "
                    "following the reference image composition.",
    )
    target_orientation: Optional[str] = Field(
        default=None,
        description="Post-generation orientation check: 'left' or 'right'. "
                    "When set, the generated image is inspected and mirrored "
                    "if the detected face direction does not match.",
    )


class OutfitResponse(BaseModel):
    """Response containing outfit variation results."""
    results: List[AvatarResult]
    warnings: List[str] = []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/outfits", response_model=OutfitResponse)
async def generate_outfits(req: OutfitRequest) -> OutfitResponse:
    """
    Generate outfit variations for an existing avatar.

    Uses identity-preserving generation (InstantID / PhotoMaker) when available,
    falling back to standard text-to-image if identity models aren't installed.

    The reference_image_url is used as the face anchor — the outfit_prompt
    controls what the person is wearing and the scene/setting.
    """
    if not CFG.enabled:
        raise HTTPException(503, "Avatar generator is disabled (AVATAR_ENABLED=false).")

    allowed = enabled_modes()
    warnings: List[str] = []

    # Build the combined prompt — outfit description first for maximum influence.
    # IMPORTANT: Strip clothing/outfit tokens from character_prompt so the
    # original outfit doesn't compete with the new outfit_prompt.  Keep only
    # face, body, hair, and quality descriptors for identity consistency.
    parts = []
    parts.append(req.outfit_prompt)
    if req.character_prompt:
        parts.append(_strip_outfit_tokens(req.character_prompt))
    parts.append("elegant lighting, realistic, sharp focus")
    combined_prompt = ", ".join(parts)

    # Mode selection for the ComfyUI workflow:
    #   - "identity"  → hybrid_outfit (InstantID pipeline: face ControlNet + empty latent,
    #                    text prompt fully controls pose/angle/outfit)
    #   - "standard"  → creative (text-to-image, no face preservation)
    #   - fallback    → studio_reference (basic img2img, pose locked to reference)
    #
    # hybrid_outfit is strongly preferred because it uses ApplyInstantID with
    # EmptyLatentImage, meaning the text prompt controls body pose while
    # ControlNet only anchors facial identity.  The basic img2img workflow
    # (studio_reference) bakes the reference pose into the VAE latent,
    # making non-front angles impossible.
    #
    # IMPORTANT: hybrid_outfit uses an SDXL workflow (CLIPTextEncodeSDXL).
    # If a checkpoint_override is set, it's likely an SD 1.5 model which
    # only has CLIP-L (no CLIP-G), causing a KeyError: 'g' crash.
    # Fall back to studio_reference when a checkpoint override is active.
    if req.generation_mode == "standard":
        target_mode = "creative"
    elif req.generation_mode == "reference":
        # img2img using the reference image as the latent source.
        # Preserves outfit colors/patterns from the reference without
        # face ControlNet fighting non-front angles.  The text prompt
        # controls the angle/pose via denoise_override (~0.9).
        target_mode = "studio_reference"
    elif req.checkpoint_override:
        # SD 1.5 checkpoint override → can't use SDXL workflow
        target_mode = "studio_reference"
        warnings.append(
            "Using studio_reference mode because a custom checkpoint is set. "
            "The hybrid_outfit workflow requires an SDXL model."
        )
    else:
        # Try hybrid_outfit first (proper InstantID), fall back to studio_reference
        target_mode = "hybrid_outfit"

    if target_mode not in allowed:
        target_mode = "studio_reference"
    if target_mode not in allowed:
        target_mode = "creative"
        warnings.append(
            "Identity models not available — using standard generation. "
            "Face consistency is not guaranteed. Install Avatar & Identity models "
            "for identity-preserving outfit variations."
        )
        if target_mode not in allowed:
            raise HTTPException(
                503,
                "No avatar generation modes available. "
                "Ensure ComfyUI is running and avatar models are installed.",
            )

    seeds = _make_seeds(req.seed, req.count)

    # Use high denoise (0.85) so the sampler can actually change the outfit
    # instead of reproducing the reference image structure.
    # Default img2img denoise (0.65) is too conservative for outfit changes.
    # For non-front angles, callers should pass denoise_override=1.0 so
    # the text prompt fully controls the pose/angle (the reference latent
    # is pure noise at 1.0, letting CLIP guide the composition).
    outfit_denoise = req.denoise_override if req.denoise_override is not None else 0.85

    # Build the final negative prompt.
    # The frontend already includes baseline quality negatives for view-pack
    # generation, so we only prepend the baseline when no negative is supplied.
    # Duplicating baseline tokens (lowres, blurry, …) dilutes the critical
    # angle-specific negatives (e.g. "frontal, both eyes visible") that
    # prevent wrong orientation in left/right/back views.
    baseline_negative = (
        "lowres, blurry, bad anatomy, deformed, extra fingers, "
        "missing fingers, bad hands, disfigured face, watermark, text, "
        "multiple people, duplicate, clone"
    )
    if req.negative_prompt:
        final_negative = req.negative_prompt
    else:
        final_negative = baseline_negative

    try:
        results = await run_avatar_workflow(
            comfyui_base_url=CFG.comfyui_url,
            mode=target_mode,
            prompt=combined_prompt,
            reference_image_url=req.reference_image_url,
            count=req.count,
            seed=seeds[0] if seeds else None,
            checkpoint_override=req.checkpoint_override,
            denoise_override=outfit_denoise,
            negative_prompt=final_negative,
        )

        # --- Orientation auto-fix (additive, non-destructive) ---
        # When target_orientation is "left" or "right", inspect each
        # generated image and mirror it if the face direction is wrong.
        # Safe to remove this block entirely — no other code depends on it.
        if req.target_orientation in ("left", "right"):
            results = await _apply_orientation_fix(
                results, req.target_orientation, warnings,  # type: ignore[arg-type]
            )

        return OutfitResponse(results=results, warnings=warnings)
    except ComfyUIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            500, f"Outfit generation failed: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Orientation auto-fix (additive — safe to remove this entire block)
# ---------------------------------------------------------------------------

async def _apply_orientation_fix(
    results: List[AvatarResult],
    target: str,
    warnings: List[str],
) -> List[AvatarResult]:
    """Download each result image, mirror if needed, re-upload.

    Strategy (controlled by per-direction toggles in the frontend):
    - target='left':  Always mirror — the frontend generated a right-facing
      image using the reliable right prompt.  PIL mirror → correct left.
    - target='right': Detection-based — use InsightFace to check if the
      face actually faces right; mirror only if wrong.  Falls back to
      no-op when InsightFace is not installed.
    """
    from PIL import Image as _PILImage, ImageOps as _ImageOps

    # For "right" target, try detection-based fix (needs InsightFace)
    _fix_fn = None
    if target == "right":
        try:
            from .orientation_fix import fix_image_orientation
            _fix_fn = fix_image_orientation
        except ImportError:
            logger.debug("orientation_fix unavailable, skipping right-side detection")
            return results

    fixed_results: List[AvatarResult] = []

    for item in results:
        try:
            # Fetch the generated image from ComfyUI via proxy URL
            image_url = f"{CFG.comfyui_url}/view"
            filename = item.url.replace("/comfy/view/", "").split("?")[0]
            params: dict = {"filename": filename, "type": "output"}
            if "subfolder=" in item.url:
                params["subfolder"] = item.url.split("subfolder=")[1].split("&")[0]

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(image_url, params=params)
                resp.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = Path(tmp.name)

            try:
                should_mirror = False
                method = "none"
                detected = None
                confidence = 0.0

                if target == "left":
                    # Always mirror: right-facing prompt → flip to left
                    should_mirror = True
                    method = "always_mirror_left"
                    detected = "right"
                    confidence = 1.0
                elif target == "right" and _fix_fn is not None:
                    # Detection-based fix for right
                    fix_result = _fix_fn(
                        image_path=tmp_path,
                        requested="right",
                        mode="overwrite",
                    )
                    should_mirror = fix_result.changed
                    method = fix_result.method
                    detected = fix_result.detected
                    confidence = fix_result.confidence

                if should_mirror:
                    if target == "left":
                        # Mirror in-place (fix_fn was not called for left)
                        with _PILImage.open(tmp_path) as img:
                            mirrored = _ImageOps.mirror(img)
                            mirrored.save(tmp_path)

                    # Re-upload the mirrored image to ComfyUI
                    with open(tmp_path, "rb") as f:
                        mirrored_bytes = f.read()
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        upload_resp = await client.post(
                            f"{CFG.comfyui_url}/upload/image",
                            files={"image": (filename, mirrored_bytes, "image/png")},
                            data={"overwrite": "true", "type": "output"},
                        )
                        upload_resp.raise_for_status()

                meta = {**item.metadata} if item.metadata else {}
                meta["orientation_fixed"] = should_mirror
                meta["requested_orientation"] = target
                meta["detected_orientation"] = detected
                meta["orientation_confidence"] = confidence
                meta["orientation_method"] = method
                fixed_results.append(AvatarResult(
                    url=item.url,
                    seed=item.seed,
                    metadata=meta,
                ))
            finally:
                tmp_path.unlink(missing_ok=True)

        except Exception as exc:
            logger.warning("Orientation fix failed for %s: %s", item.url, exc)
            warnings.append(f"Orientation auto-fix skipped: {exc}")
            fixed_results.append(item)

    return fixed_results


import re as _re

# Phrases that describe clothing/outfit/setting — these compete with outfit_prompt
# and must be removed from the character_prompt before combining.
_OUTFIT_STRIP_PATTERNS: list[_re.Pattern[str]] = [
    _re.compile(p, _re.IGNORECASE)
    for p in [
        # Generic outfit/clothing/fashion phrases
        r"\b(?:wearing|dressed in|outfit|attire|wardrobe)\b[^,]*",
        r"\b(?:stylish|contemporary|modern|smart|casual|elegant|executive)\s+(?:fashion|clothing|outfit|attire|look)\b[^,]*",
        # Specific garment names
        r"\b(?:blouse|shirt|top|skirt|mini skirt|pencil skirt|trousers|pants|dress|suit|blazer|jacket|coat|gown|heels|stockings|necklace|jewelry)\b[^,]*",
        # Fashion style descriptors that anchor outfits
        r"\b(?:fitted top|halter top|crop top|body-conscious|tailored|high-waisted)\b[^,]*",
        r"\b(?:clean modern aesthetic|contemporary lifestyle fashion|smart modern chic)\b[^,]*",
        # Scene/setting that should come from outfit preset instead
        r"\b(?:office|boardroom|cafe setting|studio background|nightclub)\s+(?:setting|background|scene)\b[^,]*",
    ]
]


def _strip_outfit_tokens(character_prompt: str) -> str:
    """Remove clothing/outfit/setting phrases from a character prompt.

    Keeps face, body, hair, expression, lighting, and quality descriptors
    so identity is preserved without the original outfit competing with the
    new outfit_prompt.
    """
    result = character_prompt
    for pat in _OUTFIT_STRIP_PATTERNS:
        result = pat.sub("", result)
    # Clean up leftover commas and whitespace
    result = _re.sub(r",\s*,", ",", result)
    result = _re.sub(r"^\s*,\s*", "", result)
    result = _re.sub(r"\s*,\s*$", "", result)
    result = _re.sub(r"\s{2,}", " ", result)
    return result.strip()


def _make_seeds(seed: int | None, count: int) -> List[int]:
    if seed is not None:
        return [seed + i for i in range(count)]
    return [random.randint(0, 2**31 - 1) for _ in range(count)]
