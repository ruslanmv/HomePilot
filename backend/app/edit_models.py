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

# All models by category
ALL_MODELS: Dict[ModelCategory, Dict[str, ModelInfo]] = {
    ModelCategory.UPSCALE: UPSCALE_MODELS,
    ModelCategory.FACE_RESTORE: FACE_RESTORE_MODELS,
    ModelCategory.BACKGROUND: BACKGROUND_MODELS,
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
    """
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
