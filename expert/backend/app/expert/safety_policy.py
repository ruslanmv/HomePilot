from __future__ import annotations

from dataclasses import dataclass
from typing import List


_BLOCKED_PATTERNS = [
    "how to build a bomb",
    "weaponize",
    "bypass biosafety",
]


@dataclass
class SafetyDecision:
    allowed: bool
    reasons: List[str]


def evaluate_prompt(prompt: str, profile: str = "strict-research") -> SafetyDecision:
    q = prompt.lower()
    reasons: List[str] = []

    if profile == "off":
        return SafetyDecision(True, reasons)

    for p in _BLOCKED_PATTERNS:
        if p in q:
            reasons.append(f"Blocked pattern matched: {p}")

    return SafetyDecision(allowed=not reasons, reasons=reasons)
