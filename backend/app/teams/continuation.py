# backend/app/teams/continuation.py
"""
Context-Aware Continuation Engine — smart trigger generation for autonomous conversation.

When no human sends a new message, this module analyzes room state
(topic, agenda, conversation history, participant roles) to generate
a contextual trigger that:
  1. Gives the intent scorer keywords to match persona roles
  2. Gives the LLM a clear direction for what to say next
  3. Keeps conversation natural and progressing through the agenda

Optional system — disabled by default for manual /react calls.
Automatically active during Play Mode.

Used by:
  - play_mode._play_loop() (autonomous conversation — always on)
  - routes.py /react endpoint (only when smart_continuation is enabled)
"""
from __future__ import annotations

import logging
import random
import re
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("homepilot.teams.continuation")

# Sender ID for continuation messages (distinguishable from human/persona/system)
CONTINUATION_SENDER_ID = "facilitator"


# ── Text helpers ──────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


_STOP_WORDS = frozenset({
    "that", "this", "with", "from", "have", "been", "were", "will",
    "what", "when", "where", "which", "while", "about", "their",
    "there", "would", "could", "should", "other", "after", "before",
    "between", "through", "during", "each", "some", "such", "only",
    "also", "than", "then", "very", "just", "into", "over", "like",
    "more", "most", "your", "them", "they", "these", "those",
    "being", "does", "doing", "going", "make", "made", "keep",
    "lets", "well", "good", "much", "still", "back", "need",
    "think", "know", "want", "even", "here", "come", "take",
    "said", "says", "tell", "told", "talk", "point", "right",
    "really", "great", "sure", "okay", "agree", "yeah",
})


def _extract_topics(text: str) -> List[str]:
    """Extract meaningful topic words from text."""
    words = re.findall(r"[a-zA-Z]{4,}", _normalize(text))
    seen: set = set()
    out: List[str] = []
    for w in words:
        if w not in _STOP_WORDS and w not in seen:
            out.append(w)
            seen.add(w)
    return out[:8]


# ── Conversation analysis ─────────────────────────────────────────────────


def _find_covered_agenda_items(
    messages: List[Dict[str, Any]],
    agenda: List[str],
) -> set:
    """Find which agenda items have been discussed (by keyword overlap)."""
    all_text = " ".join(
        _normalize(m.get("content", ""))
        for m in messages
        if m.get("role") == "assistant"
    )
    covered = set()
    for i, item in enumerate(agenda):
        item_words = set(re.findall(r"[a-zA-Z]{4,}", _normalize(item)))
        if not item_words:
            continue
        overlap = sum(1 for w in item_words if w in all_text)
        if overlap / max(1, len(item_words)) > 0.4:
            covered.add(i)
    return covered


def _find_quiet_participants(
    messages: List[Dict[str, Any]],
    participants: List[Dict[str, Any]],
    lookback: int = 10,
) -> List[Dict[str, Any]]:
    """Find participants who haven't spoken in recent messages."""
    recent = messages[-lookback:] if messages else []
    recent_speakers = {
        m.get("sender_id") for m in recent if m.get("role") == "assistant"
    }
    return [p for p in participants if p["persona_id"] not in recent_speakers]


def _last_assistant_message(
    messages: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Get the last assistant (persona) message."""
    for m in reversed(messages):
        if m.get("role") == "assistant":
            return m
    return None


def _conversation_phase(messages: List[Dict[str, Any]]) -> str:
    """Determine conversation phase: opening, developing, or mature."""
    assistant_count = sum(1 for m in messages if m.get("role") == "assistant")
    if assistant_count < 3:
        return "opening"
    if assistant_count < 12:
        return "developing"
    return "mature"


# ── Strategy builders ─────────────────────────────────────────────────────


def _agenda_trigger(uncovered_item: str, topic: str) -> str:
    """Generate trigger to advance to next agenda item."""
    prompts = [
        f"Let's move to the next agenda item: {uncovered_item}. What are your thoughts on this?",
        f"Moving on — the next topic is: {uncovered_item}. Who would like to start?",
        (
            f"We should discuss: {uncovered_item}. How does this relate to our overall goal of {topic}?"
            if topic
            else f"Next up: {uncovered_item}. What considerations should we keep in mind?"
        ),
    ]
    return random.choice(prompts)


def _reaction_trigger(speaker_name: str, content: str, topic: str) -> str:
    """Generate trigger that invites reaction to what was just said."""
    topics = _extract_topics(content)
    topic_phrase = ", ".join(topics[:3]) if topics else "the current discussion"
    prompts = [
        f"{speaker_name} brought up {topic_phrase}. Does anyone have a different perspective or additional insights?",
        f"Interesting points from {speaker_name} about {topic_phrase}. How does this affect our approach?",
        f"Building on {speaker_name}'s comments about {topic_phrase} — what are the implications?",
    ]
    return random.choice(prompts)


def _explore_trigger(topic: str) -> str:
    """Generate trigger to explore the main topic."""
    prompts = [
        f"Let's dive into {topic}. What are the key challenges and opportunities we should consider?",
        f"Regarding {topic} — what's the most important aspect to address first?",
        f"I'd like everyone's input on {topic}. What should our strategy be?",
    ]
    return random.choice(prompts)


def _invite_trigger(participant: Dict[str, Any], recent_topic: str) -> str:
    """Generate trigger inviting a quiet participant to speak."""
    name = participant.get("display_name", "someone")
    role_tags = participant.get("role_tags") or []
    role = role_tags[0] if role_tags else ""

    if role and recent_topic:
        return f"{name}, from a {role} perspective, what do you think about {recent_topic}?"
    elif role:
        return f"{name}, as our {role} expert, what insights can you share?"
    elif recent_topic:
        return f"{name}, we'd love to hear your thoughts on {recent_topic}."
    else:
        return f"{name}, what's your take on this discussion so far?"


def _deepening_trigger(messages: List[Dict[str, Any]], topic: str) -> str:
    """Generate trigger to deepen discussion on a mature topic."""
    topics: List[str] = []
    for m in messages[-5:]:
        if m.get("role") == "assistant":
            topics.extend(_extract_topics(m.get("content", "")))
    # Deduplicate while preserving order
    seen: set = set()
    unique: List[str] = []
    for t in topics:
        if t not in seen:
            unique.append(t)
            seen.add(t)

    if unique:
        focus = ", ".join(unique[:2])
        prompts = [
            f"We've been discussing {focus}. Are there any risks or concerns we haven't addressed?",
            f"Good progress on {focus}. What are the concrete next steps and who should take the lead?",
            f"Let's evaluate where we stand on {focus}. What decisions are still open?",
        ]
        return random.choice(prompts)
    elif topic:
        return f"Let's go deeper on {topic}. What are the trade-offs we need to weigh?"
    else:
        return "What aspects of this discussion need more attention? Are there any open questions?"


# ── Style-specific modifiers ──────────────────────────────────────────────

_STYLE_PREFIXES: Dict[str, str] = {
    "debate": "Let's hear the opposing view. ",
    "simulation": "In this scenario, ",
}


# ── Main API ──────────────────────────────────────────────────────────────


def generate_smart_trigger(
    room: Dict[str, Any],
    participants: List[Dict[str, Any]],
) -> str:
    """
    Generate a context-aware trigger message for autonomous conversation.

    Analyzes room topic, agenda, conversation history, participant roles,
    and play mode style to produce a rich trigger that:
      - The intent scorer can match keywords against (role triggers, names)
      - The LLM has clear direction on what to say

    Returns a trigger string. Never returns empty.
    """
    msgs = room.get("messages") or []
    topic = (
        room.get("topic")
        or room.get("description")
        or room.get("name")
        or ""
    )
    agenda = room.get("agenda") or []
    style = (room.get("play_mode") or {}).get("style", "discussion")
    phase = _conversation_phase(msgs)

    trigger = ""

    # ── Strategy 1: Agenda progression (developing/mature) ────────
    if agenda and phase != "opening":
        covered = _find_covered_agenda_items(msgs, agenda)
        uncovered = [a for i, a in enumerate(agenda) if i not in covered]
        if uncovered:
            trigger = _agenda_trigger(uncovered[0], topic)
            logger.debug("Continuation: agenda → '%s'", uncovered[0])

    # ── Strategy 2: React to last speaker ─────────────────────────
    if not trigger and msgs:
        last_asst = _last_assistant_message(msgs)
        if last_asst:
            trigger = _reaction_trigger(
                last_asst.get("sender_name", "Someone"),
                last_asst.get("content", ""),
                topic,
            )
            logger.debug(
                "Continuation: react to %s", last_asst.get("sender_name")
            )

    # ── Strategy 3: Invite quiet participant (30% chance in developing) ──
    if not trigger or (phase == "developing" and random.random() < 0.3):
        quiet = _find_quiet_participants(msgs, participants)
        if quiet:
            p = random.choice(quiet)
            recent_topics = _extract_topics(
                msgs[-1].get("content", "") if msgs else topic
            )
            recent_topic = ", ".join(recent_topics[:2]) if recent_topics else topic
            invite = _invite_trigger(p, recent_topic)
            if not trigger:
                trigger = invite
                logger.debug(
                    "Continuation: invite %s", p.get("display_name")
                )
            else:
                trigger = f"{trigger} {invite}"

    # ── Strategy 4: Topic exploration (opening phase) ─────────────
    if not trigger and phase == "opening" and topic:
        trigger = _explore_trigger(topic)
        logger.debug("Continuation: topic exploration")

    # ── Strategy 5: Deepening (mature conversation) ───────────────
    if not trigger and phase == "mature":
        trigger = _deepening_trigger(msgs, topic)
        logger.debug("Continuation: deepening")

    # ── Style prefix ──────────────────────────────────────────────
    prefix = _STYLE_PREFIXES.get(style, "")
    if prefix and trigger:
        trigger = prefix + trigger

    # ── Fallback (never return empty) ─────────────────────────────
    if not trigger:
        if topic:
            trigger = (
                f"Let's continue discussing {topic}. "
                "What should we address next?"
            )
        else:
            trigger = (
                "What should we discuss next? "
                "Are there any open topics or questions?"
            )
        logger.debug("Continuation: fallback")

    return trigger


def needs_continuation(room: Dict[str, Any]) -> bool:
    """Check if the room needs a continuation message.

    Returns True when the last message is NOT from a human — meaning there's
    no fresh human input for the intent scorer or LLM to work with.
    """
    msgs = room.get("messages") or []
    if not msgs:
        return True
    last = msgs[-1]
    # Fresh human input exists — no continuation needed
    if last.get("sender_id") == "human" and last.get("role") == "user":
        return False
    return True


def inject_continuation_message(
    room_id: str,
    room: Dict[str, Any],
    trigger: str,
) -> Dict[str, Any]:
    """Inject a facilitator continuation message into the room transcript.

    The message appears as a 'user' role so the LLM treats it as new input.
    Uses CONTINUATION_SENDER_ID so it can be identified/filtered.

    Returns the injected message dict.
    """
    from . import rooms as rooms_mod

    msg = {
        "id": str(uuid.uuid4()),
        "sender_id": CONTINUATION_SENDER_ID,
        "sender_name": "Facilitator",
        "content": trigger,
        "role": "user",
        "tools_used": [],
        "timestamp": time.time(),
    }
    msgs = room.get("messages") or []
    msgs.append(msg)
    rooms_mod.update_room(room_id, {"messages": msgs})
    return msg


def is_continuation_message(msg: Dict[str, Any]) -> bool:
    """Check if a message is a continuation/facilitator message."""
    return msg.get("sender_id") == CONTINUATION_SENDER_ID
