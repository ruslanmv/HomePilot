"""
LTM V1 Policy — per-category TTL, caps, and pinning rules.

Enterprise-grade retention policy for secretary/finance/long-running
personas. Works with the existing V1 ltm.py module (additive).

Design:
  - TTL_MAP: per-category time-to-live (seconds). 0 = "never expire".
  - CAP_MAP: per-category maximum entry count. 0 = "unlimited".
  - TOTAL_CAP: absolute hard cap across all categories for a persona.
  - is_duplicate(): value-level near-duplicate detection (cheap, no LLM).

These policies are consumed by ltm_v1_maintenance.py for scheduled
cleanup, and by ltm.py for inline dedup on upsert.

Golden rule: ADDITIVE ONLY — zero changes to existing ltm.py schemas.
"""
from __future__ import annotations

import re
from typing import Dict

# ---------------------------------------------------------------------------
# TTL per category (seconds). 0 means "never expire".
# ---------------------------------------------------------------------------
TTL_MAP: Dict[str, int] = {
    "fact":            0,               # Core facts persist forever
    "preference":      0,               # Preferences persist forever
    "important_date":  0,               # Dates persist forever
    "emotion_pattern": 90 * 24 * 3600,  # 90 days — moods drift
    "milestone":       0,               # Milestones persist forever
    "boundary":        0,               # Boundaries persist forever
    "summary":         30 * 24 * 3600,  # 30 days — auto-refreshed by jobs
    "working":         24 * 3600,       # 24 hours — V2 working traces (if any remain in V1 mode)
}

# Fallback TTL for categories not in the map
DEFAULT_TTL: int = 180 * 24 * 3600  # 180 days

# ---------------------------------------------------------------------------
# Per-category cap (max entries). 0 means "no per-category limit".
# ---------------------------------------------------------------------------
CAP_MAP: Dict[str, int] = {
    "fact":            50,
    "preference":      40,
    "important_date":  20,
    "emotion_pattern": 15,
    "milestone":       15,
    "boundary":        10,
    "summary":         5,
    "working":         25,
}

DEFAULT_CAP: int = 30

# ---------------------------------------------------------------------------
# Total cap — absolute maximum entries per persona (across all categories)
# ---------------------------------------------------------------------------
TOTAL_CAP: int = 200  # Matches ltm.py MAX_ENTRIES_PER_PERSONA

# ---------------------------------------------------------------------------
# Near-duplicate detection (cheap, rule-based)
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip non-alpha tokens < 3 chars."""
    t = (text or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def is_duplicate(existing_value: str, new_value: str, threshold: float = 0.85) -> bool:
    """
    Return True if new_value is a near-duplicate of existing_value.

    Uses Jaccard similarity on 3+ char tokens. Cheap and LLM-free.
    Threshold 0.85 = very high overlap required (conservative).
    """
    a = set(re.findall(r"[a-z0-9]{3,}", _normalize(existing_value)))
    b = set(re.findall(r"[a-z0-9]{3,}", _normalize(new_value)))
    if not a or not b:
        return False
    intersection = len(a & b)
    union = len(a | b)
    if union == 0:
        return False
    jaccard = intersection / union
    return jaccard >= threshold


def get_ttl(category: str) -> int:
    """Return TTL in seconds for a given category."""
    return TTL_MAP.get(category, DEFAULT_TTL)


def get_cap(category: str) -> int:
    """Return per-category cap for a given category."""
    return CAP_MAP.get(category, DEFAULT_CAP)
