"""
Model Configuration & Preset Logic (Complete)
Matches presets to model architectures (SD1.5 vs SDXL vs Flux) and returns
correct width/height/steps/cfg for a chosen aspect ratio + quality preset.

Includes:
- Full model architecture mapping for all listed models
- Resolution tables for SD1.5 and SDXL/Flux
- Step/CFG presets for each architecture
- Validation helpers + convenience functions
"""

from __future__ import annotations
from typing import Dict, Literal, TypedDict, Union

# =============================================================================
# TYPES
# =============================================================================

Architecture = Literal["sd15", "sdxl", "flux_schnell", "flux_dev"]
PresetName = Literal["low", "med", "high"]
AspectRatio = Literal["1:1", "4:3", "3:4", "16:9", "9:16"]


class Dimensions(TypedDict):
    width: int
    height: int


class StepCfg(TypedDict):
    steps: int
    cfg: float


class ModelSettings(TypedDict):
    width: int
    height: int
    steps: int
    cfg: float
    architecture: Architecture


# =============================================================================
# 1. MODEL ARCHITECTURE MAPPING
# =============================================================================
# Maps every model filename to its architecture.
# Unknown models default to SD1.5 unless you choose to enforce strict validation.

MODEL_ARCHITECTURES: Dict[str, Architecture] = {
    # --- SDXL Models (Native 1024x1024) ---
    "sd_xl_base_1.0.safetensors": "sdxl",
    "ponyDiffusionV6XL.safetensors": "sdxl",

    # --- Flux Models (Native 1024+, Special Steps / CFG behavior) ---
    "flux1-schnell.safetensors": "flux_schnell",  # 4-step turbo model
    "flux1-dev.safetensors": "flux_dev",          # High quality model

    # --- SD 1.5 Models (Native 512x512) ---
    "dreamshaper_8.safetensors": "sd15",
    "epicrealism_pureEvolution.safetensors": "sd15",
    "abyssOrangeMix3_aom3a1b.safetensors": "sd15",
    "sd15.safetensors": "sd15",
    "realisticVisionV51.safetensors": "sd15",
    "deliberate_v3.safetensors": "sd15",
    "cyberrealistic_v42.safetensors": "sd15",
    "absolutereality_v181.safetensors": "sd15",
    "aZovyaRPGArtist_v5.safetensors": "sd15",
    "unstableDiffusion.safetensors": "sd15",
    "majicmixRealistic_v7.safetensors": "sd15",
    "bbmix_v4.safetensors": "sd15",
    "realisian_v50.safetensors": "sd15",
    "counterfeit_v30.safetensors": "sd15",
    "anything_v5PrtRE.safetensors": "sd15",
}

# =============================================================================
# 2. RESOLUTION LOOKUP TABLES
# =============================================================================

# SD 1.5: Strict limits to prevent "Two Heads" (keep dimensions conservative)
SD15_RESOLUTIONS: Dict[AspectRatio, Dimensions] = {
    "1:1":  {"width": 512, "height": 512},
    "4:3":  {"width": 680, "height": 512},  # Balanced Landscape
    "3:4":  {"width": 512, "height": 680},  # Balanced Portrait
    "16:9": {"width": 768, "height": 432},  # Cinema
    "9:16": {"width": 432, "height": 768},  # Mobile
}

# SDXL / Flux: High Resolution Native (Base 1024)
SDXL_RESOLUTIONS: Dict[AspectRatio, Dimensions] = {
    "1:1":  {"width": 1024, "height": 1024},
    "4:3":  {"width": 1152, "height": 896},
    "3:4":  {"width": 896,  "height": 1152},
    "16:9": {"width": 1216, "height": 832},
    "9:16": {"width": 832,  "height": 1216},
}

# =============================================================================
# 3. GENERATION PRESETS (Steps & CFG)
# =============================================================================

PRESETS: Dict[Architecture, Dict[PresetName, StepCfg]] = {
    # Standard SD 1.5 (DreamShaper, Realistic Vision, etc.)
    "sd15": {
        "low":  {"steps": 20, "cfg": 7.0},
        "med":  {"steps": 25, "cfg": 7.0},
        "high": {"steps": 35, "cfg": 8.0},
    },

    # Standard SDXL (Base, Pony)
    "sdxl": {
        "low":  {"steps": 25, "cfg": 5.0},
        "med":  {"steps": 30, "cfg": 5.5},
        "high": {"steps": 45, "cfg": 6.0},
    },

    # Flux SCHNELL (Must be fast; optimized for very low step counts)
    "flux_schnell": {
        "low":  {"steps": 4, "cfg": 1.0},
        "med":  {"steps": 4, "cfg": 1.0},
        "high": {"steps": 6, "cfg": 1.0},
    },

    # Flux DEV (High quality; likes lower CFG)
    "flux_dev": {
        "low":  {"steps": 20, "cfg": 3.5},
        "med":  {"steps": 25, "cfg": 3.5},
        "high": {"steps": 40, "cfg": 4.0},
    },
}

# =============================================================================
# 4. VALIDATION & HELPERS
# =============================================================================

DEFAULT_ARCH: Architecture = "sd15"
DEFAULT_ASPECT: AspectRatio = "1:1"
DEFAULT_PRESET: PresetName = "med"


def list_known_models() -> list[str]:
    """Returns all known model filenames from MODEL_ARCHITECTURES."""
    return sorted(MODEL_ARCHITECTURES.keys())


def get_architecture(model_filename: str, *, strict: bool = False) -> Architecture:
    """
    Returns model architecture by filename.

    Args:
        model_filename: Exact filename (e.g. "dreamshaper_8.safetensors")
        strict: If True, raise KeyError when model is unknown.
                If False, unknown models default to DEFAULT_ARCH.

    Returns:
        Architecture string.
    """
    if strict and model_filename not in MODEL_ARCHITECTURES:
        raise KeyError(
            f"Unknown model filename: {model_filename!r}. "
            f"Add it to MODEL_ARCHITECTURES."
        )
    return MODEL_ARCHITECTURES.get(model_filename, DEFAULT_ARCH)


def get_resolution_table(arch: Architecture) -> Dict[AspectRatio, Dimensions]:
    """
    Flux uses SDXL resolution table, SD1.5 uses SD15 resolution table.
    """
    if arch in ("sdxl", "flux_schnell", "flux_dev"):
        return SDXL_RESOLUTIONS
    return SD15_RESOLUTIONS


def normalize_aspect_ratio(aspect_ratio: str) -> AspectRatio:
    """
    Coerces unknown aspect ratios to DEFAULT_ASPECT instead of raising.
    """
    allowed = set(SD15_RESOLUTIONS.keys()) | set(SDXL_RESOLUTIONS.keys())
    return aspect_ratio if aspect_ratio in allowed else DEFAULT_ASPECT  # type: ignore[return-value]


def normalize_preset(preset: str) -> PresetName:
    """
    Coerces unknown preset strings to DEFAULT_PRESET instead of raising.
    """
    return preset if preset in ("low", "med", "high") else DEFAULT_PRESET  # type: ignore[return-value]


def detect_architecture_from_filename(model_filename: str) -> Architecture:
    """
    Heuristically detect architecture from model filename patterns.
    Used for models not explicitly in MODEL_ARCHITECTURES.

    Args:
        model_filename: Model filename to analyze

    Returns:
        Best guess architecture based on naming patterns
    """
    lower = model_filename.lower()

    # Flux detection
    if "flux" in lower:
        if "schnell" in lower:
            return "flux_schnell"
        return "flux_dev"

    # SDXL detection
    if any(x in lower for x in ["sdxl", "_xl", "-xl", "xl_", "pony"]):
        return "sdxl"

    # Everything else defaults to SD1.5 (safest for preventing duplication)
    return "sd15"


# =============================================================================
# 5. MAIN LOGIC
# =============================================================================

def get_model_settings(
    model_filename: str,
    aspect_ratio: str,
    preset: str = DEFAULT_PRESET,
    *,
    strict_model: bool = False,
) -> ModelSettings:
    """
    Returns the correct Width, Height, Steps, and CFG based on the model and user choices.

    Args:
        model_filename: Exact filename (e.g., 'dreamshaper_8.safetensors')
        aspect_ratio: '1:1', '4:3', '3:4', '16:9', '9:16'
        preset: 'low', 'med', 'high'
        strict_model: If True, unknown model raises KeyError. If False, defaults to sd15.

    Returns:
        dict: {'width': int, 'height': int, 'steps': int, 'cfg': float, 'architecture': str}
    """
    # First check if model is in our known list
    if model_filename in MODEL_ARCHITECTURES:
        arch = MODEL_ARCHITECTURES[model_filename]
    elif strict_model:
        raise KeyError(
            f"Unknown model filename: {model_filename!r}. "
            f"Add it to MODEL_ARCHITECTURES."
        )
    else:
        # Use heuristic detection for unknown models
        arch = detect_architecture_from_filename(model_filename)
        print(f"[model_config] Unknown model '{model_filename}', detected as: {arch}")

    ar: AspectRatio = normalize_aspect_ratio(aspect_ratio)
    pr: PresetName = normalize_preset(preset)

    res_table = get_resolution_table(arch)
    dimensions = res_table.get(ar, res_table[DEFAULT_ASPECT])

    preset_table = PRESETS[arch]
    settings = preset_table.get(pr, preset_table[DEFAULT_PRESET])

    return {
        "width": dimensions["width"],
        "height": dimensions["height"],
        "steps": settings["steps"],
        "cfg": settings["cfg"],
        "architecture": arch,
    }


def get_safe_dimensions(
    model_filename: str,
    aspect_ratio: str = "1:1",
) -> Dimensions:
    """
    Convenience function to get just width/height for a model.

    This is the key function for preventing "two heads" - it ensures
    SD1.5 models never exceed their safe resolution limits.
    """
    settings = get_model_settings(model_filename, aspect_ratio)
    return {"width": settings["width"], "height": settings["height"]}


# =============================================================================
# 6. OPTIONAL: BULK PRESET EXPORT (All models, all aspect ratios, all presets)
# =============================================================================

def export_all_presets() -> dict:
    """
    Returns a complete nested dictionary of:
      model_filename -> aspect_ratio -> preset -> settings

    Useful for generating UI dropdown data or saving a config snapshot.
    """
    out: dict = {}
    for model in list_known_models():
        out[model] = {}
        for ar in SDXL_RESOLUTIONS.keys():  # same keys as SD15_RESOLUTIONS
            out[model][ar] = {}
            for pr in ("low", "med", "high"):
                out[model][ar][pr] = get_model_settings(model, ar, pr)
    return out


# =============================================================================
# EXAMPLE USAGE (For Testing)
# =============================================================================
if __name__ == "__main__":
    test_1 = get_model_settings("dreamshaper_8.safetensors", "9:16", "high")
    print("DreamShaper High 9:16 ->", test_1)
    # {'width': 432, 'height': 768, 'steps': 35, 'cfg': 8.0, 'architecture': 'sd15'}

    test_2 = get_model_settings("flux1-schnell.safetensors", "16:9", "med")
    print("Flux Schnell Med 16:9 ->", test_2)
    # {'width': 1216, 'height': 832, 'steps': 4, 'cfg': 1.0, 'architecture': 'flux_schnell'}

    test_3 = get_model_settings("sd_xl_base_1.0.safetensors", "1:1", "med")
    print("SDXL Base Med 1:1 ->", test_3)
    # {'width': 1024, 'height': 1024, 'steps': 30, 'cfg': 5.5, 'architecture': 'sdxl'}
