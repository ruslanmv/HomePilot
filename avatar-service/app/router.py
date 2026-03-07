"""
Avatar generation endpoint.

Non-destructive design:
  - Placeholder generation remains the DEFAULT (STYLEGAN_ENABLED=false).
  - When STYLEGAN_ENABLED=true and model weights load successfully,
    real StyleGAN2 inference is used.
  - If StyleGAN fails for any reason, falls back to placeholders
    with a warning so the caller can display a notice.
  - Capabilities endpoint lets the backend/UI detect availability
    without attempting generation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from .config import CFG
from .schemas import GenerateRequest, GenerateResponse, Result
from .storage.local_store import save_placeholder_pngs, save_pil_images

router = APIRouter(tags=["avatars"])
_log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Capabilities — lightweight probe for backend/UI
# ------------------------------------------------------------------


@router.get("/avatars/capabilities")
def capabilities() -> dict:
    """Return engine availability so the backend can report to the UI."""
    from .stylegan.loader import is_loaded

    stylegan_available = is_loaded()
    reason = None
    details = None

    if not stylegan_available:
        if not CFG.stylegan_enabled:
            reason = "disabled"
            details = "STYLEGAN_ENABLED=false (default). Set to true to enable."
        elif not CFG.model_exists:
            reason = "model_not_found"
            details = f"STYLEGAN_WEIGHTS_PATH={CFG.stylegan_weights_path!r} not found on disk."
        else:
            reason = "load_failed"
            details = "Model exists but failed to load at startup. Check logs."

    _log.info(
        "[AvatarSvc] capabilities: stylegan_available=%s, reason=%s, "
        "stylegan_enabled=%s, weights_path=%r, model_exists=%s",
        stylegan_available, reason,
        CFG.stylegan_enabled, CFG.stylegan_weights_path, CFG.model_exists,
    )

    return {
        "default_engine": "stylegan" if stylegan_available else "placeholder",
        "engines": {
            "placeholder": {"available": True},
            "stylegan": {
                "available": stylegan_available,
                "reason": reason,
                "details": details,
            },
        },
    }


# ------------------------------------------------------------------
# Generate — routes to StyleGAN or placeholder
# ------------------------------------------------------------------


@router.post("/avatars/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    """Generate avatar face images.

    Uses real StyleGAN2 inference when available, otherwise falls back
    to placeholder PNGs.  The response shape is identical in both cases.
    """
    from .stylegan.loader import is_loaded

    loaded = is_loaded()
    _log.info(
        "[AvatarSvc] generate: count=%d, truncation=%.2f, "
        "stylegan_loaded=%s, stylegan_enabled=%s, weights=%r",
        req.count, req.truncation, loaded,
        CFG.stylegan_enabled, CFG.stylegan_weights_path,
    )

    # If StyleGAN is loaded, use real inference
    if loaded:
        _log.info("[AvatarSvc] Using REAL StyleGAN2 inference")
        return _generate_stylegan(req)

    # Default: placeholder generation (existing behavior)
    _log.info("[AvatarSvc] StyleGAN not loaded → placeholder mode")
    return _generate_placeholder(req)


def _generate_stylegan(req: GenerateRequest) -> GenerateResponse:
    """Real StyleGAN2 inference."""
    from .stylegan.generator import StyleGANUnavailable, generate_faces

    try:
        faces = generate_faces(
            count=req.count,
            seeds=req.seeds,
            truncation=req.truncation,
        )
        saved = save_pil_images(faces)
        return GenerateResponse(
            results=[Result(**r) for r in saved],
            warnings=[],
        )
    except StyleGANUnavailable as exc:
        _log.warning("StyleGAN unavailable, falling back to placeholder: %s", exc)
        return _generate_placeholder(req, fallback_warning=str(exc))


def _generate_placeholder(
    req: GenerateRequest,
    fallback_warning: str | None = None,
) -> GenerateResponse:
    """Placeholder PNG generation (original behavior)."""
    results = save_placeholder_pngs(req.count, req.seeds)
    warnings = []
    if fallback_warning:
        warnings.append(f"StyleGAN unavailable ({fallback_warning}). Using placeholder.")
    else:
        warnings.append("Placeholder generator in use (STYLEGAN_ENABLED=false).")
    return GenerateResponse(
        results=[Result(**r) for r in results],
        warnings=warnings,
    )
