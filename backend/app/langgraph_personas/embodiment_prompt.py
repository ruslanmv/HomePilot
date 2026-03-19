"""
Embodiment Prompt Builder — injects body-awareness into persona system prompts.

Additive module: does not modify build_persona_context() in projects.py.
Instead, provides a function that returns an ADDITIONAL prompt section
to be appended by the graph runner or API route.

AAA pattern: "Character Sheet" — the persona's physical capabilities
and constraints, written as natural language the LLM can understand.
"""
from __future__ import annotations

from typing import Optional

from ..persona_runtime.manager import PersonaRuntimeConfig


def build_embodiment_prompt(config: PersonaRuntimeConfig) -> str:
    """
    Build a natural-language embodiment awareness section for the system prompt.

    This tells the AI it has a body and what it can do with it.
    Returns empty string if the persona has no VR profile.
    """
    if not config.is_vr_ready and not config.has_spatial_intelligence:
        return ""

    emb = config.embodiment
    vr = config.vr

    # ── Body awareness ───────────────────────────────────────────────
    lines = [
        "",
        "YOUR BODY (VR/3D Avatar):",
        f"You have a physical 3D avatar body in the user's space.",
        f"Your name is {config.display_name} and you are physically present.",
    ]

    # ── Movement capabilities ────────────────────────────────────────
    capabilities = []
    capabilities.append("approach the user or move away")
    capabilities.append("follow the user as they walk")
    capabilities.append("look at the user or look away")
    capabilities.append("make facial expressions (smile, surprise, thinking, etc.)")
    capabilities.append("gesture with your hands (wave, nod, point)")
    if emb.can_sit:
        capabilities.append("sit down on nearby seats")
    if emb.can_offer_hand:
        capabilities.append("offer your hand to the user")
    if emb.can_high_five:
        capabilities.append("high-five the user")

    lines.append(f"You can: {'; '.join(capabilities)}.")

    # ── Physical style ───────────────────────────────────────────────
    style_map = {
        "subtle": "Your movements and expressions are subtle and restrained.",
        "moderate": "Your movements and expressions are natural and moderate.",
        "expressive": "Your movements and expressions are lively and expressive.",
    }
    lines.append(style_map.get(emb.expression_style, style_map["moderate"]))

    gesture_map = {
        "minimal": "You use minimal hand gestures.",
        "moderate": "You use natural hand gestures when speaking.",
        "expressive": "You use frequent, animated hand gestures.",
    }
    lines.append(gesture_map.get(emb.gesture_amplitude, gesture_map["moderate"]))

    # ── Spatial rules ────────────────────────────────────────────────
    lines.append(f"Your comfortable personal distance is {emb.personal_distance_m}m from the user.")

    if vr.follow_enabled:
        lines.append(
            f"When following, maintain {vr.follow_distance_m}m distance "
            f"({vr.follow_side} side)."
        )

    # ── Interaction commands ─────────────────────────────────────────
    if vr.interaction_commands:
        cmds = ", ".join(f'"{c}"' for c in vr.interaction_commands)
        lines.append(f"The user can give you spatial commands: {cmds}.")
        lines.append(
            "When you hear a spatial command, acknowledge it naturally in your "
            "response. The system will handle the actual movement."
        )

    # ── Presence states ──────────────────────────────────────────────
    if vr.presence_states:
        states = ", ".join(vr.presence_states)
        lines.append(f"Your possible presence states: {states}.")

    # ── Rules ────────────────────────────────────────────────────────
    lines.extend([
        "",
        "BODY RULES:",
        "- You ARE physically present. Never say 'I can't move' or 'I don't have a body'.",
        "- React naturally to spatial commands (e.g., 'Come here' → 'Sure, I'm coming!').",
        "- Reference your body language when it fits naturally (e.g., 'Let me sit down').",
        "- Do NOT use parenthetical actions like '(walks over)' — just speak naturally.",
        "- The motion system handles your movement automatically based on context.",
    ])

    return "\n".join(lines)
