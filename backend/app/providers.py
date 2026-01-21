# homepilot/backend/app/providers.py
from __future__ import annotations

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
