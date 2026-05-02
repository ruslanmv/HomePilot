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
INTERACTIVE_PLAYBACK_IMAGE_WORKFLOW      (str,   default 'avatar_txt2img')
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
_FALSY = {"0", "false", "no", "off", "n"}


def _bool_env(name: str, *, default: bool = False) -> bool:
    """Read an env bool with an explicit default.

    Returns the default when the env is unset / blank / neither
    truthy nor falsy. Empty string is treated as unset so an
    operator who clears a Settings UI field falls back to the
    built-in default instead of silently flipping the value.
    """
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return default


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
    render_workflow: str        # video workflow (Animate / SVD / Wan)
    image_workflow: str         # still-image workflow (txt2img)
    render_timeout_s: float

    def workflow_for(self, media_type: str) -> str:
        """Pick the workflow name for the requested media kind.

        ``media_type`` is the string stamped onto the experience's
        ``audience_profile.render_media_type`` at wizard time.
        Unknown / empty values fall back to the video workflow so
        experiences created before this knob existed keep rendering
        the same clips they always did.
        """
        kind = (media_type or "").strip().lower()
        if kind == "image":
            return self.image_workflow
        return self.render_workflow


def load_playback_config() -> PlaybackConfig:
    """Read env vars fresh. Cheap; safe to call per request.

    Defaults tuned for "batteries-included" behaviour on a fresh
    install: if you have Ollama + ComfyUI running locally,
    ``make start`` gives you a working Interactive surface
    without touching any env vars. Explicit opt-outs still
    honoured — set ``INTERACTIVE_PLAYBACK_LLM=false`` or
    ``INTERACTIVE_PLAYBACK_RENDER=false`` to force the heuristic
    / skip-render paths (useful in CI + headless setups).
    """
    return PlaybackConfig(
        # LLM default-on: the planner is the whole point — users
        # who really want the text-only heuristic path opt out.
        llm_enabled=_bool_env("INTERACTIVE_PLAYBACK_LLM", default=True),
        llm_timeout_s=_float_env("INTERACTIVE_PLAYBACK_LLM_TIMEOUT_S", 12.0),
        llm_max_tokens=_int_env("INTERACTIVE_PLAYBACK_LLM_MAX_TOKENS", 350),
        llm_temperature=_float_env("INTERACTIVE_PLAYBACK_LLM_TEMPERATURE", 0.65),
        # Render default-on: per-scene failure is non-fatal (the
        # stream emits scene_render_failed and keeps going), so
        # flipping the default removes the biggest "why nothing
        # rendered?" support paper-cut. Users without a ComfyUI
        # install get clean failure events instead of silent skips.
        render_enabled=_bool_env("INTERACTIVE_PLAYBACK_RENDER", default=True),
        render_workflow=os.getenv("INTERACTIVE_PLAYBACK_RENDER_WORKFLOW", "animate").strip() or "animate",
        image_workflow=os.getenv("INTERACTIVE_PLAYBACK_IMAGE_WORKFLOW", "avatar_txt2img").strip() or "avatar_txt2img",
        render_timeout_s=_float_env("INTERACTIVE_PLAYBACK_RENDER_TIMEOUT_S", 180.0),
    )
