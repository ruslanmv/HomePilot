"""
FastAPI router for the interactive service.

Batch 7/8 — the router composes the authoring + planner + play
sub-routers from the ``routes`` subpackage. When
``InteractiveConfig.enabled=False`` the router is deliberately
empty so the mount line in ``app/main.py`` is safe regardless of
the runtime flag.

Contract with ``app/main.py``: a single call to
``build_router(load_config())`` returns an ``APIRouter`` ready to
include. The router is safe to include unconditionally — when
disabled it simply has no paths.
"""
from __future__ import annotations

from fastapi import APIRouter

from .config import InteractiveConfig
from .errors import InteractiveError
from .routes import build_all


def build_router(cfg: InteractiveConfig) -> APIRouter:
    """Build the interactive service router.

    ``cfg.enabled=False`` → empty router (no paths, no OpenAPI
    surface). ``cfg.enabled=True`` → health ping + authoring +
    planner + play endpoints.
    """
    router = APIRouter(prefix="/v1/interactive", tags=["interactive"])

    if not cfg.enabled:
        # Deliberately empty. Keeps the mount line in ``main.py``
        # idempotent regardless of the runtime flag.
        return router

    @router.get("/health")
    def health() -> dict:
        """Liveness + configuration readout for the interactive service."""
        return {
            "ok": True,
            "service": "interactive",
            "enabled": True,
            "limits": {
                "max_branches": cfg.max_branches,
                "max_depth": cfg.max_depth,
                "max_nodes_per_experience": cfg.max_nodes_per_experience,
            },
            "chassis_guardrails": {
                "require_consent_for_mature": cfg.require_consent_for_mature,
                "enforce_region_block": cfg.enforce_region_block,
                "moderate_mature_narration": cfg.moderate_mature_narration,
                "blocked_regions": len(cfg.region_block),
            },
            "runtime_latency_target_ms": cfg.runtime_latency_target_ms,
        }

    router.include_router(build_all(cfg))
    return router
