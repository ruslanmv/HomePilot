"""
Stage-2 auto-generator — turn a Stage-1 PlanForm (persisted on an
experience) into a complete scene graph: nodes + edges + action
catalog ready to insert into the database.

LLM path asks for a structured JSON payload matching the shape the
UX spec defined:

    {
      "scenes": [
        {
          "id": "intro",
          "type": "scene" | "decision" | "ending",
          "title": "...",
          "script": "...",
          "visual_direction": "...",
          "interaction": {
            "type": "choice" | "quiz" | "none",
            "options": [{"label": "...", "next": "scene_id"}]
          },
          "next": ["scene_id"]
        }
      ],
      "logic": { "start_scene": "intro" }
    }

Mapping to our existing DB:
  type        → ix_nodes.kind  (normalized to scene/decision/ending)
  title       → ix_nodes.title
  script      → ix_nodes.narration
  visual_direction → ix_nodes.image_prompt
  next[]                 → ix_edges (trigger_kind='auto')
  interaction.options[]  → ix_edges (trigger_kind='choice') +
                            ix_action_catalog rows

Heuristic fallback reuses the deterministic ``branching.build_graph``
seeder so this generator never raises — the route always gets back
a usable GraphPlan.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..branching.builder import build_graph as build_heuristic_graph
from ..branching.graph import GraphValidationError, validate_graph
from ..config import InteractiveConfig
from ..models import Experience
from ..planner.intent import parse_prompt
from ..playback.playback_config import PlaybackConfig, load_playback_config


log = logging.getLogger(__name__)


_ALLOWED_KINDS = {"scene", "decision", "merge", "ending"}
# type → kind normalization so LLMs that use "intro" / "outro" still
# land as valid rows. First match wins.
_KIND_ALIASES = {
    "intro": "scene",
    "opening": "scene",
    "scene": "scene",
    "middle": "scene",
    "decision": "decision",
    "choice": "decision",
    "branch": "decision",
    "merge": "merge",
    "ending": "ending",
    "outro": "ending",
    "end": "ending",
    "conclusion": "ending",
    "finale": "ending",
}

_MAX_NODES = 40  # hard cap so an LLM can't emit a graph-of-doom


# ── Public shapes ──────────────────────────────────────────────

@dataclass(frozen=True)
class NodeSpec:
    """One node to insert into ix_nodes."""

    local_id: str          # LLM / heuristic id; used to resolve edges
    kind: str              # scene | decision | merge | ending
    title: str
    narration: str = ""
    image_prompt: str = ""
    is_entry: bool = False


@dataclass(frozen=True)
class EdgeSpec:
    """One transition to insert into ix_edges."""

    from_local_id: str
    to_local_id: str
    trigger_kind: str = "auto"   # auto | choice | hotspot | timer | fallback | intent
    label: str = ""
    ordinal: int = 0


@dataclass(frozen=True)
class ActionSpec:
    """One catalog row to insert into ix_action_catalog."""

    label: str
    intent_code: str = "choice"
    xp_award: int = 5


@dataclass(frozen=True)
class GraphPlan:
    nodes: List[NodeSpec]
    edges: List[EdgeSpec]
    actions: List[ActionSpec] = field(default_factory=list)
    source: str = "heuristic"    # 'llm' | 'heuristic'
    warnings: List[str] = field(default_factory=list)


# ── Public entry point ─────────────────────────────────────────

async def generate_graph(
    experience: Experience,
    *,
    cfg: InteractiveConfig,
    playback_cfg: Optional[PlaybackConfig] = None,
) -> GraphPlan:
    """Produce a full GraphPlan for this experience. Never raises."""
    pcfg = playback_cfg or load_playback_config()
    if pcfg.llm_enabled:
        llm_plan = await _generate_via_llm(experience, cfg=cfg, pcfg=pcfg)
        if llm_plan is not None:
            return llm_plan
    return _heuristic_graph(experience, cfg)


# ── Heuristic path ─────────────────────────────────────────────

def _heuristic_graph(experience: Experience, cfg: InteractiveConfig) -> GraphPlan:
    prompt = (experience.description or experience.objective or experience.title
              or "an interactive experience").strip()
    mode = experience.experience_mode or "sfw_general"
    try:
        intent = parse_prompt(prompt, cfg=cfg, mode=mode)
    except Exception as exc:  # noqa: BLE001
        log.warning("autogen_heuristic_parse_error: %s", str(exc)[:200])
        intent = None

    if intent is None:
        # Last-resort graph: a single scene + single ending.
        return GraphPlan(
            nodes=[
                NodeSpec(local_id="intro", kind="scene", title="Welcome",
                         narration="Welcome in.", is_entry=True),
                NodeSpec(local_id="end_a", kind="ending", title="Thanks for watching",
                         narration="See you soon."),
            ],
            edges=[
                EdgeSpec(from_local_id="intro", to_local_id="end_a"),
            ],
            actions=[],
            source="heuristic",
        )

    branch_graph = build_heuristic_graph(intent)
    nodes = [
        NodeSpec(
            local_id=n.id, kind=n.kind, title=n.title,
            narration=n.narration, image_prompt="", is_entry=n.is_entry,
        )
        for n in branch_graph.nodes
    ]
    edges = [
        EdgeSpec(
            from_local_id=e.from_id, to_local_id=e.to_id,
            trigger_kind=e.trigger_kind, label=e.label, ordinal=e.ordinal,
        )
        for e in branch_graph.edges
    ]
    return GraphPlan(nodes=nodes, edges=edges, actions=[], source="heuristic")


# ── LLM path ───────────────────────────────────────────────────

async def _generate_via_llm(
    experience: Experience,
    *, cfg: InteractiveConfig, pcfg: PlaybackConfig,
) -> Optional[GraphPlan]:
    from ...llm import chat_ollama  # late import

    messages = _build_messages(experience, cfg=cfg)
    # Graph generation is heavier than a one-line chat reply →
    # grant a more generous token ceiling but keep the call
    # bounded by the configured render-side timeout.
    max_tokens = max(pcfg.llm_max_tokens, 1500)
    timeout_s = max(pcfg.llm_timeout_s, 30.0)
    try:
        response = await asyncio.wait_for(
            chat_ollama(
                messages,
                temperature=0.55,
                max_tokens=max_tokens,
                response_format="json",
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning("autogen_llm_timeout after %.1fs", timeout_s)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("autogen_llm_error: %s", str(exc)[:400])
        return None

    content = _extract_content(response)
    if not content:
        log.warning("autogen_llm_empty_content")
        return None
    payload = _parse_json(content)
    if payload is None:
        log.warning(
            "autogen_llm_malformed_json — first 200 chars: %r",
            content[:200],
        )
        return None

    plan = _payload_to_graph_plan(payload, cfg=cfg)
    if plan is None:
        return None

    # Defence in depth: run the same validators the authoring UI
    # uses so an LLM that emits a cycle or dangling edge doesn't
    # corrupt the DB. validate_graph raises → fall back.
    try:
        _run_validation(plan, cfg=cfg)
    except GraphValidationError as exc:
        issues = getattr(exc, "issues", [])
        log.warning(
            "autogen_llm_graph_invalid: %d issues — %s",
            len(issues), str(issues[:3])[:300],
        )
        return None
    return plan


def _build_messages(
    experience: Experience, *, cfg: InteractiveConfig,
) -> List[Dict[str, Any]]:
    title = (experience.title or "").strip() or "Interactive experience"
    desc = (experience.description or experience.objective or "").strip()
    mode = experience.experience_mode or "sfw_general"

    system = (
        "You are an AI Interactive Video Generator. Given a short brief, "
        "produce a COMPLETE interactive video graph as JSON. Respond "
        "with ONLY a JSON object matching this schema exactly:\n\n"
        "{\n"
        '  "scenes": [\n'
        "    {\n"
        '      "id": str,                 # unique lowercase slug\n'
        '      "type": str,               # scene | decision | ending\n'
        '      "title": str,              # 1-60 chars\n'
        '      "script": str,             # 1-4 short sentences\n'
        '      "visual_direction": str,   # camera, mood, lighting cues\n'
        '      "interaction": {           # optional\n'
        '        "type": "choice" | "quiz" | "none",\n'
        '        "options": [ {"label": str, "next": str} ]\n'
        "      },\n"
        '      "next": [str]              # scene ids this node flows into\n'
        "    }\n"
        "  ],\n"
        '  "logic": { "start_scene": str }\n'
        "}\n\n"
        "Rules:\n"
        "- Exactly ONE scene is the entry point (logic.start_scene).\n"
        "- Every non-ending scene has ≥1 outbound edge — either a\n"
        "  'next' entry or choice options with 'next' ids.\n"
        "- At least one scene has type='ending'.\n"
        "- Keep it small: 4–10 scenes total.\n"
        "- No cycles. The graph is a DAG.\n"
        "- Script lines are natural spoken language, 5–20 seconds each.\n"
        "- visual_direction should guide a video renderer (no story text).\n"
        "- Never describe minors, violence, or non-consensual content.\n"
        "- No prose, no markdown fences. Strict JSON."
    )
    user = (
        f"Title: {title}\n"
        f"Brief: {desc or '(author did not add a description)'}\n"
        f"Mode: {mode}\n"
        f"Caps: max_branches={cfg.max_branches}, max_depth={cfg.max_depth}, "
        f"max_nodes={cfg.max_nodes_per_experience}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── Parsing ────────────────────────────────────────────────────

def _extract_content(response: Dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    msg = first.get("message") or {}
    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        return msg["content"].strip()
    return ""


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(content: str) -> Optional[Dict[str, Any]]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    m = _JSON_BLOCK.search(stripped)
    if not m:
        return None
    try:
        payload = json.loads(m.group(0))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slug(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = _SLUG_RE.sub("_", text).strip("_")
    if not text:
        return fallback
    return text[:40]


def _clean_str(value: Any, *, max_len: int = 200) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def _normalize_kind(raw_type: Any) -> str:
    raw = str(raw_type or "").strip().lower()
    return _KIND_ALIASES.get(raw, "scene")


def _payload_to_graph_plan(
    payload: Dict[str, Any], *, cfg: InteractiveConfig,
) -> Optional[GraphPlan]:
    scenes_raw = payload.get("scenes")
    if not isinstance(scenes_raw, list) or not scenes_raw:
        log.warning("autogen_llm_no_scenes")
        return None

    logic = payload.get("logic") if isinstance(payload.get("logic"), dict) else {}
    start_id = _slug(logic.get("start_scene"), fallback="")

    # First pass: materialize nodes with deduped ids.
    seen_ids: Dict[str, int] = {}
    nodes: List[NodeSpec] = []
    id_map: Dict[str, str] = {}  # raw id → final slug

    for i, scene in enumerate(scenes_raw[:_MAX_NODES]):
        if not isinstance(scene, dict):
            continue
        raw_id = str(scene.get("id") or f"s{i}")
        slug = _slug(raw_id, fallback=f"s{i}")
        # Dedup: if the same slug appears twice, suffix a counter.
        if slug in seen_ids:
            seen_ids[slug] += 1
            slug = f"{slug}_{seen_ids[slug]}"
        else:
            seen_ids[slug] = 0
        id_map[raw_id] = slug

        kind = _normalize_kind(scene.get("type"))
        nodes.append(NodeSpec(
            local_id=slug,
            kind=kind,
            title=_clean_str(scene.get("title"), max_len=80)
                  or f"Scene {len(nodes) + 1}",
            narration=_clean_str(scene.get("script"), max_len=600),
            image_prompt=_clean_str(scene.get("visual_direction"), max_len=300),
            is_entry=False,
        ))

    if not nodes:
        log.warning("autogen_llm_all_scenes_invalid")
        return None

    # Ensure exactly one entry node — prefer the one logic.start_scene
    # points at, else the first node.
    entry_slug = id_map.get(start_id, nodes[0].local_id)
    nodes = [
        NodeSpec(
            local_id=n.local_id, kind=n.kind, title=n.title,
            narration=n.narration, image_prompt=n.image_prompt,
            is_entry=(n.local_id == entry_slug),
        )
        for n in nodes
    ]

    # At least one ending — if the LLM missed it, promote the last
    # node to type='ending' so validate_graph's V3 (every non-ending
    # has an outbound edge) doesn't flag the tail.
    if not any(n.kind == "ending" for n in nodes):
        nodes[-1] = NodeSpec(
            local_id=nodes[-1].local_id, kind="ending",
            title=nodes[-1].title, narration=nodes[-1].narration,
            image_prompt=nodes[-1].image_prompt, is_entry=nodes[-1].is_entry,
        )

    # Second pass: edges + actions.
    edges: List[EdgeSpec] = []
    actions: List[ActionSpec] = []

    for scene in scenes_raw[:_MAX_NODES]:
        if not isinstance(scene, dict):
            continue
        raw_id = str(scene.get("id") or "")
        src = id_map.get(raw_id)
        if not src:
            continue

        # interaction.options[] → choice edges + action rows
        interaction = scene.get("interaction") if isinstance(scene.get("interaction"), dict) else {}
        options = interaction.get("options") if isinstance(interaction, dict) else []
        if isinstance(options, list):
            for ord_, opt in enumerate(options[:8]):
                if not isinstance(opt, dict):
                    continue
                label = _clean_str(opt.get("label"), max_len=60)
                dst_raw = str(opt.get("next") or "")
                dst = id_map.get(dst_raw)
                if not label or not dst:
                    continue
                edges.append(EdgeSpec(
                    from_local_id=src, to_local_id=dst,
                    trigger_kind="choice", label=label, ordinal=ord_,
                ))
                actions.append(ActionSpec(
                    label=label,
                    intent_code=_slug(label, fallback="choice"),
                    xp_award=5,
                ))

        # plain 'next' array → auto edges
        nexts = scene.get("next") if isinstance(scene.get("next"), list) else []
        base_ordinal = len([e for e in edges if e.from_local_id == src])
        for ord_, raw_dst in enumerate(nexts):
            dst = id_map.get(str(raw_dst))
            if not dst:
                continue
            # Avoid duplicate (src, dst) if the LLM put the same
            # target in both 'next' and an option.
            if any(e.from_local_id == src and e.to_local_id == dst for e in edges):
                continue
            edges.append(EdgeSpec(
                from_local_id=src, to_local_id=dst,
                trigger_kind="auto", ordinal=base_ordinal + ord_,
            ))

    return GraphPlan(nodes=nodes, edges=edges, actions=actions, source="llm")


# ── Validation helper ─────────────────────────────────────────

def _run_validation(plan: GraphPlan, *, cfg: InteractiveConfig) -> None:
    """Translate GraphPlan → BranchGraph → validate_graph.

    Raises GraphValidationError on any issue. Caller (which is
    inside the LLM path) catches + returns None to fall back.
    """
    from ..branching.graph import BranchGraph, GraphEdge, GraphNode

    bg = BranchGraph()
    for n in plan.nodes:
        bg.nodes.append(GraphNode(
            id=n.local_id, kind=n.kind, title=n.title,
            narration=n.narration, is_entry=n.is_entry, metadata={},
        ))
    for e in plan.edges:
        bg.edges.append(GraphEdge(
            from_id=e.from_local_id, to_id=e.to_local_id,
            trigger_kind=e.trigger_kind, label=e.label,
            payload={}, ordinal=e.ordinal,
        ))
    validate_graph(
        bg,
        max_depth=cfg.max_depth,
        max_nodes=cfg.max_nodes_per_experience,
    )
