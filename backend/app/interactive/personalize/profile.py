"""
Read-only view of the viewer's profile from HomePilot's user
tables. No writes — this module only reads.

Returns a ``PersonalizationProfile`` with the fields the rule
evaluator needs: role / level / language / country / tags /
prior-interaction signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PersonalizationProfile:
    """Snapshot of viewer data used for rule evaluation."""

    user_id: str = ""
    role: str = "viewer"
    level: str = "beginner"
    language: str = "en"
    country: str = ""
    tags: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


def resolve_profile(
    *, user_id: str = "", session_personalization: Optional[Dict[str, Any]] = None,
) -> PersonalizationProfile:
    """Resolve a personalization profile for the viewer.

    Preference order: session-scoped personalization dict beats
    user-table lookup beats defaults. No user lookup happens if
    ``user_id`` is empty (anonymous viewer).
    """
    base: Dict[str, Any] = {}
    if user_id:
        try:
            from ...users import list_users
            for u in list_users():
                if u.get("id") == user_id:
                    base = dict(u)
                    break
        except Exception:
            base = {}
    if session_personalization:
        base.update(session_personalization)

    return PersonalizationProfile(
        user_id=user_id,
        role=str(base.get("role") or "viewer"),
        level=str(base.get("level") or "beginner"),
        language=str(base.get("language") or "en"),
        country=str(base.get("country") or ""),
        tags=list(base.get("tags") or []),
        raw=base,
    )
