"""
Quick Face — fast seed-based face generation endpoint.

Additive: does NOT modify router.py or any existing endpoint.
Registered as a separate router, included in main.py alongside the
existing router.

Uses the same StyleGAN2 model already loaded at startup by the existing
code path. If StyleGAN is not loaded, falls back to fetching from
thispersondoesnotexist.com, then to placeholder.

Endpoint:
  POST /v1/avatars/quickface
"""

from __future__ import annotations

import io
import logging
import random
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .config import CFG
from .storage.local_store import save_pil_images

router = APIRouter(tags=["quickface"])
_log = logging.getLogger(__name__)

_WEB_URL = "https://thispersondoesnotexist.com"
_WEB_UA = "HomePilot-AvatarService/1.0"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class QuickFaceRequest(BaseModel):
    count: int = Field(default=4, ge=1, le=8)
    seed: Optional[int] = None
    truncation: float = Field(default=0.7, ge=0.1, le=1.0)
    output_size: int = Field(default=512, ge=256, le=1024)


class QuickFaceResult(BaseModel):
    url: str
    seed: Optional[int] = None
    engine: str = "unknown"
    generation_ms: Optional[int] = None
    metadata: Dict[str, Any] = {}


class QuickFaceResponse(BaseModel):
    engine: str
    resolution: Optional[int] = None
    results: List[QuickFaceResult]
    warnings: List[str] = []


# ---------------------------------------------------------------------------
# Capabilities extension
# ---------------------------------------------------------------------------


def quickface_status() -> Dict[str, Any]:
    """Return quickface engine availability for the capabilities endpoint."""
    from .stylegan.loader import is_loaded

    local_ok = is_loaded()
    return {
        "available": True,  # Always available (web + placeholder fallbacks)
        "local_gpu": local_ok,
        "web_fallback": True,
        "source": "stylegan2_local" if local_ok else "web_or_placeholder",
        "resolution": 1024 if local_ok else None,
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/avatars/quickface", response_model=QuickFaceResponse)
def quickface(req: QuickFaceRequest) -> QuickFaceResponse:
    """Generate photorealistic faces via the fastest available engine.

    Fallback chain:
      1. Local StyleGAN2 (GPU, sub-second, seed-reproducible)
      2. thispersondoesnotexist.com (web fetch, random)
      3. Placeholder (Pillow-drawn, always works)
    """
    from .stylegan.loader import is_loaded

    _log.info(
        "[QuickFace] generate: count=%d, seed=%s, truncation=%.2f, stylegan=%s",
        req.count, req.seed, req.truncation, is_loaded(),
    )

    # --- Strategy 1: Local StyleGAN2 ---
    if is_loaded():
        return _quickface_local(req)

    # --- Strategy 2: Web fetch ---
    try:
        return _quickface_web(req)
    except Exception as exc:
        _log.warning("[QuickFace] Web fallback failed: %s", exc)

    # --- Strategy 3: Placeholder ---
    return _quickface_placeholder(req)


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------


def _quickface_local(req: QuickFaceRequest) -> QuickFaceResponse:
    """Generate faces using in-process StyleGAN2 (fastest path)."""
    from .stylegan.generator import generate_faces, StyleGANUnavailable

    seeds = _resolve_seeds(req.seed, req.count)

    try:
        t0 = time.monotonic()
        faces = generate_faces(
            count=req.count,
            seeds=seeds,
            truncation=req.truncation,
            output_size=req.output_size,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        saved = save_pil_images(faces)
        results = [
            QuickFaceResult(
                url=r["url"],
                seed=r.get("seed"),
                engine="stylegan2_local",
                generation_ms=elapsed_ms // req.count,
                metadata=r.get("metadata", {}),
            )
            for r in saved
        ]

        return QuickFaceResponse(
            engine="stylegan2_local",
            resolution=1024,
            results=results,
        )
    except StyleGANUnavailable as exc:
        _log.warning("[QuickFace] Local StyleGAN failed: %s, trying web", exc)
        try:
            return _quickface_web(req)
        except Exception:
            return _quickface_placeholder(req)


def _quickface_web(req: QuickFaceRequest) -> QuickFaceResponse:
    """Fetch random faces from thispersondoesnotexist.com."""
    from PIL import Image

    results: list[QuickFaceResult] = []
    warnings: list[str] = []

    for i in range(req.count):
        t0 = time.monotonic()
        try:
            http_req = urllib.request.Request(
                _WEB_URL, headers={"User-Agent": _WEB_UA}
            )
            with urllib.request.urlopen(http_req, timeout=15) as resp:
                data = resp.read()

            if len(data) < 10_000:
                warnings.append(f"Face {i + 1}: response too small, skipped")
                continue

            img = Image.open(io.BytesIO(data))

            # Resize to requested output size
            if img.size != (req.output_size, req.output_size):
                img = img.resize(
                    (req.output_size, req.output_size), Image.LANCZOS
                )

            elapsed_ms = int((time.monotonic() - t0) * 1000)

            # Save via existing storage
            face_entry = [{
                "image": img,
                "seed": None,
                "metadata": {"source": "thispersondoesnotexist.com"},
            }]
            saved = save_pil_images(face_entry)

            results.append(QuickFaceResult(
                url=saved[0]["url"],
                seed=None,
                engine="web_stylegan2",
                generation_ms=elapsed_ms,
                metadata={"source": "thispersondoesnotexist.com"},
            ))

        except Exception as exc:
            warnings.append(f"Face {i + 1} web fetch failed: {exc}")

        # Polite delay between requests
        if i < req.count - 1:
            time.sleep(0.5)

    if not results:
        raise RuntimeError("All web fetches failed")

    return QuickFaceResponse(
        engine="web_stylegan2",
        resolution=1024,
        results=results,
        warnings=warnings,
    )


def _quickface_placeholder(req: QuickFaceRequest) -> QuickFaceResponse:
    """Built-in placeholder faces (always works, zero deps)."""
    from .storage.local_store import save_placeholder_pngs

    seeds = _resolve_seeds(req.seed, req.count)
    saved = save_placeholder_pngs(req.count, seeds)

    results = [
        QuickFaceResult(
            url=r["url"],
            seed=r.get("seed"),
            engine="placeholder",
            metadata=r.get("metadata", {}),
        )
        for r in saved
    ]

    return QuickFaceResponse(
        engine="placeholder",
        results=results,
        warnings=["Using placeholder faces (StyleGAN unavailable, web unreachable)."],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_seeds(base_seed: Optional[int], count: int) -> list[int]:
    """Build a list of deterministic seeds from a base seed."""
    if base_seed is not None:
        return [base_seed + i for i in range(count)]
    return [random.randint(0, 2**31 - 1) for _ in range(count)]
