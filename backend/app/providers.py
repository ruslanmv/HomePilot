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


def get_comfyui_root() -> Path:
    """Get the path to ComfyUI installation root (where custom_nodes lives)."""
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent

    candidates = [
        repo_root / "ComfyUI",           # Local development
        Path("/ComfyUI"),                # Docker container
        Path.home() / "ComfyUI",         # Home directory
        Path("/mnt/c/workspace/homegrok/homepilot/ComfyUI"),  # WSL specific
    ]
    for p in candidates:
        if p.exists() and (p / "custom_nodes").exists():
            return p
    return candidates[0]


def get_comfy_object_info(base_url: str = None) -> dict:
    """
    Fetch ComfyUI's /object_info to check which nodes are available.
    Returns dict of node_name -> node_info, or empty dict on failure.
    """
    import requests
    url = (base_url or COMFY_BASE_URL).rstrip("/")
    try:
        r = requests.get(f"{url}/object_info", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def check_comfy_nodes_available(node_names: List[str], base_url: str = None) -> bool:
    """
    Check if specific ComfyUI nodes are available via /object_info.
    Returns True if at least one of the nodes exists (addon is loaded).
    """
    object_info = get_comfy_object_info(base_url)
    if not object_info:
        return False
    # Check if any of the nodes exist
    return any(name in object_info for name in node_names)

# ---------------------------------------------------------------------------
# Video model filename patterns – used to distinguish video from image models
# when dynamically discovering checkpoints on disk.
# ---------------------------------------------------------------------------
VIDEO_MODEL_PATTERNS = (
    "svd",          # Stable Video Diffusion (svd.safetensors, svd_xt.safetensors, svd_xt_1_1.safetensors)
    "ltx-video",    # LTX-Video
    "ltx_video",    # LTX-Video (underscore variant)
    "hunyuanvideo", # HunyuanVideo
    "wan2",         # Wanxian 2.x
    "mochi",        # Mochi preview
    "cogvideo",     # CogVideoX
    "animatediff",  # AnimateDiff
    "videocrafter", # VideoCrafter
    "modelscope",   # ModelScope text-to-video
    "zeroscope",    # Zeroscope video
    "hotshot",      # Hotshot-XL video
)

# Inpainting / edit model patterns – should not appear in image or video lists
EDIT_MODEL_PATTERNS = (
    "inpainting",
    "inpaint",
)


def _is_video_model(filename: str) -> bool:
    """Return True if *filename* looks like a video generation model."""
    lower = filename.lower()
    return any(pat in lower for pat in VIDEO_MODEL_PATTERNS)


def _is_edit_model(filename: str) -> bool:
    """Return True if *filename* looks like an inpainting / edit model."""
    lower = filename.lower()
    return any(pat in lower for pat in EDIT_MODEL_PATTERNS)


def _discover_checkpoint_files(models_path: Path) -> List[str]:
    """
    Dynamically scan the checkpoints directory for model files that are not
    in the hardcoded known-model lists.  Returns a list of filenames.
    """
    checkpoints_dir = models_path / "checkpoints"
    if not checkpoints_dir.exists():
        return []

    discovered: List[str] = []
    for ext in ("*.safetensors", "*.ckpt", "*.pth"):
        for f in checkpoints_dir.glob(ext):
            try:
                if f.is_file() and f.stat().st_size > 0:
                    discovered.append(f.name)
            except OSError:
                continue
    return discovered


def scan_installed_models(model_type: str = "image") -> List[str]:
    """
    Scan filesystem for actually installed ComfyUI models.
    Returns list of catalog IDs (filenames) that are installed.
    This matches the IDs used in model_catalog_data.json for proper UI display.

    For "image" and "video" types, also dynamically discovers checkpoint files
    on disk and classifies them using VIDEO_MODEL_PATTERNS so that video models
    never leak into the image list and vice-versa.
    """
    models_path = get_comfy_models_path()
    installed = []

    # Model checks: catalog_id -> file path
    # The catalog_id matches model_catalog_data.json "id" field
    if model_type == "image":
        checks = {
            # Standard SFW models
            "sd_xl_base_1.0.safetensors": models_path / "checkpoints" / "sd_xl_base_1.0.safetensors",
            "flux1-schnell.safetensors": models_path / "unet" / "flux1-schnell.safetensors",
            "flux1-dev.safetensors": models_path / "unet" / "flux1-dev.safetensors",
            "sd15.safetensors": models_path / "checkpoints" / "v1-5-pruned-emaonly.safetensors",
            "realisticVisionV51.safetensors": models_path / "checkpoints" / "realisticVisionV51.safetensors",
            # NSFW models (shown when Spice Mode enabled)
            "ponyDiffusionV6XL_v6.safetensors": models_path / "checkpoints" / "ponyDiffusionV6XL_v6.safetensors",
            "dreamshaper_8.safetensors": models_path / "checkpoints" / "dreamshaper_8.safetensors",
            "deliberate_v3.safetensors": models_path / "checkpoints" / "deliberate_v3.safetensors",
            "epicrealism_pureEvolution.safetensors": models_path / "checkpoints" / "epicrealism_pureEvolution.safetensors",
            "cyberrealistic_v42.safetensors": models_path / "checkpoints" / "cyberrealistic_v42.safetensors",
            "absolutereality_v181.safetensors": models_path / "checkpoints" / "absolutereality_v181.safetensors",
            "aZovyaRPGArtist_v5.safetensors": models_path / "checkpoints" / "aZovyaRPGArtist_v5.safetensors",
            "unstableDiffusion.safetensors": models_path / "checkpoints" / "unstableDiffusion.safetensors",
            "majicmixRealistic_v7.safetensors": models_path / "checkpoints" / "majicmixRealistic_v7.safetensors",
            "bbmix_v4.safetensors": models_path / "checkpoints" / "bbmix_v4.safetensors",
            "realisian_v50.safetensors": models_path / "checkpoints" / "realisian_v50.safetensors",
            "abyssOrangeMix3_aom3a1b.safetensors": models_path / "checkpoints" / "abyssOrangeMix3_aom3a1b.safetensors",
        }
    elif model_type == "video":
        checks = {
            # SVD models
            "svd_xt_1_1.safetensors": models_path / "checkpoints" / "svd_xt_1_1.safetensors",
            "svd_xt.safetensors": models_path / "checkpoints" / "svd_xt.safetensors",
            "svd.safetensors": models_path / "checkpoints" / "svd.safetensors",
            # LTX-Video
            "ltx-video-2b-v0.9.1.safetensors": models_path / "checkpoints" / "ltx-video-2b-v0.9.1.safetensors",
            # HunyuanVideo GGUF pack (check primary unet file)
            "hunyuanvideo_t2v_720p_gguf_q4_k_m_pack": models_path / "unet" / "hunyuanvideo-q4_k_m.gguf",
            # Wan 2.2 pack (check primary diffusion model)
            "wan2.2_5b_fp16_pack": models_path / "diffusion_models" / "wan2.2_ti2v_5B_fp16.safetensors",
            # Mochi FP8 pack (check primary diffusion model)
            "mochi_preview_fp8_pack": models_path / "diffusion_models" / "mochi_preview_fp8_scaled.safetensors",
            # CogVideoX snapshot (check diffusers directory exists)
            "cogvideox1.5_5b_i2v_snapshot": models_path / "diffusers" / "CogVideoX1.5-5B-I2V",
        }
    elif model_type == "edit":
        checks = {
            # Inpainting backbones
            "sd_xl_base_1.0_inpainting_0.1.safetensors": models_path / "checkpoints" / "sd_xl_base_1.0_inpainting_0.1.safetensors",
            "sd-v1-5-inpainting.ckpt": models_path / "checkpoints" / "sd-v1-5-inpainting.ckpt",
            # ControlNet (inpaint guidance)
            "control_v11p_sd15_inpaint.safetensors": models_path / "controlnet" / "control_v11p_sd15_inpaint.safetensors",
            # Optional helpers / adapters
            "sam_vit_h_4b8939.pth": models_path / "sams" / "sam_vit_h_4b8939.pth",
            "u2net.onnx": models_path / "rembg" / "u2net.onnx",
        }
    elif model_type == "enhance":
        checks = {
            # ComfyUI upscale / restoration weights
            "4x-UltraSharp.pth": models_path / "upscale_models" / "4x-UltraSharp.pth",
            "RealESRGAN_x4plus.pth": models_path / "upscale_models" / "RealESRGAN_x4plus.pth",
            "realesr-general-x4v3.pth": models_path / "upscale_models" / "realesr-general-x4v3.pth",
            "SwinIR_4x.pth": models_path / "upscale_models" / "SwinIR_4x.pth",
            # Optional face restoration
            "GFPGANv1.4.pth": models_path / "gfpgan" / "GFPGANv1.4.pth",
            "codeformer.pth": models_path / "codeformer" / "codeformer.pth",
        }
    elif model_type == "addons":
        # For addons, check custom_nodes directory existence
        # and/or ComfyUI's /object_info for loaded nodes
        comfyui_root = get_comfyui_root()
        custom_nodes_dir = comfyui_root / "custom_nodes"

        # Addon checks: addon_id -> (folder_name, sample_node_names)
        addon_checks = {
            "ComfyUI-VideoHelperSuite": ("ComfyUI-VideoHelperSuite", ["VHS_VideoCombine"]),
            "ComfyUI-LTXVideo": ("ComfyUI-LTXVideo", ["LTXVLoader"]),
            "ComfyUI-GGUF": ("ComfyUI-GGUF", ["UnetLoaderGGUF"]),
            "ComfyUI-CogVideoXWrapper": ("ComfyUI-CogVideoXWrapper", ["CogVideoXDiffusersLoader"]),
            "ComfyUI-Impact-Pack": ("ComfyUI-Impact-Pack", ["SAMLoader"]),
        }

        for addon_id, (folder_name, sample_nodes) in addon_checks.items():
            addon_path = custom_nodes_dir / folder_name
            # Check if folder exists first (fast check)
            if addon_path.exists() and addon_path.is_dir():
                # Optionally verify nodes are loaded via /object_info
                # This confirms the addon is actually working
                if check_comfy_nodes_available(sample_nodes):
                    installed.append(addon_id)
                else:
                    # Folder exists but nodes not loaded (maybe ComfyUI needs restart)
                    # Still mark as installed but frontend can show "restart needed"
                    installed.append(addon_id)

        return installed
    else:
        # Unknown model_type, return empty
        checks = {}

    # Check which models are actually installed (from the known list)
    for catalog_id, model_path in checks.items():
        if model_path.exists() and model_path.stat().st_size > 0:
            installed.append(catalog_id)

    # -----------------------------------------------------------------------
    # Dynamic discovery: also scan the checkpoints directory for model files
    # that are NOT in our hardcoded lists.  Classify them as image or video
    # based on filename patterns so that video models never appear in the
    # image dropdown and vice-versa.
    # -----------------------------------------------------------------------
    if model_type in ("image", "video"):
        # Collect all catalog IDs we already know about (across ALL types)
        # so we don't duplicate them.
        all_known_ids = set(checks.keys())

        for filename in _discover_checkpoint_files(models_path):
            if filename in all_known_ids:
                continue  # already handled by the hardcoded list

            is_video = _is_video_model(filename)
            is_edit = _is_edit_model(filename)

            if model_type == "image" and not is_video and not is_edit:
                installed.append(filename)
            elif model_type == "video" and is_video and not is_edit:
                installed.append(filename)

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
                "edit": True,
            },
        },
    }
