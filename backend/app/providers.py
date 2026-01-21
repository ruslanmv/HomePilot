# homepilot/backend/app/providers.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any, List

from .config import (
    DEFAULT_PROVIDER,
    LLM_BASE_URL,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    COMFY_BASE_URL,
    IMAGE_MODEL,
    VIDEO_MODEL,
    NSFW_MODE,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL,
)

def available_providers() -> List[str]:
    """Providers exposed to the frontend.

    NOTE: openai/claude availability is determined by backend env vars (API keys),
    but we still expose them so the UI can show a clear 'missing key' error when
    listing models.
    """
    return [
        "openai_compat",
        "ollama",
        "openai",
        "claude",
        "watsonx",
        "comfyui",
    ]

def available_image_models() -> List[str]:
    """
    Returns list of available image generation models.
    These correspond to ComfyUI workflow files.
    """
    return [
        "sdxl",           # Stable Diffusion XL (default)
        "flux-schnell",   # Flux Schnell (fast, uncensored)
        "flux-dev",       # Flux Dev (higher quality, uncensored)
        "pony-xl",        # Pony Diffusion XL (NSFW optimized)
        "sd15-uncensored",# SD 1.5 with uncensored checkpoint
    ]

def available_video_models() -> List[str]:
    """
    Returns list of available video generation models.
    These correspond to ComfyUI workflow files.
    """
    return [
        "svd",            # Stable Video Diffusion (default)
        "wan-2.2",        # Wanxian 2.2 (uncensored)
        "seedream",       # Seedream 4.0+ (uncensored)
    ]

def get_comfy_models_path() -> Path:
    """Get the path to ComfyUI models directory."""
    # Try to find models directory
    # Priority: 1) ./models/comfy  2) ./ComfyUI/models  3) /ComfyUI/models (Docker)
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent

    # Check ./models/comfy (HomePilot standard)
    models_path = repo_root / "models" / "comfy"
    if models_path.exists():
        return models_path

    # Check ./ComfyUI/models (local ComfyUI clone)
    comfyui_models = repo_root / "ComfyUI" / "models"
    if comfyui_models.exists():
        return comfyui_models

    # Check /ComfyUI/models (Docker)
    docker_models = Path("/ComfyUI/models")
    if docker_models.exists():
        return docker_models

    # Default to expected path even if it doesn't exist
    return models_path

def scan_installed_models(model_type: str = "image") -> List[str]:
    """
    Scan filesystem for actually installed ComfyUI models.
    Returns list of workflow IDs that have their required files.
    """
    models_path = get_comfy_models_path()
    installed = []

    # Model file to workflow mapping
    if model_type == "image":
        # Check for actual model files and map to workflow names
        checks = {
            "sdxl": models_path / "checkpoints" / "sd_xl_base_1.0.safetensors",
            "flux-schnell": models_path / "unet" / "flux1-schnell.safetensors",
            "flux-dev": models_path / "unet" / "flux1-dev.safetensors",
            "pony-xl": models_path / "checkpoints" / "ponyDiffusionV6XL.safetensors",
            "sd15-uncensored": models_path / "checkpoints" / "dreamshaper_8.safetensors",
        }
    else:  # video
        checks = {
            "svd": models_path / "checkpoints" / "svd_xt.safetensors",
        }

    # Check which models are actually installed
    for workflow_id, model_path in checks.items():
        if model_path.exists() and model_path.stat().st_size > 0:
            installed.append(workflow_id)

    # If no models found, return the available list (backward compatibility)
    if not installed:
        return available_image_models() if model_type == "image" else available_video_models()

    return installed

def provider_info() -> Dict[str, Dict[str, Any]]:
    """
    Safe info for frontend settings UI (no secrets).
    Includes capabilities for each provider.
    """
    return {
        "openai_compat": {
            "label": "OpenAI-compatible (vLLM)",
            "base_url": LLM_BASE_URL,
            "default_model": LLM_MODEL,
            "capabilities": {
                "chat": True,
                "models_list": True,
                "images": False,
                "video": False,
            },
        },
        "ollama": {
            "label": "Ollama (optional)",
            "base_url": OLLAMA_BASE_URL,
            "default_model": OLLAMA_MODEL or "",
            "capabilities": {
                "chat": True,
                "models_list": True,
                "images": False,
                "video": False,
            },
        },
        "openai": {
            "label": "OpenAI",
            "base_url": OPENAI_BASE_URL,
            "default_model": OPENAI_MODEL,
            "capabilities": {
                "chat": True,
                "models_list": True,
                "images": False,
                "video": False,
            },
        },
        "claude": {
            "label": "Claude (Anthropic)",
            "base_url": ANTHROPIC_BASE_URL,
            "default_model": ANTHROPIC_MODEL,
            "capabilities": {
                "chat": True,
                "models_list": True,
                "images": False,
                "video": False,
            },
        },
        "watsonx": {
            "label": "Watsonx.ai (IBM)",
            "base_url": "",
            "default_model": "",
            "capabilities": {
                # Model listing is supported; chat requires additional IBM IAM config
                "chat": False,
                "models_list": True,
                "images": False,
                "video": False,
            },
        },
        "comfyui": {
            "label": "ComfyUI (Local Generation)",
            "base_url": COMFY_BASE_URL,
            "default_image_model": IMAGE_MODEL,
            "default_video_model": VIDEO_MODEL,
            "nsfw_mode": NSFW_MODE,
            "capabilities": {
                "chat": False,
                "models_list": True,
                "images": True,
                "video": True,
            },
        },
    }
