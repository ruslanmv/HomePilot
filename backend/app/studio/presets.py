"""
Generation presets for Studio module.

Handles loading presets from model catalog and applying prompt injections
for specific use cases (anime fan service, romantic scenes, etc.).
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

# Path to model catalog
CATALOG_PATH = Path(__file__).parent.parent / "model_catalog_data.json"


@dataclass
class SamplerSettings:
    """Sampler configuration for generation."""
    sampler: str = "dpm++_2m_karras"
    steps: int = 25
    cfg_scale: float = 6.0
    clip_skip: int = 2


@dataclass
class PromptInjection:
    """Prompt modifications to apply."""
    positive_prefix: str = ""
    positive_suffix: str = ""
    negative: str = ""


@dataclass
class GenerationPreset:
    """A curated generation preset."""
    id: str
    label: str
    description: str
    content_rating: str  # "sfw" | "mature"
    requires_mature_mode: bool
    recommended_models: List[str]
    sampler_settings: SamplerSettings
    prompt_injection: PromptInjection
    safety_guidelines: List[str]


def load_presets() -> Dict[str, GenerationPreset]:
    """Load all generation presets from the model catalog."""
    if not CATALOG_PATH.exists():
        return {}

    with open(CATALOG_PATH, "r") as f:
        catalog = json.load(f)

    presets_data = catalog.get("generation_presets", {})
    presets = {}

    for key, data in presets_data.items():
        if key.startswith("_"):  # Skip comments
            continue

        sampler_data = data.get("sampler_settings", {})
        injection_data = data.get("prompt_injection", {})

        presets[key] = GenerationPreset(
            id=data.get("id", key),
            label=data.get("label", key),
            description=data.get("description", ""),
            content_rating=data.get("content_rating", "sfw"),
            requires_mature_mode=data.get("requires_mature_mode", False),
            recommended_models=data.get("recommended_models", []),
            sampler_settings=SamplerSettings(
                sampler=sampler_data.get("sampler", "dpm++_2m_karras"),
                steps=sampler_data.get("steps", 25),
                cfg_scale=sampler_data.get("cfg_scale", 6.0),
                clip_skip=sampler_data.get("clip_skip", 2),
            ),
            prompt_injection=PromptInjection(
                positive_prefix=injection_data.get("positive_prefix", ""),
                positive_suffix=injection_data.get("positive_suffix", ""),
                negative=injection_data.get("negative", ""),
            ),
            safety_guidelines=data.get("safety_guidelines", []),
        )

    return presets


def get_preset(preset_id: str) -> Optional[GenerationPreset]:
    """Get a specific preset by ID."""
    presets = load_presets()
    return presets.get(preset_id)


def get_anime_presets() -> List[GenerationPreset]:
    """Get all anime-related presets."""
    presets = load_presets()
    return [p for p in presets.values() if "anime" in p.id.lower()]


def get_mature_presets() -> List[GenerationPreset]:
    """Get all presets that require mature mode."""
    presets = load_presets()
    return [p for p in presets.values() if p.requires_mature_mode]


def get_sfw_presets() -> List[GenerationPreset]:
    """Get all SFW presets."""
    presets = load_presets()
    return [p for p in presets.values() if not p.requires_mature_mode]


def apply_preset_to_prompt(
    prompt: str,
    preset_id: str,
    content_rating: str = "sfw",
    mature_mode_enabled: bool = False,
) -> Dict[str, Any]:
    """
    Apply a preset's prompt injection to a user prompt.

    Args:
        prompt: The user's original prompt
        preset_id: ID of the preset to apply
        content_rating: Current content rating ("sfw" or "mature")
        mature_mode_enabled: Whether mature mode is enabled (env check)

    Returns:
        Dict with:
            - positive: The enhanced positive prompt
            - negative: The negative prompt from preset
            - sampler_settings: Recommended sampler settings
            - applied: Whether the preset was applied
            - blocked: Whether the preset was blocked due to policy
            - block_reason: Reason if blocked
    """
    preset = get_preset(preset_id)

    if not preset:
        return {
            "positive": prompt,
            "negative": "",
            "sampler_settings": None,
            "applied": False,
            "blocked": False,
            "block_reason": f"Preset '{preset_id}' not found",
        }

    # Check if preset requires mature mode
    if preset.requires_mature_mode:
        if not mature_mode_enabled:
            return {
                "positive": prompt,
                "negative": "",
                "sampler_settings": None,
                "applied": False,
                "blocked": True,
                "block_reason": "Preset requires mature mode (STUDIO_ALLOW_MATURE=1)",
            }
        if content_rating != "mature":
            return {
                "positive": prompt,
                "negative": "",
                "sampler_settings": None,
                "applied": False,
                "blocked": True,
                "block_reason": "Content rating must be 'mature' for this preset",
            }

    # Apply prompt injection
    injection = preset.prompt_injection
    enhanced_prompt = f"{injection.positive_prefix}{prompt}{injection.positive_suffix}"

    return {
        "positive": enhanced_prompt,
        "negative": injection.negative,
        "sampler_settings": {
            "sampler": preset.sampler_settings.sampler,
            "steps": preset.sampler_settings.steps,
            "cfg_scale": preset.sampler_settings.cfg_scale,
            "clip_skip": preset.sampler_settings.clip_skip,
        },
        "applied": True,
        "blocked": False,
        "block_reason": None,
        "preset_label": preset.label,
        "recommended_models": preset.recommended_models,
        "safety_guidelines": preset.safety_guidelines,
    }


def is_mature_mode_enabled() -> bool:
    """Check if mature mode is enabled via environment variable."""
    return os.environ.get("STUDIO_ALLOW_MATURE", "").lower() in ("1", "true", "yes")


def get_presets_for_api() -> List[Dict[str, Any]]:
    """
    Get presets formatted for API response.

    Filters based on current mature mode setting.
    """
    presets = load_presets()
    mature_enabled = is_mature_mode_enabled()

    result = []
    for preset in presets.values():
        # Only show mature presets if mature mode is enabled
        if preset.requires_mature_mode and not mature_enabled:
            continue

        result.append({
            "id": preset.id,
            "label": preset.label,
            "description": preset.description,
            "content_rating": preset.content_rating,
            "requires_mature_mode": preset.requires_mature_mode,
            "recommended_models": preset.recommended_models,
            "sampler_settings": {
                "sampler": preset.sampler_settings.sampler,
                "steps": preset.sampler_settings.steps,
                "cfg_scale": preset.sampler_settings.cfg_scale,
                "clip_skip": preset.sampler_settings.clip_skip,
            },
            "safety_guidelines": preset.safety_guidelines if preset.requires_mature_mode else [],
        })

    return result
