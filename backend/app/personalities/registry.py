"""
Personality Registry

Thread-safe, O(1) lookup registry for all personality agents.
Single source of truth — no personality exists outside this registry.

Usage:
    from backend.app.personalities.registry import registry

    agent = registry.get("therapist")
    all_agents = registry.all()
    general_agents = registry.by_category("general")
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .types import PersonalityAgent
from .definitions import ALL_MODULES

logger = logging.getLogger(__name__)


class PersonalityRegistry:
    """Immutable-after-init registry of PersonalityAgent instances."""

    def __init__(self) -> None:
        self._agents: Dict[str, PersonalityAgent] = {}
        self._load()

    def _load(self) -> None:
        """Auto-discover and register every AGENT constant in definitions/."""
        for module in ALL_MODULES:
            agent: Optional[PersonalityAgent] = getattr(module, "AGENT", None)
            if agent is None:
                logger.warning("Module %s has no AGENT constant — skipped", module.__name__)
                continue
            if agent.id in self._agents:
                raise ValueError(
                    f"Duplicate personality id '{agent.id}' "
                    f"in {module.__name__} — ids must be unique"
                )
            self._agents[agent.id] = agent
            logger.debug("Registered personality: %s (%s)", agent.id, agent.label)

        logger.info("Personality registry loaded: %d agents", len(self._agents))

    # -- Public API ----------------------------------------------------------

    def get(self, personality_id: str) -> Optional[PersonalityAgent]:
        """Retrieve a personality by id. Returns None if not found."""
        return self._agents.get(personality_id)

    def get_or_default(self, personality_id: str) -> PersonalityAgent:
        """Retrieve a personality by id, falling back to 'custom'."""
        return self._agents.get(personality_id) or self._agents["custom"]

    def all(self) -> List[PersonalityAgent]:
        """Return all registered agents, sorted by label."""
        return sorted(self._agents.values(), key=lambda a: a.label)

    def by_category(self, category: str) -> List[PersonalityAgent]:
        """Return agents filtered by category."""
        return [a for a in self._agents.values() if a.category == category]

    def ids(self) -> List[str]:
        """Return all registered personality ids."""
        return list(self._agents.keys())

    def __contains__(self, personality_id: str) -> bool:
        return personality_id in self._agents

    def __len__(self) -> int:
        return len(self._agents)


# Module-level singleton — import this
registry = PersonalityRegistry()
