"""
FastAPI routes for Studio module.

Mount this router in your main app:
    from app.studio import router as studio_router
    app.include_router(studio_router)
"""
from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Literal
from pydantic import BaseModel, Field

from .models import StudioVideoCreate, GenerationRequest, ExportRequest, StudioSceneCreate, StudioSceneUpdate
from .repo import list_videos, get_video, list_scenes, get_scene, create_scene, update_scene, delete_scene, update_video
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


@router.patch("/videos/{video_id}")
def video_update(video_id: str, title: Optional[str] = None, logline: Optional[str] = None, status: Optional[str] = None):
    """Update video project fields."""
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")

    updates = {}
    if title is not None:
        updates["title"] = title
    if logline is not None:
        updates["logline"] = logline
    if status is not None:
        if status not in ("draft", "in_review", "approved", "archived"):
            raise HTTPException(status_code=400, detail="Invalid status")
        updates["status"] = status

    if updates:
        v = update_video(video_id, **updates)

    return {"video": v.model_dump()}


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

    for tag in tags:
        if tag.startswith("visual:"):
            visual_style = tag.replace("visual:", "").replace("_", " ")
        elif tag.startswith("tone:"):
            tones.append(tag.replace("tone:", "").replace("_", " "))
        elif tag.startswith("goal:"):
            goal = tag.replace("goal:", "")

    tone_desc = ", ".join(tones) if tones else "documentary"

    # Build the outline generation prompt
    system_prompt = """You are a professional story planner for visual storytelling.
Your task is to create a complete story outline with scene-by-scene breakdown.

Output ONLY valid JSON. No markdown, no explanation, just the JSON object.

JSON schema:
{
  "title": "string",
  "logline": "string (1-2 sentences)",
  "visual_style": "string",
  "tone": "string",
  "story_arc": {
    "beginning": "string (setup/hook)",
    "rising_action": "string (build tension)",
    "climax": "string (peak moment)",
    "falling_action": "string (consequences)",
    "resolution": "string (ending)"
  },
  "scenes": [
    {
      "scene_number": 1,
      "title": "string (brief scene title)",
      "description": "string (what happens)",
      "narration": "string (2-3 sentences of narration text)",
      "image_prompt": "string (detailed visual description for image generation)",
      "negative_prompt": "string (what to avoid in image)",
      "duration_sec": 5.0
    }
  ]
}

Guidelines:
- Create exactly the requested number of scenes
- Each scene should advance the story
- Image prompts should be detailed and include the visual style
- Narration should be engaging and descriptive
- Keep consistent character descriptions across scenes"""

    user_prompt = f"""Create a story outline with the following parameters:

Title: {v.title}
Logline/Description: {v.logline or v.title}
Visual Style: {visual_style}
Tone: {tone_desc}
Goal: {goal}
Number of Scenes: {req.target_scenes}
Scene Duration: {req.scene_duration} seconds each

Create a complete story with a clear beginning, middle, and end.
Each scene should have detailed narration and image prompts that match the visual style.
Make the story engaging and suitable for visual storytelling."""

    base_url = req.ollama_base_url or OLLAMA_BASE_URL
    model = req.ollama_model or OLLAMA_MODEL or "llama3:8b"

    try:
        # Call LLM to generate outline
        response = await chat_ollama(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            base_url=base_url,
            model=model,
            temperature=0.7,
            max_tokens=4000,
        )

        # Parse the response
        response_text = response.get("content", "") if isinstance(response, dict) else str(response)

        # Try to extract JSON from the response
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            outline = json.loads(json_match.group())
        else:
            raise ValueError("No valid JSON found in response")

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
# Health
# ============================================================================

@router.get("/health")
def health():
    """Studio module health check."""
    return {"status": "ok", "module": "studio"}
