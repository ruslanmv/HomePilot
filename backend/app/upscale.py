"""
Upscale endpoint for image enhancement.

This module provides a dedicated API endpoint for upscaling images using
ComfyUI's upscale models (RealESRGAN, UltraSharp, SwinIR, etc.).

Features:
- Automatic dimension detection from source image
- Scale factor support (2x or 4x)
- Model selection (defaults to 4x-UltraSharp)
- Guardrails for max output size
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .comfy import run_workflow
from .config import UPLOAD_DIR

router = APIRouter(prefix="/v1", tags=["upscale"])


class UpscaleRequest(BaseModel):
    """Request model for upscale endpoint."""
    image_url: str = Field(..., description="Image URL (preferably from /files)")
    scale: int = Field(2, ge=1, le=4, description="Scale factor (2 or 4 recommended)")
    model: str = Field("4x-UltraSharp.pth", description="Comfy upscaler model name")
    # Optional override if client already knows dimensions
    width: Optional[int] = Field(None, description="Override output width")
    height: Optional[int] = Field(None, description="Override output height")


def _get_local_file_path(url: str) -> Path | None:
    """
    Extract the local file path from a backend /files/ URL.
    Returns None if not a valid local backend URL.
    """
    try:
        parsed = urlparse(url)
        if not parsed.path.startswith('/files/'):
            return None

        # Extract filename from /files/<filename>
        filename = parsed.path.replace('/files/', '', 1)
        if not filename:
            return None

        # Build the local path from UPLOAD_DIR
        local_path = Path(UPLOAD_DIR) / filename
        if local_path.exists():
            return local_path
        return None
    except Exception:
        return None


def _get_image_size(url: str) -> Tuple[int, int]:
    """
    Get image dimensions from URL.
    First tries to read from local filesystem, then falls back to HTTP.
    """
    try:
        from PIL import Image
    except ImportError:
        raise HTTPException(500, "PIL/Pillow not installed")

    # Try local file first
    local_path = _get_local_file_path(url)
    if local_path:
        try:
            with Image.open(local_path) as img:
                return img.size  # (width, height)
        except Exception as e:
            print(f"[UPSCALE] Warning: Failed to read local file: {e}")

    # Fall back to HTTP
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content))
            img.load()
            return img.size
    except Exception as e:
        raise HTTPException(400, f"Cannot read image dimensions: {e}")


@router.post("/upscale")
async def upscale_image(req: UpscaleRequest):
    """
    Upscale an image using ComfyUI upscale models.

    The endpoint:
    - Accepts an image URL (must be from your own /files endpoint for best performance)
    - Computes width/height automatically by reading the image
    - Calls the upscale workflow
    - Returns the same response shape as other comfy results (media.images)

    Guardrails:
    - Max output edge: 4096px
    - Max scale: 4x
    - Only accepts image URLs
    """
    print(f"[UPSCALE] Request: image_url={req.image_url}, scale={req.scale}, model={req.model}")

    # Compute width/height if not provided
    if req.width is None or req.height is None:
        try:
            w, h = _get_image_size(req.image_url)
            print(f"[UPSCALE] Detected image size: {w}x{h}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Cannot read image dimensions: {e}")

        req.width = int(w * req.scale)
        req.height = int(h * req.scale)

    print(f"[UPSCALE] Output size will be: {req.width}x{req.height}")

    # Guardrails: max output size
    max_edge = 4096
    if req.width > max_edge or req.height > max_edge:
        raise HTTPException(
            400,
            f"Requested output too large ({req.width}x{req.height}). Max edge is {max_edge}px. "
            f"Try a smaller scale factor."
        )

    # Run the upscale workflow
    try:
        result = run_workflow("upscale", {
            "image_path": req.image_url,
            "upscale_model": req.model,
            "width": req.width,
            "height": req.height,
            "filename_prefix": "homepilot_upscale"
        })
        print(f"[UPSCALE] Workflow completed successfully")
        return result
    except Exception as e:
        print(f"[UPSCALE] Workflow failed: {e}")
        raise HTTPException(500, f"Upscale workflow failed: {e}")
