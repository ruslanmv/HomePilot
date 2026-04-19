"""
FastAPI router for the interactive service.

Batch 1/8 — scaffolding only. The router exists but contributes
zero routes when ``InteractiveConfig.enabled`` is False. When
enabled, it exposes a health ping so operators can verify the
service mounted correctly. All authoring / runtime endpoints land
in later batches.

Contract with ``app/main.py``: a single call to
``build_router(load_config())`` returns an ``APIRouter`` ready to
include. The router is safe to include unconditionally — when
disabled it simply has no paths.
"""
from __future__ import annotations

from fastapi import APIRouter

from .config import InteractiveConfig


def build_router(cfg: InteractiveConfig) -> APIRouter:
    """Build the interactive service router.

    ``cfg.enabled=False`` → empty router (no paths, no OpenAPI
    surface). ``cfg.enabled=True`` → scaffold + health ping in
    this batch; real endpoints get layered in by batches 2-8.
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

    return router
