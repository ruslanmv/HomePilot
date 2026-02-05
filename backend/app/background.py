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
    Apply gaussian blur to the entire image (simple blur effect).
    For true background-only blur, use ComfyUI workflow with segmentation.
    Returns (result_bytes, has_alpha).
    """
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        raise HTTPException(500, "PIL/Pillow not installed")

    # Load image
    img = Image.open(io.BytesIO(img_bytes))
    if img.mode not in ('RGB', 'RGBA'):
        img = img.convert('RGB')

    # Apply gaussian blur
    blurred = img.filter(ImageFilter.GaussianBlur(radius=blur_strength))

    # Save to bytes
    output = io.BytesIO()
    blurred.save(output, format='PNG')
    output.seek(0)

    return output.getvalue(), False


def _check_rembg_available() -> bool:
    """Check if rembg library is available."""
    try:
        from rembg import remove
        return True
    except ImportError:
        return False


def _check_onnx_rembg_available() -> bool:
    """Check if we can do ONNX-based background removal (Python 3.11+ compatible)."""
    try:
        import onnxruntime
        from PIL import Image
        import numpy as np
        return True
    except ImportError:
        return False


def _get_u2net_model_path() -> Optional[Path]:
    """
    Get path to U2Net ONNX model, downloading if necessary.

    Checks these locations in order:
    1. ComfyUI models path: models/comfy/rembg/u2net.onnx (from make download-edit)
    2. User cache: ~/.u2net/u2net.onnx (auto-downloaded if needed)

    Uses pooch for reliable model downloading with caching.
    """
    try:
        # First, check if model exists in ComfyUI models directory
        from .providers import get_comfy_models_path
        comfy_model_path = get_comfy_models_path() / "rembg" / "u2net.onnx"
        if comfy_model_path.exists() and comfy_model_path.stat().st_size > 100_000_000:
            print(f"[BACKGROUND] Using U2Net from ComfyUI models: {comfy_model_path}")
            return comfy_model_path
    except Exception:
        pass  # ComfyUI path not configured, continue to user cache

    try:
        import pooch

        # U2Net model URL (same as rembg uses)
        model_url = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
        model_hash = "md5:60024c5c889badc19c04ad937298a77b"

        # Cache in user's home directory
        cache_dir = Path.home() / ".u2net"
        cache_dir.mkdir(parents=True, exist_ok=True)

        model_path = cache_dir / "u2net.onnx"

        # If model exists and is valid, use it
        if model_path.exists() and model_path.stat().st_size > 100_000_000:  # ~176MB
            return model_path

        # Download using pooch
        print("[BACKGROUND] Downloading U2Net model (this may take a minute)...")
        print("[BACKGROUND] Tip: Run 'make download-edit' to pre-download edit models")
        downloaded = pooch.retrieve(
            url=model_url,
            known_hash=model_hash,
            path=str(cache_dir),
            fname="u2net.onnx",
            progressbar=True,
        )
        return Path(downloaded)

    except Exception as e:
        print(f"[BACKGROUND] Failed to get U2Net model: {e}")
        return None


def _remove_background_onnx(img_bytes: bytes) -> Tuple[Optional[bytes], bool]:
    """
    Remove background using ONNX Runtime directly with U2Net model.
    This is Python 3.11+ compatible (no numba dependency).
    Returns (result_bytes, has_alpha) or (None, False) if not available.
    """
    try:
        import onnxruntime as ort
        from PIL import Image
        import numpy as np

        # Get model path
        model_path = _get_u2net_model_path()
        if not model_path or not model_path.exists():
            print("[BACKGROUND] U2Net model not available")
            return None, False

        # Load and preprocess image
        img = Image.open(io.BytesIO(img_bytes))
        original_size = img.size

        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize to model input size (320x320)
        input_size = (320, 320)
        resized = img.resize(input_size, Image.Resampling.LANCZOS)

        # Normalize to [0, 1] and then to model's expected range
        np_img = np.array(resized).astype(np.float32) / 255.0

        # Normalize with ImageNet mean/std (as rembg does)
        mean = np.array([0.485, 0.456, 0.406])
        std = np.array([0.229, 0.224, 0.225])
        np_img = (np_img - mean) / std

        # Transpose to NCHW format
        np_img = np_img.transpose(2, 0, 1)
        np_img = np.expand_dims(np_img, axis=0).astype(np.float32)

        # Run inference
        session = ort.InferenceSession(str(model_path), providers=['CPUExecutionProvider'])
        input_name = session.get_inputs()[0].name
        output = session.run(None, {input_name: np_img})

        # Process output mask
        mask = output[0][0, 0]  # Get first output, first batch, first channel

        # Normalize mask to 0-255
        mask = (mask - mask.min()) / (mask.max() - mask.min() + 1e-8)
        mask = (mask * 255).astype(np.uint8)

        # Resize mask back to original size
        mask_img = Image.fromarray(mask).resize(original_size, Image.Resampling.LANCZOS)

        # Log mask statistics for debugging
        mask_array = np.array(mask_img)
        mask_mean = mask_array.mean()
        print(f"[BACKGROUND] Mask stats: mean={mask_mean:.1f}, size={original_size}")

        # Invert mask if needed - U2Net may detect background as salient
        # If mean > 128, bright areas are larger (likely background), so invert
        # If mean < 128, bright areas are smaller (could be either), check and invert if needed
        # For consistent behavior, always invert since our workflow expects foreground=bright
        mask_inverted = 255 - mask_array
        mask_img = Image.fromarray(mask_inverted.astype(np.uint8))
        print(f"[BACKGROUND] Mask inverted: new mean={mask_inverted.mean():.1f}")

        # Apply mask to original image
        original = Image.open(io.BytesIO(img_bytes))
        if original.mode != 'RGBA':
            original = original.convert('RGBA')

        # Create output with alpha channel
        # mask=255 means paste the pixel, mask=0 means keep transparent
        result = Image.new('RGBA', original_size, (0, 0, 0, 0))
        result.paste(original, mask=mask_img)

        # Save to bytes
        output_buffer = io.BytesIO()
        result.save(output_buffer, format='PNG')
        output_buffer.seek(0)

        print("[BACKGROUND] Background removed using ONNX Runtime")
        return output_buffer.getvalue(), True

    except ImportError as e:
        print(f"[BACKGROUND] ONNX dependencies not installed: {e}")
        return None, False
    except Exception as e:
        print(f"[BACKGROUND] ONNX background removal failed: {e}")
        return None, False


def _remove_background_rembg(img_bytes: bytes) -> Tuple[Optional[bytes], bool]:
    """
    Remove background using rembg library (if available).
    Returns (result_bytes, has_alpha) or (None, False) if not available.
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
        print("[BACKGROUND] rembg not installed, trying ONNX fallback...")
        return _remove_background_onnx(img_bytes)
    except Exception as e:
        print(f"[BACKGROUND] rembg failed: {e}, trying ONNX fallback...")
        return _remove_background_onnx(img_bytes)


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
        # Try rembg library first, it's faster and doesn't need ComfyUI
        print("[BACKGROUND] Removing background")

        # Try rembg first (faster, no ComfyUI needed)
        result_bytes, has_alpha = _remove_background_rembg(img_bytes)

        if result_bytes:
            result_url = _save_image_to_uploads(result_bytes, prefix="nobg")
            print(f"[BACKGROUND] Background removed (rembg): {result_url}")
        else:
            # rembg not available - check if ComfyUI workflow might work
            # Note: The ComfyUI workflow requires the ComfyUI-rembg custom node
            # which may not be installed
            print("[BACKGROUND] rembg not available, trying ComfyUI workflow...")
            try:
                result = run_workflow("remove_background", {
                    "image_path": req.image_url,
                    "filename_prefix": "homepilot_nobg"
                })
                images = result.get("images", [])
                if images:
                    result_url = images[0]
                    has_alpha = True
                    print(f"[BACKGROUND] Background removed (ComfyUI): {result_url}")
                else:
                    raise HTTPException(500, "No image returned from workflow")
            except Exception as e:
                error_msg = str(e)
                print(f"[BACKGROUND] ComfyUI workflow failed: {error_msg}")

                # Provide helpful error message based on the error
                if "does not exist" in error_msg or "ImageRemoveBackgroundRembg" in error_msg:
                    raise HTTPException(
                        503,
                        "Background removal is not available. "
                        "Please install the ComfyUI-rembg custom node or the rembg Python package. "
                        "Run: pip install rembg[onnxruntime] (recommended for Python 3.11+)"
                    )
                raise HTTPException(500, f"Background removal failed: {e}")

    elif req.action == BackgroundAction.REPLACE:
        # Use ComfyUI workflow for background replacement
        if not req.prompt:
            raise HTTPException(400, "prompt is required for replace action")

        print(f"[BACKGROUND] Replacing background with prompt: {req.prompt[:50]}...")

        # Step 1: Save the original image (for VAEEncode - no black background)
        original_url = _save_image_to_uploads(img_bytes, prefix="original", ext="png")
        print(f"[BACKGROUND] Original image saved: {original_url}")

        # Step 2: Remove background to get alpha mask
        print("[BACKGROUND] Step 2: Removing background for masking...")
        masked_bytes, mask_ok = _remove_background_rembg(img_bytes)

        if not masked_bytes:
            raise HTTPException(
                503,
                "Background replacement requires background removal capability. "
                "Please ensure onnxruntime is installed."
            )

        # Step 3: Save the pre-masked image (PNG with alpha for mask extraction)
        masked_url = _save_image_to_uploads(masked_bytes, prefix="masked", ext="png")
        print(f"[BACKGROUND] Pre-masked image saved: {masked_url}")

        # Step 4: Use the premask workflow with both original and masked images
        try:
            # Try common inpainting checkpoints in order of preference
            checkpoints = [
                "sd_xl_base_1.0_inpainting_0.1.safetensors",
                "sd_xl_base_1.0.safetensors",
                "v1-5-pruned-emaonly.safetensors",
                "v1-5-pruned.safetensors",
            ]

            # Use the first available checkpoint (workflow will fail if none exist)
            checkpoint = checkpoints[0]  # Default to inpainting model

            import random
            result = run_workflow("change_background_premask", {
                "image_path": masked_url,
                "original_image_path": original_url,
                "prompt": req.prompt,
                "negative_prompt": req.negative_prompt or "blurry, low quality, distorted",
                "checkpoint": checkpoint,
                "seed": random.randint(1, 2147483647),
                "filename_prefix": "homepilot_newbg"
            })

            images = result.get("images", [])
            if images:
                result_url = images[0]
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
