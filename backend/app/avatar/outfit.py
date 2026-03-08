"""
Outfit Variations — generate wardrobe changes for an existing avatar.

Additive module — does NOT modify any existing avatar or generation code.

Uses the same generation pipeline as /v1/avatars/generate but with the
reference image always passed as the identity anchor and the outfit_prompt
injected into the generation prompt.

Falls back to standard text-to-image if identity models aren't installed.
"""

from __future__ import annotations

import random
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import CFG
from .availability import enabled_modes
from .schemas import AvatarResult
from .service import FeatureUnavailable
from ..services.comfyui.client import ComfyUIUnavailable
from ..services.comfyui.workflows import run_avatar_workflow

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
        description="'identity' (face-preserving) or 'standard' (text-only fallback)",
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

    # Build the final negative prompt by combining:
    #   1. Workflow baseline (quality/artifact prevention)
    #   2. Frontend-supplied negatives (framing + style preset hints)
    # This prevents wrong clothing/nudity while preserving scene coherence.
    baseline_negative = (
        "lowres, blurry, bad anatomy, deformed, extra fingers, "
        "missing fingers, bad hands, disfigured face, watermark, text, "
        "multiple people, duplicate, clone"
    )
    if req.negative_prompt:
        final_negative = f"{baseline_negative}, {req.negative_prompt}"
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
        return OutfitResponse(results=results, warnings=warnings)
    except ComfyUIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            500, f"Outfit generation failed: {exc}"
        ) from exc


import re as _re

# ---------------------------------------------------------------------------
# Character-prompt stripping
# ---------------------------------------------------------------------------
# When generating outfits, the character_prompt describes the anchor photo
# (face, body, hair, original clothing, scene).  We strip clothing, scene,
# and professional-identity tokens so the new outfit_prompt fully controls
# what the person wears and where they stand.
#
# The patterns below match FULL comma-segments (via [^,]* anchors) so that
# orphaned adjectives like "fitted ," never remain.
# ---------------------------------------------------------------------------

_OUTFIT_STRIP_PATTERNS: list[_re.Pattern[str]] = [
    _re.compile(p, _re.IGNORECASE)
    for p in [
        # ── Generic outfit/clothing/fashion phrases ──
        r"\b(?:wearing|dressed in|outfit|attire|wardrobe)\b[^,]*",
        r"\b(?:stylish|contemporary|modern|smart|casual|elegant|executive)\s+(?:fashion|clothing|outfit|attire|look)\b[^,]*",
        # "modern stylish contemporary fashion" — multi-word fashion descriptor
        r"[^,]*\b(?:contemporary|stylish)\s+(?:contemporary\s+)?fashion\b[^,]*",

        # ── Specific garment names (match full comma-segment) ──
        r"[^,]*\b(?:blouse|shirt|top|skirt|mini skirt|pencil skirt|trousers|pants|"
        r"dress|suit|blazer|jacket|coat|gown|heels|stockings|necklace|jewelry|"
        r"sneakers|shoes|boots|sandals|sunglasses|belt|loafers|wristwatch|"
        r"clutch|earrings|bracelet|stilettos|turtleneck|sweater|jeans|chinos|"
        r"leggings|sports bra|crop top|bodysuit|lingerie|bikini|robe|"
        r"neckwear|tie|cufflinks|scarf)\b[^,]*",

        # ── Fashion style descriptors ──
        r"[^,]*\b(?:fitted top|halter top|crop top|body-conscious|tailored|"
        r"high-waisted|sheath dress|satin gown|cocktail dress)\b[^,]*",
        r"\b(?:clean modern aesthetic|contemporary lifestyle fashion|smart modern chic)\b[^,]*",
        r"\b(?:modern fashion|clean aesthetic)\b[^,]*",

        # ── Scene/setting — should come from outfit preset instead ──
        r"[^,]*\b(?:professional office|corporate office|luxury penthouse office|"
        r"modern office|office with plants|boardroom|cafe background|"
        r"studio background|nightclub|urban park|ballroom|grand ballroom|"
        r"gym with mirrors|modern gym)\b[^,]*",
        r"[^,]*\b(?:neutral studio background|clean minimal studio background|"
        r"clean studio background)\b[^,]*",

        # ── Professional/formal identity tokens ──
        # These describe the anchor's persona, not the clothing.  In NSFW or
        # casual outfit contexts they fight the target aesthetic.
        r"\bprofessional\s+appearance\b[^,]*",
        r"\bimpeccable\s+grooming\b[^,]*",
        r"\bformal\s+neckwear\b[^,]*",
        r"\bwell\s+groomed\b[^,]*",
        r"[^,]*\bclean studio lighting[^,]*",

        # ── Clothing-adjacent phrases ──
        r"\bclothing\s+and\b[^,]*",
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
    # Clean up: split on commas, trim each segment, drop empties, rejoin.
    segments = [seg.strip() for seg in result.split(",")]
    segments = [seg for seg in segments if seg]
    return ", ".join(segments)


def _make_seeds(seed: int | None, count: int) -> List[int]:
    if seed is not None:
        return [seed + i for i in range(count)]
    return [random.randint(0, 2**31 - 1) for _ in range(count)]
