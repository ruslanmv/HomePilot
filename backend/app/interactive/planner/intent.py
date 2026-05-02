"""
Intent parsing — prompt → structured plan.

Phase 1 implementation: deterministic heuristic. Scans the prompt
for length hints, branch-count hints, topic keywords, then stitches
a full Intent from the matching PlanningPreset.

Phase 2: swap in ``backend/app/openai_compat_endpoint.run_turn``
(or any LLM) for topic extraction — the ``parse_prompt`` signature
stays stable so downstream modules don't change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import InteractiveConfig
from .audience import Audience, resolve_audience
from .presets import PlanningPreset, get_preset


@dataclass(frozen=True)
class Intent:
    """Fully-resolved planner output.

    Everything downstream (branching/builder, script/generator)
    works purely from this struct — no re-parsing of the prompt.
    """

    prompt: str
    mode: str
    objective: str
    audience: Audience
    topic: str = ""
    branch_count: int = 3
    depth: int = 3
    scenes_per_branch: int = 3
    success_metric: str = ""
    seed_intents: List[str] = field(default_factory=list)
    scheme: str = "xp_level"
    raw_hints: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# Heuristic hint extractors
# ─────────────────────────────────────────────────────────────────

_BRANCH_HINT = re.compile(r"(\d+)\s*(?:branches|paths|choices)", re.I)
_DEPTH_HINT = re.compile(r"(\d+)\s*(?:steps|scenes|levels)\s*deep", re.I)
_SCENES_HINT = re.compile(r"(\d+)\s*(?:scenes|clips)(?!\s*deep)", re.I)
_TOPIC_HINT = re.compile(r"(?:about|teach|explain|demonstrate)\s+([a-zA-Z][\w\s\-]{1,60}?)(?:[,\.]|$)", re.I)
_METRIC_HINT = re.compile(r"(?:until|so that|so)\s+(?:the|they|user)\s+(.{5,60}?)(?:[,\.]|$)", re.I)


def _extract_int(prompt: str, pattern: re.Pattern[str], default: int, max_: int) -> int:
    m = pattern.search(prompt)
    if not m:
        return default
    try:
        v = int(m.group(1))
        return max(1, min(v, max_))
    except (TypeError, ValueError):
        return default


def _extract_topic(prompt: str) -> str:
    m = _TOPIC_HINT.search(prompt)
    if not m:
        return ""
    return m.group(1).strip().strip('"\'')


def _extract_metric(prompt: str) -> str:
    m = _METRIC_HINT.search(prompt)
    if not m:
        return ""
    return m.group(1).strip().rstrip('.,')


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def parse_prompt(
    prompt: str,
    *,
    cfg: InteractiveConfig,
    mode: str = "sfw_general",
    audience_hints: Optional[Dict[str, Any]] = None,
) -> Intent:
    """Turn a free-text prompt into a fully-resolved Intent.

    Raises
    ------
    ValueError
        If ``mode`` has no matching preset AND no sane default.
    """
    preset: Optional[PlanningPreset] = get_preset(mode) or get_preset("sfw_general")
    if preset is None:
        raise ValueError(f"No planning preset for mode '{mode}'")

    audience = resolve_audience(prompt, explicit=audience_hints, default_language="en")

    branch_count = _extract_int(prompt, _BRANCH_HINT, preset.default_branch_count, cfg.max_branches)
    depth = _extract_int(prompt, _DEPTH_HINT, preset.default_depth, cfg.max_depth)
    scenes_per_branch = _extract_int(prompt, _SCENES_HINT, preset.default_scenes_per_branch, 20)
    topic = _extract_topic(prompt)
    metric = _extract_metric(prompt)

    # Cap total nodes at the configured ceiling — branches * depth *
    # scenes_per_branch is an UPPER bound before merge-point
    # collapsing, so scale branch_count down if we're over.
    est_nodes = branch_count * depth * max(1, scenes_per_branch)
    while est_nodes > cfg.max_nodes_per_experience and branch_count > 1:
        branch_count -= 1
        est_nodes = branch_count * depth * max(1, scenes_per_branch)

    objective = preset.objective_template
    if topic:
        objective = objective.replace("{topic}", topic)
    objective = objective.replace("{level}", audience.level)

    return Intent(
        prompt=prompt,
        mode=mode,
        objective=objective,
        audience=audience,
        topic=topic,
        branch_count=branch_count,
        depth=depth,
        scenes_per_branch=scenes_per_branch,
        success_metric=metric,
        seed_intents=list(preset.seed_intents),
        scheme=preset.default_scheme,
        raw_hints={"preset": preset.mode, "topology": preset.default_topology},
    )
