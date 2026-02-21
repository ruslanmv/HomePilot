"""
Avatar Studio — FastAPI router.

All endpoints are additive and mounted under ``/v1``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services.comfyui.errors import ComfyUITimeout, ComfyUIWorkflowError
from .availability import enabled_modes, packs_status
from .licensing import LicenseDenied
from .schemas import (
    AvatarGenerateRequest,
    AvatarGenerateResponse,
    AvatarPackInfo,
    AvatarPacksResponse,
)
from .service import FeatureUnavailable, generate

router = APIRouter(prefix="/v1", tags=["avatars"])


# ------------------------------------------------------------------
# Pack availability
# ------------------------------------------------------------------


@router.get("/avatars/packs", response_model=AvatarPacksResponse)
def get_packs() -> AvatarPacksResponse:
    """Return installed packs, modes enabled, and licensing warnings."""
    packs = packs_status()
    enabled = enabled_modes()
    return AvatarPacksResponse(
        packs=[AvatarPackInfo(**p) for p in packs],
        enabled_modes=enabled,
    )


# ------------------------------------------------------------------
# Generate
# ------------------------------------------------------------------


@router.post("/avatars/generate", response_model=AvatarGenerateResponse)
async def generate_avatars(req: AvatarGenerateRequest) -> AvatarGenerateResponse:
    """Generate avatar images (routes to ComfyUI or avatar-service)."""
    try:
        return await generate(req)
    except FeatureUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LicenseDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ComfyUIWorkflowError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ComfyUITimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Avatar generation failed: {exc}",
        ) from exc
