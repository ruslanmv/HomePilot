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

    # Build the combined prompt — outfit description first for maximum influence
    parts = []
    parts.append(req.outfit_prompt)
    if req.character_prompt:
        parts.append(req.character_prompt)
    parts.append("elegant lighting, realistic, sharp focus")
    combined_prompt = ", ".join(parts)

    # Prefer identity mode (studio_reference) for face preservation
    target_mode = "studio_reference"
    if target_mode not in allowed:
        # Fallback to creative mode (text-only, no face preservation)
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
    outfit_denoise = 0.85

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
        )
        return OutfitResponse(results=results, warnings=warnings)
    except ComfyUIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            500, f"Outfit generation failed: {exc}"
        ) from exc


def _make_seeds(seed: int | None, count: int) -> List[int]:
    if seed is not None:
        return [seed + i for i in range(count)]
    return [random.randint(0, 2**31 - 1) for _ in range(count)]
