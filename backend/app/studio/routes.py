"""
FastAPI routes for Studio module.

Mount this router in your main app:
    from app.studio import router as studio_router
    app.include_router(studio_router)
"""
from __future__ import annotations

import re
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Literal, List, Tuple
from pydantic import BaseModel, Field


# ============================================================================
# JSON Repair Utilities (for handling truncated LLM responses)
# ============================================================================

def _is_truncated_json(text: str) -> bool:
    """
    Check if JSON appears to be truncated.
    Returns True if the text doesn't end with proper JSON closure.
    """
    if not text or not text.strip():
        return True

    cleaned = text.strip()
    # Valid JSON should end with } or ] (possibly followed by whitespace)
    if not cleaned.endswith('}') and not cleaned.endswith(']'):
        return True

    # Count braces/brackets - if unbalanced, it's truncated
    depth_brace = 0
    depth_bracket = 0
    in_string = False
    escape_next = False

    for char in cleaned:
        if escape_next:
            escape_next = False
            continue
        if char == '\\':
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            depth_brace += 1
        elif char == '}':
            depth_brace -= 1
        elif char == '[':
            depth_bracket += 1
        elif char == ']':
            depth_bracket -= 1

    return depth_brace != 0 or depth_bracket != 0


def _repair_truncated_json(text: str) -> Tuple[str, bool]:
    """
    Attempt to repair truncated JSON by closing open structures.
    Returns (repaired_text, was_repaired).

    This handles common truncation patterns:
    - Missing closing braces/brackets
    - Truncated string values (closes with ")
    - Missing array elements
    """
    if not text or not text.strip():
        return text, False

    cleaned = text.strip()

    # Track open structures
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape_next = False
    last_char = ''

    for i, char in enumerate(cleaned):
        if escape_next:
            escape_next = False
            last_char = char
            continue
        if char == '\\':
            escape_next = True
            last_char = char
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            last_char = char
            continue
        if in_string:
            last_char = char
            continue

        if char == '{':
            open_braces += 1
        elif char == '}':
            open_braces -= 1
        elif char == '[':
            open_brackets += 1
        elif char == ']':
            open_brackets -= 1
        last_char = char

    # If already balanced, no repair needed
    if open_braces == 0 and open_brackets == 0 and not in_string:
        return cleaned, False

    repaired = cleaned
    was_repaired = False

    # Close unclosed string
    if in_string:
        repaired += '"'
        was_repaired = True

    # Remove trailing incomplete fields (e.g., "key": "incomplete or "key":)
    # Pattern: trailing comma, incomplete key-value pairs
    repaired = re.sub(r',\s*"[^"]*"?\s*:\s*"?[^",}\]]*$', '', repaired)
    repaired = re.sub(r',\s*$', '', repaired)  # Remove trailing comma

    # Close open brackets first (inner), then braces (outer)
    for _ in range(open_brackets):
        repaired += ']'
        was_repaired = True

    for _ in range(open_braces):
        repaired += '}'
        was_repaired = True

    return repaired, was_repaired


def _extract_partial_outline(text: str) -> Optional[dict]:
    """
    Try to extract a partial outline from truncated JSON.
    Even if incomplete, we may be able to salvage some scenes.
    """
    import json

    # First, try to repair the JSON
    repaired, was_repaired = _repair_truncated_json(text)

    if was_repaired:
        print(f"[Outline] Attempted JSON repair (added {len(repaired) - len(text)} chars)")

    try:
        parsed = json.loads(repaired)
        if isinstance(parsed, dict):
            # Validate we have at least the basic structure
            if "scenes" in parsed and isinstance(parsed["scenes"], list):
                # Filter out incomplete scenes (missing required fields)
                valid_scenes = []
                for scene in parsed["scenes"]:
                    if isinstance(scene, dict):
                        has_narration = scene.get("narration") and len(str(scene.get("narration", ""))) > 10
                        has_prompt = scene.get("image_prompt") and len(str(scene.get("image_prompt", ""))) > 10
                        if has_narration or has_prompt:
                            # Ensure negative_prompt is complete
                            if "negative_prompt" in scene:
                                neg = scene.get("negative_prompt", "")
                                if isinstance(neg, str) and not neg.endswith('"'):
                                    # Truncated negative prompt - use default
                                    from ..defaults import DEFAULT_NEGATIVE_PROMPT
                                    scene["negative_prompt"] = DEFAULT_NEGATIVE_PROMPT
                            valid_scenes.append(scene)

                if valid_scenes:
                    parsed["scenes"] = valid_scenes
                    parsed["_repaired"] = was_repaired
                    parsed["_original_scene_count"] = len(parsed.get("scenes", []))
                    return parsed
    except json.JSONDecodeError as e:
        print(f"[Outline] JSON repair failed: {e}")

    return None

from .models import (
    StudioVideoCreate, GenerationRequest, ExportRequest, StudioSceneCreate, StudioSceneUpdate,
    StudioProjectCreate, AssetKind, TrackKind, AutosavePayload,
)
from .repo import (
    list_videos, get_video, list_scenes, get_scene, create_scene, update_scene, delete_scene, update_video, delete_video,
    # Professional project functions
    create_project, list_projects, get_project, update_project, delete_project,
    # Asset functions
    create_asset, list_assets, get_asset, delete_asset,
    # Audio track functions
    create_audio_track, list_audio_tracks, get_audio_track, update_audio_track, delete_audio_track,
    # Caption functions
    create_caption, list_captions, get_caption, update_caption, delete_caption,
    # Version functions
    create_version, list_versions, get_version, get_latest_version, delete_version,
    # Share link functions
    create_share_link, get_share_link, list_share_links, delete_share_link,
)
from .service import (
    create,
    policy_check_generation,
    get_video_policy_summary,
    update_content_rating,
)
from .audit import list_events, get_policy_violations
from .exporter import export_pack, get_available_exports
from .policy import get_mature_content_guide, enforce_image_policy, org_allows_mature
from .models import ProviderPolicy
from .story_genres import (
    GENRES,
    get_genre,
    get_mature_genres,
    get_sfw_genres,
    validate_genre_for_rating,
    build_mature_story_prompt,
    StoryTone,
    ExplicitnessLevel,
    MatureStoryConfig,
)
from .prompt_refinement import (
    refine_prompt,
    get_regeneration_options,
    apply_regeneration_constraint,
    validate_output,
)
from .presets import (
    get_presets_for_api,
    get_preset,
    apply_preset_to_prompt,
    is_mature_mode_enabled,
    get_anime_presets,
)
from .library import (
    list_style_kits,
    get_style_kit,
    list_templates,
    get_template,
)
from .exporter import (
    export_project,
    get_project_available_exports,
)
from ..defaults import DEFAULT_NEGATIVE_PROMPT, ANTI_DUPLICATE_TERMS

router = APIRouter(prefix="/studio", tags=["studio"])


# ============================================================================
# Video CRUD
# ============================================================================

@router.get("/videos")
def videos_list(
    q: Optional[str] = Query(default=None, description="Search query"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    preset: Optional[str] = Query(default=None, description="Filter by platform preset"),
    contentRating: Optional[str] = Query(default=None, description="Filter by content rating"),
):
    """List all video projects with optional filters."""
    vids = list_videos(q=q, status=status, preset=preset, contentRating=contentRating)
    return {"videos": [v.model_dump() for v in vids]}


@router.post("/videos")
def video_create(inp: StudioVideoCreate):
    """Create a new video project."""
    v = create(inp)
    return {"video": v.model_dump()}


@router.get("/videos/{video_id}")
def video_detail(video_id: str):
    """Get video project details."""
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"video": v.model_dump()}


class VideoUpdateRequest(BaseModel):
    title: Optional[str] = None
    logline: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    platformPreset: Optional[str] = None
    contentRating: Optional[str] = None


@router.patch("/videos/{video_id}")
def video_update(video_id: str, body: VideoUpdateRequest):
    """Update video project fields."""
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    updates = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.logline is not None:
        updates["logline"] = body.logline
    if body.status is not None:
        if body.status not in ("draft", "in_review", "approved", "archived"):
            raise HTTPException(status_code=400, detail="Invalid status")
        updates["status"] = body.status
    if body.tags is not None:
        updates["tags"] = body.tags
    if body.platformPreset is not None:
        if body.platformPreset not in ("youtube_16_9", "shorts_9_16", "slides_16_9"):
            raise HTTPException(status_code=400, detail="Invalid platform preset")
        updates["platformPreset"] = body.platformPreset
    if body.contentRating is not None:
        if body.contentRating not in ("sfw", "mature"):
            raise HTTPException(status_code=400, detail="Invalid content rating")
        updates["contentRating"] = body.contentRating

    if updates:
        v = update_video(video_id, **updates)

    return {"video": v.model_dump()}


@router.delete("/videos/{video_id}")
def video_delete(video_id: str):
    """Delete a video project and all its scenes."""
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    deleted = delete_video(video_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete video")

    return {"ok": True}


# ============================================================================
# Scenes
# ============================================================================

@router.get("/videos/{video_id}/scenes")
def scenes_list(video_id: str):
    """List all scenes for a video project."""
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    scenes = list_scenes(video_id)
    return {"scenes": [s.model_dump() for s in scenes]}


@router.post("/videos/{video_id}/scenes")
def scene_create(video_id: str, inp: StudioSceneCreate):
    """Create a new scene for a video project."""
    scene = create_scene(video_id, inp)
    if not scene:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"scene": scene.model_dump()}


@router.get("/videos/{video_id}/scenes/{scene_id}")
def scene_detail(video_id: str, scene_id: str):
    """Get scene details."""
    scene = get_scene(scene_id)
    if not scene or scene.videoId != video_id:
        raise HTTPException(status_code=404, detail="Scene not found")
    return {"scene": scene.model_dump()}


@router.patch("/videos/{video_id}/scenes/{scene_id}")
def scene_update(video_id: str, scene_id: str, inp: StudioSceneUpdate):
    """Update a scene."""
    scene = get_scene(scene_id)
    if not scene or scene.videoId != video_id:
        raise HTTPException(status_code=404, detail="Scene not found")

    scene = update_scene(scene_id, inp)
    return {"scene": scene.model_dump()}


@router.delete("/videos/{video_id}/scenes/{scene_id}")
def scene_delete(video_id: str, scene_id: str):
    """Delete a scene."""
    scene = get_scene(scene_id)
    if not scene or scene.videoId != video_id:
        raise HTTPException(status_code=404, detail="Scene not found")

    delete_scene(scene_id)
    return {"ok": True}


# ============================================================================
# Policy
# ============================================================================

@router.get("/videos/{video_id}/policy")
def video_policy(video_id: str):
    """Get policy summary for a video project."""
    summary = get_video_policy_summary(video_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"policy": summary}


@router.post("/videos/{video_id}/policy/check")
def policy_check(video_id: str, req: GenerationRequest):
    """
    Check if a generation prompt is allowed by policy.

    Use this before generating content to verify compliance.
    """
    result = policy_check_generation(
        video_id=video_id,
        prompt=req.prompt,
        provider=req.provider,
    )
    return result


@router.patch("/videos/{video_id}/content-rating")
def update_rating(video_id: str, contentRating: str = Query(...)):
    """Update video content rating (sfw or mature)."""
    if contentRating not in ("sfw", "mature"):
        raise HTTPException(status_code=400, detail="Invalid content rating")

    v = update_content_rating(video_id, contentRating)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"video": v.model_dump()}


class ImageGenerationRequest(BaseModel):
    """Request for image generation policy check."""
    model_config = {"protected_namespaces": ()}

    prompt: str
    provider: str = "comfyui"
    model_id: Optional[str] = None


@router.post("/videos/{video_id}/policy/check-image")
def image_policy_check(video_id: str, req: ImageGenerationRequest):
    """
    Check if an IMAGE generation prompt is allowed by policy.

    IMAGE GENERATION IS MORE PERMISSIVE:
    - When NSFW/mature mode enabled, explicit content (porn) IS allowed
    - Only absolute blocks apply (CSAM, non-consent, illegal content)
    - Use anime models (AOM3, Counterfeit, Anything V5) for full NSFW

    This is different from text/story generation which uses literary standards.
    """
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # Build provider policy from video settings
    provider_policy = ProviderPolicy(
        allowMature=v.contentRating == "mature",
        allowedProviders=["comfyui", "ollama", "local"],
        localOnly=True,
    )

    result = enforce_image_policy(
        prompt=req.prompt,
        content_rating=v.contentRating,
        provider=req.provider,
        provider_policy=provider_policy,
    )

    return {
        "allowed": result.allowed,
        "reason": result.reason,
        "flags": result.flags,
        "content_rating": v.contentRating,
        "nsfw_enabled": org_allows_mature() and v.contentRating == "mature",
        "model_id": req.model_id,
        "policy_type": "image",
        "note": "Image generation allows explicit content when NSFW is enabled. Only illegal content is blocked.",
    }


# ============================================================================
# Audit
# ============================================================================

@router.get("/videos/{video_id}/audit")
def audit_log(
    video_id: str,
    event_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
):
    """Get audit log for a video project."""
    events = list_events(video_id, event_type=event_type, limit=limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/videos/{video_id}/policy-violations")
def policy_violations(video_id: str):
    """Get policy violation events for a video."""
    violations = get_policy_violations(video_id)
    return {"violations": [v.model_dump() for v in violations]}


# ============================================================================
# Export
# ============================================================================

@router.get("/videos/{video_id}/exports")
def available_exports(video_id: str):
    """Get available export formats for a video."""
    return get_available_exports(video_id)


@router.post("/videos/{video_id}/export")
def do_export(video_id: str, req: ExportRequest):
    """Export video project assets."""
    return export_pack(video_id, kind=req.kind)


# ============================================================================
# Story Genres & Mature Content
# ============================================================================

@router.get("/genres")
def list_genres(content_rating: Optional[str] = Query(default=None)):
    """
    List available story genres.

    Filter by content_rating to see only allowed genres.
    """
    if content_rating == "sfw":
        genres = get_sfw_genres()
    elif content_rating == "mature":
        genres = list(GENRES.values())  # Mature can see all
    else:
        genres = list(GENRES.values())

    return {
        "genres": [
            {
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "requires_mature": g.requires_mature,
                "default_tone": g.default_tone.value,
                "allowed_tones": [t.value for t in g.allowed_tones],
            }
            for g in genres
        ]
    }


@router.get("/genres/{genre_id}")
def get_genre_detail(genre_id: str):
    """Get detailed information about a genre."""
    genre = get_genre(genre_id)
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")

    return {
        "genre": {
            "id": genre.id,
            "name": genre.name,
            "description": genre.description,
            "requires_mature": genre.requires_mature,
            "default_tone": genre.default_tone.value,
            "allowed_tones": [t.value for t in genre.allowed_tones],
            "content_guidelines": genre.content_guidelines,
            "blocked_elements": genre.blocked_elements,
            "example_themes": genre.example_themes,
        }
    }


@router.get("/mature-guide")
def mature_content_guide():
    """
    Get the mature content creation guide.

    This explains what's allowed in Mature mode and how to prompt properly.
    """
    return {"guide": get_mature_content_guide()}


# ============================================================================
# Story Generation (with policy enforcement)
# ============================================================================

class MatureStoryRequest(BaseModel):
    """Request to generate a mature story with proper constraints."""
    prompt: str
    tone: str = "sensual"
    explicitness: str = "suggestive"
    setting: Optional[str] = None
    characters: Optional[str] = "two consenting adults"
    provider: str = "ollama"


class RefinePromptRequest(BaseModel):
    """Request to refine a prompt for safety and quality."""
    prompt: str
    apply_softening: bool = True
    add_constraints: bool = True


class RegenerateRequest(BaseModel):
    """Request to regenerate with a constraint."""
    prompt: str
    constraint_id: str


@router.post("/videos/{video_id}/story/prepare")
def prepare_story_prompt(video_id: str, req: MatureStoryRequest):
    """
    Prepare a properly constrained story prompt.

    This builds the system and user prompts for mature story generation,
    applying all policy constraints and quality guidelines.
    """
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # Validate genre requirements
    if v.contentRating != "mature":
        raise HTTPException(
            status_code=400,
            detail="Mature story generation requires mature content rating"
        )

    # Parse tone and explicitness
    try:
        tone = StoryTone(req.tone)
    except ValueError:
        tone = StoryTone.SENSUAL

    try:
        explicitness = ExplicitnessLevel(req.explicitness)
    except ValueError:
        explicitness = ExplicitnessLevel.SUGGESTIVE

    # Build the constrained prompt
    prepared = build_mature_story_prompt(
        prompt=req.prompt,
        tone=tone,
        explicitness=explicitness,
        setting=req.setting,
        characters=req.characters,
    )

    # Also run policy check on the user's input
    policy_result = policy_check_generation(
        video_id=video_id,
        prompt=req.prompt,
        provider=req.provider,
    )

    return {
        "prepared_prompt": prepared,
        "policy_check": policy_result,
        "guidelines": get_mature_content_guide()["tips"],
    }


@router.post("/videos/{video_id}/prompt/refine")
def refine_user_prompt(video_id: str, req: RefinePromptRequest):
    """
    Refine a user prompt for safer, higher-quality generation.

    Applies softening rules and adds constraints to improve output.
    """
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    result = refine_prompt(
        prompt=req.prompt,
        content_rating=v.contentRating,
        apply_softening=req.apply_softening,
        add_constraints=req.add_constraints,
    )

    return {
        "original": result.original,
        "refined": result.refined,
        "applied_rules": result.applied_rules,
        "warnings": result.warnings,
        "blocked": result.blocked,
        "block_reason": result.block_reason,
    }


@router.get("/regeneration-options")
def list_regeneration_options():
    """
    Get available regeneration constraint options.

    These allow users to adjust story output without re-prompting.
    """
    return {"options": get_regeneration_options()}


@router.post("/prompt/regenerate")
def apply_regeneration(req: RegenerateRequest):
    """Apply a regeneration constraint to a prompt."""
    result = apply_regeneration_constraint(req.prompt, req.constraint_id)
    return {"prompt": result}


@router.post("/output/validate")
def validate_generated_output(
    text: str = Query(...),
    content_rating: str = Query(default="sfw"),
):
    """
    Validate generated output against content policies.

    Use this to check if generated text meets policy requirements.
    """
    if content_rating not in ("sfw", "mature"):
        raise HTTPException(status_code=400, detail="Invalid content rating")

    is_valid, issues = validate_output(text, content_rating)

    return {
        "valid": is_valid,
        "issues": issues,
        "content_rating": content_rating,
    }


# ============================================================================
# Generation Presets
# ============================================================================

class ApplyPresetRequest(BaseModel):
    """Request to apply a preset to a prompt."""
    prompt: str
    preset_id: str


@router.get("/presets")
def list_presets():
    """
    List available generation presets.

    Presets are filtered based on mature mode setting.
    Mature presets only shown when STUDIO_ALLOW_MATURE=1.
    """
    return {
        "presets": get_presets_for_api(),
        "mature_mode_enabled": is_mature_mode_enabled(),
    }


@router.get("/presets/anime")
def list_anime_presets():
    """
    List anime-specific presets.

    Useful for fan service and mature anime content generation.
    """
    presets = get_anime_presets()
    mature_enabled = is_mature_mode_enabled()

    return {
        "presets": [
            {
                "id": p.id,
                "label": p.label,
                "description": p.description,
                "content_rating": p.content_rating,
                "requires_mature_mode": p.requires_mature_mode,
                "recommended_models": p.recommended_models,
                "available": not p.requires_mature_mode or mature_enabled,
            }
            for p in presets
        ],
        "mature_mode_enabled": mature_enabled,
    }


@router.get("/presets/{preset_id}")
def get_preset_detail(preset_id: str):
    """Get detailed information about a preset."""
    preset = get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    mature_enabled = is_mature_mode_enabled()

    return {
        "preset": {
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
            "prompt_injection": {
                "positive_prefix": preset.prompt_injection.positive_prefix,
                "positive_suffix": preset.prompt_injection.positive_suffix,
                "negative": preset.prompt_injection.negative,
            },
            "safety_guidelines": preset.safety_guidelines,
            "available": not preset.requires_mature_mode or mature_enabled,
        }
    }


@router.post("/presets/apply")
def apply_preset(req: ApplyPresetRequest, content_rating: str = Query(default="sfw")):
    """
    Apply a preset's prompt injection to a user prompt.

    Returns enhanced prompt with sampler settings and safety guidelines.
    """
    if content_rating not in ("sfw", "mature"):
        raise HTTPException(status_code=400, detail="Invalid content rating")

    result = apply_preset_to_prompt(
        prompt=req.prompt,
        preset_id=req.preset_id,
        content_rating=content_rating,
        mature_mode_enabled=is_mature_mode_enabled(),
    )

    return result


# ============================================================================
# Image Policy (Standalone)
# ============================================================================

@router.post("/image/policy-check")
def standalone_image_policy_check(
    prompt: str = Query(...),
    content_rating: str = Query(default="sfw"),
    provider: str = Query(default="comfyui"),
):
    """
    Standalone image policy check (no video context required).

    IMAGE NSFW POLICY:
    - When content_rating="mature" AND STUDIO_ALLOW_MATURE=1:
      - Explicit content (porn, nudity, sex) IS ALLOWED
      - Only illegal content blocked (CSAM, non-consent)
    - When content_rating="sfw":
      - Explicit content blocked
      - Standard safe-for-work filtering

    Use this for quick policy checks before image generation.
    """
    if content_rating not in ("sfw", "mature"):
        raise HTTPException(status_code=400, detail="Invalid content rating")

    provider_policy = ProviderPolicy(
        allowMature=content_rating == "mature",
        allowedProviders=["comfyui", "ollama", "local"],
        localOnly=True,
    )

    result = enforce_image_policy(
        prompt=prompt,
        content_rating=content_rating,
        provider=provider,
        provider_policy=provider_policy,
    )

    mature_enabled = org_allows_mature()

    return {
        "allowed": result.allowed,
        "reason": result.reason,
        "flags": result.flags,
        "content_rating": content_rating,
        "nsfw_enabled": mature_enabled and content_rating == "mature",
        "policy_type": "image",
        "explicit_allowed": mature_enabled and content_rating == "mature",
        "info": {
            "sfw": "Blocks explicit/sexual content",
            "mature": "Allows explicit content (porn OK). Only illegal content blocked.",
        },
    }


@router.get("/image/nsfw-info")
def nsfw_image_info():
    """
    Get information about NSFW image generation capabilities.

    Returns current NSFW status and what content is allowed.
    """
    mature_enabled = org_allows_mature()

    return {
        "nsfw_enabled": mature_enabled,
        "env_var": "STUDIO_ALLOW_MATURE",
        "current_value": "1" if mature_enabled else "0 (or not set)",
        "when_enabled": {
            "explicit_content": "ALLOWED",
            "porn": "ALLOWED",
            "nudity": "ALLOWED",
            "fan_service": "ALLOWED",
            "ecchi": "ALLOWED",
            "hentai_style": "ALLOWED",
        },
        "always_blocked": {
            "csam": "Child sexual abuse material - ALWAYS BLOCKED",
            "minors": "Any sexual content involving minors - ALWAYS BLOCKED",
            "non_consensual": "Rape, forced scenarios - ALWAYS BLOCKED",
            "illegal": "Bestiality, incest - ALWAYS BLOCKED",
        },
        "recommended_models": [
            "abyssOrangeMix3_aom3a1b.safetensors",
            "counterfeit_v30.safetensors",
            "anything_v5PrtRE.safetensors",
            "ponyDiffusionV6XL_v6.safetensors",
            "dreamshaper_8.safetensors",
        ],
        "how_to_enable": "Set environment variable: STUDIO_ALLOW_MATURE=1",
    }


# ============================================================================
# Story Outline Generation (AI-powered)
# ============================================================================

class GenerateOutlineRequest(BaseModel):
    """Request to generate an AI-powered story outline."""
    target_scenes: int = Field(8, ge=4, le=24)
    scene_duration: int = Field(5, ge=3, le=15)
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


class SceneOutline(BaseModel):
    """Single scene outline."""
    scene_number: int
    title: str
    description: str
    narration: str
    image_prompt: str
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT  # Use centralized default
    duration_sec: float = 5.0


class StoryOutlineResponse(BaseModel):
    """AI-generated story outline."""
    title: str
    logline: str
    visual_style: str
    tone: str
    story_arc: dict
    scenes: list


@router.post("/videos/{video_id}/generate-outline")
async def generate_story_outline(video_id: str, req: GenerateOutlineRequest):
    """
    Generate an AI-powered story outline based on project settings.

    This uses the project's title, logline, visual style, and tone tags
    to create a complete story arc with scene-by-scene outlines.
    """
    from ..llm import chat_ollama
    from ..config import OLLAMA_BASE_URL, OLLAMA_MODEL
    import json

    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # Extract tags from project
    tags = v.tags if hasattr(v, 'tags') and v.tags else []

    visual_style = "cinematic"
    tones = []
    goal = "entertain"
    project_llm_model = None

    for tag in tags:
        if tag.startswith("visual:"):
            visual_style = tag.replace("visual:", "").replace("_", " ")
        elif tag.startswith("tone:"):
            tones.append(tag.replace("tone:", "").replace("_", " "))
        elif tag.startswith("goal:"):
            goal = tag.replace("goal:", "")
        elif tag.startswith("llm:"):
            project_llm_model = tag.replace("llm:", "")

    tone_desc = ", ".join(tones) if tones else "documentary"

    # Use centralized anti-duplicate terms to prevent common Stable Diffusion issues
    anti_duplicate_terms = ANTI_DUPLICATE_TERMS

    # Check content rating and mature mode for adult content generation
    content_rating = v.contentRating if hasattr(v, 'contentRating') else "sfw"
    mature_mode_enabled = org_allows_mature() and content_rating == "mature"

    print(f"[Outline] Content rating: {content_rating}, Mature mode enabled: {mature_mode_enabled}")

    # Build example JSON based on content rating
    if mature_mode_enabled:
        # Mature mode: Allow adult content, fan service, sensual descriptions
        example_scene = {
            "scene_number": 1,
            "title": "The Dressing Room",
            "description": "We meet Sophia in her private dressing room, wearing elegant lingerie as she prepares for a special evening. The atmosphere is intimate and sensual.",
            "narration": "In the soft glow of her dressing room, Sophia admires her reflection. Her silk robe barely conceals her curves as she applies the finishing touches to her makeup. Tonight will be unforgettable.",
            "image_prompt": f"{visual_style} style, beautiful young woman named Sophia in an elegant boudoir, wearing delicate lace lingerie, sitting at a vanity mirror, soft romantic lighting, sensual atmosphere, detailed figure, alluring pose, high quality, masterpiece, solo",
            "negative_prompt": f"blurry, low quality, text, watermark, ugly, deformed, {anti_duplicate_terms}",
            "duration_sec": req.scene_duration
        }
    else:
        # SFW mode: Keep safe for work content
        example_scene = {
            "scene_number": 1,
            "title": "The Dressing Room",
            "description": "We meet Sophia in her dressing room, surrounded by mirrors and costumes, preparing for her big performance.",
            "narration": "In the heart of the theater, Sophia sits before a wall of mirrors. Tonight is the night she has been waiting for her entire life.",
            "image_prompt": f"{visual_style} style, young woman named Sophia sitting at a vanity table in a theater dressing room, surrounded by illuminated mirrors, elegant costumes hanging in background, warm golden lighting, anticipation in her eyes, detailed interior, high quality, single subject",
            "negative_prompt": f"blurry, low quality, text, watermark, ugly, deformed, {anti_duplicate_terms}",
            "duration_sec": req.scene_duration
        }

    # Build the outline generation prompt based on content rating
    if mature_mode_enabled:
        # Mature mode prompt - allows adult content, fan service, sensual/explicit descriptions
        system_prompt = f"""You are a professional adult content screenwriter. Generate a story outline as a JSON object.

THIS IS MATURE/ADULT CONTENT MODE - You are ALLOWED and ENCOURAGED to:
- Write sensual, romantic, and explicit content
- Include fan service elements (revealing clothing, suggestive poses, intimate moments)
- Describe physical attributes, body features, and attractive appearances in detail
- Create romantic tension, seduction scenes, and intimate encounters
- Use adult themes appropriate for mature audiences
- Generate uncensored, provocative image prompts that showcase beauty and sensuality

Output ONLY valid JSON with this exact structure:
{{
  "title": "Story Title",
  "logline": "One sentence summary",
  "visual_style": "{visual_style}",
  "tone": "{tone_desc}",
  "story_arc": {{
    "beginning": "Setup description",
    "rising_action": "Tension builds",
    "climax": "Peak moment",
    "falling_action": "Resolution begins",
    "resolution": "Conclusion"
  }},
  "scenes": [
    {json.dumps(example_scene)}
  ]
}}

CRITICAL REQUIREMENTS FOR MATURE IMAGE PROMPTS:
- Each image_prompt MUST be detailed and visually descriptive for adult content
- Include specific physical descriptions: body type, clothing (or lack thereof), poses, expressions
- Use terms like: beautiful, alluring, sensual, seductive, elegant, stunning, gorgeous
- For intimate scenes, describe the setting, mood, and character positioning
- Include quality boosters: masterpiece, best quality, highly detailed, professional
- DO NOT censor or tone down the descriptions - this is mature content mode
- Always start with "{visual_style}" style keywords
- For single-character scenes, add "solo" or "1girl"/"1boy" to the image_prompt
- Example mature prompt: "{visual_style} style, beautiful woman with long flowing hair, wearing revealing red dress, sensual pose on silk sheets, bedroom setting, soft romantic lighting, alluring expression, detailed figure, masterpiece, solo"

CRITICAL REQUIREMENTS FOR NEGATIVE PROMPTS:
- Every negative_prompt MUST include anti-duplicate terms: "duplicate, clone, multiple people, two heads, split image"
- Include quality terms: "blurry, low quality, text, watermark, ugly, deformed"
- For mature content, also add: "child, minor, underage" (ALWAYS blocked)

CONTENT GUIDELINES FOR MATURE MODE:
- Adult romantic/sensual content: ALLOWED
- Fan service and revealing outfits: ALLOWED
- Suggestive poses and intimate moments: ALLOWED
- Nudity and explicit content: ALLOWED
- ALWAYS BLOCKED: minors, non-consensual content, illegal content

OTHER REQUIREMENTS:
- Output ONLY the JSON object, no other text
- Create exactly {req.target_scenes} scenes in the scenes array
- Each scene narration should be 2-3 sentences with sensual/adult tone
- Make the story coherent with romantic/adult themes from beginning to end"""

    else:
        # SFW mode prompt - safe for work content only
        system_prompt = f"""You are a professional screenwriter. Generate a story outline as a JSON object.

Output ONLY valid JSON with this exact structure:
{{
  "title": "Story Title",
  "logline": "One sentence summary",
  "visual_style": "{visual_style}",
  "tone": "{tone_desc}",
  "story_arc": {{
    "beginning": "Setup description",
    "rising_action": "Conflict builds",
    "climax": "Peak moment",
    "falling_action": "Resolution begins",
    "resolution": "Conclusion"
  }},
  "scenes": [
    {json.dumps(example_scene)}
  ]
}}

CRITICAL REQUIREMENTS FOR IMAGE PROMPTS:
- Each image_prompt MUST describe the SPECIFIC characters, setting, and action from that scene's description
- Include character names, their appearance, specific locations, and what they are doing
- DO NOT use generic placeholders like "detailed visual description" or "scene content here"
- The image_prompt must paint a vivid picture that matches the narration
- Always start with "{visual_style}" style keywords
- For single-character scenes, add "single subject" or "solo" to the image_prompt
- Example: If the scene is about "John discovers an ancient map in the library", the image_prompt should be: "{visual_style} style, man named John in a dusty old library, holding an ancient weathered map, surrounded by towering bookshelves, dust particles in light beams, expression of wonder and discovery, single subject"

CRITICAL REQUIREMENTS FOR NEGATIVE PROMPTS:
- Every negative_prompt MUST include anti-duplicate terms: "duplicate, clone, multiple people, two heads, split image"
- This prevents the AI from generating doubled/cloned subjects in images
- Always include quality terms: "blurry, low quality, text, watermark, ugly, deformed"
- Full example: "blurry, low quality, text, watermark, ugly, deformed, duplicate, clone, multiple people, two heads, two faces, split image, disfigured, extra limbs"

OTHER REQUIREMENTS:
- Output ONLY the JSON object, no other text
- Create exactly {req.target_scenes} scenes in the scenes array
- Each scene narration should be 2-3 sentences
- Make the story coherent from beginning to end"""

    # Build user prompt based on content rating
    if mature_mode_enabled:
        user_prompt = f"""Create a {req.target_scenes}-scene MATURE/ADULT story outline for:

Title: {v.title}
Description: {v.logline or "A compelling adult visual story"}
Style: {visual_style}
Tone: {tone_desc}
Goal: {goal}
Content Rating: MATURE (adult content allowed)

Remember: This is mature mode - include sensual descriptions, fan service elements, and adult themes as appropriate for the story. Do not censor or tone down the content.

Generate the complete JSON now:"""
    else:
        user_prompt = f"""Create a {req.target_scenes}-scene story outline for:

Title: {v.title}
Description: {v.logline or "A compelling visual story"}
Style: {visual_style}
Tone: {tone_desc}
Goal: {goal}

Generate the complete JSON now:"""

    base_url = req.ollama_base_url or OLLAMA_BASE_URL

    # Model selection priority: request > project tags > env var > smart default
    model = req.ollama_model or project_llm_model or OLLAMA_MODEL

    # If no model specified anywhere, try to find an available one
    if not model:
        # Try to get available models from Ollama
        try:
            import httpx
            models_url = f"{base_url.rstrip('/')}/api/tags"
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(models_url)
                if resp.status_code == 200:
                    models_data = resp.json()
                    available_models = [m.get("name") for m in models_data.get("models", [])]
                    # Prefer llama3:8b, then any llama model, then first available
                    for preferred in ["llama3:8b", "llama3:latest"]:
                        if preferred in available_models:
                            model = preferred
                            break
                    if not model:
                        llama_models = [m for m in available_models if "llama" in m.lower()]
                        if llama_models:
                            model = llama_models[0]
                        elif available_models:
                            # Skip deepseek-r1 as default (has thinking output issues)
                            non_deepseek = [m for m in available_models if "deepseek" not in m.lower()]
                            model = non_deepseek[0] if non_deepseek else available_models[0]

                    if not model and available_models:
                        # Provide helpful error
                        raise HTTPException(
                            status_code=400,
                            detail=f"No suitable LLM model found. Available models: {', '.join(available_models[:5])}. Please select a model in project settings."
                        )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Cannot connect to Ollama at {base_url}. Please ensure Ollama is running."
            )

    # Final check - if still no model, fail with helpful message
    if not model:
        raise HTTPException(
            status_code=400,
            detail="No LLM model specified. Please select a model in project settings or set OLLAMA_MODEL environment variable."
        )

    # Verify the model exists in Ollama
    try:
        import httpx
        models_url = f"{base_url.rstrip('/')}/api/tags"
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(models_url)
            if resp.status_code == 200:
                models_data = resp.json()
                available_models = [m.get("name") for m in models_data.get("models", [])]
                if model not in available_models:
                    # Try to suggest a similar model
                    suggestions = [m for m in available_models if model.split(":")[0] in m]
                    suggestion_text = f" (Did you mean {suggestions[0]}?)" if suggestions else ""
                    raise HTTPException(
                        status_code=500,
                        detail=f"Ollama model '{model}' not found. Available models: {', '.join(available_models[:5])}{suggestion_text}"
                    )
    except httpx.RequestError:
        pass  # Continue anyway, let the actual call fail if model doesn't exist

    print(f"[Outline] Generating outline with model: {model}")
    print(f"[Outline] Title: {v.title}, Scenes: {req.target_scenes}")

    # Determine max_tokens based on model
    # DeepSeek R1 and other "thinking" models need more tokens as they use tokens for reasoning
    is_deepseek = "deepseek" in model.lower()
    is_thinking_model = is_deepseek or "r1" in model.lower() or "reasoning" in model.lower()

    # Base tokens needed: ~300 tokens per scene for outline content
    base_tokens = req.target_scenes * 400 + 500  # scenes + overhead

    if is_thinking_model:
        # Thinking models may use 2-3x tokens for reasoning
        max_tokens = max(8000, base_tokens * 3)
        print(f"[Outline] Using extended max_tokens={max_tokens} for thinking model")
    else:
        max_tokens = max(4000, base_tokens)

    # Retry configuration
    max_retries = 2
    last_error = None
    partial_outline = None

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                print(f"[Outline] Retry attempt {attempt}/{max_retries}")
                # On retry, increase tokens further
                max_tokens = int(max_tokens * 1.5)

            # Call LLM to generate outline - use response_format="json" for better results
            response = await chat_ollama(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                base_url=base_url,
                model=model,
                temperature=0.7,
                max_tokens=max_tokens,
                response_format="json",  # Tell Ollama to output JSON
            )

            # Extract content from the OpenAI-compatible response format
            # chat_ollama returns: {"choices": [{"message": {"content": ...}}], "provider_raw": ...}
            response_text = ""
            provider_raw = {}
            if isinstance(response, dict):
                choices = response.get("choices", [])
                if choices and isinstance(choices, list) and len(choices) > 0:
                    message = choices[0].get("message", {})
                    response_text = message.get("content", "")
                # Fallback to direct content key
                if not response_text:
                    response_text = response.get("content", "")
                # Get provider raw for truncation detection
                provider_raw = response.get("provider_raw", {})
            else:
                response_text = str(response)

            print(f"[Outline] Response length: {len(response_text)} chars")
            print(f"[Outline] Response preview: {response_text[:300]}...")

            # Check for truncation indicators from Ollama
            done_reason = provider_raw.get("done_reason", "")
            if done_reason == "length":
                print(f"[Outline] WARNING: Response was truncated (done_reason=length)")

            if not response_text.strip():
                last_error = "LLM returned empty response. Please try again or check Ollama is running."
                continue

            # Check if response appears truncated
            is_truncated = _is_truncated_json(response_text)
            if is_truncated:
                print(f"[Outline] Response appears truncated, attempting repair...")

            # Clean up response - remove markdown code blocks if present
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            outline = None

            # Try 1: Parse cleaned text directly if it starts with {
            if cleaned.startswith("{"):
                try:
                    outline = json.loads(cleaned)
                    print("[Outline] Parsed JSON directly from cleaned response")
                except json.JSONDecodeError as e:
                    print(f"[Outline] Direct parse failed: {e}")

            # Try 2: Find JSON object in the text using brace matching
            if not outline:
                start_idx = response_text.find("{")
                if start_idx != -1:
                    depth = 0
                    end_idx = start_idx
                    in_string = False
                    escape_next = False

                    for i, char in enumerate(response_text[start_idx:], start_idx):
                        if escape_next:
                            escape_next = False
                            continue
                        if char == "\\":
                            escape_next = True
                            continue
                        if char == '"' and not escape_next:
                            in_string = not in_string
                            continue
                        if in_string:
                            continue
                        if char == "{":
                            depth += 1
                        elif char == "}":
                            depth -= 1
                            if depth == 0:
                                end_idx = i + 1
                                break

                    if end_idx > start_idx:
                        json_str = response_text[start_idx:end_idx]
                        try:
                            outline = json.loads(json_str)
                            print(f"[Outline] Parsed JSON via brace matching ({len(json_str)} chars)")
                        except json.JSONDecodeError as e:
                            print(f"[Outline] Brace match parse failed: {e}")

            # Try 3: Regex fallback for simpler cases
            if not outline:
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    try:
                        outline = json.loads(json_match.group())
                        print("[Outline] Parsed JSON via regex")
                    except json.JSONDecodeError as e:
                        print(f"[Outline] Regex parse failed: {e}")

            # Try 4: Attempt to repair truncated JSON
            if not outline and is_truncated:
                print("[Outline] Attempting JSON repair for truncated response...")
                partial_outline = _extract_partial_outline(cleaned)
                if partial_outline:
                    scene_count = len(partial_outline.get("scenes", []))
                    print(f"[Outline] Repair successful! Recovered {scene_count} scenes")
                    if scene_count >= 2:  # Accept if we got at least 2 valid scenes
                        outline = partial_outline
                        outline["_warning"] = "Response was truncated and repaired. Some scenes may be incomplete."

            if not outline:
                # Log the full response for debugging (truncated to prevent log spam)
                log_text = response_text[:2000] + "..." if len(response_text) > 2000 else response_text
                print(f"[Outline] FAILED - Response (truncated for log):\n{log_text}")
                last_error = "No valid JSON found in response. The AI model may need a different prompt format."

                # If truncated, provide more specific error
                if is_truncated:
                    last_error = f"Response was truncated (got {len(response_text)} chars). Try using a different model or reducing scene count."

                # Store partial for potential use
                if partial_outline:
                    last_error = f"Response was truncated but recovered {len(partial_outline.get('scenes', []))} scenes."

                continue

            # Validate outline has required fields
            if "scenes" not in outline or not isinstance(outline.get("scenes"), list):
                print(f"[Outline] Invalid outline structure: {list(outline.keys())}")
                last_error = "Outline missing 'scenes' array"
                continue

            if len(outline["scenes"]) == 0:
                last_error = "Outline has no scenes"
                continue

            # Ensure all scenes have required fields with defaults
            for i, scene in enumerate(outline["scenes"]):
                if not scene.get("negative_prompt"):
                    scene["negative_prompt"] = DEFAULT_NEGATIVE_PROMPT
                if not scene.get("duration_sec"):
                    scene["duration_sec"] = req.scene_duration
                if not scene.get("scene_number"):
                    scene["scene_number"] = i + 1

            print(f"[Outline] SUCCESS - Generated {len(outline['scenes'])} scenes")

            # Store outline in project metadata
            update_video(video_id, metadata={"story_outline": outline})

            result = {
                "ok": True,
                "outline": outline,
                "model_used": model,
            }

            # Add warnings if applicable
            if outline.get("_repaired"):
                result["warning"] = "Response was truncated and automatically repaired."
            if outline.get("_warning"):
                result["warning"] = outline.pop("_warning")

            return result

        except json.JSONDecodeError as e:
            last_error = f"Failed to parse AI response: {str(e)}"
            print(f"[Outline] JSON error on attempt {attempt}: {e}")
            continue
        except Exception as e:
            last_error = f"Failed to generate outline: {str(e)}"
            print(f"[Outline] Error on attempt {attempt}: {e}")
            continue

    # All retries exhausted - return error response instead of raising 500
    # Check if we have a partial outline we can use
    if partial_outline and len(partial_outline.get("scenes", [])) >= 2:
        print(f"[Outline] Using partial outline with {len(partial_outline['scenes'])} scenes after retries exhausted")
        update_video(video_id, metadata={"story_outline": partial_outline})
        return {
            "ok": True,
            "outline": partial_outline,
            "model_used": model,
            "warning": f"Response was truncated. Only {len(partial_outline['scenes'])} of {req.target_scenes} scenes were generated. You can generate more scenes manually.",
            "partial": True,
        }

    # Return structured error response (not 500)
    return {
        "ok": False,
        "error": "outline_generation_failed",
        "message": last_error or "Failed to generate outline after multiple attempts",
        "model_used": model,
        "hints": [
            "Try using a different LLM model (llama3:8b recommended)",
            f"Reduce the number of scenes (currently {req.target_scenes})",
            "Check that Ollama is running and responsive",
            "The model may have run out of tokens - try a model with larger context",
        ],
    }


@router.get("/videos/{video_id}/outline")
def get_story_outline(video_id: str):
    """Get the stored story outline for a project."""
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    metadata = v.metadata if hasattr(v, 'metadata') and v.metadata else {}
    outline = metadata.get("story_outline")

    if not outline:
        return {"ok": False, "outline": None, "message": "No outline generated yet"}

    return {"ok": True, "outline": outline}


@router.post("/videos/{video_id}/sync-outline")
def sync_outline_with_scenes(video_id: str):
    """
    Synchronize the story outline with the current scenes.

    This updates the outline to reflect the actual scenes that exist,
    adding any new scenes and removing any that were deleted.
    """
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # Get current scenes
    current_scenes = list_scenes(video_id)

    # Get existing outline
    metadata = v.metadata if hasattr(v, 'metadata') and v.metadata else {}
    outline = metadata.get("story_outline") or {}

    # Build updated scenes list from actual scenes
    updated_outline_scenes = []
    for i, scene in enumerate(current_scenes):
        updated_outline_scenes.append({
            "scene_number": i + 1,
            "title": f"Scene {i + 1}",  # Could extract from narration
            "description": scene.narration[:100] if scene.narration else "",
            "narration": scene.narration or "",
            "image_prompt": scene.imagePrompt or "",
            "negative_prompt": scene.negativePrompt or DEFAULT_NEGATIVE_PROMPT,
            "duration_sec": scene.durationSec or 5.0,
        })

    # Update the outline
    outline["scenes"] = updated_outline_scenes
    outline["scene_count"] = len(updated_outline_scenes)

    # Store updated outline
    update_video(video_id, metadata={"story_outline": outline})

    return {
        "ok": True,
        "outline": outline,
        "scene_count": len(updated_outline_scenes),
        "message": f"Outline synchronized with {len(updated_outline_scenes)} scenes"
    }


@router.post("/videos/{video_id}/scenes/generate-from-outline")
async def generate_scene_from_outline(
    video_id: str,
    scene_index: int = Query(..., ge=0),
    ollama_base_url: Optional[str] = None,
    ollama_model: Optional[str] = None,
):
    """
    Generate a scene based on the story outline.
    Uses the pre-planned scene outline to create the scene.

    Returns ok=False with reason if outline is exhausted (instead of 400 error).
    """
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    metadata = v.metadata if hasattr(v, 'metadata') and v.metadata else {}
    outline = metadata.get("story_outline")

    if not outline or not outline.get("scenes"):
        # Return structured response instead of 400 error
        return {
            "ok": False,
            "reason": "no_outline",
            "message": "No story outline found. Generate outline first or use continuation.",
        }

    scenes = outline.get("scenes", [])
    if scene_index >= len(scenes):
        # Return structured response instead of 400 error - allows frontend to gracefully fallback
        return {
            "ok": False,
            "reason": "outline_exhausted",
            "message": f"Outline has {len(scenes)} scenes. Scene index {scene_index} is beyond the outline.",
            "outline_scene_count": len(scenes),
            "requested_index": scene_index,
        }

    scene_plan = scenes[scene_index]

    # Create the scene from the outline - use centralized default negative prompt
    scene = create_scene(video_id, StudioSceneCreate(
        narration=scene_plan.get("narration", ""),
        imagePrompt=scene_plan.get("image_prompt", ""),
        negativePrompt=scene_plan.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT),
        durationSec=scene_plan.get("duration_sec", 5.0),
    ))

    if not scene:
        raise HTTPException(status_code=500, detail="Failed to create scene")

    return {
        "ok": True,
        "scene": scene.model_dump(),
        "from_outline": True,
        "scene_plan": scene_plan,
    }


@router.post("/videos/{video_id}/scenes/generate-continuation")
async def generate_scene_continuation(
    video_id: str,
    ollama_base_url: Optional[str] = None,
    ollama_model: Optional[str] = None,
):
    """
    Generate a continuation scene using AI based on previous scene context.

    This endpoint is used when the story outline has been exhausted but the user
    wants to continue the story. It uses the previous scenes and project context
    to generate a coherent continuation.
    """
    from ..llm import chat_ollama
    from ..config import OLLAMA_BASE_URL, OLLAMA_MODEL
    import json

    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    # Get existing scenes for context
    existing_scenes = list_scenes(video_id)
    if not existing_scenes:
        raise HTTPException(status_code=400, detail="No existing scenes to continue from. Create a first scene or generate from outline.")

    # Get project settings
    metadata = v.metadata if hasattr(v, 'metadata') and v.metadata else {}
    outline = metadata.get("story_outline", {})
    tags = v.tags if hasattr(v, 'tags') and v.tags else []

    # Extract visual style and tones from tags
    visual_style = "cinematic"
    tones = []
    project_llm_model = None

    for tag in tags:
        if tag.startswith("visual:"):
            visual_style = tag.replace("visual:", "").replace("_", " ")
        elif tag.startswith("tone:"):
            tones.append(tag.replace("tone:", "").replace("_", " "))
        elif tag.startswith("llm:"):
            project_llm_model = tag.replace("llm:", "")

    tone_desc = ", ".join(tones) if tones else "documentary, calm"

    # Get the last 2-3 scenes for context
    context_scenes = existing_scenes[-3:] if len(existing_scenes) >= 3 else existing_scenes
    scene_context = []
    for i, scene in enumerate(context_scenes):
        scene_context.append({
            "scene_number": len(existing_scenes) - len(context_scenes) + i + 1,
            "narration": scene.narration or "",
            "image_prompt": scene.imagePrompt or "",
        })

    next_scene_number = len(existing_scenes) + 1

    # Check content rating
    content_rating = v.contentRating if hasattr(v, 'contentRating') else "sfw"
    mature_mode_enabled = org_allows_mature() and content_rating == "mature"

    # Build the continuation prompt
    if mature_mode_enabled:
        content_instructions = """
CONTENT MODE: MATURE/ADULT
- You are allowed to generate sensual, romantic, and adult content
- Include appropriate fan service, intimate moments, and detailed physical descriptions
- Match the tone of the previous scenes while continuing the story"""
    else:
        content_instructions = """
CONTENT MODE: SAFE FOR WORK
- Keep content appropriate for general audiences
- Focus on storytelling, emotion, and visual interest"""

    system_prompt = f"""You are a professional screenwriter continuing a visual story. Generate the next scene as a JSON object.

STORY CONTEXT:
Title: {v.title}
Description: {v.logline or "A compelling visual story"}
Visual Style: {visual_style}
Tone: {tone_desc}
Story Arc: {json.dumps(outline.get("story_arc", {})) if outline.get("story_arc") else "Continue naturally"}
{content_instructions}

PREVIOUS SCENES FOR CONTEXT:
{json.dumps(scene_context, indent=2)}

Generate the next scene (Scene {next_scene_number}) that:
1. Continues the story naturally from where it left off
2. Maintains consistency with characters, setting, and tone
3. Advances the plot or character development
4. Creates a vivid image prompt that matches the new narration

Output ONLY valid JSON with this exact structure:
{{
  "scene_number": {next_scene_number},
  "title": "Scene Title",
  "description": "Brief scene description",
  "narration": "2-3 sentences of narration text that continues the story",
  "image_prompt": "{visual_style} style, detailed visual description of the scene matching the narration, high quality, masterpiece",
  "negative_prompt": "blurry, low quality, text, watermark, ugly, deformed, duplicate, clone, multiple people, two heads, split image"
}}

CRITICAL: The narration and image_prompt MUST continue the story from the previous scenes, not repeat or contradict them."""

    user_prompt = f"""Generate Scene {next_scene_number} continuing from the previous scenes shown above.

The new scene should naturally follow the story progression and maintain visual consistency.

Output the JSON now:"""

    base_url = ollama_base_url or OLLAMA_BASE_URL
    model = ollama_model or project_llm_model or OLLAMA_MODEL

    # If no model specified, try to find one
    if not model:
        try:
            import httpx
            models_url = f"{base_url.rstrip('/')}/api/tags"
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(models_url)
                if resp.status_code == 200:
                    models_data = resp.json()
                    available_models = [m.get("name") for m in models_data.get("models", [])]
                    for preferred in ["llama3:8b", "llama3:latest"]:
                        if preferred in available_models:
                            model = preferred
                            break
                    if not model and available_models:
                        model = available_models[0]
        except Exception:
            pass

    if not model:
        raise HTTPException(status_code=400, detail="No LLM model available. Please configure Ollama.")

    print(f"[Continuation] Generating scene {next_scene_number} with model: {model}")

    try:
        response = await chat_ollama(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            base_url=base_url,
            model=model,
            temperature=0.7,
            max_tokens=2000,
            response_format="json",
        )

        # Extract content
        response_text = ""
        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices and isinstance(choices, list) and len(choices) > 0:
                message = choices[0].get("message", {})
                response_text = message.get("content", "")
            if not response_text:
                response_text = response.get("content", "")
        else:
            response_text = str(response)

        if not response_text.strip():
            raise ValueError("LLM returned empty response")

        # Parse JSON
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        scene_data = None
        try:
            scene_data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                scene_data = json.loads(json_match.group())

        if not scene_data:
            raise ValueError("Could not parse scene data from AI response")

        # Create the scene
        scene = create_scene(video_id, StudioSceneCreate(
            narration=scene_data.get("narration", ""),
            imagePrompt=scene_data.get("image_prompt", ""),
            negativePrompt=scene_data.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT),
            durationSec=scene_data.get("duration_sec", 5.0),
        ))

        if not scene:
            raise HTTPException(status_code=500, detail="Failed to create scene")

        print(f"[Continuation] Successfully generated scene {next_scene_number}")

        return {
            "ok": True,
            "scene": scene.model_dump(),
            "from_continuation": True,
            "scene_data": scene_data,
            "model_used": model,
        }

    except json.JSONDecodeError as e:
        print(f"[Continuation] JSON parse error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse AI response: {str(e)}")
    except Exception as e:
        print(f"[Continuation] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate continuation: {str(e)}")


# ============================================================================
# Library - Style Kits and Templates
# ============================================================================

@router.get("/library/style-kits")
def library_style_kits():
    """List all available style kits."""
    kits = list_style_kits()
    return {"styleKits": [k.model_dump() for k in kits]}


@router.get("/library/style-kits/{kit_id}")
def library_style_kit_detail(kit_id: str):
    """Get a style kit by ID."""
    kit = get_style_kit(kit_id)
    if not kit:
        raise HTTPException(status_code=404, detail="Style kit not found")
    return {"styleKit": kit.model_dump()}


@router.get("/library/templates")
def library_templates(project_type: Optional[str] = Query(default=None)):
    """List templates, optionally filtered by project type."""
    templates = list_templates(project_type=project_type)
    return {"templates": [t.model_dump() for t in templates]}


@router.get("/library/templates/{template_id}")
def library_template_detail(template_id: str):
    """Get a template by ID."""
    tpl = get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"template": tpl.model_dump()}


# ============================================================================
# Professional Projects CRUD
# ============================================================================

@router.get("/projects")
def projects_list(
    q: Optional[str] = Query(default=None, description="Search query"),
    project_type: Optional[str] = Query(default=None, description="Filter by project type"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=100, le=500),
):
    """List all professional projects with optional filters."""
    projects = list_projects(q=q, project_type=project_type, status=status, limit=limit)
    return {"projects": [p.model_dump() for p in projects]}


@router.post("/projects")
def project_create(inp: StudioProjectCreate):
    """Create a new professional project."""
    proj = create_project(inp)
    return {"project": proj.model_dump()}


@router.get("/projects/{project_id}")
def project_detail(project_id: str):
    """Get professional project details."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": proj.model_dump()}


class ProjectUpdateRequest(BaseModel):
    """Request to update project fields."""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    styleKitId: Optional[str] = None
    templateId: Optional[str] = None


@router.patch("/projects/{project_id}")
def project_update(project_id: str, req: ProjectUpdateRequest):
    """Update professional project fields."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    updates = req.model_dump(exclude_unset=True)

    if "status" in updates and updates["status"]:
        if updates["status"] not in ("draft", "in_review", "approved", "archived"):
            raise HTTPException(status_code=400, detail="Invalid status")

    if updates:
        proj = update_project(project_id, **updates)

    return {"project": proj.model_dump()}


@router.delete("/projects/{project_id}")
def project_delete(project_id: str):
    """Delete a professional project and all associated data."""
    deleted = delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


# ============================================================================
# Assets
# ============================================================================

class AssetCreateRequest(BaseModel):
    """Request to create a new asset."""
    kind: AssetKind
    filename: str
    mime: str
    sizeBytes: int
    url: str


@router.get("/projects/{project_id}/assets")
def assets_list(
    project_id: str,
    kind: Optional[AssetKind] = Query(default=None),
):
    """List assets for a project."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    assets = list_assets(project_id, kind=kind)
    return {"assets": [a.model_dump() for a in assets]}


@router.post("/projects/{project_id}/assets")
def asset_create(project_id: str, req: AssetCreateRequest):
    """Create a new asset for a project."""
    asset = create_asset(
        project_id=project_id,
        kind=req.kind,
        filename=req.filename,
        mime=req.mime,
        size_bytes=req.sizeBytes,
        url=req.url,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"asset": asset.model_dump()}


@router.get("/projects/{project_id}/assets/{asset_id}")
def asset_detail(project_id: str, asset_id: str):
    """Get asset details."""
    asset = get_asset(asset_id)
    if not asset or asset.projectId != project_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"asset": asset.model_dump()}


@router.delete("/projects/{project_id}/assets/{asset_id}")
def asset_delete(project_id: str, asset_id: str):
    """Delete an asset."""
    asset = get_asset(asset_id)
    if not asset or asset.projectId != project_id:
        raise HTTPException(status_code=404, detail="Asset not found")

    delete_asset(asset_id)
    return {"ok": True}


# ============================================================================
# Audio Tracks
# ============================================================================

class AudioTrackCreateRequest(BaseModel):
    """Request to create a new audio track."""
    kind: TrackKind
    assetId: Optional[str] = None
    url: Optional[str] = None
    volume: float = 1.0
    startSec: float = 0.0
    endSec: Optional[float] = None


class AudioTrackUpdateRequest(BaseModel):
    """Request to update an audio track."""
    volume: Optional[float] = None
    startSec: Optional[float] = None
    endSec: Optional[float] = None


@router.get("/projects/{project_id}/audio")
def audio_tracks_list(
    project_id: str,
    kind: Optional[TrackKind] = Query(default=None),
):
    """List audio tracks for a project."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    tracks = list_audio_tracks(project_id, kind=kind)
    return {"tracks": [t.model_dump() for t in tracks]}


@router.post("/projects/{project_id}/audio")
def audio_track_create(project_id: str, req: AudioTrackCreateRequest):
    """Create a new audio track for a project."""
    track = create_audio_track(
        project_id=project_id,
        kind=req.kind,
        asset_id=req.assetId,
        url=req.url,
        volume=req.volume,
        start_sec=req.startSec,
        end_sec=req.endSec,
    )
    if not track:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"track": track.model_dump()}


@router.patch("/projects/{project_id}/audio/{track_id}")
def audio_track_update(project_id: str, track_id: str, req: AudioTrackUpdateRequest):
    """Update an audio track."""
    track = get_audio_track(track_id)
    if not track or track.projectId != project_id:
        raise HTTPException(status_code=404, detail="Track not found")

    updates = req.model_dump(exclude_unset=True)
    if updates:
        track = update_audio_track(track_id, **updates)

    return {"track": track.model_dump()}


@router.delete("/projects/{project_id}/audio/{track_id}")
def audio_track_delete(project_id: str, track_id: str):
    """Delete an audio track."""
    track = get_audio_track(track_id)
    if not track or track.projectId != project_id:
        raise HTTPException(status_code=404, detail="Track not found")

    delete_audio_track(track_id)
    return {"ok": True}


# ============================================================================
# Captions
# ============================================================================

class CaptionCreateRequest(BaseModel):
    """Request to create a caption segment."""
    startSec: float
    endSec: float
    text: str


class CaptionUpdateRequest(BaseModel):
    """Request to update a caption segment."""
    startSec: Optional[float] = None
    endSec: Optional[float] = None
    text: Optional[str] = None


@router.get("/projects/{project_id}/captions")
def captions_list(project_id: str):
    """List captions for a project."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    captions = list_captions(project_id)
    return {"captions": [c.model_dump() for c in captions]}


@router.post("/projects/{project_id}/captions")
def caption_create(project_id: str, req: CaptionCreateRequest):
    """Create a new caption segment."""
    cap = create_caption(
        project_id=project_id,
        start_sec=req.startSec,
        end_sec=req.endSec,
        text=req.text,
    )
    if not cap:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"caption": cap.model_dump()}


@router.patch("/projects/{project_id}/captions/{caption_id}")
def caption_update(project_id: str, caption_id: str, req: CaptionUpdateRequest):
    """Update a caption segment."""
    cap = get_caption(caption_id)
    if not cap or cap.projectId != project_id:
        raise HTTPException(status_code=404, detail="Caption not found")

    updates = req.model_dump(exclude_unset=True)
    if updates:
        cap = update_caption(caption_id, **updates)

    return {"caption": cap.model_dump()}


@router.delete("/projects/{project_id}/captions/{caption_id}")
def caption_delete(project_id: str, caption_id: str):
    """Delete a caption segment."""
    cap = get_caption(caption_id)
    if not cap or cap.projectId != project_id:
        raise HTTPException(status_code=404, detail="Caption not found")

    delete_caption(caption_id)
    return {"ok": True}


# ============================================================================
# Autosave and Versions
# ============================================================================

@router.post("/projects/{project_id}/autosave")
def project_autosave(project_id: str, payload: AutosavePayload):
    """Save current project state as an autosave snapshot."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    version = create_version(
        project_id=project_id,
        state=payload.state,
        label="autosave",
    )
    return {"version": version.model_dump()}


@router.get("/projects/{project_id}/versions")
def versions_list(
    project_id: str,
    limit: int = Query(default=50, le=200),
):
    """List version snapshots for a project."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    versions = list_versions(project_id, limit=limit)
    return {"versions": [v.model_dump() for v in versions]}


@router.get("/projects/{project_id}/versions/latest")
def version_latest(project_id: str):
    """Get the most recent version snapshot."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    version = get_latest_version(project_id)
    if not version:
        return {"version": None, "message": "No versions found"}
    return {"version": version.model_dump()}


@router.get("/projects/{project_id}/versions/{version_id}")
def version_detail(project_id: str, version_id: str):
    """Get a specific version snapshot."""
    version = get_version(version_id)
    if not version or version.projectId != project_id:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"version": version.model_dump()}


class VersionCreateRequest(BaseModel):
    """Request to create a named version."""
    label: str = "snapshot"
    state: dict


@router.post("/projects/{project_id}/versions")
def version_create(project_id: str, req: VersionCreateRequest):
    """Create a named version snapshot."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    version = create_version(
        project_id=project_id,
        state=req.state,
        label=req.label,
    )
    return {"version": version.model_dump()}


@router.delete("/projects/{project_id}/versions/{version_id}")
def version_delete(project_id: str, version_id: str):
    """Delete a version snapshot."""
    version = get_version(version_id)
    if not version or version.projectId != project_id:
        raise HTTPException(status_code=404, detail="Version not found")

    delete_version(version_id)
    return {"ok": True}


# ============================================================================
# Share Links
# ============================================================================

class ShareLinkCreateRequest(BaseModel):
    """Request to create a share link."""
    expiresInHours: Optional[int] = None


@router.get("/projects/{project_id}/share")
def share_links_list(project_id: str):
    """List share links for a project."""
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    links = list_share_links(project_id)
    return {"shareLinks": [link.model_dump() for link in links]}


@router.post("/projects/{project_id}/share")
def share_link_create(project_id: str, req: ShareLinkCreateRequest):
    """Create a new share link for read-only access."""
    link = create_share_link(
        project_id=project_id,
        expires_in_hours=req.expiresInHours,
    )
    if not link:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"shareLink": link.model_dump()}


@router.delete("/projects/{project_id}/share/{token}")
def share_link_delete(project_id: str, token: str):
    """Delete a share link."""
    link = get_share_link(token)
    if not link or link.projectId != project_id:
        raise HTTPException(status_code=404, detail="Share link not found")

    delete_share_link(token)
    return {"ok": True}


@router.get("/shared/{token}")
def shared_project_view(token: str):
    """
    View a shared project (read-only).

    This is the public endpoint for viewing shared projects.
    """
    link = get_share_link(token)
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found or expired")

    proj = get_project(link.projectId)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    # Return read-only view of the project
    return {
        "project": proj.model_dump(),
        "mode": link.mode,
        "expiresAt": link.expiresAt,
    }


# ============================================================================
# Professional Project Exports
# ============================================================================

@router.get("/projects/{project_id}/exports")
def project_available_exports(project_id: str):
    """Get available export formats for a professional project."""
    return get_project_available_exports(project_id)


class ProjectExportRequest(BaseModel):
    """Request to export a professional project."""
    kind: Literal["json_metadata", "storyboard_pdf", "slides_pdf", "slides_pptx", "zip_assets"] = "json_metadata"


@router.post("/projects/{project_id}/export")
def project_do_export(project_id: str, req: ProjectExportRequest):
    """Export a professional project in the specified format."""
    return export_project(project_id, kind=req.kind)


# ============================================================================
# Media Proxy (for proper WebM playback)
# ============================================================================

from fastapi.responses import StreamingResponse
import httpx

@router.get("/media")
async def studio_media_proxy(url: str = Query(..., description="URL of the media file to proxy")):
    """
    Proxy media files from ComfyUI with correct Content-Type headers.

    This ensures WebM videos and animated WebP images are served with proper headers.
    Supports Range requests for video seeking. Fixes issues where ComfyUI returns
    wrong Content-Type or missing CORS headers.
    """
    from fastapi import Request
    from starlette.requests import Request as StarletteRequest
    import inspect

    # Basic validation - only allow localhost ComfyUI URLs for security
    if not (url.startswith("http://localhost:8188/") or url.startswith("http://127.0.0.1:8188/")):
        raise HTTPException(status_code=400, detail="Invalid media URL - only local ComfyUI URLs allowed")

    # Determine correct Content-Type from URL extension
    url_lower = url.lower()
    if ".webp" in url_lower:
        content_type = "image/webp"
    elif ".gif" in url_lower:
        content_type = "image/gif"
    elif ".webm" in url_lower:
        content_type = "video/webm"
    elif ".mp4" in url_lower:
        content_type = "video/mp4"
    elif ".png" in url_lower:
        content_type = "image/png"
    elif ".jpg" in url_lower or ".jpeg" in url_lower:
        content_type = "image/jpeg"
    else:
        content_type = "application/octet-stream"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(url)
            if r.status_code not in (200, 206):
                raise HTTPException(status_code=502, detail=f"Upstream media fetch failed: {r.status_code}")

            # Build response headers
            response_headers = {
                "Content-Disposition": "inline",
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*",
                "Accept-Ranges": "bytes",
            }

            # Pass through content-length if available
            if "content-length" in r.headers:
                response_headers["Content-Length"] = r.headers["content-length"]

            # Stream the response with correct headers
            async def generate():
                async for chunk in r.aiter_bytes():
                    yield chunk

            return StreamingResponse(
                generate(),
                status_code=r.status_code,
                media_type=content_type,
                headers=response_headers,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Media fetch timed out")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Media fetch error: {str(e)}")


# ============================================================================
# Health
# ============================================================================

@router.get("/health")
def health():
    """Studio module health check."""
    return {"status": "ok", "module": "studio"}
