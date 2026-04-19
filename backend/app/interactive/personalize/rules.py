"""
Personalization rule DSL.

Rules are persisted in ``ix_personalization_rules`` with two JSON
fields:

  condition  = a dict describing the match criteria
  action     = a dict describing what the rule does

Supported condition keys (phase 1):
  role            str     viewer role must equal
  level           str     viewer level must equal
  language        str     viewer language must equal
  country         str     viewer country must equal
  has_tag         str     viewer tags must contain
  mood            str     character_mood must equal
  min_affinity    float   character affinity_score >= value
  max_affinity    float   character affinity_score <= value
  metric          dict    { scheme, key, min?, max? } — progress metric in range

Supported action keys (phase 1):
  route_to_node      str   override the next_node_id with this
  prefer_tone        str   override the tone for this turn
  bump_affinity      float delta to apply to affinity_score

A rule is 'applicable' if ALL conditions pass. The evaluator picks
the highest-priority applicable rule (lowest priority wins ties).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_ALLOWED_CONDITION_KEYS = {
    "role", "level", "language", "country", "has_tag",
    "mood", "min_affinity", "max_affinity", "metric",
}
_ALLOWED_ACTION_KEYS = {
    "route_to_node", "prefer_tone", "bump_affinity",
}


@dataclass(frozen=True)
class RuleCondition:
    """Resolved condition object."""

    raw: Dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)


@dataclass(frozen=True)
class Rule:
    """A personalization rule, ready for the evaluator."""

    id: str
    name: str
    condition: RuleCondition
    action: Dict[str, Any]
    priority: int = 100
    enabled: bool = True


def validate_rule(condition: Dict[str, Any], action: Dict[str, Any]) -> List[str]:
    """Return a list of problems (empty list = valid)."""
    problems: List[str] = []
    for k in condition:
        if k not in _ALLOWED_CONDITION_KEYS:
            problems.append(f"unknown condition key: {k}")
    for k in action:
        if k not in _ALLOWED_ACTION_KEYS:
            problems.append(f"unknown action key: {k}")
    metric = condition.get("metric") if isinstance(condition.get("metric"), dict) else None
    if metric is not None:
        if not metric.get("scheme") or not metric.get("key"):
            problems.append("metric condition requires 'scheme' and 'key'")
    if "bump_affinity" in action:
        try:
            float(action["bump_affinity"])
        except (TypeError, ValueError):
            problems.append("bump_affinity must be numeric")
    return problems
