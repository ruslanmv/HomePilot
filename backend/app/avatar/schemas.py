"""
Avatar Studio — Pydantic request / response models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Mode literal
# ---------------------------------------------------------------------------

AvatarMode = Literal[
    "creative",           # text-only → ComfyUI diffusion
    "studio_random",      # StyleGAN microservice (no reference image)
    "studio_reference",   # InstantID / PhotoMaker (identity-preserving)
    "studio_faceswap",    # body prompt → swap face → restore
]

# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


class AvatarGenerateRequest(BaseModel):
    mode: AvatarMode = "studio_reference"
    count: int = Field(default=4, ge=1, le=8)
    seed: Optional[int] = None
    truncation: float = Field(default=0.7, ge=0.1, le=1.0)
    prompt: Optional[str] = None
    reference_image_url: Optional[str] = None
    persona_id: Optional[str] = None


class AvatarResult(BaseModel):
    url: str
    seed: Optional[int] = None
    metadata: Dict[str, Any] = {}


class AvatarGenerateResponse(BaseModel):
    mode: AvatarMode
    results: List[AvatarResult]
    warnings: List[str] = []


# ---------------------------------------------------------------------------
# Packs
# ---------------------------------------------------------------------------


class AvatarPackInfo(BaseModel):
    id: str
    title: str
    installed: bool
    license: str
    commercial_ok: bool
    modes_enabled: List[str]
    notes: Optional[str] = None


class AvatarPacksResponse(BaseModel):
    packs: List[AvatarPackInfo]
    enabled_modes: List[str]


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------


class AvatarLibraryItem(BaseModel):
    id: str
    url: str
    seed: Optional[int] = None
    mode: Optional[AvatarMode] = None
    persona_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
