"""
Interactive-service routes package.

Composes the HTTP surface from four sub-routers:

  authoring.py  — experience / node / edge / action / rule CRUD
  planner.py    — POST /plan (prompt → PlanningPreset + seed graph)
  play.py       — session lifecycle + resolve_next + catalog + progress
  lifecycle.py  — manifest preview + QA + publish + analytics (batch 8)

Each sub-router is built by a factory so the top-level ``router.py``
can stage them under one prefix and apply the feature-flag / error
translator uniformly. Sub-routers never read the flag themselves —
that gate is enforced one layer up in ``build_router``.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..config import InteractiveConfig
from .authoring import build_authoring_router
from .generator_auto import build_generator_auto_router
from .lifecycle import build_lifecycle_router
from .planner import build_planner_router
from .planner_auto import build_planner_auto_router
from .play import build_play_router
from .playback import build_playback_router
from .persona_live import build_persona_live_router


def build_all(cfg: InteractiveConfig) -> APIRouter:
    """Combine every sub-router under one APIRouter.

    The caller is expected to mount this under the interactive
    prefix (``/v1/interactive``). Each sub-router uses tags so the
    OpenAPI grouping reads naturally in the docs.
    """
    router = APIRouter()
    router.include_router(build_authoring_router(cfg))
    router.include_router(build_planner_router(cfg))
    router.include_router(build_planner_auto_router(cfg))
    router.include_router(build_generator_auto_router(cfg))
    router.include_router(build_play_router(cfg))
    router.include_router(build_lifecycle_router(cfg))
    router.include_router(build_playback_router(cfg))
    router.include_router(build_persona_live_router(cfg))
    return router


__all__ = ["build_all"]
