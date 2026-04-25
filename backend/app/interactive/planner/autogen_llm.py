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
    """Produce a full GraphPlan for this experience. Never raises.

    Persona Live Play gets its own purpose-built graph (intent → reaction
    → followup) — the runtime doesn't traverse the scene tree (actions
    come from _INTENT_CATALOG), but publish / QA still require at least
    one entry scene. The scene-spine LLM path was producing invalid
    graphs for persona_live projects ("next=None"), aborting 3x, then
    falling back to the Standard Interactive topology (entry → decision
    → branches → ending) which produced the "Continue / Ask for a hint"
    catalog and the user-reported "only 1 ending node" skeleton.

    Three paths, tried in order for non-persona_live projects:

      1. Two-prompt workflow (REV-4) — opt-in via
         ``INTERACTIVE_AUTOGEN_WORKFLOW=true``. Spine call +
         per-scene script fan-out through the runner.
      2. Legacy monolithic LLM call — when playback LLM is enabled
         and the workflow path is disabled or aborted.
      3. Heuristic fallback — deterministic seeder that always
         produces a usable graph.
    """
    # Persona Live Play short-circuit. Deterministic, no LLM round-trip,
    # always valid — the user picked a persona, the wizard already has
    # the intent-driven action catalog wired; a pre-baked graph just
    # satisfies the QA entry-scene check and gives Publish something
    # real to ship.
    if str(getattr(experience, "project_type", "") or "").strip().lower() == "persona_live":
        return _persona_live_graph(experience)

    from .autogen_workflow import (
        run_autogen_workflow, workflow_enabled,
    )

    pcfg = playback_cfg or load_playback_config()

    if workflow_enabled():
        try:
            plan = await run_autogen_workflow(experience)
        except Exception as exc:  # noqa: BLE001
            log.warning("autogen_workflow_error: %s", str(exc)[:400])
            plan = None
        if plan is not None:
            # Same safety net as the legacy LLM path.
            try:
                _run_validation(plan, cfg=cfg)
                return plan
            except GraphValidationError as exc:
                issues = getattr(exc, "issues", [])
                log.warning(
                    "autogen_workflow_graph_invalid: %d issues — %s",
                    len(issues), str(issues[:3])[:300],
                )

    if pcfg.llm_enabled:
        llm_plan = await _generate_via_llm(experience, cfg=cfg, pcfg=pcfg)
        if llm_plan is not None:
            return llm_plan
    return _heuristic_graph(experience, cfg)


# ── Persona Live Play path ─────────────────────────────────────

# Level-1 player intents this graph keys off — matches the
# ``_INTENT_CATALOG`` level-1 row in ``routes/persona_live.py`` so the
# scene graph, the Live Action panel, and the renderer all agree on the
# same four opening beats. Keeping the list short is deliberate: scenes
# are publish-metadata placeholders that the runtime doesn't traverse,
# they just have to exist and be internally consistent for QA.
_PERSONA_LIVE_LEVEL_1_INTENTS: tuple[tuple[str, str, str, str], ...] = (
    # (intent_id, reaction_label, scene_title, one-line narration)
    (
        "say_playful",
        "playful smirk",
        "Playful smirk",
        "{name} catches your teasing, tilts her head, and gives you a slow smirk.",
    ),
    (
        "compliment",
        "soft blush",
        "Soft blush",
        "{name} glances down, a little caught off guard by the compliment, then meets your eyes again.",
    ),
    (
        "ask_about_her",
        "warm smile",
        "Warm smile",
        "{name} settles in, relaxes her shoulders, and starts telling you about her day.",
    ),
    (
        "stay_quiet",
        "quiet anticipation",
        "Quiet anticipation",
        "{name} holds the silence comfortably, eyes on you, inviting you to make the next move.",
    ),
)


def _persona_live_graph(experience: Experience) -> GraphPlan:
    """Deterministic Persona Live scene graph.

    Shape (satisfies publish / QA without pretending to be a tree):

        lina_intro_start  (scene, entry)
              ├── choice:say_playful     → lina_reaction_say_playful      (scene)
              ├── choice:compliment      → lina_reaction_compliment       (scene)
              ├── choice:ask_about_her   → lina_reaction_ask_about_her    (scene)
              └── choice:stay_quiet      → lina_reaction_stay_quiet       (scene)
        every reaction   (auto)           → lina_followup                 (scene)
        lina_followup    (auto)           → lina_epilogue                 (ending)

    Each reaction scene carries a narration that shows what Lina DOES in
    response to the player's intent (smirk / blush / warm smile / held
    silence) — the authoring UI now shows a meaningful spine the
    operator can edit, and the runtime's intent-driven Live Action panel
    stays the actual source of truth for play.
    """
    persona_name = _persona_label_from_experience(experience) or "Lina"

    intro = NodeSpec(
        local_id="lina_intro_start",
        kind="scene",
        title=f"First moment with {persona_name}",
        narration=(
            f"{persona_name} notices you. She holds your gaze for a beat, "
            "then lets the corner of her mouth lift. "
            "'Hey… you made it. What's on your mind?'"
        ),
        is_entry=True,
    )
    followup = NodeSpec(
        local_id="lina_followup",
        kind="scene",
        title="Keep the moment going",
        narration=(
            f"{persona_name} stays engaged, leaning into the connection. "
            "The pull between you is easy now — ready for whatever you bring next."
        ),
    )
    epilogue = NodeSpec(
        local_id="lina_epilogue",
        kind="ending",
        title="Until next time",
        narration=(
            f"{persona_name} gives you a soft look. 'Come find me again soon.' "
            "The scene fades on her smile."
        ),
    )

    nodes: List[NodeSpec] = [intro]
    edges: List[EdgeSpec] = []
    for ordinal, (intent_id, reaction_label, scene_title, narration_tpl) in enumerate(
        _PERSONA_LIVE_LEVEL_1_INTENTS
    ):
        reaction_id = f"lina_reaction_{intent_id}"
        nodes.append(NodeSpec(
            local_id=reaction_id,
            kind="scene",
            title=scene_title,
            narration=narration_tpl.format(name=persona_name),
        ))
        # Choice edge from the intro to this reaction — label is the
        # player intent so the Editor / Graph view reads cleanly.
        edges.append(EdgeSpec(
            from_local_id=intro.local_id,
            to_local_id=reaction_id,
            trigger_kind="choice",
            label=intent_id,
            ordinal=ordinal,
        ))
        # Each reaction flows into the shared follow-up scene.
        edges.append(EdgeSpec(
            from_local_id=reaction_id,
            to_local_id=followup.local_id,
            trigger_kind="auto",
            label="continue",
        ))

    nodes.append(followup)
    nodes.append(epilogue)
    edges.append(EdgeSpec(
        from_local_id=followup.local_id,
        to_local_id=epilogue.local_id,
        trigger_kind="auto",
        label="epilogue",
    ))

    # Action catalog — intent-driven, mirrors ``_INTENT_CATALOG`` level 1
    # in ``routes/persona_live.py``. This is what replaces the generic
    # "Continue / Ask for a hint" default the user complained about.
    actions: List[ActionSpec] = [
        ActionSpec(label="Say something playful",  intent_code="say_playful",   xp_award=5),
        ActionSpec(label="Compliment her",          intent_code="compliment",    xp_award=5),
        ActionSpec(label="Ask about her day",       intent_code="ask_about_her", xp_award=5),
        ActionSpec(label="Stay quiet and listen",   intent_code="stay_quiet",    xp_award=3),
    ]

    return GraphPlan(
        nodes=nodes,
        edges=edges,
        actions=actions,
        source="persona_live",
    )


def _persona_label_from_experience(experience: Experience) -> str:
    """Best-effort persona label lookup for narration templates.

    Priority:
      1. audience_profile.persona_label  (wizard stamps this)
      2. audience_profile.persona_name   (legacy)
      3. experience.title (last-resort; typically "sexy girl" etc.)
    """
    ap = getattr(experience, "audience_profile", None) or {}
    if isinstance(ap, dict):
        for key in ("persona_label", "persona_name"):
            val = str(ap.get(key) or "").strip()
            if val:
                return val
    return str(getattr(experience, "title", "") or "").strip()


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

    topic = _topic_label(intent, experience)

    if intent is None:
        # Last-resort graph: a single scene + single ending, still
        # topic-aware so authors see meaningful titles up front.
        return GraphPlan(
            nodes=[
                NodeSpec(
                    local_id="intro", kind="scene",
                    title=f"Welcome — {topic}" if topic else "Welcome",
                    narration=(
                        f"Let's walk through {topic}." if topic
                        else "Welcome in."
                    ),
                    is_entry=True,
                ),
                NodeSpec(
                    local_id="end_a", kind="ending",
                    title=f"Wrap up — {topic}" if topic else "Thanks for watching",
                    narration="Nice work. Here's a quick recap before you go.",
                ),
            ],
            edges=[EdgeSpec(from_local_id="intro", to_local_id="end_a")],
            actions=[],
            source="heuristic",
        )

    branch_graph = build_heuristic_graph(intent)
    branch_count = max(1, intent.branch_count)

    nodes: List[NodeSpec] = []
    for n in branch_graph.nodes:
        title, narration = _rewrite_heuristic_title(
            raw_title=n.title,
            raw_narration=n.narration,
            topic=topic,
            kind=n.kind,
            is_entry=n.is_entry,
            metadata=getattr(n, "metadata", {}) or {},
            branch_count=branch_count,
        )
        nodes.append(NodeSpec(
            local_id=n.id, kind=n.kind, title=title,
            narration=narration, image_prompt="", is_entry=n.is_entry,
        ))
    edges = [
        EdgeSpec(
            from_local_id=e.from_id, to_local_id=e.to_id,
            trigger_kind=e.trigger_kind, label=e.label, ordinal=e.ordinal,
        )
        for e in branch_graph.edges
    ]
    return GraphPlan(nodes=nodes, edges=edges, actions=[], source="heuristic")


# Title post-processor — makes 'Branch 0 step 1' human-facing.
#
# The shared branching.build_graph intentionally emits generic
# titles so the schema-level tests stay deterministic. Authoring-
# facing output wants real words the viewer could read on screen,
# so we rewrite the obvious generic patterns using the topic and
# a small bank of branch labels. LLM path overrides all of this
# when enabled.

_BRANCH_LABELS = (
    "Option A", "Option B", "Option C",
    "Option D", "Option E", "Option F",
)


def _topic_label(intent, experience) -> str:  # noqa: ANN001 — typed via caller
    raw = ""
    if intent is not None and getattr(intent, "topic", ""):
        raw = str(intent.topic)
    if not raw:
        raw = (experience.title or experience.description or "").strip()
    raw = re.sub(r"\s+", " ", raw).strip().strip(".")
    if len(raw) > 60:
        raw = raw[:57].rstrip() + "…"
    return raw


def _rewrite_heuristic_title(
    *, raw_title: str, raw_narration: str, topic: str, kind: str,
    is_entry: bool, metadata: Dict[str, Any], branch_count: int,
) -> tuple[str, str]:
    """Turn a generic builder title into a topic-aware one.

    Returns (title, narration). Narration is only synthesized when
    the builder didn't already set one.
    """
    title = (raw_title or "").strip()
    narration = (raw_narration or "").strip()

    if is_entry or title.lower() == "introduction":
        new_title = f"Welcome — {topic}" if topic else "Welcome"
        new_narration = narration or (
            f"Let's walk through {topic}." if topic
            else "Welcome to this interactive experience."
        )
        return new_title, new_narration

    if kind == "decision" or title.lower() == "choose a path":
        new_title = "Pick your path"
        new_narration = narration or (
            f"Which approach to {topic} would you like to explore?"
            if topic else "Which path would you like to explore?"
        )
        return new_title, new_narration

    if title.lower() == "epilogue" or metadata.get("purpose") == "shared_ending":
        new_title = f"Wrap up — {topic}" if topic else "Wrap up"
        new_narration = narration or (
            "Here's what you picked up along the way."
        )
        return new_title, new_narration

    # "Branch N step M" → topic-aware path/step label.
    m = re.match(r"Branch\s+(\d+)\s+step\s+(\d+)", title, re.I)
    if m:
        branch = int(m.group(1))
        step = int(m.group(2))
        label = _BRANCH_LABELS[branch] if branch < len(_BRANCH_LABELS) else f"Path {branch + 1}"
        if step == 1:
            new_title = f"{label} · explore"
            default_narration = (
                f"This path dives into {topic}." if topic
                else "This path explores one of the options."
            )
        else:
            new_title = f"{label} · step {step}"
            default_narration = (
                f"Going a little deeper on {topic}." if topic
                else "Going a little deeper."
            )
        return new_title, narration or default_narration

    # Per-branch ending fallback.
    m2 = re.match(r"Branch\s+(\d+)\s+ending", title, re.I)
    if m2:
        branch = int(m2.group(1))
        label = _BRANCH_LABELS[branch] if branch < len(_BRANCH_LABELS) else f"Path {branch + 1}"
        return f"{label} · outcome", narration or "That's where this path lands."

    return title or "Scene", narration


# ── LLM path ───────────────────────────────────────────────────

def _audience_adult_llm(experience: Experience) -> str:
    """Read the wizard's per-experience LLM override from
    ``audience_profile.adult_llm``. Empty when unset.

    Surfaced for autogen + the workflow spine so Mature (gated)
    projects can route around the default Llama 3 / 3.2 refusals.
    Pulled out of inline dict access so tests can patch this one
    function deterministically.
    """
    ap = getattr(experience, "audience_profile", None) or {}
    if not isinstance(ap, dict):
        return ""
    return str(ap.get("adult_llm") or "").strip()


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
    # Per-experience LLM override for Mature (gated) projects — the
    # default Llama 3 / 3.2 refuses explicit content with "I cannot
    # create content that describes explicit sexual situations." The
    # wizard's Step 0 picker stamps the operator's preferred
    # uncensored/abliterated model into ``audience_profile.adult_llm``
    # and we honor it here. Empty / unset → server default.
    adult_llm = _audience_adult_llm(experience)
    try:
        response = await asyncio.wait_for(
            chat_ollama(
                messages,
                temperature=0.55,
                max_tokens=max_tokens,
                response_format="json",
                model=adult_llm or None,
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
        "- Titles must be human-facing (something a viewer could\n"
        "  read on screen): e.g. 'Greeting: Hola, ¿cómo estás?' —\n"
        "  NEVER shapes like 'Branch 0 step 1' or 'Scene 3'.\n"
        "- Scripts are natural spoken language, 5–20 seconds each,\n"
        "  specific to the topic (not generic filler).\n"
        "- At least one decision scene must include interaction.options\n"
        "  with concrete labels a viewer could tap — NOT 'Option A'.\n"
        "- visual_direction guides a video renderer (camera, mood,\n"
        "  lighting, pose) — no story text, no dialogue.\n"
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
