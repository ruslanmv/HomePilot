# backend/app/teams/continuation.py
"""
Context-Aware Continuation Engine — smart trigger generation.

When no human sends a new message, generates a context-rich trigger
string used ONLY for intent scoring (deciding who speaks next).
The trigger is NEVER injected into the room transcript.

The LLM already sees other personas' messages as user-role input
via build_chat_messages, so no injection is needed for response generation.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("homepilot.teams.continuation")


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


def _reaction_trigger(speaker_name: str, content: str) -> str:
    """Generate trigger that invites reaction to what was just said."""
    topics = _extract_topics(content)
    topic_phrase = ", ".join(topics[:3]) if topics else "the current discussion"
    prompts = [
        f"{speaker_name} mentioned {topic_phrase}. What do others think?",
        f"Building on {speaker_name}'s point about {topic_phrase} — any other perspectives?",
        f"{speaker_name} raised {topic_phrase}. How does this affect our approach?",
    ]
    return random.choice(prompts)


def _explore_trigger(topic: str) -> str:
    """Generate trigger to explore the main topic."""
    prompts = [
        f"Let's discuss {topic}. What are the key challenges?",
        f"Regarding {topic} — what should we address first?",
        f"Everyone's input on {topic} — what should our strategy be?",
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
            f"On {focus} — any risks we haven't addressed?",
            f"Good progress on {focus}. What are the concrete next steps?",
            f"Where do we stand on {focus}? What's still open?",
        ]
        return random.choice(prompts)
    elif topic:
        return f"Let's go deeper on {topic}. What are the trade-offs we need to weigh?"
    else:
        return "What aspects of this discussion need more attention? Are there any open questions?"


# ── Main API ──────────────────────────────────────────────────────────────


def _task_anchor_trigger(topic: str, agenda: List[str], msgs: List[Dict[str, Any]]) -> str:
    """Build a task-anchored trigger that keeps discussion on track.

    Instead of reacting to the last poetic sentence, re-grounds the
    conversation in the original task / topic / agenda.
    """
    covered = _find_covered_agenda_items(msgs, agenda) if agenda else set()
    uncovered = [a for i, a in enumerate(agenda) if i not in covered]

    parts: List[str] = []
    if topic:
        parts.append(f"Remember, our goal is: {topic}.")
    if uncovered:
        parts.append(f"Next agenda item: {uncovered[0]}.")
    elif agenda and not uncovered:
        parts.append("All agenda items covered. What concrete next steps should we take?")

    parts.append("Add a NEW specific detail, step, or alternative — do NOT repeat or recap what was already said.")
    return " ".join(parts)


def _play_anchor_trigger(topic: str, msgs: List[Dict[str, Any]]) -> str:
    """Build a topic-anchored trigger for general play mode conversations.

    Prevents trigger chaining (where the last recap becomes the next trigger)
    by always anchoring to the original topic.
    """
    parts: List[str] = []
    if topic:
        parts.append(f"The topic is: {topic}.")
    else:
        parts.append("Continue the conversation naturally.")

    # Mention what was discussed so far to encourage NEW angles
    recent_topics = _extract_topics(
        " ".join(m.get("content", "") for m in msgs[-3:] if m.get("role") == "assistant")
    )
    if recent_topics:
        parts.append(f"Already discussed: {', '.join(recent_topics[:4])}.")
    parts.append("Respond with a NEW thought, question, or perspective — do NOT summarize or recap.")
    return " ".join(parts)


def generate_smart_trigger(
    room: Dict[str, Any],
    participants: List[Dict[str, Any]],
) -> str:
    """Generate a context-aware trigger for intent scoring.

    Used ONLY for the `last_human_message` parameter in run_reactive_step.
    Never injected into the transcript. Never seen by the LLM.
    """
    msgs = room.get("messages") or []
    topic = (
        room.get("topic")
        or room.get("description")
        or room.get("name")
        or ""
    )
    agenda = room.get("agenda") or []
    phase = _conversation_phase(msgs)

    # ── Play Mode: always use topic-anchored triggers ─────────────
    # Prevents trigger chaining where the last assistant message's recap
    # becomes the next trigger, causing runaway repetition loops.
    _task_indicators = [
        "plan", "step-by-step", "step by step", "draft", "design",
        "outline", "create", "organize", "prepare", "budget",
        "schedule", "proposal", "strategy", "build",
    ]
    play_mode = room.get("play_mode") or {}
    is_playing = play_mode.get("enabled", False)
    combined = f"{topic} ".lower()
    # Also check the original human message for task words
    for m in msgs:
        if m.get("role") == "user" and m.get("sender_id") != "system":
            combined += (m.get("content") or "").lower() + " "
            break
    is_task = any(w in combined for w in _task_indicators)

    # In Play Mode, ALWAYS use topic-anchored triggers (not just tasks)
    # to prevent recap/mirroring loops from trigger chaining.
    if is_playing and phase != "opening":
        if is_task:
            trigger = _task_anchor_trigger(topic, agenda, msgs)
        else:
            trigger = _play_anchor_trigger(topic, msgs)
        # Still invite quiet participants
        quiet = _find_quiet_participants(msgs, participants)
        if quiet and random.random() < 0.4:
            p = random.choice(quiet)
            trigger += f" {p.get('display_name', 'someone')}, what's your input?"
        logger.debug("Continuation: anchored trigger (play mode, task=%s)", is_task)
        return trigger

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
