"""
Persona profile loader for Persona Live Play prompts.

Reads a persona project (via ``app.projects.get_project_by_id``)
and normalises its sprawling JSON shape into the flat variable
bundle the ``personaplay.*`` prompts declare. Keeping this in one
place means the prompt YAMLs don't have to know anything about how
a persona is stored on disk.

The loader is deliberately tolerant: every field has a sensible
default, so a half-populated persona (e.g. one with no backstory
yet) still renders a usable prompt. The one signal we always honour
is ``safety.allow_explicit`` — that's the gate between PG-13 and
spicy, and never gets a silent default.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


_DEFAULT_DURATION = 5


def load_persona_prompt_vars(
    persona_project_id: str,
    *,
    persona_label: str = "",
    persona_emotion: str = "neutral",
    affinity_score: float = 0.0,
    synopsis: str = "",
    viewer_message: str = "",
    intent_hint: str = "",
    duration_sec: int = _DEFAULT_DURATION,
) -> Optional[Dict[str, Any]]:
    """Return a flat dict of variables for the personaplay prompts.

    ``None`` is returned when the persona project can't be found or
    isn't a persona project — the caller falls back to the generic
    composer without surfacing an error to the viewer.

    ``persona_label`` is a last-resort fallback for the display
    name: the experience carries it in ``audience_profile``, and we
    use it when the linked persona project has been deleted.
    """
    project = _lookup_persona(persona_project_id)
    if project is None:
        if not persona_label:
            return None
        # Persona project gone, but the experience remembered the
        # label — render a minimal prompt off just that so the
        # opener isn't an empty "I am ." sentence.
        return _minimal_vars(
            persona_label=persona_label,
            persona_emotion=persona_emotion,
            affinity_score=affinity_score,
            synopsis=synopsis,
            viewer_message=viewer_message,
            intent_hint=intent_hint,
            duration_sec=duration_sec,
        )

    persona_agent = project.get("persona_agent") or {}
    appearance = project.get("persona_appearance") or {}
    agentic = project.get("agentic") or {}
    safety = persona_agent.get("safety") or {}
    response_style = persona_agent.get("response_style") or {}

    name = (
        persona_label
        or persona_agent.get("label")
        or project.get("name")
        or "Persona"
    )
    role = _first_nonempty(
        persona_agent.get("role"),
        _class_label(persona_agent.get("persona_class")),
    )
    objective = _first_nonempty(
        agentic.get("goal"),
        project.get("instructions"),
        project.get("description"),
    )
    backstory = _first_nonempty(
        persona_agent.get("system_prompt"),
        project.get("instructions"),
        project.get("description"),
    )
    traits = _join_list(persona_agent.get("unique_behaviors")) or _join_list(
        persona_agent.get("key_techniques")
    )
    tone = _first_nonempty(response_style.get("tone"), "warm, professional")
    style = _first_nonempty(
        appearance.get("style_preset"),
        persona_agent.get("image_style_hint"),
    )
    outfit = _outfit_sentence(appearance)
    allow_explicit = bool(safety.get("allow_explicit", False))

    return {
        "persona_name": name,
        "persona_role": role or "Companion",
        "persona_objective": objective or "Engage the viewer in conversation.",
        "persona_traits": traits or "attentive, responsive, consistent",
        "persona_tone": tone,
        "persona_style": style or "natural, grounded",
        "persona_backstory": backstory or "No additional backstory.",
        "persona_outfit": outfit or "casual, current wardrobe",
        "persona_emotion": persona_emotion or "neutral",
        "allow_explicit": "true" if allow_explicit else "false",
        "affinity_tier": _affinity_tier(affinity_score),
        "affinity_pct": int(max(0.0, min(1.0, affinity_score)) * 100),
        "synopsis": synopsis or "(this is the first turn)",
        "viewer_message": viewer_message or "(no message yet)",
        "intent_hint": intent_hint or "",
        "duration_sec": max(2, min(int(duration_sec or _DEFAULT_DURATION), 15)),
    }


# ── Helpers ─────────────────────────────────────────────────────

def _lookup_persona(persona_project_id: str) -> Optional[Dict[str, Any]]:
    """Load a persona project by id. Returns None if not a persona
    project or if the project store is unavailable (tests)."""
    pid = (persona_project_id or "").strip()
    if not pid:
        return None
    try:
        from ... import projects  # late import so tests can skip this module
    except Exception:
        return None
    try:
        data = projects.get_project_by_id(pid)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("project_type") != "persona":
        return None
    return data


_CLASS_LABELS = {
    "secretary": "Executive Secretary",
    "assistant": "Personal Assistant",
    "companion": "Companion",
    "girlfriend": "Romantic Partner",
    "partner": "Romantic Partner",
    "custom": "Custom Persona",
}


def _class_label(persona_class: Any) -> str:
    if not isinstance(persona_class, str) or not persona_class:
        return ""
    return _CLASS_LABELS.get(persona_class, persona_class.replace("_", " ").title())


def _first_nonempty(*values: Any) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _join_list(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts = [str(v).strip() for v in value if isinstance(v, str) and v.strip()]
    return ", ".join(parts[:6])


def _outfit_sentence(appearance: Dict[str, Any]) -> str:
    """Best-effort outfit descriptor from persona_appearance."""
    avatar = appearance.get("avatar_settings") or {}
    for key in ("outfit_prompt", "character_prompt"):
        val = avatar.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


_AFFINITY_TIERS = (
    (0.75, "close"),
    (0.5, "warm"),
    (0.2, "friendly"),
    (0.0, "stranger"),
)


def _affinity_tier(score: float) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "stranger"
    for threshold, label in _AFFINITY_TIERS:
        if value >= threshold:
            return label
    return "stranger"


def _minimal_vars(
    *, persona_label: str, persona_emotion: str, affinity_score: float,
    synopsis: str, viewer_message: str, intent_hint: str, duration_sec: int,
) -> Dict[str, Any]:
    """Degraded-mode variables when the persona project has been
    deleted but the experience still remembers the label."""
    return {
        "persona_name": persona_label,
        "persona_role": "Companion",
        "persona_objective": "Engage the viewer in conversation.",
        "persona_traits": "attentive, responsive, consistent",
        "persona_tone": "warm",
        "persona_style": "natural, grounded",
        "persona_backstory": "No additional backstory.",
        "persona_outfit": "casual, current wardrobe",
        "persona_emotion": persona_emotion or "neutral",
        "allow_explicit": "false",
        "affinity_tier": _affinity_tier(affinity_score),
        "affinity_pct": int(max(0.0, min(1.0, affinity_score)) * 100),
        "synopsis": synopsis or "(this is the first turn)",
        "viewer_message": viewer_message or "(no message yet)",
        "intent_hint": intent_hint or "",
        "duration_sec": max(2, min(int(duration_sec or _DEFAULT_DURATION), 15)),
    }


__all__ = ["load_persona_prompt_vars"]
