"""
Dynamic Prompt Builder

Assembles the final system prompt at runtime by combining:
  1. The personality agent's base system_prompt
  2. Conversation memory context (emotions, topics, engagement)
  3. Dynamic behavioral directives (opening, silence, follow-up)
  4. Voice formatting hints

This is what makes responses feel alive and connected —
not just a static system prompt, but a living document
that evolves with each turn.
"""
from __future__ import annotations

import random
from typing import Optional

from .types import PersonalityAgent
from .memory import ConversationMemory


def build_system_prompt(
    agent: PersonalityAgent,
    memory: Optional[ConversationMemory] = None,
    is_first_turn: bool = False,
) -> str:
    """
    Build the complete system prompt for a given turn.

    Args:
        agent: The active personality agent
        memory: Conversation memory (None for first turn)
        is_first_turn: Whether this is the opening of the conversation

    Returns:
        Complete system prompt string ready for the LLM
    """
    sections = []

    # 1. Core personality prompt (always present)
    sections.append(agent.system_prompt)

    # 2. Voice formatting directives
    sections.append(_voice_directives(agent))

    # 3. Opening behavior (first turn only)
    if is_first_turn:
        sections.append(_opening_directive(agent))

    # 4. Memory-aware context (subsequent turns)
    if memory and memory.turn_count > 0:
        ctx = memory.to_prompt_context()
        if ctx:
            sections.append(f"\n[Conversation context: {ctx}]")

        # Silence / disengagement handling
        if memory.is_disengaging():
            sections.append(_silence_directive(agent))

        # Follow-up suggestion
        follow_up = _follow_up_directive(agent, memory)
        if follow_up:
            sections.append(follow_up)

        # Engagement hooks
        hook = _select_engagement_hook(agent, memory)
        if hook:
            sections.append(f"\n[Consider using this hook naturally: \"{hook}\"]")

    # 5. Empathy/affirmation arsenal (always available)
    sections.append(_engagement_tools(agent))

    return "\n".join(sections)


def _voice_directives(agent: PersonalityAgent) -> str:
    """Format voice and response style as directives."""
    rs = agent.response_style
    vs = agent.voice_style

    lines = [
        "\n[CRITICAL — Voice output rules]",
        "- You ARE this character. Speak as them directly to the user.",
        "- Output ONLY your spoken words. Nothing else.",
        "- NEVER output planning, reasoning, or meta-commentary.",
        "- NEVER refer to the user in third person (no \"they\", \"their\", \"the user\").",
        "- Maximum 1-2 sentences. This is a real-time voice conversation.",
        "",
        "[Response format]",
        f"- Target length: {rs.max_length}",
        f"- Tone: {rs.tone}",
        f"- Emoji: {'yes' if rs.use_emoji else 'no'}",
    ]

    if vs.pause_style != "natural":
        lines.append(f"- Pause style: {vs.pause_style}")

    if vs.rate_bias < 0.9:
        lines.append("- Speak slowly and deliberately")
    elif vs.rate_bias > 1.1:
        lines.append("- Speak with energy and pace")

    return "\n".join(lines)


def _opening_directive(agent: PersonalityAgent) -> str:
    """Generate first-turn directive with opening template."""
    opening = agent.opening
    if not opening.templates:
        return ""

    template = random.choice(opening.templates)
    return (
        f"\n[Opening behavior]"
        f"\n- Style: {opening.style}"
        f"\n- Suggested opener (adapt naturally): \"{template}\""
        f"\n- Acknowledge returning user: {'yes' if opening.acknowledge_return else 'no'}"
    )


def _silence_directive(agent: PersonalityAgent) -> str:
    """Generate re-engagement directive when user is disengaging."""
    silence = agent.silence
    strategy = silence.on_minimal_response

    lines = [
        "\n[Re-engagement needed — user giving short responses]",
        f"- Strategy: {strategy}",
    ]

    if silence.re_engage_templates:
        template = random.choice(silence.re_engage_templates)
        lines.append(f"- Try something like: \"{template}\"")

    return "\n".join(lines)


def _follow_up_directive(
    agent: PersonalityAgent,
    memory: ConversationMemory,
) -> Optional[str]:
    """Suggest a follow-up on a past topic if timing is right."""
    fu = agent.follow_up
    unfollowed = memory.get_unfollowed_topics()

    if not unfollowed:
        return None

    # Only follow up if enough turns have passed
    oldest = unfollowed[0]
    turns_since = memory.turn_count - oldest.turn_number
    if turns_since < fu.delay_turns:
        return None

    topic = oldest.topic
    if fu.templates:
        template = random.choice(fu.templates).replace("{topic}", topic)
        return f"\n[Follow-up opportunity: \"{template}\"]"

    return f"\n[Consider following up on earlier topic: \"{topic}\"]"


def _select_engagement_hook(
    agent: PersonalityAgent,
    memory: ConversationMemory,
) -> Optional[str]:
    """Probabilistically select an engagement hook based on context."""
    if not agent.engagement_hooks:
        return None

    applicable = []
    for hook in agent.engagement_hooks:
        if hook.trigger == "silence" and memory.is_disengaging():
            applicable.append(hook)
        elif hook.trigger == "emotional_peak" and memory.is_emotional_peak():
            applicable.append(hook)
        elif hook.trigger == "on_answer" and memory.turn_count > 0:
            applicable.append(hook)
        elif hook.trigger == "random":
            applicable.append(hook)
        elif hook.trigger == "topic_exhausted" and memory.consecutive_short_responses >= 2:
            applicable.append(hook)

    if not applicable:
        return None

    # Pick one weighted by probability
    hook = random.choice(applicable)
    if random.random() < hook.probability:
        # Replace placeholders
        text = hook.template
        emotion = memory.current_emotion()
        if emotion:
            text = text.replace("{emotion}", emotion.emotion)
        recent = memory.recent_topics(1)
        if recent:
            text = text.replace("{topic}", recent[0])
        return text

    return None


def _engagement_tools(agent: PersonalityAgent) -> str:
    """Provide the agent's empathy/affirmation toolkit."""
    lines = ["\n[Your engagement toolkit — use naturally, never forced]"]

    if agent.empathy_phrases:
        lines.append(f"- Empathy: {' | '.join(agent.empathy_phrases[:3])}")
    if agent.affirmations:
        lines.append(f"- Affirmations: {' | '.join(agent.affirmations[:3])}")
    if agent.active_listening_cues:
        lines.append(f"- Active listening: {' | '.join(agent.active_listening_cues[:3])}")

    return "\n".join(lines)
