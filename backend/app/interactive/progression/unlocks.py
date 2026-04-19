"""
Action unlock check.

``is_action_unlocked`` evaluates whether an action's
``required_level`` (in the action's ``required_scheme`` /
``required_metric_key``) is satisfied by the current session's
progress snapshot.

Returns a tuple ``(unlocked, reason)`` — the reason is either
empty (when unlocked) or a short code like ``level_gate`` that the
catalog renderer can display next to the lock icon.
"""
from __future__ import annotations

from typing import Dict, Tuple

from ..models import Action


def is_action_unlocked(
    action: Action, progress: Dict[str, Dict[str, float]],
) -> Tuple[bool, str]:
    scheme = action.required_scheme or "xp_level"
    metric_key = action.required_metric_key or "level"
    required = float(action.required_level or 1)

    if scheme == "xp_level":
        # 'level' key → compare to level directly; otherwise assume xp.
        current_val = float(progress.get(scheme, {}).get(metric_key, 0))
        if metric_key == "level":
            # New viewers are level 1 implicitly even before any
            # progress row exists — otherwise every action with
            # required_level=1 would appear locked on turn 0.
            effective = max(1, int(current_val))
            ok = effective >= int(required)
        else:
            # Treat required_level as XP threshold.
            ok = current_val >= required
        return (ok, "" if ok else "level_gate")

    if scheme == "mastery":
        current_val = float(progress.get(scheme, {}).get(metric_key or "pct", 0))
        ok = current_val >= (required / 100.0)  # required_level treated as 0..100 pct
        return (ok, "" if ok else "mastery_gate")

    if scheme == "cefr":
        tier = int(progress.get(scheme, {}).get(metric_key or "tier", 1) or 1)
        ok = tier >= int(required)
        return (ok, "" if ok else "cefr_gate")

    if scheme == "affinity_tier":
        aff = float(progress.get(scheme, {}).get(metric_key or "affinity", 0))
        ok = aff >= (required / 100.0)  # required_level as 0..100
        return (ok, "" if ok else "affinity_gate")

    if scheme == "certification":
        stage = int(progress.get(scheme, {}).get(metric_key or "stage", 0) or 0)
        ok = stage >= int(required)
        return (ok, "" if ok else "certification_gate")

    # Unknown scheme — fail safe (lock).
    return (False, "unknown_scheme")
