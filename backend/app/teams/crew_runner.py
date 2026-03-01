# backend/app/teams/crew_runner.py
"""
Engine switch for Teams crew workflow.

Routes to **real CrewAI** when ``TEAMS_CREWAI_ENABLED=true`` and the
``crewai`` package is installed, otherwise falls back to the legacy
custom crew engine.  This keeps the product stable regardless of
deployment config.

Usage in routes.py / play_mode.py::

    from .crew_runner import run_crew_turn
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..config import TEAMS_CREWAI_ENABLED

logger = logging.getLogger("homepilot.teams.crew_runner")


async def run_crew_turn(
    *,
    room_id: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    max_concurrent: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute one workflow stage step.

    Prefer real CrewAI when enabled + installed; fall back to legacy
    custom engine otherwise.
    """
    if TEAMS_CREWAI_ENABLED:
        try:
            from .crewai_engine import run_crew_turn as _crewai_turn

            logger.debug("[RUNNER] Dispatching to CrewAI engine")
            return await _crewai_turn(
                room_id=room_id,
                provider=provider,
                model=model,
                base_url=base_url,
                max_concurrent=max_concurrent,
            )
        except ImportError as exc:
            logger.warning(
                "TEAMS_CREWAI_ENABLED=true but crewai is not installed (%s). "
                "Falling back to legacy crew engine.",
                exc,
            )

    # Legacy custom crew engine (always available, no extra deps)
    from .crew_engine import run_crew_turn as _legacy_turn

    logger.debug("[RUNNER] Dispatching to legacy crew engine")
    return await _legacy_turn(
        room_id=room_id,
        provider=provider,
        model=model,
        base_url=base_url,
        max_concurrent=max_concurrent,
    )
