"""
Video Generation Presets Module

Provides quality presets for video generation with model-specific overrides.
Supports GPU VRAM-based auto-selection of appropriate presets.
"""

import json
import os
from typing import Dict, Any, Optional, List

# Load presets from JSON file
_PRESETS_FILE = os.path.join(os.path.dirname(__file__), "video_presets.json")
_presets_cache: Optional[Dict[str, Any]] = None


def _load_presets() -> Dict[str, Any]:
    """Load presets from JSON file (cached)."""
    global _presets_cache
    if _presets_cache is None:
        with open(_PRESETS_FILE, "r") as f:
            _presets_cache = json.load(f)
    return _presets_cache


def get_preset_names() -> List[str]:
    """Get list of available preset names."""
    presets = _load_presets()
    return list(presets.get("presets", {}).keys())


def get_preset_info() -> List[Dict[str, Any]]:
    """Get preset info for UI display (label, description, etc.)."""
    presets = _load_presets()
    result = []
    for name, preset in presets.get("presets", {}).items():
        ui = preset.get("ui", {})
        result.append({
            "id": name,
            "label": ui.get("label", name.title()),
            "short": ui.get("short", ""),
            "description": ui.get("description", ""),
        })
    return result


def detect_model_type(model_name: Optional[str]) -> Optional[str]:
    """
    Detect the model type from a model filename.
    Returns: 'svd', 'ltx', 'wan', 'hunyuan', 'mochi', 'cogvideo', or None
    """
    if not model_name:
        return None

    lower = model_name.lower()

    if "ltx" in lower:
        return "ltx"
    elif "svd" in lower:
        return "svd"
    elif "wan" in lower:
        return "wan"
    elif "hunyuan" in lower:
        return "hunyuan"
    elif "mochi" in lower:
        return "mochi"
    elif "cogvideo" in lower or "cog" in lower:
        return "cogvideo"

    return None


def get_preset_for_vram(vram_gb: Optional[float] = None) -> str:
    """
    Auto-select a preset based on available VRAM.

    Args:
        vram_gb: Available VRAM in GB. If None, returns fallback preset.

    Returns:
        Preset name (e.g., 'low', 'medium', 'high', 'ultra')
    """
    presets = _load_presets()
    auto_config = presets.get("vram_auto_select", {})
    fallback = auto_config.get("fallback", "medium")

    if vram_gb is None:
        return fallback

    rules = auto_config.get("rules", [])
    for rule in rules:
        if vram_gb <= rule.get("max_vram_gb", 999):
            return rule.get("preset", fallback)

    return fallback


def enforce_frame_rule(model_type: Optional[str], frames: int, strategy: str = "closest") -> int:
    """
    Enforce model-specific frame rules.

    Args:
        model_type: The detected model type
        frames: Requested frame count
        strategy: "closest" (default) or "ceil" (round up to next valid)

    Returns:
        Adjusted frame count that satisfies model requirements
    """
    presets = _load_presets()
    rules = presets.get("model_rules", {})

    if not model_type or model_type not in rules:
        return frames

    rule = rules[model_type]
    frame_rule = rule.get("frame_rule", "any")

    if frame_rule == "fixed":
        return rule.get("fixed_frames", frames)

    elif frame_rule == "8n+1":
        # LTX-Video: frames must be 8n+1 (9, 17, 25, 33, ...)
        valid = rule.get("valid_frames", [])
        min_frames = rule.get("min_frames", 9)

        if frames < min_frames:
            return min_frames

        # Find valid frame count based on strategy
        if valid:
            valid_filtered = sorted([f for f in valid if f >= min_frames])
            if valid_filtered:
                if strategy == "ceil":
                    # Round up to next valid frame count
                    for v in valid_filtered:
                        if v >= frames:
                            return v
                    # If frames exceeds all valid, return max valid
                    return valid_filtered[-1]
                else:
                    # Default: find closest valid frame count
                    closest = min(valid_filtered, key=lambda x: abs(x - frames))
                    return closest

        # Calculate: find n such that 8n+1 is closest to frames
        n = max(1, (frames - 1) // 8)
        return 8 * n + 1

    elif frame_rule == "6n+1":
        # Mochi: frames must be 6n+1 (37, 43, 49, ...)
        valid = rule.get("valid_frames", [])
        min_frames = rule.get("min_frames", 37)

        if frames < min_frames:
            return min_frames

        if valid:
            # Find closest valid frame count >= min_frames
            valid_filtered = [f for f in valid if f >= min_frames]
            if valid_filtered:
                closest = min(valid_filtered, key=lambda x: abs(x - frames))
                return closest

        # Calculate: find n such that 6n+1 is closest to frames
        n = max(6, (frames - 1) // 6)
        return 6 * n + 1

    return frames


def get_workflow_vars(
    preset_name: str,
    model_type: Optional[str] = None,
    custom_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Get workflow variables for a given preset and model.

    Args:
        preset_name: Name of the preset ('low', 'medium', 'high', 'ultra')
        model_type: Optional model type for model-specific overrides
        custom_overrides: Optional dict of custom values to override preset

    Returns:
        Dict with: width, height, fps, frames, steps, cfg, denoise, etc.
    """
    presets = _load_presets()
    preset_data = presets.get("presets", {}).get(preset_name)

    if not preset_data:
        # Fallback to medium if preset not found
        preset_data = presets.get("presets", {}).get("medium", {})

    # Start with base settings
    result = dict(preset_data.get("base", {}))

    # Apply model-specific overrides if available
    if model_type:
        model_overrides = preset_data.get("model_overrides", {}).get(model_type, {})
        result.update(model_overrides)

    # Apply custom overrides (from user's Advanced Controls)
    if custom_overrides:
        for key, value in custom_overrides.items():
            if value is not None:
                result[key] = value

    # Enforce frame rules
    if "frames" in result:
        result["frames"] = enforce_frame_rule(model_type, result["frames"])

    return result


def apply_preset_to_workflow_vars(
    preset_name: Optional[str],
    model_name: Optional[str],
    vid_seconds: Optional[int] = None,
    vid_fps: Optional[int] = None,
    vid_steps: Optional[int] = None,
    vid_cfg: Optional[float] = None,
    vid_denoise: Optional[float] = None,
    vid_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Convenience function to apply preset with user overrides.

    This is the main entry point for the orchestrator.

    Args:
        preset_name: Preset to use ('low', 'medium', 'high', 'ultra', or None for medium)
        model_name: Full model filename to detect type from
        vid_*: Optional user overrides from Advanced Controls

    Returns:
        Dict with all workflow variables ready to use
    """
    # Detect model type
    model_type = detect_model_type(model_name)

    # Use medium as default if no preset specified
    if not preset_name:
        preset_name = "medium"

    # Build custom overrides from user inputs
    custom_overrides = {}
    if vid_steps is not None:
        custom_overrides["steps"] = vid_steps
    if vid_cfg is not None:
        custom_overrides["cfg"] = vid_cfg
    if vid_denoise is not None:
        custom_overrides["denoise"] = vid_denoise
    if vid_fps is not None:
        custom_overrides["fps"] = vid_fps

    # Get preset values with overrides
    result = get_workflow_vars(preset_name, model_type, custom_overrides)

    # Handle seconds -> frames conversion if seconds provided
    if vid_seconds is not None:
        fps = result.get("fps", 8)
        frames = vid_seconds * fps
        # Enforce frame rules with ceil strategy (round up to ensure requested duration)
        result["frames"] = enforce_frame_rule(model_type, frames, strategy="ceil")
        result["seconds"] = vid_seconds

    # Enforce max_frames cap to prevent GPU overload
    max_frames = result.get("max_frames")
    if max_frames and result.get("frames", 0) > max_frames:
        # Cap to max_frames, then enforce frame rule again
        result["frames"] = enforce_frame_rule(model_type, max_frames)

    # Add seed if provided
    if vid_seed is not None:
        result["seed"] = vid_seed

    return result


# Expose preset info for API endpoints
def get_presets_for_api() -> Dict[str, Any]:
    """Get preset data formatted for API response."""
    presets = _load_presets()
    return {
        "presets": get_preset_info(),
        "model_rules": presets.get("model_rules", {}),
        "vram_auto_select": presets.get("vram_auto_select", {}),
        "model_min_vram": presets.get("model_min_vram", {}),
    }
