"""
Edit Models Configuration - Centralized model management for Edit features.

This module provides:
- Detection of installed ComfyUI models for upscale/enhance/face restoration
- Default model configuration with fallbacks
- User-configurable model preferences
- Consistent model access across enhance.py, upscale.py, etc.

Model Categories:
- UPSCALE: 4x-UltraSharp, RealESRGAN, realesr-general, SwinIR
- FACE_RESTORE: GFPGANv1.4, CodeFormer
- BACKGROUND: u2net (rembg), SAM
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

from .providers import get_comfy_models_path


class ModelCategory(str, Enum):
    """Categories of edit models."""
    UPSCALE = "upscale"
    FACE_RESTORE = "face_restore"
    BACKGROUND = "background"
    # Additive: Avatar/Persona wizard specialized models
    AVATAR_GENERATION = "avatar_generation"


@dataclass
class ModelInfo:
    """Information about a single model."""
    id: str
    name: str
    category: ModelCategory
    filename: str
    subdir: str  # Directory under models/ (e.g., "upscale_models", "gfpgan")
    description: str = ""
    is_default: bool = False
    # Additive metadata (backwards-safe — all have defaults)
    license: str = ""
    commercial_use_ok: Optional[bool] = None
    homepage: str = ""
    download_url: str = ""
    sha256: str = ""
    requires: List[str] = field(default_factory=list)  # model IDs this depends on

    @property
    def path(self) -> Path:
        """Get the full path to this model."""
        models_path = get_comfy_models_path()
        return models_path / self.subdir / self.filename

    @property
    def installed(self) -> bool:
        """Check if this model is installed."""
        p = self.path
        return p.exists() and p.stat().st_size > 0


# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

UPSCALE_MODELS: Dict[str, ModelInfo] = {
    "4x-UltraSharp": ModelInfo(
        id="4x-UltraSharp",
        name="4x UltraSharp",
        category=ModelCategory.UPSCALE,
        filename="4x-UltraSharp.pth",
        subdir="upscale_models",
        description="High-quality upscaling with sharp details",
        is_default=True,
    ),
    "RealESRGAN_x4plus": ModelInfo(
        id="RealESRGAN_x4plus",
        name="RealESRGAN x4+",
        category=ModelCategory.UPSCALE,
        filename="RealESRGAN_x4plus.pth",
        subdir="upscale_models",
        description="Photo enhancement with natural texture recovery",
    ),
    "realesr-general-x4v3": ModelInfo(
        id="realesr-general-x4v3",
        name="RealESRGAN General v3",
        category=ModelCategory.UPSCALE,
        filename="realesr-general-x4v3.pth",
        subdir="upscale_models",
        description="General purpose upscaling",
    ),
    "SwinIR_4x": ModelInfo(
        id="SwinIR_4x",
        name="SwinIR 4x",
        category=ModelCategory.UPSCALE,
        filename="SwinIR_4x.pth",
        subdir="upscale_models",
        description="Artifact removal and restoration",
    ),
}

FACE_RESTORE_MODELS: Dict[str, ModelInfo] = {
    "GFPGANv1.4": ModelInfo(
        id="GFPGANv1.4",
        name="GFPGAN v1.4",
        category=ModelCategory.FACE_RESTORE,
        filename="GFPGANv1.4.pth",
        subdir="gfpgan",  # Matches Makefile download path
        description="Face restoration and enhancement",
        is_default=True,
    ),
    "codeformer": ModelInfo(
        id="codeformer",
        name="CodeFormer",
        category=ModelCategory.FACE_RESTORE,
        filename="codeformer.pth",
        subdir="codeformer",  # Matches providers.py scan path
        description="AI face restoration with fidelity control",
    ),
}

BACKGROUND_MODELS: Dict[str, ModelInfo] = {
    "u2net": ModelInfo(
        id="u2net",
        name="U2-Net",
        category=ModelCategory.BACKGROUND,
        filename="u2net.onnx",
        subdir="rembg",
        description="Background removal segmentation",
        is_default=True,
    ),
    "sam_vit_h": ModelInfo(
        id="sam_vit_h",
        name="SAM ViT-H",
        category=ModelCategory.BACKGROUND,
        filename="sam_vit_h_4b8939.pth",
        subdir="sams",
        description="Segment Anything Model (high quality)",
    ),
}

# =============================================================================
# AVATAR GENERATION MODELS (Additive — Golden Rule 1.0)
# These models extend the registry for the PersonaWizard "Portrait Studio".
# They do NOT replace or affect existing text-to-image, edit, or enhance models.
# =============================================================================

AVATAR_GENERATION_MODELS: Dict[str, ModelInfo] = {
    # ── Face analysis / embeddings (commonly used by InstantID & face-swap) ──
    "insightface-antelopev2": ModelInfo(
        id="insightface-antelopev2",
        name="InsightFace AntelopeV2",
        category=ModelCategory.AVATAR_GENERATION,
        filename="antelopev2.zip",
        subdir="insightface/models",
        description="Face detection & embedding pack used by InstantID and face-swap workflows.",
        license="InsightFace model zoo (code MIT, models vary)",
        commercial_use_ok=True,
        homepage="https://github.com/deepinsight/insightface",
        download_url="https://huggingface.co/MonsterMMORPG/tools/resolve/main/antelopev2.zip",
        sha256="",
        requires=[],
        is_default=True,
    ),

    # ── Face swap model (optional) ──
    "insightface-inswapper-128": ModelInfo(
        id="insightface-inswapper-128",
        name="InsightFace InSwapper 128 (ONNX)",
        category=ModelCategory.AVATAR_GENERATION,
        filename="inswapper_128.onnx",
        subdir="insightface",
        description="Face swap ONNX model for consistent identity transfer onto generated images.",
        license="Model distribution varies (see source)",
        commercial_use_ok=True,
        homepage="https://github.com/deepinsight/insightface",
        download_url="https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx",
        sha256="",
        requires=["insightface-antelopev2"],
    ),

    # ── InstantID (identity-preserving adapter, Apache 2.0) ──
    "instantid-ip-adapter": ModelInfo(
        id="instantid-ip-adapter",
        name="InstantID IP-Adapter",
        category=ModelCategory.AVATAR_GENERATION,
        filename="ip-adapter.bin",
        subdir="instantid",
        description="InstantID adapter checkpoint for identity-preserving diffusion generation.",
        license="Apache 2.0",
        commercial_use_ok=True,
        homepage="https://huggingface.co/InstantX/InstantID",
        download_url="https://huggingface.co/InstantX/InstantID/resolve/main/ip-adapter.bin",
        sha256="",
        requires=["insightface-antelopev2"],
    ),

    # ── InstantID ControlNet ──
    "instantid-controlnet": ModelInfo(
        id="instantid-controlnet",
        name="InstantID ControlNet",
        category=ModelCategory.AVATAR_GENERATION,
        filename="diffusion_pytorch_model.safetensors",
        subdir="controlnet/InstantID",
        description="InstantID ControlNet for facial keypoint guidance during generation.",
        license="Apache 2.0",
        commercial_use_ok=True,
        homepage="https://huggingface.co/InstantX/InstantID",
        download_url="https://huggingface.co/InstantX/InstantID/resolve/main/ControlNetModel/diffusion_pytorch_model.safetensors",
        sha256="",
        requires=["instantid-ip-adapter"],
    ),

    # ── PhotoMaker V2 (identity-preserving, Apache 2.0) ──
    "photomaker-v2": ModelInfo(
        id="photomaker-v2",
        name="PhotoMaker V2",
        category=ModelCategory.AVATAR_GENERATION,
        filename="photomaker-v2.bin",
        subdir="photomaker",
        description="PhotoMaker V2 identity-preserving encoder for SDXL-compatible workflows.",
        license="Apache 2.0",
        commercial_use_ok=True,
        homepage="https://huggingface.co/TencentARC/PhotoMaker-V2",
        download_url="https://huggingface.co/TencentARC/PhotoMaker-V2/resolve/main/photomaker-v2.bin",
        sha256="",
        requires=[],
    ),

    # ── PuLID (Flux adapter, advanced) ──
    "pulid-flux": ModelInfo(
        id="pulid-flux",
        name="PuLID for FLUX",
        category=ModelCategory.AVATAR_GENERATION,
        filename="pulid_flux_v0.9.0.safetensors",
        subdir="pulid",
        description="PuLID adapter for FLUX identity customization with minimal disruption.",
        license="Apache 2.0",
        commercial_use_ok=True,
        homepage="https://huggingface.co/guozinan/PuLID",
        download_url="https://huggingface.co/guozinan/PuLID/resolve/main/pulid_flux_v0.9.0.safetensors",
        sha256="",
        requires=["insightface-antelopev2"],
    ),

    # ── IP-Adapter FaceID Plus V2 (face-conditioned generation) ──
    "ip-adapter-faceid-plusv2": ModelInfo(
        id="ip-adapter-faceid-plusv2",
        name="IP-Adapter FaceID Plus V2 (SDXL)",
        category=ModelCategory.AVATAR_GENERATION,
        filename="ip-adapter-faceid-plusv2_sdxl.bin",
        subdir="ipadapter",
        description="Face-conditioned generation adapter for SDXL. Non-commercial license.",
        license="Non-Commercial (h94)",
        commercial_use_ok=False,
        homepage="https://huggingface.co/h94/IP-Adapter-FaceID",
        download_url="https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl.bin",
        sha256="",
        requires=["insightface-antelopev2"],
    ),

    # ── StyleGAN2 FFHQ 256 (fast random faces, non-commercial) ──
    "stylegan2-ffhq-256": ModelInfo(
        id="stylegan2-ffhq-256",
        name="StyleGAN2 FFHQ 256",
        category=ModelCategory.AVATAR_GENERATION,
        filename="stylegan2-ffhq-256x256.pkl",
        subdir="avatar",
        description="Fast random-face generator (FFHQ 256). Non-commercial (NVIDIA).",
        license="NVIDIA Source Code License (Non-commercial)",
        commercial_use_ok=False,
        homepage="https://github.com/NVlabs/stylegan2",
        download_url="https://api.ngc.nvidia.com/v2/models/nvidia/research/stylegan2/versions/1/files/stylegan2-ffhq-256x256.pkl",
        sha256="",
        requires=[],
    ),

    # ── StyleGAN2 FFHQ 1024 (high-quality random faces, non-commercial) ──
    "stylegan2-ffhq-1024": ModelInfo(
        id="stylegan2-ffhq-1024",
        name="StyleGAN2 FFHQ 1024",
        category=ModelCategory.AVATAR_GENERATION,
        filename="stylegan2-ffhq-1024x1024.pkl",
        subdir="avatar",
        description="High-quality random-face generator (FFHQ 1024). Non-commercial (NVIDIA).",
        license="NVIDIA Source Code License (Non-commercial)",
        commercial_use_ok=False,
        homepage="https://github.com/NVlabs/stylegan2",
        download_url="https://api.ngc.nvidia.com/v2/models/nvidia/research/stylegan2/versions/1/files/stylegan2-ffhq-1024x1024.pkl",
        sha256="",
        requires=[],
    ),
}


# All models by category
ALL_MODELS: Dict[ModelCategory, Dict[str, ModelInfo]] = {
    ModelCategory.UPSCALE: UPSCALE_MODELS,
    ModelCategory.FACE_RESTORE: FACE_RESTORE_MODELS,
    ModelCategory.BACKGROUND: BACKGROUND_MODELS,
    # Additive: used by PersonaWizard "Portrait Studio" (future)
    ModelCategory.AVATAR_GENERATION: AVATAR_GENERATION_MODELS,
}


# =============================================================================
# ENHANCE MODE CONFIGURATION
# =============================================================================

@dataclass
class EnhanceModeConfig:
    """Configuration for an enhance mode."""
    mode: str
    name: str
    description: str
    workflow: str
    model_category: ModelCategory
    default_model_id: str
    param_name: str = "upscale_model"  # Workflow parameter name


# Default enhance mode configurations
ENHANCE_MODES: Dict[str, EnhanceModeConfig] = {
    "photo": EnhanceModeConfig(
        mode="photo",
        name="Photo Enhancement",
        description="Natural photo enhancement with texture recovery",
        workflow="upscale",
        model_category=ModelCategory.UPSCALE,
        default_model_id="4x-UltraSharp",
        param_name="upscale_model",
    ),
    "restore": EnhanceModeConfig(
        mode="restore",
        name="Restoration",
        description="Remove artifacts and mild blur",
        workflow="upscale",
        model_category=ModelCategory.UPSCALE,
        default_model_id="4x-UltraSharp",
        param_name="upscale_model",
    ),
    "faces": EnhanceModeConfig(
        mode="faces",
        name="Face Restoration",
        description="Restore and enhance faces",
        workflow="fix_faces_gfpgan",
        model_category=ModelCategory.FACE_RESTORE,
        default_model_id="GFPGANv1.4",
        param_name="model_name",
    ),
}


# =============================================================================
# USER PREFERENCES (Runtime State)
# =============================================================================

@dataclass
class EditModelPreferences:
    """User preferences for edit models."""
    # Selected model IDs by mode
    upscale_model: str = "4x-UltraSharp"
    photo_model: str = "4x-UltraSharp"
    restore_model: str = "4x-UltraSharp"
    faces_model: str = "GFPGANv1.4"

    def get_model_for_mode(self, mode: str) -> str:
        """Get the selected model ID for a given mode."""
        mapping = {
            "upscale": self.upscale_model,
            "photo": self.photo_model,
            "restore": self.restore_model,
            "faces": self.faces_model,
        }
        return mapping.get(mode, self.upscale_model)

    def set_model_for_mode(self, mode: str, model_id: str) -> None:
        """Set the selected model ID for a given mode."""
        if mode == "upscale":
            self.upscale_model = model_id
        elif mode == "photo":
            self.photo_model = model_id
        elif mode == "restore":
            self.restore_model = model_id
        elif mode == "faces":
            self.faces_model = model_id


# Global preferences instance (can be modified at runtime)
_preferences = EditModelPreferences()


def get_preferences() -> EditModelPreferences:
    """Get current model preferences."""
    return _preferences


def set_preferences(prefs: EditModelPreferences) -> None:
    """Set model preferences."""
    global _preferences
    _preferences = prefs


# =============================================================================
# MODEL DETECTION & SELECTION
# =============================================================================

def get_installed_models(category: ModelCategory) -> List[ModelInfo]:
    """Get list of installed models in a category."""
    models = ALL_MODELS.get(category, {})
    return [m for m in models.values() if m.installed]


def get_all_models(category: ModelCategory) -> List[ModelInfo]:
    """Get all models in a category (installed or not)."""
    return list(ALL_MODELS.get(category, {}).values())


def get_model_info(model_id: str) -> Optional[ModelInfo]:
    """Get model info by ID, searching all categories."""
    for category_models in ALL_MODELS.values():
        if model_id in category_models:
            return category_models[model_id]
    return None


def get_default_model(category: ModelCategory) -> Optional[ModelInfo]:
    """Get the default model for a category."""
    models = ALL_MODELS.get(category, {})
    for model in models.values():
        if model.is_default:
            return model
    # Return first if no default specified
    return next(iter(models.values()), None) if models else None


def get_available_model(category: ModelCategory, preferred_id: Optional[str] = None) -> Optional[ModelInfo]:
    """
    Get an available model, preferring the specified one.

    Priority:
    1. Preferred model if installed
    2. Default model if installed
    3. Any installed model
    4. None if nothing installed
    """
    # Try preferred model first
    if preferred_id:
        model = get_model_info(preferred_id)
        if model and model.installed:
            return model

    # Try default model
    default = get_default_model(category)
    if default and default.installed:
        return default

    # Try any installed model
    installed = get_installed_models(category)
    if installed:
        return installed[0]

    return None


# =============================================================================
# HIGH-LEVEL API FOR ENHANCE/UPSCALE
# =============================================================================

def get_upscale_model() -> tuple[Optional[str], Optional[str]]:
    """
    Get the upscale model to use.

    Returns:
        (model_filename, error_message) - filename if available, error if not
    """
    prefs = get_preferences()
    model = get_available_model(ModelCategory.UPSCALE, prefs.upscale_model)

    if model:
        return model.filename, None

    # No model available
    all_models = get_all_models(ModelCategory.UPSCALE)
    model_names = [m.name for m in all_models]
    return None, f"No upscale model installed. Please install one of: {', '.join(model_names)}"


def get_enhance_model(mode: str) -> tuple[Optional[str], Optional[str], Optional[EnhanceModeConfig]]:
    """
    Get the model to use for an enhance mode.

    Args:
        mode: "photo", "restore", or "faces"

    Returns:
        (model_filename, error_message, mode_config)
    """
    mode_config = ENHANCE_MODES.get(mode)
    if not mode_config:
        return None, f"Unknown enhance mode: {mode}", None

    prefs = get_preferences()
    preferred = prefs.get_model_for_mode(mode)
    model = get_available_model(mode_config.model_category, preferred)

    if model:
        return model.filename, None, mode_config

    # No model available
    all_models = get_all_models(mode_config.model_category)
    model_names = [m.name for m in all_models]
    return None, f"No {mode_config.name} model installed. Please install one of: {', '.join(model_names)}", mode_config


def get_face_restore_model() -> tuple[Optional[str], Optional[str]]:
    """
    Get the face restoration model to use.

    Returns:
        (model_filename, error_message)
    """
    prefs = get_preferences()
    model = get_available_model(ModelCategory.FACE_RESTORE, prefs.faces_model)

    if model:
        return model.filename, None

    all_models = get_all_models(ModelCategory.FACE_RESTORE)
    model_names = [m.name for m in all_models]
    return None, f"No face restoration model installed. Please install one of: {', '.join(model_names)}"


# =============================================================================
# STATUS & REPORTING
# =============================================================================

def get_edit_models_status() -> Dict[str, Any]:
    """
    Get comprehensive status of all edit models.

    Returns a dict suitable for API response with installed/available models.
    Includes standalone face restoration availability.
    """
    # Check standalone face restoration availability
    try:
        from .face_restore import check_standalone_available
        standalone_ok, standalone_reason = check_standalone_available()
    except Exception:
        standalone_ok, standalone_reason = False, "Import error"

    status: Dict[str, Any] = {
        "upscale": {
            "installed": [],
            "available": [],
            "selected": get_preferences().upscale_model,
            "default": None,
        },
        "enhance": {
            "photo": {
                "installed": [],
                "available": [],
                "selected": get_preferences().photo_model,
            },
            "restore": {
                "installed": [],
                "available": [],
                "selected": get_preferences().restore_model,
            },
            "faces": {
                "installed": [],
                "available": [],
                "selected": get_preferences().faces_model,
                "standalone_available": standalone_ok,
                "standalone_status": standalone_reason,
            },
        },
    }

    # Upscale models
    for model in get_all_models(ModelCategory.UPSCALE):
        model_info = {
            "id": model.id,
            "name": model.name,
            "description": model.description,
            "filename": model.filename,
            "installed": model.installed,
            "is_default": model.is_default,
        }
        status["upscale"]["available"].append(model_info)
        if model.installed:
            status["upscale"]["installed"].append(model.id)
        if model.is_default:
            status["upscale"]["default"] = model.id

    # Face restore models
    for model in get_all_models(ModelCategory.FACE_RESTORE):
        model_info = {
            "id": model.id,
            "name": model.name,
            "description": model.description,
            "filename": model.filename,
            "installed": model.installed,
            "is_default": model.is_default,
        }
        status["enhance"]["faces"]["available"].append(model_info)
        if model.installed:
            status["enhance"]["faces"]["installed"].append(model.id)

    # Copy upscale info to photo/restore (they use same models)
    status["enhance"]["photo"]["available"] = status["upscale"]["available"]
    status["enhance"]["photo"]["installed"] = status["upscale"]["installed"]
    status["enhance"]["restore"]["available"] = status["upscale"]["available"]
    status["enhance"]["restore"]["installed"] = status["upscale"]["installed"]

    return status


def set_model_preference(mode: str, model_id: str) -> tuple[bool, Optional[str]]:
    """
    Set the preferred model for a mode.

    Args:
        mode: "upscale", "photo", "restore", or "faces"
        model_id: The model ID to use

    Returns:
        (success, error_message)
    """
    # Validate model exists
    model = get_model_info(model_id)
    if not model:
        return False, f"Unknown model: {model_id}"

    # Validate model category matches mode
    mode_to_category = {
        "upscale": ModelCategory.UPSCALE,
        "photo": ModelCategory.UPSCALE,
        "restore": ModelCategory.UPSCALE,
        "faces": ModelCategory.FACE_RESTORE,
    }

    expected_category = mode_to_category.get(mode)
    if not expected_category:
        return False, f"Unknown mode: {mode}"

    if model.category != expected_category:
        return False, f"Model {model_id} is not compatible with mode {mode}"

    # Check if installed
    if not model.installed:
        return False, f"Model {model.name} is not installed. Please install it first."

    # Set preference
    prefs = get_preferences()
    prefs.set_model_for_mode(mode, model_id)

    return True, None


# =============================================================================
# AVATAR MODEL STATUS (Additive — does NOT affect edit/enhance behavior)
# =============================================================================

def get_avatar_models_status() -> Dict[str, Any]:
    """
    Return installed/available status for Avatar Generator models.

    Intended for the PersonaWizard UI to gate avatar generation modes
    (enable/disable based on which models are downloaded).
    This does NOT alter existing edit/enhance behavior.
    """
    models = get_all_models(ModelCategory.AVATAR_GENERATION)

    available = []
    installed_ids = []

    # Feature-to-model mapping: which models each feature needs
    FEATURE_MODELS: Dict[str, Dict[str, Any]] = {
        "photo_variations": {
            "label": "Same-Person Photo Variations",
            "description": "Generate new photos preserving the persona's identity",
            "required": ["insightface-antelopev2", "instantid-ip-adapter"],
            "recommended": ["instantid-controlnet"],
        },
        "outfit_generation": {
            "label": "Outfit / Wardrobe Generation",
            "description": "Generate outfit variations with identity preservation",
            "required": ["insightface-antelopev2", "instantid-ip-adapter", "instantid-controlnet"],
            "recommended": ["photomaker-v2", "pulid-flux"],
            "recommended_note": "PhotoMaker V2 for SDXL models, PuLID for FLUX models",
        },
        "face_swap": {
            "label": "Face Swap",
            "description": "Transfer identity onto generated or existing images",
            "required": ["insightface-antelopev2", "insightface-inswapper-128"],
            "recommended": [],
        },
        "random_faces": {
            "label": "Random Face Generator",
            "description": "Generate random realistic faces (non-commercial)",
            "required": ["stylegan2-ffhq-256"],
            "recommended": ["stylegan2-ffhq-1024"],
            "recommended_note": "1024px version for higher quality output",
        },
    }

    # Build model→features reverse index
    model_features: Dict[str, list] = {}
    for feat_id, feat in FEATURE_MODELS.items():
        for mid in feat["required"]:
            model_features.setdefault(mid, []).append({"feature": feat_id, "role": "required"})
        for mid in feat.get("recommended", []):
            model_features.setdefault(mid, []).append({"feature": feat_id, "role": "recommended"})

    for m in models:
        info = {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "filename": m.filename,
            "subdir": m.subdir,
            "installed": m.installed,
            "license": m.license,
            "commercial_use_ok": m.commercial_use_ok,
            "homepage": m.homepage,
            "download_url": m.download_url,
            "sha256": m.sha256,
            "requires": m.requires,
            "is_default": m.is_default,
            "used_by": model_features.get(m.id, []),
        }
        available.append(info)
        if m.installed:
            installed_ids.append(m.id)

    # Compute feature readiness
    installed_set = set(installed_ids)
    features = {}
    for feat_id, feat in FEATURE_MODELS.items():
        required_ok = all(mid in installed_set for mid in feat["required"])
        required_missing = [mid for mid in feat["required"] if mid not in installed_set]
        recommended_ok = all(mid in installed_set for mid in feat.get("recommended", []))
        features[feat_id] = {
            "label": feat["label"],
            "description": feat["description"],
            "ready": required_ok,
            "required_missing": required_missing,
            "recommended_installed": recommended_ok,
            "recommended_note": feat.get("recommended_note"),
        }

    return {
        "category": ModelCategory.AVATAR_GENERATION.value,
        "installed": installed_ids,
        "available": available,
        "defaults": [m.id for m in models if m.is_default],
        "features": features,
    }
