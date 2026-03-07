"""
Hybrid avatar generation — Pydantic request/response models.

Additive module.  Defines schemas for the two-stage pipeline:
  Stage A: StyleGAN face generation (fast, seeded)
  Stage B: ComfyUI full-body/outfit from selected face (identity-preserving)

Does not modify any existing schema or model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


HybridStage = Literal["face_only", "full_body"]


# ---------------------------------------------------------------------------
# Stage A — StyleGAN face generation
# ---------------------------------------------------------------------------


class HybridFaceRequest(BaseModel):
    """Request to generate face variations via StyleGAN (or placeholder)."""

    count: int = Field(default=4, ge=1, le=8)
    seed: Optional[int] = None
    truncation: float = Field(default=0.7, ge=0.1, le=1.0)


class HybridFaceResult(BaseModel):
    url: str
    seed: Optional[int] = None
    metadata: Dict[str, Any] = {}


class HybridFaceResponse(BaseModel):
    stage: HybridStage = "face_only"
    results: List[HybridFaceResult]
    warnings: List[str] = []


# ---------------------------------------------------------------------------
# Stage B — ComfyUI full-body/outfit from selected face
# ---------------------------------------------------------------------------


class HybridFullBodyRequest(BaseModel):
    """Request to generate full-body/outfit images preserving the face identity.

    The ``face_image_url`` is the URL of the face selected in Stage A.
    The diffusion checkpoint always comes from global settings.
    """

    face_image_url: str = Field(
        ..., description="URL of the face image to preserve (from Stage A)"
    )
    count: int = Field(default=2, ge=1, le=8)

    # Wizard-derived appearance fields (all optional — sensible defaults used)
    outfit_style: Optional[str] = Field(None, description="e.g. 'Corporate Formal', 'Casual'")
    profession: Optional[str] = Field(None, description="e.g. 'Executive Secretary'")
    body_type: Optional[str] = Field(None, description="e.g. 'slim', 'average', 'athletic'")
    posture: Optional[str] = Field(None, description="e.g. 'upright', 'confident'")
    gender: Optional[str] = Field(None, description="e.g. 'female', 'male', 'neutral'")
    age_range: Optional[str] = Field(None, description="e.g. 'young_adult', 'adult', 'mature'")
    background: Optional[str] = Field(None, description="e.g. 'office', 'studio', 'outdoors'")
    lighting: Optional[str] = Field(None, description="e.g. 'soft', 'dramatic', 'natural'")
    prompt_extra: Optional[str] = Field(
        None, description="Additional text appended to the generated prompt"
    )

    # Controls
    identity_strength: float = Field(
        default=0.75, ge=0.1, le=1.0,
        description="How strongly to preserve the face identity (0.1=creative, 1.0=strict)",
    )
    seed: Optional[int] = None

    # Workflow method selection — allows switching between body generation pipelines
    workflow_method: Optional[str] = Field(
        None,
        description=(
            "Which body generation workflow to use. "
            "Options: 'default' (InstantID SDXL), 'sdxl_hq' (SDXL high-quality 1024x1536), "
            "'pose' (InstantID + OpenPose). "
            "When not set, uses 'default' (hybrid_body)."
        ),
    )
    pose_image_url: Optional[str] = Field(
        None,
        description="URL of the pose reference image (required for 'pose' workflow method).",
    )


class HybridFullBodyResult(BaseModel):
    url: str
    seed: Optional[int] = None
    metadata: Dict[str, Any] = {}


class HybridFullBodyResponse(BaseModel):
    stage: HybridStage = "full_body"
    results: List[HybridFullBodyResult]
    warnings: List[str] = []
    used_checkpoint: Optional[str] = None
