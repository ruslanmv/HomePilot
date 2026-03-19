"""
Perceive Node — gathers context before reasoning.

AAA pattern: "Perception System" — collects world state, memory, and
sensory input into a unified context the AI can reason about.
Runs BEFORE the think node so the LLM has full situational awareness.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import PersonaAgentState

logger = logging.getLogger(__name__)


async def perceive(state: PersonaAgentState) -> Dict[str, Any]:
    """
    Build a perception summary from world state and conversation context.

    This node is lightweight and never calls an LLM — it structures
    raw sensor data into a natural-language context block that the
    think node can consume.
    """
    parts: list[str] = []

    # ── World state perception ───────────────────────────────────────
    ws = state.get("world_snapshot") or {}
    if ws:
        avatar_dist = ws.get("avatar_distance_m")
        if avatar_dist is not None:
            proximity = (
                "very close" if avatar_dist < 0.8
                else "nearby" if avatar_dist < 2.0
                else "at a distance" if avatar_dist < 5.0
                else "far away"
            )
            parts.append(f"The user is {proximity} ({avatar_dist:.1f}m away).")

        vel = ws.get("user_velocity_mps", 0.0)
        if vel > 0.5:
            parts.append(f"The user is moving ({vel:.1f} m/s).")
        elif vel > 0.1:
            parts.append("The user is shifting slightly.")

        user_hands = []
        if ws.get("user_left_hand"):
            user_hands.append("left")
        if ws.get("user_right_hand"):
            user_hands.append("right")
        if user_hands:
            parts.append(f"User hands visible: {', '.join(user_hands)}.")

        anchors = ws.get("anchors", [])
        if anchors:
            seat_count = sum(1 for a in anchors if a.get("type") == "seat")
            if seat_count:
                parts.append(f"There {'is' if seat_count == 1 else 'are'} {seat_count} seat(s) in the room.")

        avatar_state = ws.get("avatar_state", "idle")
        parts.append(f"Your current state: {avatar_state}.")

    # ── Conversation context ─────────────────────────────────────────
    history = state.get("conversation_history", [])
    if history:
        turn_count = len([m for m in history if m.get("role") == "user"])
        parts.append(f"Conversation turn #{turn_count + 1}.")

    # ── Embodiment awareness ─────────────────────────────────────────
    parts.append(f"Your personal distance preference: {state.get('personal_distance_m', 1.2)}m.")

    perception = " ".join(parts) if parts else "No spatial context available."

    logger.debug("[perceive] %s", perception)

    return {
        "perception_summary": perception,
        "avatar_state": "thinking",
    }
