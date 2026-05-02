"""
Planner — "director brain" for the interactive service.

Takes a prompt + optional audience/context and produces a
structured ``Intent`` that downstream modules (branching, script,
scene) can deterministically consume.

The planner is swap-friendly: ``parse_prompt`` has a heuristic
phase-1 implementation today; swapping to an LLM-driven
implementation later keeps the same input/output signature so
nothing downstream changes.

Submodules:

  intent.py     Intent dataclass + parse_prompt(text, cfg) → Intent
  audience.py   Audience dataclass + resolve_audience helper
  presets.py    Per-mode planning templates (SFW education, social
                romantic, mature gated, language learning, …)
"""
from .audience import Audience, resolve_audience
from .intent import Intent, parse_prompt
from .presets import PlanningPreset, get_preset, list_presets

__all__ = [
    "Audience",
    "resolve_audience",
    "Intent",
    "parse_prompt",
    "PlanningPreset",
    "get_preset",
    "list_presets",
]
