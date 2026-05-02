"""
Media-generation provider router (PIPE-1).

Sister of ``llm_router``: reads ``IMAGE_MODEL`` / ``VIDEO_MODEL`` /
``COMFY_BASE_URL`` live from ``os.environ`` so the Enterprise
Settings UI can change them at runtime and the interactive
playback pipeline picks up the new values on the next scene
render — no backend restart required.

Why this exists
---------------

Before PIPE-1 the scene render pipeline called
``render_adapter._build_variables`` without ever naming the
ComfyUI model explicitly. The model was baked into the workflow
JSON on disk, so changing ``IMAGE_MODEL`` in Global Settings had
no effect on the interactive surface until the backend
restarted.

This module resolves the current image + video model + base URL
on every call. ``render_adapter`` threads the result into the
workflow variable bag (``image_model``, ``video_model``,
``comfy_base_url``, ``checkpoint``, ``ckpt_name``) so operators
can update their workflow JSON to reference any of those
placeholders and have it track Global Settings automatically.
Unknown variables are harmless — the workflow engine only
substitutes keys that actually appear in the JSON.

Keeping this file thin (pure read-env + defaults) means the
render pipeline stays easy to test: the router has no network
I/O and no side effects.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from ..runtime_config import read_runtime_config

log = logging.getLogger(__name__)


# ── Resolved snapshot ──────────────────────────────────────────

@dataclass(frozen=True)
class MediaProviders:
    """One call's worth of live-resolved media settings.

    Immutable; callers can stash it alongside telemetry so replay
    debugging can answer "which model rendered scene N".
    """

    image_model: str
    video_model: str
    comfy_base_url: str

    def describe(self) -> str:
        """Compact label for log lines."""
        return (
            f"image={self.image_model} "
            f"video={self.video_model} "
            f"comfy={self.comfy_base_url}"
        )


# ── Resolution ─────────────────────────────────────────────────

_DEFAULT_IMAGE_MODEL = "sdxl"
_DEFAULT_VIDEO_MODEL = "svd"


def resolve_current_image_model(
    *, override: Optional[str] = None,
) -> str:
    """Return the ComfyUI image checkpoint the interactive pipeline
    should ask for right now.

    Resolution order:

      1. explicit ``override`` argument (tests / admin calls)
      2. ``INTERACTIVE_IMAGE_MODEL`` — interactive-scoped override
         so ops can force a smaller / faster checkpoint here
         without touching the Studio/Animate chain.
      3. ``IMAGE_MODEL`` — HomePilot-wide image model.
      4. built-in ``sdxl`` fallback.

    Never raises. An empty env var is treated as "unset" so a
    blank value in the Settings UI falls back to the next tier.
    """
    runtime = read_runtime_config()
    return (
        override
        or _nonempty(os.getenv("INTERACTIVE_IMAGE_MODEL"))
        or _nonempty(runtime.get("IMAGE_MODEL"))
        or _nonempty(os.getenv("IMAGE_MODEL"))
        or _DEFAULT_IMAGE_MODEL
    )


def resolve_current_video_model(
    *, override: Optional[str] = None,
) -> str:
    """Return the ComfyUI video checkpoint (Animate / SVD / Wan).

    Same resolution order as the image variant, scoped to video
    env vars (``INTERACTIVE_VIDEO_MODEL`` → ``VIDEO_MODEL`` →
    default ``svd``).
    """
    runtime = read_runtime_config()
    return (
        override
        or _nonempty(os.getenv("INTERACTIVE_VIDEO_MODEL"))
        or _nonempty(runtime.get("VIDEO_MODEL"))
        or _nonempty(os.getenv("VIDEO_MODEL"))
        or _DEFAULT_VIDEO_MODEL
    )


def resolve_current_comfy_base_url(
    *, override: Optional[str] = None,
) -> str:
    """Return the ComfyUI endpoint the interactive pipeline
    should hit. Resolution order mirrors the model resolvers.

    Unlike the model strings, the base URL has a Docker-aware
    default: inside a container we prefer the ``comfyui`` service
    DNS, otherwise localhost. Matches ``app.config.COMFY_BASE_URL``'s
    startup logic but reads live so the Settings UI wins.
    """
    runtime = read_runtime_config()
    return (
        override
        or _nonempty(os.getenv("INTERACTIVE_COMFY_BASE_URL"))
        or _nonempty(runtime.get("COMFY_BASE_URL"))
        or _nonempty(os.getenv("COMFY_BASE_URL"))
        or _default_comfy_base_url()
    )


def resolve_current_providers() -> MediaProviders:
    """One-shot convenience — grab the full triple for logging
    and for injection into workflow variables."""
    return MediaProviders(
        image_model=resolve_current_image_model(),
        video_model=resolve_current_video_model(),
        comfy_base_url=resolve_current_comfy_base_url(),
    )


# ── Helpers ────────────────────────────────────────────────────

def _nonempty(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = v.strip()
    return s if s else None


def _default_comfy_base_url() -> str:
    in_docker = (
        os.path.exists("/.dockerenv")
        or os.getenv("DOCKER_CONTAINER", "").lower() == "true"
    )
    return (
        "http://comfyui:8188" if in_docker else "http://localhost:8188"
    ).rstrip("/")


__all__ = [
    "MediaProviders",
    "resolve_current_comfy_base_url",
    "resolve_current_image_model",
    "resolve_current_providers",
    "resolve_current_video_model",
]
