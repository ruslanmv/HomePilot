"""
Script generation subsystem.

Turns a planned branch graph into concrete text: narration,
dialogue, CTA copy, response lines after user choices. Every
module in here is LLM-swap-friendly: the public functions accept
a BranchGraph/Intent and return the same BranchGraph with text
fields populated — internal implementation can move from
heuristic templates to LLM calls without changing call sites.

Submodules:

  generator.py        fill_scripts(graph, intent) — populates
                      narration/title/image_prompt on every node.
  tone.py             per-profile tone filter (formal, playful, …).
  i18n.py             multilingual variant generator — produces
                      ix_node_variants rows for target languages.
  safety_rewriter.py  rewrites text that classifier flags as close
                      to a policy boundary, so it stays in profile.
"""
from .generator import fill_scripts, generate_narration_for_node
from .i18n import generate_language_variants
from .safety_rewriter import rewrite_for_safety
from .tone import ToneSpec, apply_tone

__all__ = [
    "fill_scripts",
    "generate_narration_for_node",
    "generate_language_variants",
    "rewrite_for_safety",
    "ToneSpec",
    "apply_tone",
]
