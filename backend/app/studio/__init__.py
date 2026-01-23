"""
Studio module (enterprise-style):
- YouTube + presentations workflow
- Optional Mature content handling with policy gating
- Mature Romance / Adult Fiction support (literary, not explicit)
- Audit trail hooks

Additive only: mount in main app by importing router.

Usage:
    from app.studio.routes import router as studio_router
    app.include_router(studio_router)

Enterprise Mature gate: set env STUDIO_ALLOW_MATURE=1 to allow mature mode.

Mature Content Philosophy:
- "Mature" means literary erotica - emotional intimacy, desire, tension
- NOT explicit pornography
- All characters must be adults (18+)
- Focus on atmosphere and emotion, not explicit acts
- Think published romance novels, not adult content sites
"""

from .routes import router
from .policy import (
    enforce_policy,
    enforce_image_policy,
    get_policy_summary,
    get_mature_content_guide,
)
from .story_genres import (
    GENRES,
    get_genre,
    get_mature_genres,
    get_sfw_genres,
    build_mature_story_prompt,
    StoryTone,
    ExplicitnessLevel,
)
from .prompt_refinement import (
    refine_prompt,
    get_regeneration_options,
    validate_output,
)
from .presets import (
    get_preset,
    get_presets_for_api,
    apply_preset_to_prompt,
    is_mature_mode_enabled,
    get_anime_presets,
    get_mature_presets,
    get_sfw_presets,
    GenerationPreset,
)

__all__ = [
    "router",
    # Policy
    "enforce_policy",
    "enforce_image_policy",
    "get_policy_summary",
    "get_mature_content_guide",
    # Genres
    "GENRES",
    "get_genre",
    "get_mature_genres",
    "get_sfw_genres",
    "build_mature_story_prompt",
    "StoryTone",
    "ExplicitnessLevel",
    # Refinement
    "refine_prompt",
    "get_regeneration_options",
    "validate_output",
    # Presets
    "get_preset",
    "get_presets_for_api",
    "apply_preset_to_prompt",
    "is_mature_mode_enabled",
    "get_anime_presets",
    "get_mature_presets",
    "get_sfw_presets",
    "GenerationPreset",
]
