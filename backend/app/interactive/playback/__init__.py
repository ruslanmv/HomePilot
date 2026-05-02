"""
Live-play subsystem.

Houses the real-time scene-generation loop that powers the
candy.ai-style interactive player: chat arrives, the planner
picks the next scene, a video job runs against the existing
Animate pipeline, and the clip streams back over SSE.

Modules land per batch and are imported lazily so this subpackage
can be extended without touching the top-level router while
intermediate batches are in flight.

  PLAY-1  scene_memory.py   rolling context (pure, in-memory synopsis).
  PLAY-2  scene_planner.py  chat turn → ScenePlan (heuristic phase-1).
"""
from .scene_memory import (
    SceneMemory,
    TurnSnapshot,
    build_scene_memory,
    reset_session,
    set_synopsis,
    should_refresh_synopsis,
)
from .scene_planner import (
    ScenePlan,
    plan_next_scene,
    plan_next_scene_async,
    synthesize_synopsis,
)
from .asset_urls import resolve_asset_url
from .edit_recipes import EditRecipe, LoRAEntry, pick_recipe
from .persona_assets import PersonaAssets, resolve_persona_assets
from .persona_profile import load_persona_prompt_vars
from .schema import ensure_playback_schema
from .video_job import (
    SceneJob,
    get_job,
    list_jobs,
    mark_failed,
    mark_ready,
    mark_rendering,
    render_now,
    render_now_async,
    submit_scene_job,
)

__all__ = [
    "SceneMemory",
    "TurnSnapshot",
    "build_scene_memory",
    "reset_session",
    "set_synopsis",
    "should_refresh_synopsis",
    "ScenePlan",
    "plan_next_scene",
    "plan_next_scene_async",
    "synthesize_synopsis",
    "EditRecipe",
    "LoRAEntry",
    "PersonaAssets",
    "ensure_playback_schema",
    "load_persona_prompt_vars",
    "pick_recipe",
    "resolve_asset_url",
    "resolve_persona_assets",
    "SceneJob",
    "get_job",
    "list_jobs",
    "mark_failed",
    "mark_ready",
    "mark_rendering",
    "render_now",
    "render_now_async",
    "submit_scene_job",
]
