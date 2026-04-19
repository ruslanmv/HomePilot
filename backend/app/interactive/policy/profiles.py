"""
Policy profiles — declarative rules per experience mode.

Stored as YAML under ``backend/app/interactive/policy/profiles/*.yaml``
so adding a new mode (e.g. "kids_safety", "medical_training") is
a data change, not a code change.

Each profile declares:
  - id                      unique profile id (matches file stem)
  - display_name            human label for admin UIs
  - applicable_modes        list of ExperienceMode values this covers
  - allowed_intents         whitelist; empty = allow-all
  - blocked_intents         blacklist; checked first
  - soft_refuse_template    copy to return when intent is flagged
                            as needing redirection (not outright blocked)
  - progression_schemes     which ``ix_session_progress`` schemes apply
  - default_language        BCP-47 code
  - mature_consent_required forces chassis consent check
  - max_risk_level          0..3; planner/script generator honors this

Unknown fields are preserved (forward-compat).

Loading is cached in-process — profile files are read once unless
``reload_profiles()`` is called (used by tests).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover — graceful degradation
    _YAML_AVAILABLE = False


_PROFILES_DIR = Path(__file__).resolve().parent / "profiles"


@dataclass(frozen=True)
class PolicyProfile:
    """A resolved policy profile — immutable snapshot."""

    id: str
    display_name: str = ""
    applicable_modes: List[str] = field(default_factory=list)
    allowed_intents: List[str] = field(default_factory=list)
    blocked_intents: List[str] = field(default_factory=list)
    soft_refuse_template: str = ""
    progression_schemes: List[str] = field(default_factory=list)
    default_language: str = "en"
    mature_consent_required: bool = False
    max_risk_level: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    def allows_intent(self, intent_code: str) -> bool:
        """Whitelist check. Empty allowed list = allow-all."""
        if intent_code in self.blocked_intents:
            return False
        if not self.allowed_intents:
            return True
        return intent_code in self.allowed_intents

    def blocks_intent(self, intent_code: str) -> bool:
        return intent_code in self.blocked_intents


# Built-in fallback profiles — used when the YAML directory is
# missing (e.g. in a minimal container image) so the service still
# has a sensible default for each experience mode.
_BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "sfw_general": {
        "id": "sfw_general",
        "display_name": "General SFW",
        "applicable_modes": ["sfw_general"],
        "blocked_intents": ["explicit_request", "violence_request"],
        "soft_refuse_template": "Let's keep it friendly — tell me a bit more?",
        "progression_schemes": ["xp_level"],
        "default_language": "en",
        "mature_consent_required": False,
        "max_risk_level": 0,
    },
    "sfw_education": {
        "id": "sfw_education",
        "display_name": "Education / Teaching",
        "applicable_modes": ["sfw_education", "enterprise_training"],
        "allowed_intents": [
            "greeting", "question_about_topic", "answer_attempt",
            "request_hint", "request_example", "skip_topic",
        ],
        "blocked_intents": ["explicit_request", "violence_request", "off_topic_flirt"],
        "soft_refuse_template": "Let's stay on topic — what would you like to learn next?",
        "progression_schemes": ["mastery"],
        "default_language": "en",
        "mature_consent_required": False,
        "max_risk_level": 0,
    },
    "language_learning": {
        "id": "language_learning",
        "display_name": "Language Learning",
        "applicable_modes": ["language_learning"],
        "allowed_intents": [
            "greeting", "question_about_topic", "answer_attempt",
            "request_hint", "request_translation", "switch_language",
            "pronounce_request", "vocabulary_lookup",
        ],
        "blocked_intents": ["explicit_request", "violence_request"],
        "soft_refuse_template": "Let's practice — try saying that in the target language?",
        "progression_schemes": ["cefr", "mastery"],
        "default_language": "en",
        "mature_consent_required": False,
        "max_risk_level": 0,
    },
    "enterprise_training": {
        "id": "enterprise_training",
        "display_name": "Enterprise Training",
        "applicable_modes": ["enterprise_training"],
        "allowed_intents": [
            "greeting", "question_about_topic", "answer_attempt",
            "request_hint", "quiz_response", "request_example",
        ],
        "blocked_intents": ["explicit_request", "violence_request"],
        "soft_refuse_template": "Let's continue the training — ready for the next scenario?",
        "progression_schemes": ["mastery", "certification"],
        "default_language": "en",
        "mature_consent_required": False,
        "max_risk_level": 0,
    },
    "social_romantic": {
        "id": "social_romantic",
        "display_name": "Social / Romantic",
        "applicable_modes": ["social_romantic"],
        "allowed_intents": [
            "greeting", "flirt", "compliment", "ask_personal",
            "request_photo_safe", "tease",
        ],
        "blocked_intents": ["explicit_request", "minor_reference", "violence_request"],
        "soft_refuse_template": "Slow down there — let's get to know each other first.",
        "progression_schemes": ["xp_level", "affinity_tier"],
        "default_language": "en",
        "mature_consent_required": False,
        "max_risk_level": 1,
    },
    "mature_gated": {
        "id": "mature_gated",
        "display_name": "Mature (Gated)",
        "applicable_modes": ["mature_gated"],
        "allowed_intents": [
            "greeting", "flirt", "compliment", "tease", "explicit_request",
            "request_action", "ask_personal",
        ],
        "blocked_intents": ["minor_reference", "violence_request", "non_consent_scenario"],
        "soft_refuse_template": "Slow down, cutie — let's build up to that.",
        "progression_schemes": ["xp_level", "affinity_tier"],
        "default_language": "en",
        "mature_consent_required": True,
        "max_risk_level": 3,
    },
}


# In-process cache. Cleared by ``reload_profiles`` in tests.
_cache: Dict[str, PolicyProfile] = {}
_cache_initialized: bool = False


def _profile_from_dict(d: Dict[str, Any]) -> PolicyProfile:
    return PolicyProfile(
        id=str(d.get("id", "")),
        display_name=str(d.get("display_name", "")),
        applicable_modes=list(d.get("applicable_modes") or []),
        allowed_intents=list(d.get("allowed_intents") or []),
        blocked_intents=list(d.get("blocked_intents") or []),
        soft_refuse_template=str(d.get("soft_refuse_template", "")),
        progression_schemes=list(d.get("progression_schemes") or []),
        default_language=str(d.get("default_language", "en")),
        mature_consent_required=bool(d.get("mature_consent_required", False)),
        max_risk_level=int(d.get("max_risk_level", 0) or 0),
        raw=dict(d),
    )


def _initialize() -> None:
    """Populate the cache on first call. Built-ins seed defaults;
    YAML files overlay / replace by id."""
    global _cache_initialized
    if _cache_initialized:
        return
    # Built-ins first — guaranteed defaults.
    for pid, spec in _BUILTIN_PROFILES.items():
        _cache[pid] = _profile_from_dict(spec)
    # YAML overlays.
    if _YAML_AVAILABLE and _PROFILES_DIR.is_dir():
        for path in sorted(_PROFILES_DIR.glob("*.yaml")):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                if not isinstance(data, dict) or not data.get("id"):
                    continue
                _cache[str(data["id"])] = _profile_from_dict(data)
            except Exception:
                # Bad YAML shouldn't kill the service — fall back to built-ins.
                continue
    _cache_initialized = True


def load_profile(profile_id: str) -> Optional[PolicyProfile]:
    """Resolve a profile by id. Returns None if unknown."""
    _initialize()
    return _cache.get(profile_id)


def list_profiles() -> List[PolicyProfile]:
    """All registered profiles, including built-ins."""
    _initialize()
    return list(_cache.values())


def reload_profiles() -> None:
    """Clear the cache — re-read built-ins + YAML on next access.
    Used by tests; not part of the public runtime surface."""
    global _cache_initialized
    _cache.clear()
    _cache_initialized = False
