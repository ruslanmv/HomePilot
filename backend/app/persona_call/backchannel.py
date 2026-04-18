"""
Server-originated backchannel emission — the separate low-volume
stream (per the user's chosen default).

A backchannel is NOT a turn. It's a "mm-hm" / "yeah" / "got it" the
server emits *while the user is still speaking* so the caller hears
recipiency instead of silence. Research (Jefferson 1984) shows humans
emit one every 2–3 clauses on the phone — they compensate for the
absence of visual nods.

Design rules baked in:

  * Token pulled from the persona's own pool (VoiceFacets.ack_tokens)
    so Darkangel666 sounds like Darkangel666 even when backchanneling.
  * Cadence: at most one per ``backchannel_min_gap_ms``, and only after
    ``backchannel_clause_trigger`` clause boundaries in the CURRENT
    user utterance.
  * Anti-repetition: never the same token two backchannels in a row.
  * Played at ``backchannel_volume_db`` below the main TTS stream so
    it overlaps the user's voice without fighting it (the client
    applies the gain — this module just names the dB).
  * Skipped entirely when ``facets.backchannel_rate`` is 0.

The emission itself is a WS event; this module picks the token and
decides IF/WHEN. The actual ``ws.send`` call lives in ws.py.
"""
from __future__ import annotations

import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import PersonaCallConfig
from .facets import VoiceFacets


# Rough clause boundaries — commas, semicolons, sentence enders,
# conjunctions that start a clause ("and then…", "but…", "so…").
# Runs on the partial STT transcript, so it fires as the user speaks.
_CLAUSE_BOUNDARY = re.compile(
    r"("
    r"[,;]|[.!?]\s+|"              # punctuation
    r"\b(and|but|so|because|then|however|actually)\b\s"  # discourse markers
    r")",
    re.I,
)


def count_clause_boundaries(partial_text: str) -> int:
    """How many clause boundaries have been uttered in the current
    user turn so far."""
    if not partial_text:
        return 0
    return len(_CLAUSE_BOUNDARY.findall(partial_text))


def _now_ms() -> int:
    return int(time.time() * 1000)


def choose_token(
    facets: VoiceFacets,
    *,
    recent_acks: List[str],
    seed_utterance: str = "",
) -> Optional[str]:
    """Pick a backchannel token that is (a) in the persona's pool and
    (b) not the most recent one. Returns None iff the pool is empty.

    Mild stance-sensitivity: if the partial utterance ended with a
    rising question mark, we bias toward stance tokens ('oh really?',
    'yeah?'); falling-period endings bias toward acknowledgments.
    """
    pool = [t for t in facets.ack_tokens if t]
    if not pool:
        return None
    last = (recent_acks[-1].lower() if recent_acks else "")
    candidates = [t for t in pool if t.lower() != last] or pool
    # Stance nudge — prefer single-syllable quick tokens on
    # exclamations / questions, longer ones on plain pauses.
    is_query = bool(seed_utterance.rstrip().endswith(("?", "!")))
    if is_query:
        candidates = sorted(candidates, key=lambda t: len(t))
    return random.choice(candidates)


def should_emit(
    *,
    partial_text: str,
    last_backchannel_ms: int,
    facets: VoiceFacets,
    cfg: PersonaCallConfig,
) -> bool:
    """True iff we should send a backchannel right now. Pure decision;
    no side effects."""
    if facets.backchannel_rate <= 0:
        return False
    # Scale the clause threshold by the persona's own rate. Low-rate
    # personas (e.g. reserved / clinical) need more clauses before a
    # backchannel; chatty personas need fewer.
    trigger = max(
        1, int(round(cfg.backchannel_clause_trigger / max(0.25, facets.backchannel_rate)))
    )
    if count_clause_boundaries(partial_text) < trigger:
        return False
    min_gap = int(cfg.backchannel_min_gap_ms / max(0.25, facets.backchannel_rate))
    if _now_ms() - int(last_backchannel_ms or 0) < min_gap:
        return False
    return True


def build_event(token: str, volume_db: float) -> Dict[str, Any]:
    """Shape the WS event payload ws.py will serialize."""
    return {
        "type": "assistant.backchannel",
        "payload": {
            "token": token,
            "volume_db": float(volume_db),
            "ts": _now_ms(),
        },
    }
