"""
Live-play subsystem (PLAY-*/8).

Houses the real-time scene-generation loop that powers the
candy.ai-style interactive player: chat arrives, the planner
picks the next scene, a video job runs against the existing
Animate pipeline, and the clip streams back over SSE.

Modules land per-batch and are imported lazily so this subpackage
can be extended without touching the top-level router while
intermediate batches are in flight.

  PLAY-1 (this commit) scene_memory.py — rolling context for the
                                          scene planner. Pure,
                                          synchronous, no LLM calls.
"""
from .scene_memory import (
    SceneMemory,
    TurnSnapshot,
    build_scene_memory,
    reset_session,
    set_synopsis,
    should_refresh_synopsis,
)

__all__ = [
    "SceneMemory",
    "TurnSnapshot",
    "build_scene_memory",
    "reset_session",
    "set_synopsis",
    "should_refresh_synopsis",
]
