"""
Per-persona ``voice_facets`` — non-destructive voice personalization.

Facets live in an OPTIONAL field on the persona manifest
(``persona.voice_facets``). Any existing persona with no facets gets
the neutral-English default — its chat behavior is completely
unchanged either way.

The facets object drives four things at runtime:

  * backchannel token pools (``mm``, ``yeah``, ``right`` etc.)
  * pre-closing + closing token pools
  * filler / thinking tokens for the latency hook
  * scalar voice knobs (warmth, pace, formality) interpolated into
    the per-turn system suffix as raw numbers — the model reads the
    number, not an adjective. This avoids the same three adjectives
    bleeding into every reply.

The *base system prompt* of the persona is never touched. This file
never rewrites a persona; it only reads the optional facets field.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Default facets — applied when a persona ships no voice_facets ───
#
# Values chosen from the CA literature + common-sense phone norms.
# Token pools kept short on purpose: fewer options → easier anti-
# repetition tracking → cleaner entropy metric.

_DEFAULT_ACKS     = ["mm", "mm-hm", "yeah", "right", "got it", "okay"]
_DEFAULT_THINKING = ["hmm", "let me think", "one sec", "hold on"]
_DEFAULT_PRE_CLOSE = ["okay", "alright", "so", "well"]
_DEFAULT_CLOSING   = ["take care", "talk soon", "bye for now", "later"]


@dataclass(frozen=True)
class VoiceFacets:
    """Immutable snapshot for one persona.

    All scalar knobs are clamped on load so downstream code can trust
    the range. Token pools are deduplicated + lowercased to keep the
    anti-repetition ledger case-insensitive.
    """

    warmth: float           # 0 clinical … 1 affectionate
    pace: float             # 0.25 … 2.0   speech-rate multiplier
    formality: float        # 0 casual … 1 formal
    humor: float            # 0 none … 1 playful
    self_disclosure: float  # 0 reserved … 1 volunteers a lot
    sentence_max_words: int
    typical_reply_sentences: List[int]
    language_register: str
    ack_tokens: List[str]
    thinking_tokens: List[str]
    pre_closing_tokens: List[str]
    closing_tokens: List[str]
    backchannel_rate: float  # 0..2, multiplier on default cadence

    @property
    def tone_line(self) -> str:
        """One-line summary of scalar knobs, ready to drop into the
        per-turn system suffix. Numeric so the model interpolates
        rather than falling back on the same adjective."""
        return (
            f"warmth {self.warmth:.1f} · pace {self.pace:.2f} · "
            f"formality {self.formality:.1f} · humor {self.humor:.1f}"
        )


def _clamp(x: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return lo


def _tokens(raw: Any, default: List[str]) -> List[str]:
    """Normalize a token-pool field: list[str], lowercase, de-dup,
    keep stable order. Returns the default if input is empty / bad."""
    if not isinstance(raw, list) or not raw:
        return list(default)
    seen, out = set(), []
    for item in raw:
        if not isinstance(item, str):
            continue
        t = item.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out if out else list(default)


def default_facets() -> VoiceFacets:
    """Neutral English phone-call default. What an unmodified persona
    gets — indistinguishable from today's behavior except for the phone
    context itself."""
    return VoiceFacets(
        warmth=0.5,
        pace=1.0,
        formality=0.4,
        humor=0.3,
        self_disclosure=0.3,
        sentence_max_words=22,
        typical_reply_sentences=[1, 2, 3],
        language_register="en-US-casual",
        ack_tokens=list(_DEFAULT_ACKS),
        thinking_tokens=list(_DEFAULT_THINKING),
        pre_closing_tokens=list(_DEFAULT_PRE_CLOSE),
        closing_tokens=list(_DEFAULT_CLOSING),
        backchannel_rate=1.0,
    )


def from_manifest(manifest: Optional[Dict[str, Any]]) -> VoiceFacets:
    """Parse a persona manifest dict into a VoiceFacets.

    Any missing / malformed field falls back to the default. Safe to
    call with ``None`` or ``{}`` — returns :func:`default_facets` in
    those cases. Never raises; a broken facets block must not break a
    call.
    """
    d = default_facets()
    if not isinstance(manifest, dict):
        return d
    raw = manifest.get("voice_facets")
    if not isinstance(raw, dict):
        return d

    sig = raw.get("signature_tokens") or {}
    if not isinstance(sig, dict):
        sig = {}

    reply_ns = raw.get("typical_reply_sentences")
    if isinstance(reply_ns, list) and reply_ns:
        reply_ns = [int(n) for n in reply_ns if isinstance(n, (int, float))]
    else:
        reply_ns = list(d.typical_reply_sentences)

    return VoiceFacets(
        warmth=_clamp(raw.get("warmth", d.warmth), 0.0, 1.0),
        pace=_clamp(raw.get("pace", d.pace), 0.25, 2.0),
        formality=_clamp(raw.get("formality", d.formality), 0.0, 1.0),
        humor=_clamp(raw.get("humor", d.humor), 0.0, 1.0),
        self_disclosure=_clamp(
            raw.get("self_disclosure", d.self_disclosure), 0.0, 1.0
        ),
        sentence_max_words=int(raw.get("sentence_max_words", d.sentence_max_words)),
        typical_reply_sentences=reply_ns,
        language_register=str(raw.get("language_register", d.language_register)),
        ack_tokens=_tokens(sig.get("acknowledgments"), d.ack_tokens),
        thinking_tokens=_tokens(sig.get("thinking"), d.thinking_tokens),
        pre_closing_tokens=_tokens(sig.get("pre_closing"), d.pre_closing_tokens),
        closing_tokens=_tokens(sig.get("closings"), d.closing_tokens),
        backchannel_rate=_clamp(raw.get("backchannel_rate", 1.0), 0.0, 2.0),
    )


# ── Runtime lookup — never mutates persona storage ───────────────────

def for_persona_id(persona_id: Optional[str]) -> VoiceFacets:
    """Load facets for a persona without touching persona storage.

    Looks up the persona's manifest (if any) via the existing personas
    module. Any error returns the neutral default — persona_call must
    degrade silently when persona storage has not yet been initialized
    (e.g. early tests).
    """
    if not persona_id:
        return default_facets()
    try:
        # Lazy import to avoid any import-time coupling to personas.
        from ..personas.repo import get_persona  # type: ignore
        manifest = get_persona(persona_id)
    except Exception:
        return default_facets()
    return from_manifest(manifest)
