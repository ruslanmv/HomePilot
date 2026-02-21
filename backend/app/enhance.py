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

from .comfy import check_nodes_available, run_workflow
from .config import UPLOAD_DIR
from .edit_models import get_enhance_model, get_face_restore_model
from .face_restore import check_standalone_available, restore_faces

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


def _run_face_restore_standalone(image_url: str, model_filename: str) -> Optional[dict]:
    """
    Attempt face restoration using the standalone service (no ComfyUI).

    Returns:
        dict with {"images": [...], "videos": []} on success, or None if
        standalone is not available / failed.
    """
    standalone_ok, standalone_reason = check_standalone_available()
    if not standalone_ok:
        print(f"[ENHANCE] Standalone face restore not available: {standalone_reason}")
        return None

    print(f"[ENHANCE] Trying standalone face restoration (bypassing ComfyUI)")
    try:
        output_filename, error = restore_faces(
            image_path=image_url,
            model_name=model_filename,
        )
        if error:
            print(f"[ENHANCE] Standalone face restore failed: {error}")
            return None

        # Build a /files/ URL for the output
        output_url = f"/files/{output_filename}"
        print(f"[ENHANCE] Standalone face restore succeeded: {output_url}")
        return {"images": [output_url], "videos": []}

    except Exception as e:
        print(f"[ENHANCE] Standalone face restore exception: {e}")
        return None


def _run_face_restore_comfyui(image_url: str, model_filename: str) -> Optional[dict]:
    """
    Attempt face restoration using the ComfyUI workflow.

    Returns:
        dict with {"images": [...], "videos": []} on success, or None if
        ComfyUI nodes are not available.

    Raises:
        Exception if ComfyUI is available but the workflow fails.
    """
    # Pre-flight: check if the required ComfyUI nodes exist
    ok, missing = check_nodes_available(["FaceRestoreModelLoader", "FaceRestoreWithModel"])
    if not ok:
        print(f"[ENHANCE] ComfyUI face restore nodes missing: {missing}")
        return None

    print(f"[ENHANCE] Running face restoration via ComfyUI workflow")
    result = run_workflow("fix_faces_gfpgan", {
        "image_path": image_url,
        "model_name": model_filename,
        "filename_prefix": "homepilot_enhance_faces",
    })
    return result


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

    Face restoration fallback chain:
    1. Standalone GFPGAN (runs directly in backend, no ComfyUI needed)
    2. ComfyUI workflow (requires Impact-Pack custom nodes)
    3. Clear error with install instructions for both approaches

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

    # ── Face restoration with fallback chain ──────────────────────
    # For faces mode, we try multiple approaches before giving up:
    #   1. Standalone GFPGAN (no ComfyUI dependency)
    #   2. ComfyUI workflow (requires Impact-Pack)
    #   3. Error with clear install instructions
    if req.mode == EnhanceMode.FACES:
        # Attempt 1: Standalone GFPGAN
        standalone_result = _run_face_restore_standalone(req.image_url, model_filename)
        if standalone_result:
            images = standalone_result.get("images", [])
            return EnhanceResponse(
                media=standalone_result,
                mode_used="faces",
                model_used=f"{model_filename} (standalone)",
                original_size=(orig_w, orig_h),
                enhanced_size=(out_w, out_h),
            )

        # Attempt 2: ComfyUI workflow
        try:
            comfyui_result = _run_face_restore_comfyui(req.image_url, model_filename)
            if comfyui_result:
                return EnhanceResponse(
                    media=comfyui_result,
                    mode_used="faces",
                    model_used=f"{model_filename} (comfyui)",
                    original_size=(orig_w, orig_h),
                    enhanced_size=(out_w, out_h),
                )
        except Exception as e:
            print(f"[ENHANCE] ComfyUI face restore failed: {e}")

        # Both approaches failed — give a comprehensive error
        standalone_ok, standalone_reason = check_standalone_available()
        raise HTTPException(
            503,
            "Face restoration is not available. Both approaches failed:\n\n"
            "Option A — Standalone (recommended, no ComfyUI needed):\n"
            f"  Status: {standalone_reason}\n"
            "  Fix: pip install gfpgan facexlib basicsr torch\n"
            "       (in the backend Python env, then restart the backend)\n\n"
            "Option B — ComfyUI workflow:\n"
            "  Status: FaceRestoreModelLoader/FaceRestoreWithModel nodes not registered\n"
            "  Fix: git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git "
            "ComfyUI/custom_nodes/ComfyUI-Impact-Pack\n"
            "       pip install facexlib gfpgan (in ComfyUI's Python env)\n"
            "       Then restart ComfyUI.\n\n"
            "After fixing either option, retry the request."
        )

    # ── Standard enhancement workflow (photo / restore) ───────────
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
            if images:
                face_model, face_error = get_face_restore_model()
                if face_model:
                    # Try standalone first for the second pass too
                    face_result = _run_face_restore_standalone(images[0], face_model)
                    if face_result:
                        images = face_result.get("images", [])
                        videos = face_result.get("videos", [])
                        print(f"[ENHANCE] Face enhancement pass completed (standalone)")
                    else:
                        # Fall back to ComfyUI for second pass
                        try:
                            face_result = _run_face_restore_comfyui(images[0], face_model)
                            if face_result:
                                images = face_result.get("images", [])
                                videos = face_result.get("videos", [])
                                print(f"[ENHANCE] Face enhancement pass completed (comfyui)")
                            else:
                                print(f"[ENHANCE] Face enhancement skipped — neither standalone nor ComfyUI available")
                        except Exception as e:
                            print(f"[ENHANCE] Face enhancement ComfyUI pass failed: {e}")
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

        # Check for missing node classes (preflight or ComfyUI validation)
        if "does not exist" in error_str or "not registered" in error_str:
            raise HTTPException(
                503,
                f"ComfyUI nodes required by this workflow are not available. {error_str}\n\n"
                "Common fixes:\n"
                "  • Face restore: pip install facexlib gfpgan (in ComfyUI env) + install ComfyUI-Impact-Pack\n"
                "  • InstantID: pip install insightface onnxruntime (in ComfyUI env) + install ComfyUI_InstantID\n"
                "Then restart ComfyUI and verify nodes at http://localhost:8188/object_info"
            )

        raise HTTPException(500, f"Enhance workflow failed: {e}")


# =============================================================================
# Identity-Aware Edit Endpoint (additive — does NOT modify existing enhance)
# =============================================================================

class IdentityToolType(str, Enum):
    FIX_FACES_IDENTITY = "fix_faces_identity"
    INPAINT_IDENTITY = "inpaint_identity"
    CHANGE_BG_IDENTITY = "change_bg_identity"
    FACE_SWAP = "face_swap"


class IdentityEditRequest(BaseModel):
    image_url: str = Field(..., description="URL of the image to edit")
    tool_type: IdentityToolType = Field(..., description="Identity tool to apply")
    reference_image_url: Optional[str] = Field(None, description="Reference face image for face swap")
    mask_data_url: Optional[str] = Field(None, description="Mask data URL for inpaint_identity")
    prompt: Optional[str] = Field(None, description="Optional prompt for bg replacement or inpainting")


class IdentityEditResponse(BaseModel):
    media: dict = Field(default_factory=dict)
    tool_used: str = ""
    error: Optional[str] = None


@router.post("/edit/identity", response_model=IdentityEditResponse)
async def identity_edit(req: IdentityEditRequest):
    """
    Identity-aware image editing using Avatar & Identity models.

    This endpoint is **additive** — it does NOT replace or modify the existing
    /enhance endpoint.  It provides new editing capabilities that preserve
    facial identity using InsightFace + InstantID models.

    Tools:
    - **fix_faces_identity**: Fix faces while preserving identity (Basic Pack)
    - **inpaint_identity**: Inpaint regions while keeping the face consistent (Basic Pack)
    - **change_bg_identity**: Replace background while preserving the person (Basic Pack)
    - **face_swap**: Transfer identity onto another image (Full Pack — requires InSwapper)

    When the corresponding ComfyUI workflows are integrated, this endpoint will
    route to the appropriate identity-preserving pipeline.  Until then, it falls
    back to the standard enhance workflows where possible.
    """
    tool = req.tool_type.value
    print(f"[IDENTITY EDIT] Request: tool={tool}, image={req.image_url[:80]}...")

    # ---- Routing ----
    # TODO: Replace fallback workflows with dedicated InstantID workflows
    #       when they are created:
    #   fix_faces_identity  -> "fix_faces_instantid"
    #   inpaint_identity    -> "inpaint_instantid"
    #   change_bg_identity  -> "change_bg_instantid"
    #   face_swap           -> "face_swap_inswapper"

    try:
        if tool == "fix_faces_identity":
            # Try standalone GFPGAN first, then ComfyUI fallback
            face_model, face_error = get_face_restore_model()
            if not face_model:
                raise HTTPException(503, f"Face restoration model not available: {face_error}")

            # Attempt 1: Standalone GFPGAN (no ComfyUI needed)
            standalone_result = _run_face_restore_standalone(req.image_url, face_model)
            if standalone_result:
                print(f"[IDENTITY EDIT] fix_faces_identity completed (standalone)")
                images = standalone_result.get("images", [])
                return IdentityEditResponse(media={"images": images}, tool_used=tool)

            # Attempt 2: ComfyUI workflow fallback
            print(f"[IDENTITY EDIT] Running fix_faces_identity (fallback: ComfyUI GFPGAN)")
            result = run_workflow("fix_faces_gfpgan", {
                "image_path": req.image_url,
                "model_name": face_model,
                "filename_prefix": "homepilot_identity_faces",
            })
            images = result.get("images", [])
            return IdentityEditResponse(media={"images": images}, tool_used=tool)

        elif tool == "inpaint_identity":
            # Fallback: use standard inpaint workflow until InstantID inpaint is ready
            # This is non-destructive — when a dedicated inpaint_instantid workflow
            # is available, we can route to it instead.
            if not req.mask_data_url:
                raise HTTPException(400, "inpaint_identity requires a mask_data_url")
            print(f"[IDENTITY EDIT] inpaint_identity — using standard inpaint fallback (identity mode not yet integrated)")
            result = run_workflow("edit_inpaint", {
                "image_path": req.image_url,
                "mask_path": req.mask_data_url,
                "prompt": req.prompt or "high quality, detailed",
                "negative_prompt": "low quality, blurry, artifacts",
                "seed": __import__("random").randint(1, 2**32),
                "steps": 20,
                "cfg": 7.0,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 0.85,
                "ckpt_name": "sd_xl_base_1.0_inpainting_0.1.safetensors",
                "filename_prefix": "homepilot_identity_inpaint_fallback",
            })
            images = result.get("images", [])
            return IdentityEditResponse(media={"images": images}, tool_used=tool)

        elif tool == "change_bg_identity":
            # Fallback: use standard background replacement workflow until
            # InstantID background workflow is available.
            print(f"[IDENTITY EDIT] change_bg_identity — using standard change_background fallback (identity mode not yet integrated)")
            result = run_workflow("change_background", {
                "image_path": req.image_url,
                "prompt": req.prompt or "beautiful background, high quality",
                "negative_prompt": "low quality, blurry",
                "seed": __import__("random").randint(1, 2**32),
                "ckpt_name": "sd_xl_base_1.0_inpainting_0.1.safetensors",
                "filename_prefix": "homepilot_identity_bg_fallback",
            })
            images = result.get("images", [])
            return IdentityEditResponse(media={"images": images}, tool_used=tool)

        elif tool == "face_swap":
            if not req.reference_image_url:
                raise HTTPException(400, "Face swap requires a reference_image_url")
            print(f"[IDENTITY EDIT] face_swap — InSwapper workflow not yet integrated")
            raise HTTPException(
                501,
                "Face swap workflow is not yet integrated. "
                "Install the Full Pack to be ready when face swap becomes available.",
            )

        else:
            raise HTTPException(400, f"Unknown identity tool: {tool}")

    except HTTPException:
        raise
    except Exception as e:
        error_str = str(e)
        print(f"[IDENTITY EDIT] Failed: {e}")

        # Check for missing node classes (preflight or ComfyUI validation)
        if "does not exist" in error_str or "not registered" in error_str:
            hint = ""
            if "FaceRestore" in error_str or "GFPGAN" in error_str:
                hint = (
                    " Install gfpgan + facexlib into the SAME Python env ComfyUI "
                    "runs in, then restart ComfyUI."
                )
            if "InstantID" in error_str or "InsightFace" in error_str:
                hint = (
                    " Ensure InstantID/InsightFace ComfyUI custom nodes are installed "
                    "and ComfyUI restarted."
                )
            raise HTTPException(
                503,
                f"ComfyUI nodes required by this tool are not available. {error_str}{hint}\n\n"
                "Common fixes:\n"
                "  • Face restore: pip install facexlib gfpgan (in ComfyUI env) + install ComfyUI-Impact-Pack\n"
                "  • InstantID: pip install insightface onnxruntime (in ComfyUI env) + install ComfyUI_InstantID\n"
                "Then restart ComfyUI and verify nodes at http://localhost:8188/object_info"
            )

        raise HTTPException(500, f"Identity edit failed: {e}")
