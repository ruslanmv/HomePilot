"""
Avatar Studio — orchestrator service.

Routes generation requests to the appropriate compute backend:
  - studio_random   → avatar-service microservice (StyleGAN)
  - studio_reference / studio_faceswap / creative → ComfyUI workflows

The backend never imports torch or any ML library.
"""

from __future__ import annotations

import random
from typing import List

import httpx

from .audit import audit_event
from .config import CFG
from .availability import enabled_modes
from .licensing import LicenseDenied, enforce_license
from .schemas import AvatarGenerateRequest, AvatarGenerateResponse, AvatarResult
from ..services.comfyui.client import ComfyUIUnavailable
from ..services.comfyui.workflows import run_avatar_workflow


class FeatureUnavailable(Exception):
    """Raised when the requested avatar mode is disabled or unavailable."""


async def generate(req: AvatarGenerateRequest) -> AvatarGenerateResponse:
    """Generate avatar images based on the requested mode."""
    if not CFG.enabled:
        raise FeatureUnavailable("Avatar generator is disabled (AVATAR_ENABLED=false).")

    allowed = enabled_modes()
    if req.mode not in allowed:
        raise FeatureUnavailable(
            f"Mode '{req.mode}' is unavailable. Enabled modes: {allowed}"
        )

    audit_event("generate_request", mode=req.mode, count=req.count, seed=req.seed)

    # ------------------------------------------------------------------
    # studio_random → StyleGAN microservice
    # ------------------------------------------------------------------
    if req.mode == "studio_random":
        enforce_license(commercial_ok=False, pack_id="avatar-stylegan2")

        seeds = _make_seeds(req.seed, req.count)
        payload = {
            "count": req.count,
            "seeds": seeds,
            "truncation": req.truncation,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{CFG.avatar_service_url}/v1/avatars/generate",
                json=payload,
            )
            r.raise_for_status()
            data = r.json()

        results = [
            AvatarResult(
                url=x["url"],
                seed=x.get("seed"),
                metadata=x.get("metadata", {}),
            )
            for x in data["results"]
        ]
        return AvatarGenerateResponse(
            mode=req.mode,
            results=results,
            warnings=data.get("warnings", []),
        )

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
            )
            return AvatarGenerateResponse(
                mode=req.mode,
                results=results,
                warnings=[],
            )
        except ComfyUIUnavailable as exc:
            raise FeatureUnavailable(str(exc)) from exc

    raise FeatureUnavailable(f"Unsupported mode: {req.mode}")


def _make_seeds(seed: int | None, count: int) -> List[int]:
    if seed is not None:
        return [seed + i for i in range(count)]
    return [random.randint(0, 2**31 - 1) for _ in range(count)]
