"""
Rule evaluator — picks the winning rule for a given viewer turn.

Inputs: a list of ``Rule``s + a ``PersonalizationProfile`` + the
runtime state (mood, affinity, metrics). Output: a ``RouterHint``
describing what the rule wants the router to do.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..interaction.state import RuntimeState
from .profile import PersonalizationProfile
from .rules import Rule


@dataclass(frozen=True)
class RouterHint:
    """What the personalization layer is asking the router to do."""

    route_to_node: Optional[str] = None
    prefer_tone: Optional[str] = None
    bump_affinity: float = 0.0
    matched_rule_id: Optional[str] = None


_NO_HINT = RouterHint()


def _condition_matches(
    rule: Rule, profile: PersonalizationProfile, state: RuntimeState,
) -> bool:
    c = rule.condition
    if c.get("role") and profile.role != c.get("role"):
        return False
    if c.get("level") and profile.level != c.get("level"):
        return False
    if c.get("language") and profile.language != c.get("language"):
        return False
    if c.get("country") and profile.country.upper() != str(c.get("country")).upper():
        return False
    if c.get("has_tag") and c.get("has_tag") not in profile.tags:
        return False
    if c.get("mood") and state.character_mood != c.get("mood"):
        return False
    if c.get("min_affinity") is not None:
        try:
            if state.affinity_score < float(c.get("min_affinity")):
                return False
        except (TypeError, ValueError):
            return False
    if c.get("max_affinity") is not None:
        try:
            if state.affinity_score > float(c.get("max_affinity")):
                return False
        except (TypeError, ValueError):
            return False
    metric = c.get("metric")
    if isinstance(metric, dict):
        scheme = str(metric.get("scheme") or "")
        key = str(metric.get("key") or "")
        val = state.progress.get(scheme, {}).get(key)
        if val is None:
            return False
        if "min" in metric:
            try:
                if val < float(metric["min"]):
                    return False
            except (TypeError, ValueError):
                return False
        if "max" in metric:
            try:
                if val > float(metric["max"]):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def evaluate(
    rules: List[Rule], profile: PersonalizationProfile, state: RuntimeState,
) -> RouterHint:
    """Pick the best-matching rule. Lower priority wins ties.

    ``rules`` should already be filtered to ``enabled=True``. The
    evaluator does NOT read from storage — caller assembles the
    list.
    """
    if not rules:
        return _NO_HINT
    # Sort by priority ASC (lower = higher priority), then by id for stability.
    applicable: List[Rule] = []
    for r in rules:
        if not r.enabled:
            continue
        if _condition_matches(r, profile, state):
            applicable.append(r)
    if not applicable:
        return _NO_HINT
    applicable.sort(key=lambda r: (r.priority, r.id))
    winner = applicable[0]
    a = winner.action
    return RouterHint(
        route_to_node=a.get("route_to_node"),
        prefer_tone=a.get("prefer_tone"),
        bump_affinity=float(a.get("bump_affinity") or 0.0),
        matched_rule_id=winner.id,
    )
