"""
Anti-repetition ledger.

Three windowed deques per session, all backed by the JSON columns on
``persona_call_state``:

  recent_acks      last N acknowledgment tokens the persona used
  recent_openers   last N first-words of the persona's turns
  recent_closings  last N pre-closing tokens

Read API returns the set to FORBID in the next turn's directive; write
API is called after the reply comes back and extracts the new token via
a regex-first / LLM-never extractor so it stays cheap.

No LLM calls anywhere here — the extraction is regex + token-pool
membership. If the persona's reply starts with a token that isn't in
its own voice_facets pool, we store the first lowercased word anyway;
it still anchors the entropy metric.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .facets import VoiceFacets


_WORD_BOUNDARY = re.compile(r"^[\s\W]*([a-z][a-z\-']*)", re.I)


def _first_word(reply: str) -> Optional[str]:
    if not reply:
        return None
    m = _WORD_BOUNDARY.match(reply.strip())
    if not m:
        return None
    return m.group(1).lower()


def _roll(deque: List[str], token: str, size: int) -> List[str]:
    out = list(deque or [])
    if token:
        out.append(token)
    if len(out) > size:
        out = out[-size:]
    return out


# ── READ: directive paragraph that forbids recent tokens ─────────────

def forbid_clause(
    state: Dict[str, object],
    facets: VoiceFacets,
    *,
    max_len: int = 80,
) -> str:
    """Return the one-line directive paragraph about recent tokens.

    Empty string when there's nothing to forbid yet — keeps the
    per-turn suffix short on early turns."""
    acks = state.get("recent_acks") or []
    openers = state.get("recent_openers") or []
    if not acks and not openers:
        return ""

    dropped: Set[str] = set()
    for t in acks:
        if isinstance(t, str) and t:
            dropped.add(t.lower())
    for t in openers:
        if isinstance(t, str) and t:
            dropped.add(t.lower())

    if not dropped:
        return ""

    pool = [t for t in facets.ack_tokens if t.lower() not in dropped]
    fresh_hint = ""
    if pool:
        fresh_hint = f" Prefer a fresh one from: {', '.join(pool[:4])}."

    forbidden = sorted(dropped)[: max_len // 5]  # rough clamp
    return (
        "Avoid repeating your recent openers / acknowledgments: "
        f"{', '.join(forbidden)}." + fresh_hint
    )


# ── WRITE: record the persona's reply into the ledger ────────────────

def record_reply(
    state: Dict[str, object],
    reply: str,
    facets: VoiceFacets,
    cfg_ack_window: int,
    cfg_opener_window: int,
) -> Tuple[List[str], List[str]]:
    """Roll the ledger forward. Returns the new (recent_acks,
    recent_openers) lists for ``store.update_state``."""
    token = _first_word(reply) or ""
    acks = state.get("recent_acks") or []
    openers = state.get("recent_openers") or []

    # An ack is anything that appears in the persona's ack pool AND
    # appears in the first three words. That matches how human phone
    # acks actually work ("mm yeah I hear you"): the ack is the front
    # of the turn, not a whole separate utterance.
    front = " ".join((reply or "").lower().strip().split()[:3])
    matched_ack = None
    for pool_token in facets.ack_tokens:
        if pool_token in front:
            matched_ack = pool_token
            break

    new_acks = _roll(list(acks), matched_ack or "", cfg_ack_window)
    new_openers = _roll(list(openers), token, cfg_opener_window)
    return new_acks, new_openers


def record_closing(
    state: Dict[str, object],
    token: str,
    window: int = 3,
) -> List[str]:
    """Roll the closings deque. Called when the closing state machine
    chooses a pre-closing token."""
    prev = state.get("recent_closings") or []
    return _roll(list(prev), token.lower() if token else "", window)
