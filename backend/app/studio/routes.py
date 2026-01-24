"""
FastAPI routes for Studio module.

Mount this router in your main app:
    from app.studio import router as studio_router
    app.include_router(studio_router)
"""
from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Literal, List
from pydantic import BaseModel, Field

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
            "ponyDiffusionV6XL.safetensors",
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
    negative_prompt: str = "blurry, low quality, text, watermark, ugly, deformed"
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

    # Build example JSON to help the model understand the format
    example_scene = {
        "scene_number": 1,
        "title": "Opening",
        "description": "Brief description of what happens",
        "narration": "The narrator speaks these words to the audience.",
        "image_prompt": f"{visual_style} style, detailed visual description here, high quality",
        "negative_prompt": "blurry, low quality, text, watermark",
        "duration_sec": req.scene_duration
    }

    # Build the outline generation prompt - simpler and more direct
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

IMPORTANT:
- Output ONLY the JSON object, no other text
- Create exactly {req.target_scenes} scenes in the scenes array
- Each scene narration should be 2-3 sentences
- Each image_prompt must include "{visual_style}" style keywords
- Make the story coherent from beginning to end"""

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

    try:
        # Call LLM to generate outline - use response_format="json" for better results
        response = await chat_ollama(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            base_url=base_url,
            model=model,
            temperature=0.7,
            max_tokens=4000,
            response_format="json",  # Tell Ollama to output JSON
        )

        # Extract content from the OpenAI-compatible response format
        # chat_ollama returns: {"choices": [{"message": {"content": ...}}], "provider_raw": ...}
        response_text = ""
        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices and isinstance(choices, list) and len(choices) > 0:
                message = choices[0].get("message", {})
                response_text = message.get("content", "")
            # Fallback to direct content key
            if not response_text:
                response_text = response.get("content", "")
        else:
            response_text = str(response)

        print(f"[Outline] Response length: {len(response_text)} chars")
        print(f"[Outline] Response preview: {response_text[:300]}...")

        if not response_text.strip():
            raise ValueError("LLM returned empty response. Please try again or check Ollama is running.")

        # Try to extract JSON from the response - handle multiple formats
        import re

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

        if not outline:
            # Log the full response for debugging
            print(f"[Outline] FAILED - Full response:\n{response_text}")
            raise ValueError("No valid JSON found in response. The AI model may need a different prompt format.")

        # Validate outline has required fields
        if "scenes" not in outline or not isinstance(outline.get("scenes"), list):
            print(f"[Outline] Invalid outline structure: {list(outline.keys())}")
            raise ValueError("Outline missing 'scenes' array")

        if len(outline["scenes"]) == 0:
            raise ValueError("Outline has no scenes")

        print(f"[Outline] SUCCESS - Generated {len(outline['scenes'])} scenes")

        # Store outline in project metadata
        update_video(video_id, metadata={"story_outline": outline})

        return {
            "ok": True,
            "outline": outline,
            "model_used": model,
        }

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse AI response: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate outline: {str(e)}")


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
    """
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    metadata = v.metadata if hasattr(v, 'metadata') and v.metadata else {}
    outline = metadata.get("story_outline")

    if not outline or not outline.get("scenes"):
        raise HTTPException(status_code=400, detail="No story outline found. Generate outline first.")

    scenes = outline.get("scenes", [])
    if scene_index >= len(scenes):
        raise HTTPException(status_code=400, detail=f"Scene index {scene_index} out of range. Outline has {len(scenes)} scenes.")

    scene_plan = scenes[scene_index]

    # Create the scene from the outline
    scene = create_scene(video_id, StudioSceneCreate(
        narration=scene_plan.get("narration", ""),
        imagePrompt=scene_plan.get("image_prompt", ""),
        negativePrompt=scene_plan.get("negative_prompt", "blurry, low quality, text, watermark"),
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
# Health
# ============================================================================

@router.get("/health")
def health():
    """Studio module health check."""
    return {"status": "ok", "module": "studio"}
