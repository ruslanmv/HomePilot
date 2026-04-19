"""
Reward application — updates progression on action execution.

``apply_rewards(action, state, uses_before_this)`` returns a
``RewardOutcome`` with the delta to apply AND the updated progress
snapshot the router should persist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from ..models import Action
from .levels import describe_level, level_from_xp


@dataclass(frozen=True)
class RewardOutcome:
    """Result of applying an action's reward."""

    scheme: str
    deltas: Dict[str, float] = field(default_factory=dict)
    new_progress: Dict[str, float] = field(default_factory=dict)
    level_changed: bool = False
    new_level: int = 0
    xp_award_effective: float = 0.0


def _apply_repeat_penalty(xp: float, penalty: float, uses: int) -> float:
    """Diminishing returns — each use halves the base award by
    ``penalty`` amount. penalty=0 → no diminishing; penalty=1 →
    second use gets 0."""
    if uses <= 0 or penalty <= 0:
        return xp
    factor = max(0.0, 1.0 - penalty * uses)
    return xp * factor


def apply_rewards(
    action: Action,
    current_progress: Dict[str, Dict[str, float]],
    *,
    uses_before_this: int = 0,
) -> RewardOutcome:
    """Compute the reward delta + new progress snapshot.

    Does NOT write to DB — caller persists via state.upsert_progress.
    """
    scheme = action.required_scheme or "xp_level"
    current = dict(current_progress.get(scheme, {}) or {})

    if scheme == "xp_level":
        base_xp = float(action.xp_award or 0)
        effective = _apply_repeat_penalty(base_xp, float(action.repeat_penalty or 0), uses_before_this)
        old_xp = float(current.get("xp", 0))
        new_xp = old_xp + effective
        old_level = int(current.get("level") or level_from_xp(old_xp))
        new_level = level_from_xp(new_xp)
        new_progress = {"xp": new_xp, "level": float(new_level)}
        return RewardOutcome(
            scheme=scheme,
            deltas={"xp": effective, "level": float(new_level - old_level)},
            new_progress=new_progress,
            level_changed=new_level != old_level,
            new_level=new_level,
            xp_award_effective=effective,
        )

    if scheme == "mastery":
        # xp_award is treated as a mastery delta in 0..100 percent points.
        base = float(action.xp_award or 0) / 100.0
        effective = _apply_repeat_penalty(base, float(action.repeat_penalty or 0), uses_before_this)
        old_pct = float(current.get("pct", 0.0))
        new_pct = max(0.0, min(1.0, old_pct + effective))
        return RewardOutcome(
            scheme=scheme, deltas={"pct": effective},
            new_progress={"pct": new_pct},
        )

    if scheme == "affinity_tier":
        # xp_award is treated as 0..100 -> 0..1 delta.
        base = float(action.xp_award or 0) / 100.0
        effective = _apply_repeat_penalty(base, float(action.repeat_penalty or 0), uses_before_this)
        old = float(current.get("affinity", 0.5))
        new_val = max(0.0, min(1.0, old + effective))
        return RewardOutcome(
            scheme=scheme, deltas={"affinity": effective},
            new_progress={"affinity": new_val},
        )

    if scheme == "cefr":
        # Explicit tier bumps only — xp_award encodes tier delta.
        bump = int(action.xp_award or 0)
        old_tier = int(current.get("tier", 1) or 1)
        new_tier = max(1, min(6, old_tier + bump))
        return RewardOutcome(
            scheme=scheme, deltas={"tier": float(new_tier - old_tier)},
            new_progress={"tier": float(new_tier)},
        )

    if scheme == "certification":
        bump = int(action.xp_award or 0)
        old_stage = int(current.get("stage", 0) or 0)
        new_stage = max(0, min(3, old_stage + bump))
        return RewardOutcome(
            scheme=scheme, deltas={"stage": float(new_stage - old_stage)},
            new_progress={"stage": float(new_stage)},
        )

    # Unknown scheme — no-op.
    return RewardOutcome(scheme=scheme, deltas={}, new_progress=dict(current))
