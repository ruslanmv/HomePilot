"""
Per-turn system-suffix composer.

**Core invariant of this whole module** (the product promise):

    The persona's own system prompt is NEVER touched. `compose()`
    only produces a short suffix that is appended as a SEPARATE
    system message in addition to whatever the /v1/chat/completions
    endpoint already injects for the persona. When the call ends,
    the suffix is gone; the persona's chat behavior is identical to
    what it was before the call started.

The suffix is assembled from five small paragraphs. Each paragraph
is independently testable and individually gated by the current
phase / time / caller-context, so on an uneventful turn the suffix
is only ~4 lines long.

The five stages, in assembly order:

    1. _base_phone_frame       persona-neutral phone register
    2. _phase_frame            opening / topic / pre_closing / closed
    3. _context_frame          late-night / driving / resumed-topic
    4. _repetition_frame       ledger-enforced variety
    5. _latency_frame          filler rule for thinking pauses
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import closing, repeat, state as state_mod, store
from .config import PersonaCallConfig
from .context import CallEnv, CallerSignal
from .facets import VoiceFacets


# ── public result type ───────────────────────────────────────────────

@dataclass
class ComposedDirective:
    """Return value of :func:`compose`. Two independently useful fields:

    * ``system_suffix`` — the text we append as an additional system
      message. If :class:`PersonaCallConfig`.apply is False (shadow
      mode), this is logged but not actually sent to the model.
    * ``post_directives`` — the list of individual rules we applied,
      one string per rule, in the order composed. Dumped into
      ``persona_call_directives.post_directives`` for observability.
    """
    session_id: str
    phase: str
    turn_index: int
    system_suffix: str
    post_directives: List[str] = field(default_factory=list)


# ── paragraph builders ────────────────────────────────────────────────

def _base_phone_frame(facets: VoiceFacets) -> str:
    """Persona-neutral phone register. Same for every persona; the
    persona's identity is NOT asserted here — that stays in the
    persona's own system prompt which is already active."""
    return (
        "[PHONE CALL MODE — appended only for the duration of this call]\n"
        "You are on a live phone call. Spoken, not typed. "
        "No bullet points, no stage directions (never output '*smiles*' "
        "or similar), no markdown headers. "
        f"Keep replies in the {facets.typical_reply_sentences}-sentence range, "
        f"≤ {facets.sentence_max_words} words per sentence. "
        f"Tone: {facets.tone_line}."
    )


def _phase_frame(
    *,
    phase: str,
    turn_index: int,
    skipped_how_are_you: bool,
    asked_reason_fallback: bool,
    facets: VoiceFacets,
    env: CallEnv,
    caller: CallerSignal,
    pre_closing_trigger: Optional[str],
    cfg: PersonaCallConfig,
) -> tuple[str, List[str]]:
    """Return (paragraph, rule_names_applied) for the current phase."""
    rules: List[str] = []

    if phase == state_mod.OPENING:
        # Turn 0 — Schegloff summons-answer.
        if turn_index == 0:
            rules.append("opening.summons_answer")
            return (
                "This is turn 0. Reply with ONE short line of recognition "
                "— acknowledge you're there, use the caller's name if you "
                "know it, ≤ 6 words. Do NOT launch into topic.",
                rules,
            )
        # Turn ≥ 1 — decide on "how are you" exactly once.
        if not skipped_how_are_you and turn_index <= 2:
            # Skip "how are you" if: late hour, caller is pressed, or
            # caller already expressed a reason.
            should_skip = (
                env.local_hour >= cfg.how_are_you_late_hour
                or caller.time_pressured
                or caller.reason_expressed
            )
            if should_skip:
                rules.append("opening.skip_how_are_you")
                return (
                    "Skip the 'how are you?' exchange this time — the "
                    "caller is either pressed, late, or already on-topic. "
                    "Move directly to hearing them out.",
                    rules,
                )
            rules.append("opening.how_are_you_once")
            return (
                "One brief round of 'how are you?' is appropriate now. "
                "Ask once, let them answer, then pause for their reason "
                "for calling. Do not stack this with another question.",
                rules,
            )
        # Opening past turn 2 with no reason and no fallback asked.
        if (
            not caller.reason_expressed
            and not asked_reason_fallback
            and turn_index >= cfg.reason_fallback_turn
        ):
            rules.append("opening.reason_fallback_ask")
            return (
                "The caller has not said why they're calling yet. "
                "Ask gently, in one sentence: something like "
                "'what's on your mind today?' or 'what's up?'",
                rules,
            )
        rules.append("opening.default")
        return (
            "Still in the opening. Keep replies short and oriented to "
            "the caller's lead.",
            rules,
        )

    if phase == state_mod.TOPIC:
        rules.append("topic.default")
        return (
            "Mid-call. Be responsive: if the caller asked a question, "
            "answer it before asking one back. Ask at most ONE follow-up "
            "per turn — phone calls tolerate fewer questions per turn "
            "than chat does.",
            rules,
        )

    if phase == state_mod.PRE_CLOSING:
        rules.append("closing.pre_closing_handshake")
        return closing.pre_closing_directive(facets, pre_closing_trigger), rules

    if phase == state_mod.CLOSED:
        rules.append("closing.terminal")
        return closing.terminal_directive(facets), rules

    return "", rules


def _context_frame(
    env: CallEnv, caller: CallerSignal, cfg: PersonaCallConfig,
) -> tuple[str, List[str]]:
    """Situational rules. Paragraphs only emit when the predicate fires,
    so uneventful turns get no context frame at all."""
    lines: List[str] = []
    rules: List[str] = []

    # Late-night brevity (decision-fatigue bias).
    late = (
        env.local_hour >= cfg.late_night_brevity_hour
        or env.local_hour <= cfg.late_night_brevity_hour_end
    )
    if late:
        rules.append("context.late_night_brevity")
        lines.append(
            f"Local clock: {env.local_hour:02d}:00 for the caller. "
            "It's late — keep replies to one sentence when you can, "
            "offer to continue tomorrow for anything complex."
        )

    # Driving — safety/attention bias.
    if caller.driving:
        rules.append("context.driving")
        lines.append(
            "The caller is DRIVING. One-sentence answers, no multi-part "
            "questions, never require a yes/no decision unless it's "
            "genuinely urgent."
        )
    elif caller.walking or caller.transit:
        rules.append("context.mobile")
        lines.append(
            "The caller is mobile. Keep it brief and well-paced — they "
            "may lose signal or attention momentarily."
        )

    # Weeks-since-last-call resumption (fire at most once per call; the
    # persona_call_state doesn't need a separate flag because this only
    # fires when the topic hasn't been acknowledged yet — the composer
    # sees the same state each turn until the persona says something).
    if env.weeks_since_last_call >= 3:
        rules.append("context.resumption")
        lines.append(
            f"It has been ≈{env.weeks_since_last_call} weeks since this "
            "caller last spoke with you. One natural acknowledgment of "
            "the gap is appropriate — do NOT make it the whole turn, "
            "and say it only once this call."
        )
    if env.resumed_from_topic:
        rules.append("context.resume_topic")
        lines.append(
            f"Unfinished topic from a prior call: {env.resumed_from_topic!r}. "
            "Offer to pick it back up if natural, but don't force it."
        )

    return ("\n".join(lines) if lines else ""), rules


def _repetition_frame(
    state: Dict[str, Any], facets: VoiceFacets,
) -> tuple[str, List[str]]:
    text = repeat.forbid_clause(state, facets)
    return (text, ["repeat.ledger"] if text else [])


def _latency_frame(facets: VoiceFacets) -> tuple[str, List[str]]:
    thinking = ", ".join(facets.thinking_tokens[:3])
    return (
        "If you need a beat to think, start your reply with a short "
        f"filler from: {thinking}. Never produce a long silence — "
        "callers read silence on the phone as trouble.",
        ["latency.filler_rule"],
    )


# ── public compose() ──────────────────────────────────────────────────

def compose(
    *,
    session_id: str,
    persona_id: Optional[str],
    user_text: str,
    env: CallEnv,
    cfg: PersonaCallConfig,
    facets: Optional[VoiceFacets] = None,
) -> ComposedDirective:
    """Build the per-turn directive.

    1. Advances the phase machine on the user utterance.
    2. Composes the five paragraphs.
    3. Persists the directive in shadow mode OR applies it.
    """
    from .facets import for_persona_id
    _facets = facets if facets is not None else for_persona_id(persona_id)

    # Step 1: phase machine.
    new_state = state_mod.advance_on_user_utterance(
        session_id=session_id,
        user_text=user_text,
        reason_fallback_turn=cfg.reason_fallback_turn,
    )
    phase = str(new_state.get("phase") or state_mod.OPENING)
    turn_index = int(new_state.get("turn_index") or 0)

    # The caller_context column is already updated by the phase machine,
    # so re-derive the CallerSignal from it for the composer.
    caller = CallerSignal.from_dict(
        new_state.get("caller_context")
        if isinstance(new_state.get("caller_context"), dict) else {}
    )

    # Step 2: five paragraphs.
    rules_all: List[str] = []
    parts: List[str] = [_base_phone_frame(_facets)]
    rules_all.append("base.phone_frame")

    phase_para, r = _phase_frame(
        phase=phase,
        turn_index=turn_index - 1,  # phase machine incremented already
        skipped_how_are_you=bool(new_state.get("skipped_how_are_you")),
        asked_reason_fallback=bool(new_state.get("asked_reason_fallback")),
        facets=_facets,
        env=env,
        caller=caller,
        pre_closing_trigger=(
            str(new_state.get("pre_closing_trigger") or "")
            if new_state.get("pre_closing_trigger") else None
        ),
        cfg=cfg,
    )
    if phase_para:
        parts.append(phase_para)
        rules_all.extend(r)

    ctx_para, r = _context_frame(env, caller, cfg)
    if ctx_para:
        parts.append(ctx_para)
        rules_all.extend(r)

    rep_para, r = _repetition_frame(new_state, _facets)
    if rep_para:
        parts.append(rep_para)
        rules_all.extend(r)

    lat_para, r = _latency_frame(_facets)
    parts.append(lat_para)
    rules_all.extend(r)

    system_suffix = "\n\n".join(parts).strip()

    # Step 3: persist + (maybe) apply.
    store.record_directive(
        session_id=session_id,
        turn_index=turn_index,
        phase=phase,
        applied=cfg.apply,
        system_suffix=system_suffix,
        post_directives=rules_all,
    )

    # If we asked 'how are you' or the reason-fallback, set the flags
    # so we don't do it again.
    if "opening.how_are_you_once" in rules_all:
        state_mod.mark_how_are_you_decision(session_id, skipped=False)
    if "opening.skip_how_are_you" in rules_all:
        state_mod.mark_how_are_you_decision(session_id, skipped=True)
    if "opening.reason_fallback_ask" in rules_all:
        state_mod.mark_reason_fallback_asked(session_id)

    return ComposedDirective(
        session_id=session_id,
        phase=phase,
        turn_index=turn_index,
        system_suffix=system_suffix if cfg.apply else "",
        post_directives=rules_all,
    )


def record_persona_reply(
    *,
    session_id: str,
    persona_id: Optional[str],
    reply: str,
    cfg: PersonaCallConfig,
) -> None:
    """Called after the LLM reply comes back. Rolls the anti-repetition
    ledger forward so the next turn can forbid the just-used token."""
    from .facets import for_persona_id
    _facets = for_persona_id(persona_id)
    state = store.ensure_state(session_id)
    new_acks, new_openers = repeat.record_reply(
        state,
        reply,
        _facets,
        cfg_ack_window=cfg.ack_ledger_window,
        cfg_opener_window=cfg.opener_ledger_window,
    )
    store.update_state(
        session_id,
        recent_acks=new_acks,
        recent_openers=new_openers,
    )
