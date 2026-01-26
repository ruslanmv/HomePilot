"""
Capabilities endpoint - Reports runtime feature availability.

This endpoint checks which features are actually available at runtime,
including installed models, dependencies like PIL, and ComfyUI connectivity.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
import importlib.util

from .edit_models import (
    get_edit_models_status,
    get_available_model,
    get_installed_models,
    ModelCategory,
)


router = APIRouter(tags=["capabilities"])


class CapabilityStatus(BaseModel):
    """Status of a single capability."""
    available: bool
    reason: Optional[str] = None
    endpoint: str
    model: Optional[str] = None
    installed_models: Optional[List[str]] = None


class CapabilitiesResponse(BaseModel):
    """Response containing all capability statuses."""
    capabilities: Dict[str, CapabilityStatus]


def _check_module(module_name: str) -> tuple[bool, Optional[str]]:
    """Check if a Python module is available."""
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return False, f"{module_name} not installed"
    return True, None


def _check_pillow() -> tuple[bool, Optional[str]]:
    """Check if PIL/Pillow is available."""
    try:
        from PIL import Image
        return True, None
    except ImportError:
        return False, "PIL/Pillow not installed"


def _check_torch_gpu() -> tuple[bool, Optional[str]]:
    """Check if PyTorch with GPU is available."""
    try:
        import torch
        if torch.cuda.is_available():
            return True, None
        return True, "CPU only (no GPU)"
    except ImportError:
        return False, "PyTorch not installed"


def _check_rembg() -> tuple[bool, Optional[str]]:
    """Check if background removal is available (rembg or ONNX fallback)."""
    # First check for rembg library
    try:
        from rembg import remove
        return True, None
    except ImportError:
        pass

    # Check for ONNX-based fallback (Python 3.11+ compatible)
    try:
        import onnxruntime
        from PIL import Image
        import numpy as np

        # Check if U2Net model is available (in ComfyUI models or user cache)
        from pathlib import Path
        from .providers import get_comfy_models_path

        # Check ComfyUI models path first
        try:
            comfy_model = get_comfy_models_path() / "rembg" / "u2net.onnx"
            if comfy_model.exists() and comfy_model.stat().st_size > 100_000_000:
                return True, "Using U2Net from ComfyUI models"
        except Exception:
            pass

        # Check user cache
        user_model = Path.home() / ".u2net" / "u2net.onnx"
        if user_model.exists() and user_model.stat().st_size > 100_000_000:
            return True, "Using ONNX Runtime (Python 3.11+ compatible)"

        # Dependencies available but model not downloaded yet
        return True, "ONNX ready (U2Net model will download on first use)"

    except ImportError:
        return False, "Background removal not available. Install onnxruntime, pooch, and scikit-image."


@router.get("/v1/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities():
    """
    Get runtime capability status for all features.

    Returns availability status for each feature, including:
    - Whether the feature is available (based on installed models)
    - Reason if unavailable (missing model, dependency, etc.)
    - The API endpoint for the feature
    - The model used (if applicable)
    - List of installed models for that feature

    This allows the UI to disable unavailable features and show
    helpful error messages to users.
    """
    capabilities: Dict[str, CapabilityStatus] = {}

    # Check dependencies
    pil_ok, pil_reason = _check_pillow()

    # Get installed models for each category
    upscale_models = get_installed_models(ModelCategory.UPSCALE)
    upscale_model_ids = [m.id for m in upscale_models]
    upscale_available = len(upscale_models) > 0
    upscale_model = get_available_model(ModelCategory.UPSCALE)

    face_models = get_installed_models(ModelCategory.FACE_RESTORE)
    face_model_ids = [m.id for m in face_models]
    face_available = len(face_models) > 0
    face_model = get_available_model(ModelCategory.FACE_RESTORE)

    # Enhance photo - uses upscale models
    capabilities["enhance_photo"] = CapabilityStatus(
        available=upscale_available,
        reason=None if upscale_available else "No upscale model installed (install 4x-UltraSharp.pth or RealESRGAN_x4plus.pth)",
        endpoint="/v1/enhance",
        model=upscale_model.name if upscale_model else None,
        installed_models=upscale_model_ids,
    )

    # Enhance restore - uses upscale models
    capabilities["enhance_restore"] = CapabilityStatus(
        available=upscale_available,
        reason=None if upscale_available else "No upscale model installed (install SwinIR_4x.pth or 4x-UltraSharp.pth)",
        endpoint="/v1/enhance",
        model=upscale_model.name if upscale_model else None,
        installed_models=upscale_model_ids,
    )

    # Enhance faces - uses face restore models
    capabilities["enhance_faces"] = CapabilityStatus(
        available=face_available,
        reason=None if face_available else "No face restoration model installed (install GFPGANv1.4.pth)",
        endpoint="/v1/enhance",
        model=face_model.name if face_model else None,
        installed_models=face_model_ids,
    )

    # Upscale capability
    capabilities["upscale"] = CapabilityStatus(
        available=upscale_available,
        reason=None if upscale_available else "No upscale model installed (install 4x-UltraSharp.pth)",
        endpoint="/v1/upscale",
        model=upscale_model.name if upscale_model else None,
        installed_models=upscale_model_ids,
    )

    # Background remove - requires rembg or ComfyUI-rembg custom node
    rembg_ok, rembg_reason = _check_rembg()
    capabilities["background_remove"] = CapabilityStatus(
        available=rembg_ok,
        reason=rembg_reason,
        endpoint="/v1/background",
        model="rembg/U2Net" if rembg_ok else None,
    )

    capabilities["background_replace"] = CapabilityStatus(
        available=True,  # ComfyUI handles this
        endpoint="/v1/background",
        model="SD Inpainting",
    )

    capabilities["background_blur"] = CapabilityStatus(
        available=pil_ok,
        reason=pil_reason,
        endpoint="/v1/background",
        model="PIL GaussianBlur",
    )

    # Outpaint capability
    capabilities["outpaint"] = CapabilityStatus(
        available=True,  # ComfyUI handles this
        endpoint="/v1/outpaint",
        model="SD Outpainting",
    )

    # Inpaint capability
    capabilities["inpaint"] = CapabilityStatus(
        available=True,  # ComfyUI handles this
        endpoint="/v1/edit",
        model="SD Inpainting",
    )

    return CapabilitiesResponse(capabilities=capabilities)


@router.get("/v1/capabilities/{feature}")
async def get_capability(feature: str):
    """
    Get capability status for a specific feature.

    Valid features:
    - enhance_photo, enhance_restore, enhance_faces
    - upscale
    - background_remove, background_replace, background_blur
    - outpaint, inpaint
    """
    all_caps = await get_capabilities()

    if feature not in all_caps.capabilities:
        return {"error": f"Unknown feature: {feature}", "valid_features": list(all_caps.capabilities.keys())}

    return all_caps.capabilities[feature]


@router.get("/v1/edit-models")
async def get_edit_models():
    """
    Get comprehensive status of all edit models.

    Returns:
    - Lists of installed/available models by category
    - Currently selected models for each mode
    - Default models

    Use this to populate the settings UI for model selection.
    """
    from .edit_models import get_edit_models_status
    return get_edit_models_status()


@router.post("/v1/edit-models/preference")
async def set_edit_model_preference(mode: str, model_id: str):
    """
    Set the preferred model for an edit mode.

    Args:
        mode: "upscale", "photo", "restore", or "faces"
        model_id: The model ID to use (e.g., "4x-UltraSharp", "GFPGANv1.4")

    Returns:
        Success status and any error message
    """
    from .edit_models import set_model_preference
    success, error = set_model_preference(mode, model_id)

    if success:
        return {"success": True, "mode": mode, "model": model_id}
    else:
        return {"success": False, "error": error}
