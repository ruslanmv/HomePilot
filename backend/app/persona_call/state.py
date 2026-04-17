"""
Phase state machine.

Five phases, deterministic transitions:

     opening  ─(reason expressed OR 'how are you' cycle done)─▶  topic
     topic    ─(closing trigger)─────────────────────────────▶  pre_closing
     pre_closing ─(user terminal)──────────────────────────────▶  closed
     pre_closing ─(user recants / new topic)──────────────────▶  topic
     closed   (terminal)

Phase is the single source of truth for which paragraph
:mod:`directive` injects into the per-turn system suffix.
"""
from __future__ import annotations

from typing import Dict, Optional

from . import closing, context, store


OPENING = "opening"
TOPIC = "topic"
PRE_CLOSING = "pre_closing"
CLOSED = "closed"


def advance_on_user_utterance(
    *,
    session_id: str,
    user_text: str,
    reason_fallback_turn: int,
) -> Dict[str, object]:
    """Called by the WS orchestrator BEFORE composing the directive.

    Updates the phase, turn_index, caller_context, and reason flags
    based on the just-received user utterance. Returns the refreshed
    state row so the composer has the latest view.
    """
    state = store.ensure_state(session_id)
    turn_index = int(state.get("turn_index") or 0)
    phase = state.get("phase") or OPENING

    # Caller signal extraction — accumulate into caller_context.
    prev_signal = context.CallerSignal.from_dict(
        state.get("caller_context") if isinstance(
            state.get("caller_context"), dict) else {}
    )
    fresh = context.classify_utterance(user_text)
    merged = prev_signal.merge(fresh)

    # Phase transition rules.
    pre_closing_trigger = state.get("pre_closing_trigger")

    if phase in (OPENING, TOPIC) and closing.is_pre_closing_trigger(user_text):
        phase = PRE_CLOSING
        pre_closing_trigger = user_text.strip()
    elif phase == PRE_CLOSING and closing.is_terminal(user_text):
        phase = CLOSED
    elif phase == OPENING:
        # Move to 'topic' if the user stated a reason, OR if we've
        # already done one "how are you" cycle (2 user turns in
        # opening without a reason).
        if merged.reason_expressed:
            phase = TOPIC
        elif turn_index >= 2:
            # After two turns in 'opening' without a stated reason,
            # the phase-machine forces 'topic' — the persona will
            # ask the reason-fallback question via the composer.
            phase = TOPIC

    # Persist.
    updated = store.update_state(
        session_id,
        phase=phase,
        turn_index=turn_index + 1,
        caller_context=merged.to_dict(),
        pre_closing_trigger=pre_closing_trigger,
    )
    return updated


def mark_how_are_you_decision(session_id: str, *, skipped: bool) -> None:
    """Record that the composer made a 'how are you' decision for this
    session — idempotent; the deciding composer path may run multiple
    turns but should only fire once."""
    store.update_state(session_id, skipped_how_are_you=skipped)


def mark_reason_fallback_asked(session_id: str) -> None:
    """Record that the composer already asked the reason-fallback
    question, so it never asks twice."""
    store.update_state(session_id, asked_reason_fallback=True)


def get(session_id: str) -> Optional[Dict[str, object]]:
    """Thin pass-through to the store — avoids callers importing
    store directly."""
    return store.get_state(session_id)
