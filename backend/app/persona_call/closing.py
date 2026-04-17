"""
Two-phase closing handshake — the one place we *enforce* instead of
advise.

Why enforced: LLMs reliably collapse Schegloff's 3–6-turn closing
into "Goodbye!" the moment they hear an "ok". Humans don't. The
handshake is a short, mandatory state transition that keeps the
persona from hanging up before the caller does.

Flow (per Schegloff & Sacks 1973, *Opening up Closings*):

    user says "ok" / "alright" / "I should go" / "thanks, that's all"
              │
              ▼
    state.phase := 'pre_closing'
    pre_closing_trigger := <the user's token>
              │
              ▼
    persona reply directive FORCES a pre-closing token reply:
        - one short softener from facets.pre_closing_tokens
        - no "bye", no "goodbye", no "take care" yet
              │
              ▼  (next user turn)
    if user says "bye" / "talk later" / "see ya":
        persona reply directive FORCES a mirrored two-part close:
            <softener>, <terminal>
        e.g. "take care, bye"
    else:
        state stays in 'pre_closing'; persona speaks a normal turn.
"""
from __future__ import annotations

import re
from typing import Optional

from .facets import VoiceFacets


# User utterances that start a closing (pre-closing trigger).
# Kept tight to avoid false positives mid-conversation.
_PRE_CLOSE_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^\s*(ok|okay|alright|ok\s+then)\s*[.!?]?\s*$",
        r"\b(i should (go|run|get back)|gotta (go|run)|need to go)\b",
        r"\b(thanks[, ]+(that'?s|that is)\s+(all|it))\b",
        r"\b(talk (to you )?(later|soon)|call (you )?(later|back))\b",
    ]
]

# Pure terminal — "bye"-family tokens that complete the exchange.
_TERMINAL_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^\s*(bye|good[\- ]?bye|later|see ya|see you|ciao)\s*[.!?]?\s*$",
        r"\b(bye bye|byebye)\b",
    ]
]


def is_pre_closing_trigger(user_text: str) -> bool:
    """True iff the user just began a closing sequence."""
    if not user_text:
        return False
    return any(p.search(user_text) for p in _PRE_CLOSE_PATTERNS)


def is_terminal(user_text: str) -> bool:
    """True iff the user said goodbye — the second half of the
    two-phase close. Matched INDEPENDENTLY of the pre-close trigger
    so the state machine can skip straight to terminal if the user
    blurts out "bye!" without a prior "ok"."""
    if not user_text:
        return False
    return any(p.search(user_text) for p in _TERMINAL_PATTERNS)


# ── directive fragments for each phase ───────────────────────────────

def pre_closing_directive(facets: VoiceFacets, trigger: Optional[str]) -> str:
    """Directive the composer injects when we're in 'pre_closing'
    but the user hasn't said 'bye' yet."""
    pool = ", ".join(facets.pre_closing_tokens[:4])
    trig = f'"{trigger}"' if trigger else "a closing cue"
    return (
        f"The caller offered a pre-closing ({trig}). "
        "Reciprocate with ONE matching soft pre-closing token — "
        f"something from: {pool}. Do NOT say 'goodbye' yet. "
        "Keep the turn to ≤ 7 words and leave the actual goodbye to "
        "the caller. Research: Schegloff & Sacks 1973 — the terminal "
        "exchange is the caller's to initiate."
    )


def terminal_directive(facets: VoiceFacets) -> str:
    """Directive for the actual bye-for-bye turn."""
    softeners = ", ".join(facets.pre_closing_tokens[:3])
    closings = ", ".join(facets.closing_tokens[:3])
    return (
        "The caller just said goodbye. Mirror them with a TWO-PART "
        f"close: one softener (e.g. {softeners}) followed by one "
        f"terminal (e.g. {closings}). Never a single bare 'goodbye'. "
        "Keep it to ≤ 6 words. After this turn the call ends."
    )
