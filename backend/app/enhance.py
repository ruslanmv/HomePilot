"""
Enhance endpoint for image quality improvement.

This module provides a dedicated API endpoint for enhancing images using
various ComfyUI models:
- Upscale models: 4x-UltraSharp, RealESRGAN, SwinIR
- Face restoration: GFPGAN, CodeFormer

Features:
- Multiple enhancement modes (photo, restore, faces)
- Automatic dimension detection
- Optional face enhancement pass
- Guardrails for max output size
- Dynamic model selection based on installed models and user preferences
"""

from __future__ import annotations

import io
from enum import Enum
from pathlib import Path
from typing import Literal, Optional, Tuple
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .comfy import run_workflow
from .config import UPLOAD_DIR
from .edit_models import get_enhance_model, get_face_restore_model

router = APIRouter(prefix="/v1", tags=["enhance"])


class EnhanceMode(str, Enum):
    """Enhancement mode selection."""
    PHOTO = "photo"       # Upscale - natural photo enhancement
    RESTORE = "restore"   # Upscale - artifact/compression removal
    FACES = "faces"       # Face restoration (GFPGAN/CodeFormer)


class EnhanceRequest(BaseModel):
    """Request model for enhance endpoint."""
    image_url: str = Field(..., description="Image URL (preferably from /files)")
    mode: EnhanceMode = Field(
        default=EnhanceMode.PHOTO,
        description="Enhancement mode: photo (RealESRGAN), restore (SwinIR), faces (GFPGAN)"
    )
    scale: Literal[1, 2, 4] = Field(
        default=4,
        description="Scale factor (1 for faces mode, 2 or 4 for others)"
    )
    face_enhance: bool = Field(
        default=False,
        description="Also run GFPGAN face restoration after main enhancement"
    )


class EnhanceResponse(BaseModel):
    """Response model for enhance endpoint."""
    model_config = {"protected_namespaces": ()}

    media: dict
    mode_used: str
    model_used: str
    original_size: Tuple[int, int]
    enhanced_size: Tuple[int, int]


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
            print(f"[ENHANCE] Warning: Failed to read local file: {e}")

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content))
            img.load()
            return img.size
    except Exception as e:
        raise HTTPException(400, f"Cannot read image dimensions: {e}")


@router.post("/enhance", response_model=EnhanceResponse)
async def enhance_image(req: EnhanceRequest):
    """
    Enhance image quality using AI models.

    Modes:
    - **photo**: Best for natural photos. Uses RealESRGAN for texture recovery.
    - **restore**: Remove JPEG artifacts and mild blur. Uses SwinIR.
    - **faces**: Restore and enhance faces. Uses GFPGAN.

    The endpoint:
    - Accepts an image URL (must be from your own /files endpoint for best performance)
    - Computes dimensions automatically
    - Runs the appropriate workflow based on mode
    - Optionally runs face enhancement as a second pass

    Guardrails:
    - Max output edge: 4096px
    - Max scale: 4x
    """
    print(f"[ENHANCE] Request: mode={req.mode}, scale={req.scale}, face_enhance={req.face_enhance}")

    # Get original dimensions
    try:
        orig_w, orig_h = _get_image_size(req.image_url)
        print(f"[ENHANCE] Detected image size: {orig_w}x{orig_h}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Cannot read image dimensions: {e}")

    # For faces mode, we don't upscale - GFPGAN works on original size
    if req.mode == EnhanceMode.FACES:
        out_w, out_h = orig_w, orig_h
        scale = 1
    else:
        scale = req.scale
        out_w = orig_w * scale
        out_h = orig_h * scale

    print(f"[ENHANCE] Output size will be: {out_w}x{out_h}")

    # Guardrails
    max_edge = 4096
    if out_w > max_edge or out_h > max_edge:
        raise HTTPException(
            400,
            f"Requested output too large ({out_w}x{out_h}). Max edge is {max_edge}px. "
            f"Try a smaller scale factor."
        )

    # Get model and workflow based on installed models and preferences
    model_filename, error, mode_config = get_enhance_model(req.mode.value)

    if error or not mode_config:
        print(f"[ENHANCE] Model not available: {error}")
        raise HTTPException(
            503,
            f"Enhance mode '{req.mode.value}' is not available: {error}"
        )

    workflow_name = mode_config.workflow
    param_name = mode_config.param_name

    print(f"[ENHANCE] Using workflow={workflow_name}, model={model_filename}, param={param_name}")

    # Run the enhancement workflow
    try:
        # Build workflow params
        workflow_params = {
            "image_path": req.image_url,
            "width": out_w,
            "height": out_h,
            "filename_prefix": f"homepilot_enhance_{req.mode.value}",
            param_name: model_filename,  # Dynamic param name based on workflow
        }

        result = run_workflow(workflow_name, workflow_params)
        print(f"[ENHANCE] Workflow completed successfully")

        # run_workflow returns {"images": [...], "videos": [...]}
        images = result.get("images", [])
        videos = result.get("videos", [])

        # Optional: Run face enhancement as second pass
        if req.face_enhance and req.mode != EnhanceMode.FACES:
            # Get the output image URL from first pass
            if images:
                face_model, face_error = get_face_restore_model()
                if face_model:
                    enhanced_url = images[0]
                    print(f"[ENHANCE] Running face enhancement pass on {enhanced_url}")

                    face_result = run_workflow("fix_faces_gfpgan", {
                        "image_path": enhanced_url,
                        "model_name": face_model,
                        "filename_prefix": "homepilot_enhance_faces"
                    })
                    images = face_result.get("images", [])
                    videos = face_result.get("videos", [])
                    print(f"[ENHANCE] Face enhancement pass completed")
                else:
                    print(f"[ENHANCE] Face enhancement skipped: {face_error}")

        return EnhanceResponse(
            media={"images": images, "videos": videos},
            mode_used=req.mode.value,
            model_used=model_filename,
            original_size=(orig_w, orig_h),
            enhanced_size=(out_w, out_h)
        )

    except Exception as e:
        error_str = str(e)
        print(f"[ENHANCE] Workflow failed: {e}")

        # Check for missing face restore nodes
        if "FaceRestoreModelLoader does not exist" in error_str or "FaceRestoreWithModel does not exist" in error_str:
            raise HTTPException(
                503,
                "Face restoration nodes not available in ComfyUI. "
                "Please install the required dependencies: pip install facexlib gfpgan "
                "(in your ComfyUI Python environment), then restart ComfyUI."
            )

        raise HTTPException(500, f"Enhance workflow failed: {e}")
