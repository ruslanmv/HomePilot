from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class EvalCase:
    query: str
    expected_keywords: List[str]


@dataclass
class EvalOutcome:
    score: float
    passed: bool


def score_output(text: str, expected_keywords: List[str]) -> float:
    if not expected_keywords:
        return 1.0
    hits = sum(1 for k in expected_keywords if k.lower() in text.lower())
    return hits / len(expected_keywords)


def regression_gate(outcomes: List[EvalOutcome], min_avg: float = 0.75) -> bool:
    if not outcomes:
        return False
    avg = sum(o.score for o in outcomes) / len(outcomes)
    return avg >= min_avg and all(o.passed for o in outcomes)
