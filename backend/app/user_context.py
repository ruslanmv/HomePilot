"""
User context builder — optional helper (v1).

Turns profile + memory into a compact text block suitable for injection
into AI system prompts.  This module is purely a library function — it
does NOT change any existing prompt-building logic until explicitly wired in.
"""
from __future__ import annotations

from typing import Any, Dict, List


def build_user_context_for_ai(
    profile: Dict[str, Any],
    memory: Dict[str, Any],
    *,
    nsfw_mode: bool,
) -> str:
    """Return a human-readable context block for the AI system prompt."""
    p = profile or {}
    mem_items = (memory or {}).get("items", [])

    # Prioritise pinned items, then sort by importance
    pinned = [m for m in mem_items if m.get("pinned")]
    rest = [m for m in mem_items if not m.get("pinned")]
    rest.sort(key=lambda x: int(x.get("importance", 2)), reverse=True)
    chosen = (pinned + rest)[:10]

    lines: List[str] = []
    lines.append("USER PROFILE (user-provided):")
    if p.get("preferred_name") or p.get("display_name"):
        lines.append(f"- Name: {p.get('preferred_name') or p.get('display_name')}")
    if p.get("preferred_pronouns"):
        lines.append(f"- Pronouns: {p.get('preferred_pronouns')}")
    lines.append(f"- Tone: {p.get('preferred_tone', 'neutral')}")
    lines.append(f"- Companion mode: {'enabled' if p.get('companion_mode_enabled') else 'disabled'}")
    lines.append(f"- Affection level: {p.get('affection_level', 'friendly')}")
    lines.append(f"- Global NSFW mode: {'ON' if nsfw_mode else 'OFF'}")

    if nsfw_mode:
        lines.append(f"- Preferred spicy strength: {p.get('default_spicy_strength', 0.30)}")
        if p.get("allowed_content_tags"):
            lines.append(f"- Allowed content tags: {', '.join(p.get('allowed_content_tags'))}")
        if p.get("blocked_content_tags"):
            lines.append(f"- Blocked content tags: {', '.join(p.get('blocked_content_tags'))}")

    if p.get("hard_boundaries"):
        lines.append(f"- Hard boundaries: {', '.join(p.get('hard_boundaries'))}")
    if p.get("sensitive_topics"):
        lines.append(f"- Sensitive topics: {', '.join(p.get('sensitive_topics'))}")
    if p.get("likes"):
        lines.append(f"- Likes: {', '.join(p.get('likes'))}")
    if p.get("dislikes"):
        lines.append(f"- Dislikes: {', '.join(p.get('dislikes'))}")

    lines.append("")
    lines.append("MEMORY (user-approved):")
    if not chosen:
        lines.append("- (none)")
    else:
        for m in chosen:
            lines.append(f"- {m.get('text')}")

    return "\n".join(lines)
