"""
Outpaint/Extend endpoint for image canvas extension.

This module provides a dedicated API endpoint for extending images
beyond their original boundaries using AI inpainting:
- Extend in any direction (left, right, up, down, or all sides)
- AI generates content that seamlessly continues the image
- Optional prompt to guide the generated content

Features:
- Multiple direction options
- Configurable extension amount
- Prompt guidance for extended content
- Automatic mask generation for extended regions
"""

from __future__ import annotations

import io
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .comfy import run_workflow
from .config import UPLOAD_DIR

router = APIRouter(prefix="/v1", tags=["outpaint"])


class ExtendDirection(str, Enum):
    """Direction to extend the image."""
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"
    ALL = "all"  # Extend all sides equally
    HORIZONTAL = "horizontal"  # Left and right
    VERTICAL = "vertical"  # Up and down


class OutpaintRequest(BaseModel):
    """Request model for outpaint endpoint."""
    image_url: str = Field(..., description="Image URL (preferably from /files)")
    direction: ExtendDirection = Field(
        default=ExtendDirection.ALL,
        description="Direction to extend: left, right, up, down, all, horizontal, vertical"
    )
    extend_pixels: int = Field(
        default=256,
        ge=64,
        le=1024,
        description="Pixels to extend (64-1024)"
    )
    prompt: Optional[str] = Field(
        default="",
        description="Optional prompt to guide the extended content"
    )
    negative_prompt: Optional[str] = Field(
        default="blurry, low quality, distorted, watermark",
        description="Negative prompt for generation"
    )


class OutpaintResponse(BaseModel):
    """Response model for outpaint endpoint."""
    media: dict
    direction_used: str
    original_size: Tuple[int, int]
    new_size: Tuple[int, int]
    extend_pixels: int


def _get_local_file_path(url: str) -> Path | None:
    """
    Extract the local file path from a backend /files/ URL.
    Returns None if not a valid local backend URL.
    """
    try:
        parsed = urlparse(url)
        if not parsed.path.startswith('/files/'):
            return None

        filename = parsed.path.replace('/files/', '', 1)
        if not filename:
            return None

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

    local_path = _get_local_file_path(url)
    if local_path:
        try:
            with Image.open(local_path) as img:
                return img.size
        except Exception as e:
            print(f"[OUTPAINT] Warning: Failed to read local file: {e}")

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content))
            img.load()
            return img.size
    except Exception as e:
        raise HTTPException(400, f"Cannot read image dimensions: {e}")


def _calculate_extension(
    orig_w: int,
    orig_h: int,
    direction: ExtendDirection,
    extend_pixels: int
) -> Tuple[int, int, int, int, int, int]:
    """
    Calculate extension amounts for each side.
    Returns (left, right, top, bottom, new_width, new_height)
    """
    left = right = top = bottom = 0

    if direction == ExtendDirection.LEFT:
        left = extend_pixels
    elif direction == ExtendDirection.RIGHT:
        right = extend_pixels
    elif direction == ExtendDirection.UP:
        top = extend_pixels
    elif direction == ExtendDirection.DOWN:
        bottom = extend_pixels
    elif direction == ExtendDirection.HORIZONTAL:
        left = right = extend_pixels
    elif direction == ExtendDirection.VERTICAL:
        top = bottom = extend_pixels
    elif direction == ExtendDirection.ALL:
        left = right = top = bottom = extend_pixels

    new_w = orig_w + left + right
    new_h = orig_h + top + bottom

    return left, right, top, bottom, new_w, new_h


@router.post("/outpaint", response_model=OutpaintResponse)
async def outpaint_image(req: OutpaintRequest):
    """
    Extend image canvas and generate content beyond borders.

    Directions:
    - **left/right/up/down**: Extend in a single direction
    - **horizontal**: Extend left and right
    - **vertical**: Extend up and down
    - **all**: Extend all four sides equally

    The endpoint:
    - Accepts an image URL
    - Extends the canvas in the specified direction
    - Uses AI inpainting to generate seamless content
    - Optionally uses a prompt to guide generation

    Guardrails:
    - Max extend pixels: 1024
    - Max output size: 4096px on any edge
    """
    print(f"[OUTPAINT] Request: direction={req.direction}, extend={req.extend_pixels}px")
    if req.prompt:
        print(f"[OUTPAINT] Prompt: {req.prompt[:50]}...")

    # Get original dimensions
    try:
        orig_w, orig_h = _get_image_size(req.image_url)
        print(f"[OUTPAINT] Original size: {orig_w}x{orig_h}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Cannot read image dimensions: {e}")

    # Calculate extension
    left, right, top, bottom, new_w, new_h = _calculate_extension(
        orig_w, orig_h, req.direction, req.extend_pixels
    )

    print(f"[OUTPAINT] Extension: left={left}, right={right}, top={top}, bottom={bottom}")
    print(f"[OUTPAINT] New size: {new_w}x{new_h}")

    # Guardrails
    max_edge = 4096
    if new_w > max_edge or new_h > max_edge:
        raise HTTPException(
            400,
            f"Output too large ({new_w}x{new_h}). Max edge is {max_edge}px. "
            f"Try a smaller extend_pixels value."
        )

    # Build prompt for outpainting
    base_prompt = req.prompt or "seamless continuation of the image, same style and lighting"
    full_prompt = f"{base_prompt}, high quality, detailed"

    # Run the outpaint workflow
    try:
        result = run_workflow("outpaint", {
            "image_path": req.image_url,
            "prompt": full_prompt,
            "negative_prompt": req.negative_prompt or "blurry, low quality, distorted, watermark",
            "extend_left": left,
            "extend_right": right,
            "extend_top": top,
            "extend_bottom": bottom,
            "width": new_w,
            "height": new_h,
            "filename_prefix": "homepilot_outpaint"
        })

        images = result.get("images", [])
        if images:
            result_url = images[0]
            print(f"[OUTPAINT] Success: {result_url}")

            return OutpaintResponse(
                media={"images": images, "videos": result.get("videos", [])},
                direction_used=req.direction.value,
                original_size=(orig_w, orig_h),
                new_size=(new_w, new_h),
                extend_pixels=req.extend_pixels
            )
        else:
            raise HTTPException(500, "No image returned from workflow")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[OUTPAINT] Workflow failed: {e}")
        raise HTTPException(500, f"Outpaint workflow failed: {e}")
