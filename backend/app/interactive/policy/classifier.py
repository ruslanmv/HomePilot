"""
Intent classifier — maps free-text viewer input to an ``intent_code``.

Phase 1 (this batch) is a lightweight keyword / regex classifier.
Good enough for deterministic tests and the bootstrap demo. Phase
2 (later sprints) swaps in an LLM classifier behind the same
``classify_intent`` function signature — call sites never change.

Design rule: this module never decides policy. It only LABELS
input. The decision engine (``decision.py``) does the allow /
block / soft-refuse call using the label plus the active profile.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Pattern, Tuple


@dataclass(frozen=True)
class IntentMatch:
    """Result of classifying a single input."""

    intent_code: str
    confidence: float     # 0..1, heuristic
    matched_pattern: str  # debug aid — which rule fired


# Pattern tuples: (intent_code, regex). First match wins. Order
# matters — more specific patterns first, most general last.
#
# Intent codes are shared with ``ix_intent_map`` and the policy
# profiles' ``allowed_intents`` / ``blocked_intents`` fields.
_RULES: List[Tuple[str, Pattern[str]]] = [
    # --- Safety / hard blocks (flagged as-is; policy decides) ---
    ("minor_reference", re.compile(r"\b(child|minor|under\s*1[0-7]|kid)\b", re.I)),
    ("violence_request", re.compile(r"\b(hurt|kill|punch|stab|attack)\b", re.I)),
    ("non_consent_scenario", re.compile(r"\b(force|rape|unwilling)\b", re.I)),

    # --- Explicit (mature-only) ---
    ("explicit_request", re.compile(
        r"\b(pussy|dick|cock|boob|nude|naked|undress|strip)\b", re.I
    )),

    # --- Flirty / social-romantic ---
    ("flirt", re.compile(r"\b(baby|babe|cutie|honey|gorgeous|beautiful)\b", re.I)),
    ("tease", re.compile(r"\b(tease|lick lips|wink|smirk)\b", re.I)),
    ("compliment", re.compile(r"\b(you('?re| are) (cute|pretty|hot|sweet|amazing))\b", re.I)),

    # --- Education / language ---
    ("request_translation", re.compile(r"\b(how do you say|what does .* mean|translate)\b", re.I)),
    ("pronounce_request", re.compile(r"\b(how do I pronounce|say that again|pronunciation)\b", re.I)),
    ("request_hint", re.compile(r"\b(hint|clue|help me with|i('?m| am) stuck)\b", re.I)),
    ("skip_topic", re.compile(r"\b(skip|next topic|move on)\b", re.I)),
    ("answer_attempt", re.compile(
        r"\b(the answer is|i think it'?s|my guess|it'?s)\b", re.I
    )),
    ("quiz_response", re.compile(r"\b(option\s+[abcd]|answer\s+[abcd])\b", re.I)),
    ("request_example", re.compile(r"\b(give me an example|show me|for instance)\b", re.I)),
    ("vocabulary_lookup", re.compile(r"\b(define|meaning of|what is a )\b", re.I)),

    # --- General social ---
    ("ask_personal", re.compile(r"\b(who are you|what('?s| is) your name|tell me about yourself)\b", re.I)),
    ("request_photo_safe", re.compile(r"\b(show me (your|a) (face|smile|outfit))\b", re.I)),

    # --- Greetings / low-risk general fallback ---
    ("greeting", re.compile(r"\b(hi|hello|hey|morning|evening|yo)\b", re.I)),
    ("question_about_topic", re.compile(r"\?\s*$")),
]


def classify_intent(text: str) -> IntentMatch:
    """Classify one user utterance. Always returns an IntentMatch —
    unknown input maps to ``intent_code='unknown'`` with 0.0
    confidence. The decision engine then decides what to do with
    ``unknown`` (typically route to a default node).
    """
    if not text or not text.strip():
        return IntentMatch(intent_code="empty", confidence=0.0, matched_pattern="")
    for code, pattern in _RULES:
        if pattern.search(text):
            return IntentMatch(
                intent_code=code,
                confidence=0.7,  # regex rules are deliberately mid-confidence
                matched_pattern=pattern.pattern,
            )
    return IntentMatch(intent_code="unknown", confidence=0.0, matched_pattern="")
