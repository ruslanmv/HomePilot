"""
Interaction router — resolves one viewer action into a Transition.

This is the hot path of the runtime. One call per viewer click /
message / hotspot. Orchestrates:

  1. Build runtime state snapshot (state.build_runtime_state).
  2. If input is free text → classify + free-input decision.
  3. Personalization rule evaluation → RouterHint.
  4. Pick next node: RouterHint override OR outbound edge match.
  5. Apply progression rewards.
  6. Update character state (mood, affinity).

Return: a ``ResolvedTurn`` dataclass that the HTTP layer
serializes to the response contract defined in the design doc.

Keep this module pure on the Python side — I/O (event append, turn
append) is done by the caller (the HTTP router in batch 7).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import repo
from ..config import InteractiveConfig
from ..models import Action, Experience, Session
from ..personalize import PersonalizationProfile, RouterHint, evaluate as personalize_eval
from ..personalize.rules import Rule, RuleCondition
from ..policy import Decision, check_action_execution, check_free_input
from ..policy.classifier import classify_intent
from ..progression import apply_rewards, describe_level, is_action_unlocked
from .cooldown import check_cooldown, mark_used
from .state import RuntimeState, build_runtime_state, upsert_character_state, upsert_progress
from .types import Transition, TransitionKind


@dataclass(frozen=True)
class ActionPayload:
    """Input to the router. Either action_id or free_text is set."""

    action_id: str = ""
    free_text: str = ""
    viewer_region: str = ""
    client_ts_ms: int = 0


@dataclass(frozen=True)
class ResolvedTurn:
    """Router output. Fully self-contained response struct."""

    session_id: str
    transition: Transition
    decision: Decision
    intent_code: str
    reward_deltas: Dict[str, float] = field(default_factory=dict)
    level_description_display: str = ""
    level_description_level: int = 0
    mood: str = "neutral"
    affinity_score: float = 0.5
    matched_rule_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _pick_next_from_hint_or_edges(
    hint: RouterHint, state: RuntimeState, action_intent: Optional[str],
) -> Transition:
    """Route to hint.route_to_node if set; otherwise pick the
    outbound edge whose label matches the action's intent_code (or
    the first outbound edge as fallback)."""
    if hint.route_to_node:
        return Transition(
            to_node_id=hint.route_to_node,
            kind=TransitionKind.AUTO,
            label="personalization",
            payload={"rule_id": hint.matched_rule_id},
            rule_id=hint.matched_rule_id,
        )

    outbound = [e for e in repo.list_edges(state.experience_id) if e.from_node_id == state.current_node_id]
    if not outbound:
        # Dead end — stay on current node.
        return Transition(
            to_node_id=state.current_node_id,
            kind=TransitionKind.FALLBACK,
            label="no_outbound",
            payload={},
        )

    # Prefer edges whose trigger_payload.label matches action intent.
    if action_intent:
        for e in outbound:
            payload = e.trigger_payload or {}
            if payload.get("label") == action_intent or e.trigger_kind == "intent":
                return Transition(
                    to_node_id=e.to_node_id,
                    kind=e.trigger_kind,
                    label=str(payload.get("label", "")),
                    payload=dict(payload),
                )

    # Default: lowest-ordinal outbound.
    ordered = sorted(outbound, key=lambda e: (e.ordinal, 0))
    e = ordered[0]
    payload = e.trigger_payload or {}
    return Transition(
        to_node_id=e.to_node_id,
        kind=e.trigger_kind,
        label=str(payload.get("label", "")),
        payload=dict(payload),
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_rules_for_experience(experience_id: str) -> List[Rule]:
    """Load enabled personalization rules from DB into typed Rule list."""
    from .. import store
    with store._conn() as con:
        rows = con.execute(
            "SELECT * FROM ix_personalization_rules "
            "WHERE experience_id = ? AND enabled = 1",
            (experience_id,),
        ).fetchall()
    out: List[Rule] = []
    for r in rows:
        d = store.row_to_dict(r, json_fields=("condition", "action"))
        out.append(Rule(
            id=str(d["id"]),
            name=str(d.get("name", "")),
            condition=RuleCondition(raw=d.get("condition") or {}),
            action=dict(d.get("action") or {}),
            priority=int(d.get("priority") or 100),
            enabled=bool(d.get("enabled", True)),
        ))
    return out


# ─────────────────────────────────────────────────────────────────
# Public entry
# ─────────────────────────────────────────────────────────────────

def resolve_next(
    cfg: InteractiveConfig,
    experience: Experience,
    session: Session,
    payload: ActionPayload,
    *,
    action: Optional[Action] = None,
    profile: Optional[PersonalizationProfile] = None,
) -> ResolvedTurn:
    """Resolve one viewer turn. Returns a ``ResolvedTurn``.

    The caller supplies ``action`` when ``payload.action_id`` is
    set; when ``payload.free_text`` is set instead, the function
    classifies the intent and makes a policy decision directly.
    """
    state = build_runtime_state(session.id)
    if state is None:
        return ResolvedTurn(
            session_id=session.id,
            transition=Transition(
                to_node_id=session.current_node_id,
                kind=TransitionKind.FALLBACK,
                label="session_missing",
                payload={},
            ),
            decision=Decision(decision="block", reason_code="session_missing"),
            intent_code="",
        )

    now_ms = payload.client_ts_ms or _now_ms()
    personalization = profile or PersonalizationProfile(
        language=state.language,
        raw=state.personalization,
    )

    # ── Free-text path ──────────────────────────────────────────
    if payload.free_text and not payload.action_id:
        decision = check_free_input(
            cfg, payload.free_text, experience, session,
            viewer_region=payload.viewer_region,
        )
        intent_code = classify_intent(payload.free_text).intent_code
        if not decision.is_allow():
            return ResolvedTurn(
                session_id=session.id,
                transition=Transition(
                    to_node_id=state.current_node_id,
                    kind=TransitionKind.FALLBACK,
                    label="policy",
                    payload={"reason_code": decision.reason_code},
                ),
                decision=decision,
                intent_code=intent_code,
                mood=state.character_mood,
                affinity_score=state.affinity_score,
            )
        rules = _load_rules_for_experience(experience.id)
        hint = personalize_eval(rules, personalization, state)
        transition = _pick_next_from_hint_or_edges(hint, state, intent_code)
        return ResolvedTurn(
            session_id=session.id,
            transition=transition,
            decision=decision,
            intent_code=intent_code,
            mood=state.character_mood,
            affinity_score=state.affinity_score,
            matched_rule_id=hint.matched_rule_id,
        )

    # ── Action path ──────────────────────────────────────────────
    if not action:
        return ResolvedTurn(
            session_id=session.id,
            transition=Transition(
                to_node_id=state.current_node_id,
                kind=TransitionKind.FALLBACK,
                label="invalid",
                payload={},
            ),
            decision=Decision(decision="block", reason_code="no_action_provided"),
            intent_code="",
        )

    # Unlock / level gate.
    unlocked, lock_reason = is_action_unlocked(action, state.progress)
    if not unlocked:
        return ResolvedTurn(
            session_id=session.id,
            transition=Transition(
                to_node_id=state.current_node_id,
                kind=TransitionKind.FALLBACK,
                label="locked",
                payload={"reason": lock_reason},
            ),
            decision=Decision(decision="block", reason_code=lock_reason),
            intent_code=action.intent_code,
            mood=state.character_mood,
            affinity_score=state.affinity_score,
        )

    # Cooldown.
    remaining = check_cooldown(session.id, action.id, action.cooldown_sec, now_ms=now_ms)
    if remaining > 0:
        return ResolvedTurn(
            session_id=session.id,
            transition=Transition(
                to_node_id=state.current_node_id,
                kind=TransitionKind.FALLBACK,
                label="cooldown",
                payload={"remaining_sec": remaining},
            ),
            decision=Decision(
                decision="block", reason_code="cooldown",
                message=f"Cooldown: wait {remaining:.1f}s.",
            ),
            intent_code=action.intent_code,
            mood=state.character_mood,
            affinity_score=state.affinity_score,
        )

    # Policy re-check at execution time.
    uses_so_far = state.uses_by_action.get(action.id, 0)
    decision = check_action_execution(
        cfg, action, experience, session,
        viewer_region=payload.viewer_region,
        last_used_at_ms=0,  # cooldown already handled above
        uses_this_session=uses_so_far,
        now_ms=now_ms,
    )
    if not decision.is_allow():
        return ResolvedTurn(
            session_id=session.id,
            transition=Transition(
                to_node_id=state.current_node_id,
                kind=TransitionKind.FALLBACK,
                label="policy",
                payload={"reason_code": decision.reason_code},
            ),
            decision=decision,
            intent_code=action.intent_code,
            mood=state.character_mood,
            affinity_score=state.affinity_score,
        )

    # Apply rewards.
    reward = apply_rewards(action, state.progress, uses_before_this=uses_so_far)
    for metric_key, value in reward.new_progress.items():
        upsert_progress(session.id, reward.scheme, metric_key, value)

    # Apply character state updates from action.mood_delta + personalization bump.
    md = action.mood_delta or {}
    new_mood = str(md.get("mood") or state.character_mood)
    new_aff = state.affinity_score + float(md.get("affinity") or 0.0)

    rules = _load_rules_for_experience(experience.id)
    hint = personalize_eval(rules, personalization, state)
    new_aff += float(hint.bump_affinity or 0.0)
    new_aff = max(0.0, min(1.0, new_aff))

    upsert_character_state(
        session.id, persona_id="",
        mood=new_mood, affinity_score=new_aff,
    )

    # Cooldown mark.
    mark_used(session.id, action.id, now_ms=now_ms)

    # Pick next node.
    transition = _pick_next_from_hint_or_edges(hint, state, action.intent_code)

    # Level descriptor.
    level_desc = describe_level(reward.scheme, reward.new_progress)

    return ResolvedTurn(
        session_id=session.id,
        transition=transition,
        decision=decision,
        intent_code=action.intent_code,
        reward_deltas=dict(reward.deltas),
        level_description_display=level_desc.display,
        level_description_level=level_desc.level,
        mood=new_mood,
        affinity_score=new_aff,
        matched_rule_id=hint.matched_rule_id,
    )
