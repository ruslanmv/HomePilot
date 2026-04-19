"""
Narration / dialogue / CTA generator.

``fill_scripts(graph, intent, profile)`` walks every node in a
BranchGraph and populates its ``narration`` + ``title`` fields
according to the node's kind and position in the graph. Also
writes ``image_prompt`` / ``video_prompt`` strings that the asset
adapter layer consumes downstream.

Phase 1 uses deterministic templates per node kind so tests are
reproducible. Phase 2 swaps the template calls for LLM prompts
behind the same signature.
"""
from __future__ import annotations

from typing import Optional

from ..branching.graph import BranchGraph, GraphNode
from ..planner.intent import Intent
from ..policy.profiles import PolicyProfile, load_profile
from .safety_rewriter import rewrite_for_safety
from .tone import ToneSpec, apply_tone, default_tone_for_mode, estimate_duration_sec


# Per-kind narration templates. {objective}/{topic}/{title} fill at runtime.
_TEMPLATES = {
    "scene": "Welcome. {objective}. Here's what happens next in the journey.",
    "decision": "You have a choice. Pick the path that feels right.",
    "merge": "Paths converge here. Let's continue.",
    "assessment": "Quick check — what do you think about {topic}?",
    "remediation": "Let's look at that one more time. {topic} is important because…",
    "ending": "Thanks for playing through {objective}. Come back anytime.",
}


# ─────────────────────────────────────────────────────────────────
# Single-node generator (exposed for router-driven regeneration)
# ─────────────────────────────────────────────────────────────────

def generate_narration_for_node(
    node: GraphNode,
    intent: Intent,
    *,
    tone: Optional[ToneSpec] = None,
    profile: Optional[PolicyProfile] = None,
) -> str:
    """Produce narration for a single node.

    Applies (1) template substitution, (2) tone shaping,
    (3) safety rewriter using the active policy profile.
    """
    tone = tone or default_tone_for_mode(intent.mode)
    profile = profile or load_profile(intent.mode) or load_profile("sfw_general")
    # ``profile`` narrowed for mypy: load_profile guarantees non-None
    # for any of the built-in mode ids.
    assert profile is not None

    template = _TEMPLATES.get(node.kind, _TEMPLATES["scene"])
    raw = template.format(
        objective=intent.objective or "our story",
        topic=intent.topic or "this topic",
        title=node.title or "this step",
    )
    shaped = apply_tone(raw, tone)
    safe = rewrite_for_safety(shaped, profile).text
    return safe


def _title_for(node: GraphNode, intent: Intent) -> str:
    if node.title:
        return node.title
    if node.is_entry:
        return "Introduction"
    if node.kind == "ending":
        return "Epilogue"
    if node.kind == "decision":
        return "Choose"
    return f"{node.kind.title()} step"


def _image_prompt(node: GraphNode, intent: Intent) -> str:
    base = f"cinematic still, {intent.mode.replace('_', ' ')} scene"
    if intent.topic:
        base += f", about {intent.topic}"
    if node.kind == "decision":
        base += ", character facing two choices"
    elif node.kind == "ending":
        base += ", resolution, warm lighting"
    elif node.kind == "assessment":
        base += ", thoughtful look"
    elif node.kind == "remediation":
        base += ", teaching gesture"
    return base


def _video_prompt(node: GraphNode, intent: Intent) -> str:
    return _image_prompt(node, intent) + ", short 4-second clip, subtle motion"


# ─────────────────────────────────────────────────────────────────
# Graph-level fill
# ─────────────────────────────────────────────────────────────────

def fill_scripts(
    graph: BranchGraph,
    intent: Intent,
    *,
    profile: Optional[PolicyProfile] = None,
) -> BranchGraph:
    """Populate narration/title/image_prompt/video_prompt on every
    node. Idempotent — nodes that already have non-empty narration
    are skipped so designer edits are preserved when re-running the
    generator after a partial manual edit.
    """
    tone = default_tone_for_mode(intent.mode)
    profile = profile or load_profile(intent.mode) or load_profile("sfw_general")
    assert profile is not None

    for node in graph.nodes:
        if not node.title:
            node.title = _title_for(node, intent)

        if not node.narration:
            node.narration = generate_narration_for_node(
                node, intent, tone=tone, profile=profile,
            )

        # image_prompt / video_prompt are stored on the metadata dict
        # for now — the real ix_nodes columns get populated when the
        # caller persists the graph via the repo.
        node.metadata.setdefault("image_prompt", _image_prompt(node, intent))
        node.metadata.setdefault("video_prompt", _video_prompt(node, intent))
        node.metadata.setdefault(
            "duration_sec",
            estimate_duration_sec(node.narration, tone),
        )

    return graph
