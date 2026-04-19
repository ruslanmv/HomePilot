"""
Playback feature flags (phase-2).

One module, one job: read env vars for the two phase-2 swap
points and return booleans + tuning knobs. Everything is lazy —
env vars are re-read on each call so tests can monkeypatch
``os.environ`` between cases without re-importing.

Flags
-----
INTERACTIVE_PLAYBACK_LLM
    "1" / "true" / "on" → scene_planner tries the LLM composer
    before falling back to the heuristic one. Any other value
    (including unset) keeps the phase-1 heuristic path.

INTERACTIVE_PLAYBACK_RENDER
    "1" / "true" / "on" → video_job.render_now submits a real
    workflow to the configured Animate / ComfyUI backend. Unset
    or falsy → the deterministic stub asset id path.

Tuning knobs
------------
INTERACTIVE_PLAYBACK_LLM_TIMEOUT_S       (float, default 12)
INTERACTIVE_PLAYBACK_LLM_MAX_TOKENS      (int,   default 350)
INTERACTIVE_PLAYBACK_LLM_TEMPERATURE     (float, default 0.65)
INTERACTIVE_PLAYBACK_RENDER_WORKFLOW     (str,   default 'animate')
INTERACTIVE_PLAYBACK_RENDER_TIMEOUT_S    (float, default 180)

All flags default OFF so upgrading from phase-1 is a no-op unless
an operator opts in. Production is expected to set both flags
true once the LLM + Comfy backends are reachable; staging can
mix-and-match.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


_TRUTHY = {"1", "true", "yes", "on", "y"}


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


@dataclass(frozen=True)
class PlaybackConfig:
    """Snapshot of the current playback flags + knobs."""

    llm_enabled: bool
    llm_timeout_s: float
    llm_max_tokens: int
    llm_temperature: float
    render_enabled: bool
    render_workflow: str
    render_timeout_s: float


def load_playback_config() -> PlaybackConfig:
    """Read env vars fresh. Cheap; safe to call per request."""
    return PlaybackConfig(
        llm_enabled=_bool_env("INTERACTIVE_PLAYBACK_LLM"),
        llm_timeout_s=_float_env("INTERACTIVE_PLAYBACK_LLM_TIMEOUT_S", 12.0),
        llm_max_tokens=_int_env("INTERACTIVE_PLAYBACK_LLM_MAX_TOKENS", 350),
        llm_temperature=_float_env("INTERACTIVE_PLAYBACK_LLM_TEMPERATURE", 0.65),
        render_enabled=_bool_env("INTERACTIVE_PLAYBACK_RENDER"),
        render_workflow=os.getenv("INTERACTIVE_PLAYBACK_RENDER_WORKFLOW", "animate").strip() or "animate",
        render_timeout_s=_float_env("INTERACTIVE_PLAYBACK_RENDER_TIMEOUT_S", 180.0),
    )
