"""
Small enum-like constants + Transition dataclass shared by the
interaction engine, personalization evaluator, and router.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


class TransitionKind:
    """Why the runtime moved between nodes."""
    CHOICE = "choice"
    HOTSPOT = "hotspot"
    TIMER = "timer"
    INTENT = "intent"
    AUTO = "auto"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class Transition:
    """Result of a single viewer action's routing decision."""

    to_node_id: str
    kind: str = TransitionKind.AUTO
    label: str = ""
    payload: Dict[str, Any] = None  # type: ignore[assignment]
    rule_id: Optional[str] = None   # non-null if a personalization rule routed us
