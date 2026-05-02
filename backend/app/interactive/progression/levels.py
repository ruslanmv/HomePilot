"""
Level / tier description per progression scheme.

``describe_level`` takes a scheme + progress dict and returns a
``LevelDescription`` with (current_level, xp, xp_next, human
label). The frontend reads this to render the progress meter.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class LevelDescription:
    """Human-readable progress snapshot."""

    scheme: str
    level: int
    current_value: float
    next_threshold: float
    label: str
    display: str  # pre-formatted '15 / 35 XP → Level 2'


# ─────────────────────────────────────────────────────────────────
# xp_level — quadratic curve: level N requires 15 * N^1.5 XP total
# ─────────────────────────────────────────────────────────────────

def _xp_threshold(level: int) -> int:
    """XP needed to REACH the start of this level."""
    if level <= 1:
        return 0
    return int(15 * math.pow(level - 1, 1.5))


def level_from_xp(xp: float) -> int:
    lvl = 1
    while xp >= _xp_threshold(lvl + 1):
        lvl += 1
        if lvl >= 50:
            break
    return lvl


def _describe_xp_level(progress: Dict[str, float]) -> LevelDescription:
    xp = float(progress.get("xp", 0.0))
    level = int(progress.get("level") or level_from_xp(xp))
    next_threshold = _xp_threshold(level + 1)
    display = f"Level {level}  {int(xp)} / {next_threshold} XP → Level {level + 1}"
    return LevelDescription(
        scheme="xp_level", level=level, current_value=xp,
        next_threshold=next_threshold, label=f"Level {level}", display=display,
    )


# ─────────────────────────────────────────────────────────────────
# mastery — percentage (0..1) toward a single topic or overall
# ─────────────────────────────────────────────────────────────────

def _describe_mastery(progress: Dict[str, float]) -> LevelDescription:
    pct = float(progress.get("pct", 0.0))
    pct = max(0.0, min(1.0, pct))
    level = int(pct * 100)
    display = f"{level}% mastery"
    return LevelDescription(
        scheme="mastery", level=level, current_value=pct,
        next_threshold=1.0, label=f"{level}%", display=display,
    )


# ─────────────────────────────────────────────────────────────────
# cefr — tier (A1..C2 numeric 1..6)
# ─────────────────────────────────────────────────────────────────

_CEFR_NAMES = ["A1", "A2", "B1", "B2", "C1", "C2"]


def _describe_cefr(progress: Dict[str, float]) -> LevelDescription:
    tier = int(progress.get("tier", 1) or 1)
    tier = max(1, min(6, tier))
    name = _CEFR_NAMES[tier - 1]
    next_name = _CEFR_NAMES[tier] if tier < 6 else "C2"
    display = f"CEFR {name} → {next_name}"
    return LevelDescription(
        scheme="cefr", level=tier, current_value=float(tier),
        next_threshold=float(min(6, tier + 1)), label=name, display=display,
    )


# ─────────────────────────────────────────────────────────────────
# affinity_tier — float 0..1 mapped to named tiers
# ─────────────────────────────────────────────────────────────────

_AFFINITY_TIERS = [
    (0.0, "Stranger"),
    (0.2, "Friendly"),
    (0.5, "Close"),
    (0.75, "Intimate"),
    (0.9, "Devoted"),
]


def _describe_affinity(progress: Dict[str, float]) -> LevelDescription:
    aff = float(progress.get("affinity", 0.5))
    aff = max(0.0, min(1.0, aff))
    label = "Stranger"
    next_threshold = 1.0
    tier_idx = 0
    for i, (thresh, name) in enumerate(_AFFINITY_TIERS):
        if aff >= thresh:
            label = name
            tier_idx = i + 1
            next_threshold = _AFFINITY_TIERS[i + 1][0] if i + 1 < len(_AFFINITY_TIERS) else 1.0
    display = f"{label} ({int(aff * 100)}%)"
    return LevelDescription(
        scheme="affinity_tier", level=tier_idx, current_value=aff,
        next_threshold=next_threshold, label=label, display=display,
    )


# ─────────────────────────────────────────────────────────────────
# certification — discrete states
# ─────────────────────────────────────────────────────────────────

def _describe_certification(progress: Dict[str, float]) -> LevelDescription:
    stage = int(progress.get("stage", 0) or 0)
    stages = ["Not started", "In progress", "Passed", "Certified"]
    stage = max(0, min(len(stages) - 1, stage))
    display = stages[stage]
    return LevelDescription(
        scheme="certification", level=stage, current_value=float(stage),
        next_threshold=float(len(stages) - 1), label=stages[stage], display=display,
    )


# ─────────────────────────────────────────────────────────────────
# Public dispatcher
# ─────────────────────────────────────────────────────────────────

_DISPATCH = {
    "xp_level": _describe_xp_level,
    "mastery": _describe_mastery,
    "cefr": _describe_cefr,
    "affinity_tier": _describe_affinity,
    "certification": _describe_certification,
}


def describe_level(scheme: str, progress: Dict[str, float]) -> LevelDescription:
    fn = _DISPATCH.get(scheme, _describe_xp_level)
    return fn(progress)
