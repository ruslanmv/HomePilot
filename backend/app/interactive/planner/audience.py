"""
Audience resolution for the interactive planner.

An ``Audience`` is the viewer profile the planner targets. Today
it's resolved from free-text hints in the prompt plus optional
explicit fields (``role``, ``level``, ``language``). Tomorrow the
same signature will accept CRM / profile lookups.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Audience:
    """Resolved audience profile.

    ``level`` is coarse: 'beginner' / 'intermediate' / 'advanced' —
    the downstream planner maps that to CEFR tiers or XP ranges as
    appropriate.
    """

    role: str = "viewer"         # viewer | learner | customer | trainee | lead | unknown
    level: str = "beginner"      # beginner | intermediate | advanced
    language: str = "en"         # BCP-47
    locale_hint: str = ""        # e.g. 'italy', 'us-west'
    interests: list = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


# Ordered most-specific first so 'advanced' wins over 'first time'
# in prompts like "advanced user trying this for the first time".
_LEVEL_KEYWORDS = {
    "advanced": ("advanced", "expert", "pro", "fluent", "senior"),
    "intermediate": ("some experience", "intermediate", "mid", "practicing"),
    "beginner": ("new", "beginner", "intro", "novice", "first time", "fresh"),
}

_ROLE_KEYWORDS = {
    "learner": ("student", "learner", "studying", "class", "school"),
    "customer": ("customer", "buyer", "shopper", "prospect"),
    "trainee": ("employee", "onboarding", "new hire", "staff"),
    "lead": ("lead", "sales", "demo", "prospect"),
}


def _scan_level(text: str) -> Optional[str]:
    low = text.lower()
    for lvl, kws in _LEVEL_KEYWORDS.items():
        for kw in kws:
            if kw in low:
                return lvl
    return None


def _scan_role(text: str) -> Optional[str]:
    low = text.lower()
    for role, kws in _ROLE_KEYWORDS.items():
        for kw in kws:
            if kw in low:
                return role
    return None


def resolve_audience(
    prompt: str = "",
    *,
    explicit: Optional[Dict[str, Any]] = None,
    default_language: str = "en",
) -> Audience:
    """Best-effort audience resolution.

    Precedence: ``explicit`` fields beat prompt-scanned hints beat
    built-in defaults. Returns a frozen Audience so callers can
    safely share instances across threads.
    """
    ex = dict(explicit or {})
    role = ex.get("role") or _scan_role(prompt) or "viewer"
    level = ex.get("level") or _scan_level(prompt) or "beginner"
    language = ex.get("language") or default_language
    locale_hint = ex.get("locale_hint") or ""
    interests = list(ex.get("interests") or [])
    return Audience(
        role=str(role),
        level=str(level),
        language=str(language),
        locale_hint=str(locale_hint),
        interests=interests,
        raw=ex,
    )
