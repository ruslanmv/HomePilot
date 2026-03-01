# backend/app/teams/orchestrator.py
"""
Meeting Orchestrator — central loop for realistic meeting behavior.

  orchestrator.run_reactive_step(room_id, ...)
    1. Tick cooldowns, increment round
    2. Compute SpeakIntents for all participants
    3. Auto hand-raise for high-confidence personas (top 3, TTL-based)
    4. Select 0..N speakers based on room policy
    5. Apply redundancy + diversity gates
    6. Generate spoken text only for selected speakers
    7. Append to transcript, apply cooldowns, expire old hands, persist

Enterprise hand-raise lifecycle:
  - Auto-raised when confidence >= hand_raise_threshold
  - Max 3 visible hands (configurable)
  - Hands expire after 2 rounds (configurable TTL)
  - Hands consumed when persona speaks
  - Hands dropped when topic changes or becomes redundant

One algorithm, one place to maintain.
Personas remain portable and unchanged — the orchestrator wraps them.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Set

from .intent import SpeakIntent, compute_intent, tick_cooldowns, set_cooldown
from . import rooms

logger = logging.getLogger("homepilot.teams.orchestrator")


def _now() -> float:
    return time.time()


# ── Room defaults (additive — only set if missing) ─────────────────────────


def ensure_defaults(room: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure a room has all orchestration fields.
    Only sets missing keys — never overwrites existing values.
    """
    room.setdefault("policy", {})
    p = room["policy"]
    p.setdefault("max_speakers_per_event", 2)
    p.setdefault("max_rounds_per_event", 3)
    p.setdefault("speak_threshold", 0.45)
    p.setdefault("cooldown_turns", 1)
    # Hand-raise policy
    p.setdefault("hand_raise_threshold", 0.55)
    p.setdefault("hand_raise_ttl_rounds", 2)
    p.setdefault("max_visible_hands", 3)
    # Redundancy + dominance
    p.setdefault("redundancy_threshold", 0.7)
    p.setdefault("dominance_lookback", 10)
    p.setdefault("dominance_penalty", 0.15)
    # Context depth (how many messages each persona sees)
    p.setdefault("memory_depth", 50)

    room.setdefault("round", 0)
    room.setdefault("speaker_queue", [])
    room.setdefault("hand_raises", [])
    room.setdefault("hand_raise_meta", {})
    room.setdefault("cooldowns", {})
    room.setdefault("muted", [])
    room.setdefault("intents", {})
    return room


# ── Intent computation ─────────────────────────────────────────────────────


def compute_all_intents(
    room: Dict[str, Any],
    participants: List[Dict[str, Any]],
    last_human_message: str,
) -> List[SpeakIntent]:
    """Compute SpeakIntent for every unmuted participant."""
    out: List[SpeakIntent] = []
    muted = set(room.get("muted") or [])

    for p in participants:
        pid = p["persona_id"]
        if pid in muted:
            continue

        intent = compute_intent(
            room=room,
            persona_id=pid,
            display_name=p.get("display_name", pid),
            role_tags=p.get("role_tags") or [],
            last_human_message=last_human_message,
        )
        out.append(intent)

        # Persist intent snapshot for UI (read by GET /intents)
        room["intents"][pid] = {
            "wants_to_speak": intent.wants_to_speak,
            "confidence": intent.confidence,
            "reason": intent.reason,
            "intent_type": intent.intent_type,
            "urgency": intent.urgency,
            "topic_tags": intent.topic_tags,
            "ts": _now(),
        }

    return out


# ── Auto hand-raise management ────────────────────────────────────────────


def auto_hand_raises(room: Dict[str, Any], intents: List[SpeakIntent]) -> None:
    """Auto-raise hands for high-confidence personas and expire old ones.

    Rules:
      1. Hands raised when confidence >= hand_raise_threshold
      2. Max `max_visible_hands` hands visible at any time
      3. Hands expire after `hand_raise_ttl_rounds` rounds
      4. Expired hands are auto-lowered
      5. Top candidates sorted by (confidence, urgency)
    """
    policy = room.get("policy") or {}
    hr_threshold = float(policy.get("hand_raise_threshold", 0.55))
    ttl = int(policy.get("hand_raise_ttl_rounds", 2))
    max_hands = int(policy.get("max_visible_hands", 3))
    current_round = room.get("round", 0)
    meta: Dict[str, Any] = room.setdefault("hand_raise_meta", {})
    hrs: List[str] = room.setdefault("hand_raises", [])

    # ── Expire old hand raises ──
    expired: List[str] = [
        pid for pid, info in meta.items()
        if info.get("expires_round", 0) <= current_round
    ]
    for pid in expired:
        meta.pop(pid, None)
    room["hand_raises"] = [pid for pid in hrs if pid not in expired]
    hrs = room["hand_raises"]

    if expired:
        logger.debug("Expired %d hand raise(s): %s", len(expired), expired)

    # ── Raise new hands for qualifying intents ──
    existing_hands: Set[str] = set(meta.keys())
    candidates = sorted(
        [
            i for i in intents
            if i.confidence >= hr_threshold
            and i.persona_id not in existing_hands
        ],
        key=lambda x: (x.confidence, x.urgency),
        reverse=True,
    )

    for intent in candidates:
        if len(meta) >= max_hands:
            break
        pid = intent.persona_id
        meta[pid] = {
            "raised_at_round": current_round,
            "expires_round": current_round + ttl,
            "reason": intent.reason,
            "confidence_at_raise": intent.confidence,
            "intent_type": intent.intent_type,
        }
        if pid not in hrs:
            hrs.append(pid)
        logger.debug(
            "Auto hand-raise: %s (confidence=%.2f, expires round %d)",
            pid, intent.confidence, current_round + ttl,
        )


# ── Selection gates ────────────────────────────────────────────────────────


def redundancy_gate(
    intents: List[SpeakIntent],
    selected: List[str],
    threshold: float = 0.7,
) -> List[str]:
    """If two selected speakers have high topic_tags overlap, keep only the top one.

    Prevents two personas from saying essentially the same thing.
    """
    if len(selected) < 2:
        return selected

    intent_map = {i.persona_id: i for i in intents}
    keep = [selected[0]]
    top_tags = set(intent_map[selected[0]].topic_tags) if selected[0] in intent_map else set()

    for pid in selected[1:]:
        their_tags = set(intent_map[pid].topic_tags) if pid in intent_map else set()
        if not top_tags or not their_tags:
            keep.append(pid)
            continue
        overlap = len(top_tags & their_tags) / max(1, len(top_tags | their_tags))
        if overlap < threshold:
            keep.append(pid)
        else:
            logger.debug("Redundancy gate: dropped %s (%.0f%% overlap)", pid, overlap * 100)

    return keep


def diversity_gate(
    selected: List[str],
    participants: List[Dict[str, Any]],
) -> List[str]:
    """Prefer different role-tag combinations among selected speakers.

    If two selected speakers share identical role_tags, drop the second.
    Ensures varied perspectives in multi-speaker events.
    """
    if len(selected) < 2:
        return selected

    p_map = {p["persona_id"]: p for p in participants}
    seen_roles: set = set()
    keep: List[str] = []

    for pid in selected:
        tags = tuple(sorted(p_map.get(pid, {}).get("role_tags", [])))
        if tags and tags in seen_roles:
            logger.debug("Diversity gate: dropped %s (duplicate role tags %s)", pid, tags)
            continue
        if tags:
            seen_roles.add(tags)
        keep.append(pid)

    return keep if keep else selected[:1]


# ── Speaker selection ──────────────────────────────────────────────────────


def select_speakers(
    room: Dict[str, Any],
    intents: List[SpeakIntent],
    participants: List[Dict[str, Any]],
) -> List[str]:
    """
    Returns list of persona_ids that should speak next (0..N).

    Selection depends on turn_mode:
      - moderated: only 'called_on' or first hand-raiser
      - queue: pops from speaker_queue
      - reactive / free-form / round-robin: picks top-scoring intents

    After raw selection, applies redundancy + diversity gates.
    """
    ensure_defaults(room)
    mode = room.get("turn_mode", "reactive")
    policy = room.get("policy") or {}
    max_speakers = int(policy.get("max_speakers_per_event", 2))
    red_threshold = float(policy.get("redundancy_threshold", 0.7))

    # ── Moderated: explicit selection only ────────────────────────
    if mode == "moderated":
        called = room.get("called_on")
        if called:
            return [called]
        hrs = room.get("hand_raises") or []
        return hrs[:max_speakers]

    # ── Queue: FIFO speaker queue ─────────────────────────────────
    if mode == "queue":
        q = room.get("speaker_queue") or []
        speakers = q[:max_speakers]
        room["speaker_queue"] = q[len(speakers):]
        if speakers:
            return speakers
        # Fall through to reactive if queue is empty

    # ── Reactive / free-form / round-robin: score-based ───────────
    if mode == "round-robin":
        candidates = sorted(intents, key=lambda x: x.confidence, reverse=True)
        raw = [c.persona_id for c in candidates[:max_speakers]]
    else:
        # Default reactive: prioritize hand-raisers, then high-confidence
        hrs_set = set(room.get("hand_raises") or [])
        hand_raisers = [i for i in intents if i.persona_id in hrs_set and i.wants_to_speak]
        hand_raisers.sort(key=lambda x: (x.confidence, x.urgency), reverse=True)

        reactive_candidates = [i for i in intents if i.wants_to_speak and i.persona_id not in hrs_set]
        reactive_candidates.sort(key=lambda x: (x.confidence, x.urgency), reverse=True)

        raw = [c.persona_id for c in hand_raisers + reactive_candidates][:max_speakers]

    # ── Fallback: if nobody passed threshold but someone wants to speak,
    #    the top persona still responds.  This ensures greetings like "Hello"
    #    always get at least one reply without forcing speech when all are quiet.
    if not raw and intents:
        willing = [i for i in intents if i.wants_to_speak]
        if willing:
            best = max(willing, key=lambda x: x.confidence)
            raw = [best.persona_id]
            logger.debug("Fallback speaker: %s (score=%.2f, nobody passed threshold)", raw[0], best.confidence)
        elif room.get("messages") and any(m.get("role") == "user" for m in (room.get("messages") or [])[-2:]):
            # Also fallback when the last message was from the human (greeting/question)
            all_sorted = sorted(intents, key=lambda x: x.confidence, reverse=True)
            raw = [all_sorted[0].persona_id]
            logger.debug("Fallback speaker (human prompt): %s (score=%.2f)", raw[0], all_sorted[0].confidence)

    # ── Apply gates ───────────────────────────────────────────────
    selected = redundancy_gate(intents, raw, red_threshold)
    selected = diversity_gate(selected, participants)

    return selected


# ── Main step ──────────────────────────────────────────────────────────────


async def run_reactive_step(
    room_id: str,
    *,
    last_human_message: str,
    participants: List[Dict[str, Any]],
    generate_fn: Callable[[str, Dict[str, Any]], Awaitable[str]],
) -> Dict[str, Any]:
    """
    Run one realistic meeting step:
      - increment round counter
      - tick cooldowns
      - compute intents
      - auto hand-raise (top 3, TTL-based)
      - select speakers (with redundancy + diversity gates)
      - generate spoken text for selected speakers only
      - append to transcript
      - apply cooldowns, consume hands
      - persist

    Args:
        room_id: The room ID.
        last_human_message: The human message triggering this step.
        participants: Normalized participant dicts (from resolve_participants).
        generate_fn: async (persona_id, room_dict) -> str

    Returns:
        {"room": updated_room, "new_messages": [...], "speakers": [...]}
    """
    room = rooms.get_room(room_id)
    if not room:
        raise ValueError("Room not found")

    ensure_defaults(room)

    # Increment round counter
    room["round"] = room.get("round", 0) + 1

    tick_cooldowns(room)

    # 1. Compute intents for all participants
    intents = compute_all_intents(room, participants, last_human_message)

    # 2. Auto hand-raise management (raise new, expire old)
    auto_hand_raises(room, intents)

    # 3. Select who speaks (with gates)
    speakers = select_speakers(room, intents, participants)

    # 4. Generate content for each speaker
    new_messages: List[Dict[str, Any]] = []
    policy = room.get("policy") or {}
    cd_turns = int(policy.get("cooldown_turns", 1))

    for pid in speakers:
        text = (await generate_fn(pid, room)).strip()
        if not text:
            # Retry once: inject a temporary nudge message so the LLM
            # has fresh input to respond to, then clean up.
            logger.warning("Empty response from %s, retrying with nudge", pid)
            nudge_id = str(uuid.uuid4())
            nudge = {
                "id": nudge_id,
                "sender_id": "facilitator",
                "sender_name": "Facilitator",
                "content": "Please share your perspective on the discussion so far.",
                "role": "user",
                "tools_used": [],
                "timestamp": _now(),
            }
            room.setdefault("messages", []).append(nudge)
            text = (await generate_fn(pid, room)).strip()
            # Remove the temporary nudge (keep transcript clean)
            room["messages"] = [m for m in room.get("messages", []) if m.get("id") != nudge_id]
            if not text:
                logger.warning("Empty response from %s after retry, skipping", pid)
                continue

        display_name = _display_name_for(pid, participants)
        msg = {
            "id": str(uuid.uuid4()),
            "sender_id": pid,
            "sender_name": display_name,
            "content": text,
            "role": "assistant",
            "tools_used": [],
            "timestamp": _now(),
        }
        room.setdefault("messages", []).append(msg)
        new_messages.append(msg)
        set_cooldown(room, pid, cd_turns)

        # Consume hand raise when they speak
        hrs = room.get("hand_raises") or []
        if pid in hrs:
            room["hand_raises"] = [x for x in hrs if x != pid]
        room.get("hand_raise_meta", {}).pop(pid, None)

        # Clear called_on after they speak
        if room.get("called_on") == pid:
            room.pop("called_on", None)

    # 5. Persist
    room["updated_at"] = _now()
    rooms.update_room(room_id, {
        "messages": room.get("messages", []),
        "intents": room.get("intents", {}),
        "cooldowns": room.get("cooldowns", {}),
        "hand_raises": room.get("hand_raises", []),
        "hand_raise_meta": room.get("hand_raise_meta", {}),
        "policy": room.get("policy", {}),
        "round": room.get("round", 0),
        "updated_at": room["updated_at"],
    })

    return {
        "room": rooms.get_room(room_id),
        "new_messages": new_messages,
        "speakers": speakers,
    }


def _display_name_for(
    persona_id: str, participants: List[Dict[str, Any]],
) -> str:
    for p in participants:
        if p["persona_id"] == persona_id:
            return p.get("display_name", persona_id)
    return persona_id


# ── Preview (dry-run, no side effects) ───────────────────────────────────


def preview_next_turn(
    room_id: str,
    *,
    trigger_message: str,
    participants: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Preview who would speak next WITHOUT executing anything.
    Returns explainable candidate list (BG3-style initiative order).

    No side effects: does not modify room state, messages, or cooldowns.
    """
    room = rooms.get_room(room_id)
    if not room:
        raise ValueError("Room not found")

    # Work on a shallow copy to avoid side effects
    import copy
    room = copy.deepcopy(room)
    ensure_defaults(room)

    # Compute intents (no persistence)
    intents = compute_all_intents(room, participants, trigger_message)

    # Build candidate list with scores + reasons
    hrs_set = set(room.get("hand_raises") or [])
    called = room.get("called_on")

    candidates = []
    for intent in intents:
        pid = intent.persona_id
        reasons: List[str] = []
        if called and pid == called:
            reasons.append("called_on")
        if pid in hrs_set:
            reasons.append("hand_raise")
        if intent.wants_to_speak:
            reasons.append("wants_to_speak")
        if intent.reason and intent.reason != "listening":
            reasons.extend(intent.reason.split(", "))

        status = "called_on" if (called and pid == called) else \
                 "hand_raise" if pid in hrs_set else \
                 "auto" if intent.wants_to_speak else "waiting"

        candidates.append({
            "persona_id": pid,
            "display_name": _display_name_for(pid, participants),
            "score": intent.confidence,
            "urgency": intent.urgency,
            "intent_type": intent.intent_type,
            "reasons": list(set(reasons)),
            "status": status,
        })

    # Sort: called_on first, then hand_raisers, then by score
    candidates.sort(
        key=lambda c: (
            c["status"] == "called_on",
            c["status"] == "hand_raise",
            c["score"],
        ),
        reverse=True,
    )

    # Determine who would be selected
    selected = select_speakers(room, intents, participants)

    return {
        "candidates": candidates,
        "selected": selected,
        "selected_names": [_display_name_for(pid, participants) for pid in selected],
        "turn_mode": room.get("turn_mode", "reactive"),
        "round": room.get("round", 0),
    }
