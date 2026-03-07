"""
Hybrid avatar router — two-stage StyleGAN face → ComfyUI full-body endpoints.

Additive module.  Mounts under ``/v1/avatars/hybrid`` and does NOT modify
any existing endpoint or router.

Endpoints:
  POST /v1/avatars/hybrid/face      — Stage A: generate face variations
  POST /v1/avatars/hybrid/fullbody  — Stage B: generate full-body from face
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .hybrid_schemas import (
    HybridFaceRequest,
    HybridFaceResponse,
    HybridFullBodyRequest,
    HybridFullBodyResponse,
)
from .hybrid_service import (
    HybridUnavailable,
    generate_faces,
    generate_fullbody,
)

router = APIRouter(prefix="/v1/avatars/hybrid", tags=["avatars-hybrid"])


# ------------------------------------------------------------------
# Stage A — StyleGAN face generation
# ------------------------------------------------------------------


@router.post("/face", response_model=HybridFaceResponse)
async def hybrid_generate_face(req: HybridFaceRequest) -> HybridFaceResponse:
    """Generate face variations via StyleGAN (or placeholder).

    Stage A of the hybrid pipeline.  Returns face images that the user
    can browse and select.  The selected face is then passed to Stage B
    for full-body/outfit generation.

    This endpoint does NOT affect the default avatar generation flow.
    """
    try:
        return await generate_faces(req)
    except HybridUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Hybrid face generation failed: {exc}",
        ) from exc


# ------------------------------------------------------------------
# Stage B — ComfyUI full-body/outfit from selected face
# ------------------------------------------------------------------


@router.post("/fullbody", response_model=HybridFullBodyResponse)
async def hybrid_generate_fullbody(
    req: HybridFullBodyRequest,
) -> HybridFullBodyResponse:
    """Generate full-body/outfit images preserving the selected face identity.

    Stage B of the hybrid pipeline.  Uses ComfyUI with the face from Stage A
    as the identity anchor.  The diffusion checkpoint is ALWAYS resolved from
    global settings (``DEFAULT_AVATAR_DIFFUSION_CHECKPOINT`` env var).

    Identity strength controls how strictly the face is preserved:
      - 1.0 = very strict (face dominates, less outfit creativity)
      - 0.5 = balanced (good face preservation + outfit variety)
      - 0.1 = loose (more creative, face may drift)

    This endpoint does NOT affect the default avatar generation flow.
    """
    try:
        return await generate_fullbody(req)
    except HybridUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Hybrid full-body generation failed: {exc}",
        ) from exc
