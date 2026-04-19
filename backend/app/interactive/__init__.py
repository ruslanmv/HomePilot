"""
interactive — additive AI interactive video service.

Parallel to ``studio/``, ``voice_call/``, ``persona_call/``. Lives
entirely in this subpackage; never writes to other modules.

Feature-flagged: ``INTERACTIVE_ENABLED=false`` keeps the whole
surface inert. Enable via ``.env`` once the subsystem is ready to
expose.

Public surface (stable):
    load_config()   → InteractiveConfig
    build_router()  → FastAPI APIRouter (empty router when disabled)

Main mount (additive — single line in ``app/main.py``)::

    from .interactive import build_router as _ix_build, load_config as _ix_load
    _ix_cfg = _ix_load()
    app.include_router(_ix_build(_ix_cfg))

Rollout design: see ``docs/interactive/architecture.md`` (written
alongside later batches). For now, the module exists as scaffolding
so downstream batches can add features without revisiting folder
layout or the mount contract.
"""
from .config import InteractiveConfig, load_config
from .router import build_router

__all__ = ["InteractiveConfig", "load_config", "build_router"]
