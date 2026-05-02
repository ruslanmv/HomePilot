"""
Tone specification + lightweight text transformer.

ToneSpec is a small dataclass of knobs (formality, warmth,
pace_words_per_sec) — used to parameterize the generator and
optionally to post-process generated text. Phase 1 implements
``apply_tone`` as a simple template-style substitution so we can
unit-test tone sensitivity without needing an LLM in the loop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ToneSpec:
    """Numeric knobs for generated text."""

    # 0..1: 0 = casual, 1 = formal
    formality: float = 0.5
    # 0..1: 0 = neutral, 1 = warm/friendly
    warmth: float = 0.5
    # Words per second — the assembly layer uses this to estimate
    # node duration from narration length.
    pace_wps: float = 2.5
    # BCP-47 locale — passed through for LLM phase (no-op today).
    locale: str = "en"


# Mode → default tone. Matches the built-in policy profiles.
_DEFAULT_TONES: Dict[str, ToneSpec] = {
    "sfw_general": ToneSpec(formality=0.5, warmth=0.6, pace_wps=2.5),
    "sfw_education": ToneSpec(formality=0.6, warmth=0.5, pace_wps=2.2),
    "language_learning": ToneSpec(formality=0.5, warmth=0.7, pace_wps=1.8),
    "enterprise_training": ToneSpec(formality=0.8, warmth=0.4, pace_wps=2.3),
    "social_romantic": ToneSpec(formality=0.3, warmth=0.8, pace_wps=2.5),
    "mature_gated": ToneSpec(formality=0.2, warmth=0.9, pace_wps=2.6),
}


def default_tone_for_mode(mode: str) -> ToneSpec:
    return _DEFAULT_TONES.get(mode, ToneSpec())


_CASUAL_SUBS = [
    (re.compile(r"\bdo not\b", re.I), "don't"),
    (re.compile(r"\bcannot\b", re.I), "can't"),
    (re.compile(r"\bwill not\b", re.I), "won't"),
    (re.compile(r"\bit is\b", re.I), "it's"),
    (re.compile(r"\byou are\b", re.I), "you're"),
]
_FORMAL_SUBS = [
    (re.compile(r"\bdon't\b", re.I), "do not"),
    (re.compile(r"\bcan't\b", re.I), "cannot"),
    (re.compile(r"\bwon't\b", re.I), "will not"),
    (re.compile(r"\bit's\b", re.I), "it is"),
    (re.compile(r"\byou're\b", re.I), "you are"),
]


def apply_tone(text: str, tone: ToneSpec) -> str:
    """Light-touch tone adjustment.

    Low formality → prefers contractions ("don't").
    High formality → expands contractions ("do not").
    Warmth > 0.75 prepends a friendly lead-in for short replies.
    """
    out = text or ""
    if tone.formality >= 0.7:
        for pat, sub in _FORMAL_SUBS:
            out = pat.sub(sub, out)
    elif tone.formality <= 0.35:
        for pat, sub in _CASUAL_SUBS:
            out = pat.sub(sub, out)
    return out


def estimate_duration_sec(text: str, tone: ToneSpec) -> int:
    """Rough spoken-duration estimate. Floors at 3s, ceils at 20s."""
    words = max(1, len((text or "").split()))
    dur = words / max(0.5, tone.pace_wps)
    return max(3, min(20, int(round(dur))))
