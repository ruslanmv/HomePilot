"""
Background operations endpoint for image editing.

This module provides a dedicated API endpoint for background manipulation:
- remove: Make background transparent using U2Net/rembg
- replace: Replace background with AI-generated content
- blur: Apply gaussian blur to background (portrait mode effect)

Features:
- Multiple background actions
- PIL-based blur (no ComfyUI needed for blur)
- ComfyUI workflow integration for remove/replace
- Automatic dimension detection
"""

from __future__ import annotations

import io
import os
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

router = APIRouter(prefix="/v1", tags=["background"])


class BackgroundAction(str, Enum):
    """Background operation action."""
    REMOVE = "remove"     # Transparent background (PNG)
    REPLACE = "replace"   # New background via prompt
    BLUR = "blur"         # Gaussian blur (portrait mode)


class BackgroundRequest(BaseModel):
    """Request model for background endpoint."""
    image_url: str = Field(..., description="Image URL (preferably from /files)")
    action: BackgroundAction = Field(
        default=BackgroundAction.REMOVE,
        description="Background action: remove, replace, or blur"
    )
    # For replace action
    prompt: Optional[str] = Field(
        default=None,
        description="Background description for replace action"
    )
    negative_prompt: Optional[str] = Field(
        default="blurry, low quality, distorted",
        description="Negative prompt for replace action"
    )
    # For blur action
    blur_strength: int = Field(
        default=15,
        ge=5,
        le=50,
        description="Blur strength for blur action (5-50)"
    )


class BackgroundResponse(BaseModel):
    """Response model for background endpoint."""
    media: dict
    action_used: str
    has_alpha: bool
    original_size: Tuple[int, int]


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


def _get_image_and_size(url: str) -> Tuple[bytes, Tuple[int, int]]:
    """
    Get image bytes and dimensions from URL.
    First tries to read from local filesystem, then falls back to HTTP.
    """
    try:
        from PIL import Image
    except ImportError:
        raise HTTPException(500, "PIL/Pillow not installed")

    local_path = _get_local_file_path(url)
    if local_path:
        try:
            with open(local_path, 'rb') as f:
                img_bytes = f.read()
            img = Image.open(io.BytesIO(img_bytes))
            return img_bytes, img.size
        except Exception as e:
            print(f"[BACKGROUND] Warning: Failed to read local file: {e}")

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            img_bytes = r.content
            img = Image.open(io.BytesIO(img_bytes))
            img.load()
            return img_bytes, img.size
    except Exception as e:
        raise HTTPException(400, f"Cannot read image: {e}")


def _save_image_to_uploads(img_bytes: bytes, prefix: str = "bg", ext: str = "png") -> str:
    """Save image bytes to uploads directory and return the URL path."""
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"
    upload_path = Path(UPLOAD_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)

    file_path = upload_path / filename
    with open(file_path, 'wb') as f:
        f.write(img_bytes)

    return f"/files/{filename}"


def _apply_blur_to_background(img_bytes: bytes, blur_strength: int) -> Tuple[bytes, bool]:
    """
    Apply gaussian blur to the background while keeping the subject sharp.
    Uses simple edge detection for subject isolation.
    Returns (result_bytes, has_alpha).
    """
    try:
        from PIL import Image, ImageFilter
        import numpy as np
    except ImportError:
        raise HTTPException(500, "PIL/Pillow or numpy not installed")

    # Load image
    img = Image.open(io.BytesIO(img_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # Create blurred version
    blurred = img.filter(ImageFilter.GaussianBlur(radius=blur_strength))

    # For a simple implementation, we'll use edge detection to create a rough mask
    # This is a basic approach - a more sophisticated version would use SAM or U2Net

    # Convert to grayscale for edge detection
    gray = img.convert('L')

    # Apply edge detection
    edges = gray.filter(ImageFilter.FIND_EDGES)

    # Dilate edges to create a mask around the subject
    edges = edges.filter(ImageFilter.MaxFilter(size=5))
    edges = edges.filter(ImageFilter.GaussianBlur(radius=10))

    # Threshold to create binary mask
    edges_array = np.array(edges)
    threshold = np.percentile(edges_array, 70)  # Keep areas with strong edges
    mask_array = (edges_array > threshold).astype(np.uint8) * 255

    # Smooth the mask
    mask = Image.fromarray(mask_array, mode='L')
    mask = mask.filter(ImageFilter.GaussianBlur(radius=20))

    # Composite: sharp subject on blurred background
    result = Image.composite(img, blurred, mask)

    # Save to bytes
    output = io.BytesIO()
    result.save(output, format='PNG')
    output.seek(0)

    return output.getvalue(), False


def _remove_background_pil(img_bytes: bytes) -> Tuple[bytes, bool]:
    """
    Remove background using rembg library (if available) or fallback.
    Returns (result_bytes, has_alpha).
    """
    try:
        from rembg import remove
        from PIL import Image

        # Use rembg to remove background
        input_img = Image.open(io.BytesIO(img_bytes))
        output_img = remove(input_img)

        # Save to bytes
        output = io.BytesIO()
        output_img.save(output, format='PNG')
        output.seek(0)

        return output.getvalue(), True

    except ImportError:
        print("[BACKGROUND] rembg not installed, falling back to ComfyUI workflow")
        return None, False


@router.post("/background", response_model=BackgroundResponse)
async def process_background(req: BackgroundRequest):
    """
    Process image background.

    Actions:
    - **remove**: Returns PNG with transparent background using U2Net/rembg
    - **replace**: Generates new background from prompt using inpainting
    - **blur**: Applies gaussian blur to background (portrait mode effect)

    The endpoint:
    - Accepts an image URL (must be from your own /files endpoint for best performance)
    - Performs the requested background operation
    - Returns the processed image URL

    Guardrails:
    - Max image size: 4096px on any edge
    - Blur strength: 5-50
    """
    print(f"[BACKGROUND] Request: action={req.action}, blur_strength={req.blur_strength}")

    # Get image and dimensions
    try:
        img_bytes, (orig_w, orig_h) = _get_image_and_size(req.image_url)
        print(f"[BACKGROUND] Detected image size: {orig_w}x{orig_h}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Cannot read image: {e}")

    # Guardrails
    max_edge = 4096
    if orig_w > max_edge or orig_h > max_edge:
        raise HTTPException(
            400,
            f"Image too large ({orig_w}x{orig_h}). Max edge is {max_edge}px."
        )

    result_url = None
    has_alpha = False

    if req.action == BackgroundAction.BLUR:
        # PIL-based blur - no ComfyUI needed
        print(f"[BACKGROUND] Applying blur with strength={req.blur_strength}")
        try:
            result_bytes, has_alpha = _apply_blur_to_background(img_bytes, req.blur_strength)
            result_url = _save_image_to_uploads(result_bytes, prefix="blur")
            print(f"[BACKGROUND] Blur completed: {result_url}")
        except Exception as e:
            print(f"[BACKGROUND] Blur failed: {e}")
            raise HTTPException(500, f"Blur operation failed: {e}")

    elif req.action == BackgroundAction.REMOVE:
        # Try PIL/rembg first, fall back to ComfyUI workflow
        print("[BACKGROUND] Removing background")

        # Try rembg first (faster, no ComfyUI needed)
        result_bytes, has_alpha = _remove_background_pil(img_bytes)

        if result_bytes:
            result_url = _save_image_to_uploads(result_bytes, prefix="nobg")
            print(f"[BACKGROUND] Background removed (rembg): {result_url}")
        else:
            # Fall back to ComfyUI workflow
            try:
                result = run_workflow("remove_background", {
                    "image_path": req.image_url,
                    "filename_prefix": "homepilot_nobg"
                })
                if result.get("media", {}).get("images"):
                    result_url = result["media"]["images"][0]
                    has_alpha = True
                    print(f"[BACKGROUND] Background removed (ComfyUI): {result_url}")
                else:
                    raise HTTPException(500, "No image returned from workflow")
            except Exception as e:
                print(f"[BACKGROUND] ComfyUI workflow failed: {e}")
                raise HTTPException(500, f"Background removal failed: {e}")

    elif req.action == BackgroundAction.REPLACE:
        # Use ComfyUI workflow for background replacement
        if not req.prompt:
            raise HTTPException(400, "prompt is required for replace action")

        print(f"[BACKGROUND] Replacing background with prompt: {req.prompt[:50]}...")

        try:
            result = run_workflow("change_background", {
                "image_path": req.image_url,
                "prompt": req.prompt,
                "negative_prompt": req.negative_prompt or "blurry, low quality, distorted",
                "width": orig_w,
                "height": orig_h,
                "filename_prefix": "homepilot_newbg"
            })
            if result.get("media", {}).get("images"):
                result_url = result["media"]["images"][0]
                has_alpha = False
                print(f"[BACKGROUND] Background replaced: {result_url}")
            else:
                raise HTTPException(500, "No image returned from workflow")
        except Exception as e:
            print(f"[BACKGROUND] Replace workflow failed: {e}")
            raise HTTPException(500, f"Background replacement failed: {e}")

    if not result_url:
        raise HTTPException(500, "Operation completed but no result was generated")

    return BackgroundResponse(
        media={"images": [result_url], "videos": []},
        action_used=req.action.value,
        has_alpha=has_alpha,
        original_size=(orig_w, orig_h)
    )
