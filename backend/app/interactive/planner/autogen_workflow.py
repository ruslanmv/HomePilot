"""
Stage-2 autogen via the workflow runner (REV-4).

Replaces the single monolithic JSON call in ``autogen_llm`` with
two prompts:

  autogen.scene_spine   — one call that produces topology only
                          (ids, kinds, edges, choice labels).
  autogen.scene_script  — fan-out per scene: title + narration.

Why split
---------

The legacy prompt asked the LLM to emit the whole scene graph at
once: ids, kinds, titles, narration, image prompts, choice labels
and edge next-pointers — all in a single nested JSON payload. On
anything smaller than ~20B that call is brittle: the model loses
the thread, renames ids between fields, or collapses the schema.

Splitting lets a 4B model reliably produce the small topology
JSON, then answer seven short "one scene, please" questions — a
shape every local LLM handles well. When any single script call
fails, the per-scene fallback fills in a topic-aware title +
narration so the graph still ships; only a failed SPINE aborts
the whole generator.

Opt-in
------

``INTERACTIVE_AUTOGEN_WORKFLOW=true`` picks this path. Default
keeps the legacy LLM call for one release (REV-7 flips the
default). ``INTERACTIVE_AUTOGEN_LEGACY=true`` forces legacy even
when the workflow flag is also set, for fast rollbacks.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..models import Experience
from ..prompts import PromptLibrary, default_library
from ..workflows import Step, WorkflowEvent, WorkflowResult, WorkflowRunner
from .autoplan_workflow import (
    _parse_json_text, _parse_text,
)


log = logging.getLogger(__name__)


_ALLOWED_KINDS = {"scene", "decision", "ending"}
_MAX_SCENES = 40


# ── Feature flag ───────────────────────────────────────────────

def workflow_enabled() -> bool:
    """True when the stage-2 workflow should run instead of the
    legacy monolithic LLM call."""
    if _bool_env("INTERACTIVE_AUTOGEN_WORKFLOW"):
        return True
    if _bool_env("INTERACTIVE_AUTOGEN_LEGACY"):
        return False
    return False  # REV-7 flips this


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on", "y"}


# ── Spine parsing + validation ─────────────────────────────────

def _parse_spine(content: str) -> Dict[str, Any]:
    data = _parse_json_text(content)
    if not isinstance(data, dict):
        raise ValueError(f"spine must be object, got {type(data).__name__}")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("spine.scenes must be non-empty list")
    start = data.get("start")
    if not isinstance(start, str) or not start:
        raise ValueError("spine.start must be a non-empty string")
    return data


def _validate_spine(spine: Dict[str, Any]) -> Optional[str]:
    scenes: List[Dict[str, Any]] = list(spine.get("scenes") or [])
    if not (3 <= len(scenes) <= _MAX_SCENES):
        return f"need 3..{_MAX_SCENES} scenes, got {len(scenes)}"

    seen: Dict[str, Dict[str, Any]] = {}
    for s in scenes:
        if not isinstance(s, dict):
            return "each scene must be an object"
        sid = s.get("id")
        if not isinstance(sid, str) or not re.match(r"^[a-z][a-z0-9_]{0,23}$", sid):
            return f"scene id {sid!r} not snake_case <=24 chars"
        if sid in seen:
            return f"duplicate scene id: {sid}"
        kind = s.get("kind")
        if kind not in _ALLOWED_KINDS:
            return f"scene {sid}: kind {kind!r} not in {_ALLOWED_KINDS}"
        nxt = s.get("next")
        if nxt is None:
            if kind != "ending":
                return f"scene {sid}: non-ending must declare next[]"
        else:
            if not isinstance(nxt, list) or not all(
                isinstance(x, str) for x in nxt
            ):
                return f"scene {sid}: next must be list[str]"
            if kind == "decision":
                labels = s.get("choice_labels")
                if (not isinstance(labels, list)
                        or len(labels) != len(nxt)
                        or not all(isinstance(x, str) and x.strip() for x in labels)):
                    return f"decision {sid}: choice_labels must match next length"
        seen[sid] = s

    start = spine.get("start")
    if start not in seen:
        return f"start {start!r} not in scenes"

    # All next pointers must resolve.
    for s in scenes:
        for target in s.get("next") or []:
            if target not in seen:
                return f"scene {s.get('id')}: next {target!r} not in scenes"

    # Exactly one entry (the start) — nothing else may be unreachable.
    entry = spine["start"]
    reachable = {entry}
    frontier = [entry]
    while frontier:
        cur = frontier.pop()
        cur_scene = seen[cur]
        for nxt in cur_scene.get("next") or []:
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    if len(reachable) != len(seen):
        return f"unreachable scenes: {sorted(set(seen) - reachable)}"

    return None


# ── Script parsing + validation ────────────────────────────────

def _parse_script(content: str) -> Dict[str, str]:
    data = _parse_json_text(content)
    if not isinstance(data, dict):
        raise ValueError(f"script must be object, got {type(data).__name__}")
    return {
        "title": str(data.get("title") or "").strip(),
        "narration": str(data.get("narration") or "").strip(),
    }


def _validate_script(value: Mapping[str, str]) -> Optional[str]:
    title = value.get("title", "")
    narr = value.get("narration", "")
    if not (3 <= len(title) <= 80):
        return f"title length {len(title)} not in 3..80"
    if not (10 <= len(narr) <= 500):
        return f"narration length {len(narr)} not in 10..500"
    return None


# ── Topic-aware fallbacks ──────────────────────────────────────

def _topic_label(ctx: Mapping[str, Any]) -> str:
    """Best-effort short topic label for fallback copy."""
    topic = str(ctx.get("topic") or "").strip()
    if not topic:
        topic = str(ctx.get("title") or "").strip()
    topic = re.sub(r"\s+", " ", topic).strip(".")
    if len(topic) > 60:
        topic = topic[:57].rstrip() + "…"
    return topic


def _script_fallback_factory(
    scene: Mapping[str, Any], role: str,
):
    """Build a topic-aware default for a failing scene script.

    Captures scene + role at construction time so the Step's
    fallback signature (``(ctx, token) -> value``) stays clean.
    """
    sid = str(scene.get("id") or "scene")
    kind = str(scene.get("kind") or "scene")

    def _fallback(ctx: Mapping[str, Any], _token: Optional[str]) -> Dict[str, str]:
        topic = _topic_label(ctx)
        if role == "opening" or kind == "scene" and role.startswith("opening"):
            title = f"Welcome — {topic}" if topic else "Welcome"
            narration = (
                f"Let's walk through {topic}." if topic
                else "Welcome to this interactive experience."
            )
        elif kind == "decision":
            title = "Pick your path"
            narration = (
                f"Which approach to {topic} would you like to explore?"
                if topic else "Which path would you like to explore?"
            )
        elif kind == "ending":
            title = f"Wrap up — {topic}" if topic else "Wrap up"
            narration = "Here's what you picked up along the way."
        elif role.startswith("branch_"):
            step_num = role.split("_", 1)[1] or "1"
            title = f"{sid.replace('_', ' ').title()} · step {step_num}"
            narration = (
                f"Going a little deeper on {topic}."
                if topic else "Going a little deeper."
            )
        else:
            title = sid.replace("_", " ").title() or "Scene"
            narration = (
                f"One more step on {topic}." if topic else "One more step."
            )
        return {"title": title, "narration": narration}

    return _fallback


# ── GraphPlan assembly ─────────────────────────────────────────

def _assemble_plan(
    spine: Dict[str, Any],
    scripts: Dict[str, Dict[str, str]],
) -> Any:
    """Convert spine + per-scene scripts into a GraphPlan.

    Late-imports GraphPlan / NodeSpec / EdgeSpec / ActionSpec from
    ``autogen_llm`` to avoid a cycle (autogen_llm imports this
    module at dispatch time).
    """
    from .autogen_llm import ActionSpec, EdgeSpec, GraphPlan, NodeSpec  # late

    start = spine["start"]
    scene_map: Dict[str, Dict[str, Any]] = {
        s["id"]: s for s in spine["scenes"]
    }

    nodes: List[NodeSpec] = []
    for sid, scene in scene_map.items():
        script = scripts.get(sid) or {}
        title = script.get("title") or sid.replace("_", " ").title()
        narration = script.get("narration") or ""
        nodes.append(NodeSpec(
            local_id=sid,
            kind=str(scene.get("kind") or "scene"),
            title=title,
            narration=narration,
            image_prompt="",
            is_entry=(sid == start),
        ))

    edges: List[EdgeSpec] = []
    actions: List[ActionSpec] = []
    for scene in spine["scenes"]:
        sid = scene["id"]
        nxt: List[str] = list(scene.get("next") or [])
        kind = str(scene.get("kind"))
        labels: List[str] = list(scene.get("choice_labels") or [])

        if kind == "decision" and nxt:
            # One choice edge per option; mirror the label to actions.
            for i, (target, label) in enumerate(zip(nxt, labels)):
                edges.append(EdgeSpec(
                    from_local_id=sid, to_local_id=target,
                    trigger_kind="choice",
                    label=label[:60], ordinal=i,
                ))
                actions.append(ActionSpec(
                    label=label[:60],
                    intent_code=_label_to_intent(label),
                ))
        else:
            # Linear transitions (scene/ending); endings usually have no next.
            for i, target in enumerate(nxt):
                edges.append(EdgeSpec(
                    from_local_id=sid, to_local_id=target,
                    trigger_kind="auto", label="", ordinal=i,
                ))

    return GraphPlan(
        nodes=nodes, edges=edges, actions=actions,
        source="llm", warnings=[],
    )


def _label_to_intent(label: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    cleaned = cleaned[:40] or "choice"
    return cleaned


# ── Workflow entry point ───────────────────────────────────────

async def run_autogen_workflow(
    experience: Experience,
    *,
    library: Optional[PromptLibrary] = None,
    on_event: Optional[Any] = None,
) -> Optional[Any]:
    """Execute the stage-2 workflow and return a ``GraphPlan`` or
    ``None`` when the workflow aborted.

    Two stages:
      1. Run the spine step.
      2. For each scene, run a script step (the fan-out is a
         for-loop, not a ``Parallel`` wrapper — sequential keeps
         Ollama from thrashing on a single GPU).
    """
    lib = library or default_library()

    title = (experience.title or "").strip() or "Interactive experience"
    brief = (experience.description or experience.objective or title).strip()
    mode = str(experience.experience_mode or "sfw_general")
    topic = _coerce_topic(experience)

    # --- Stage 1: spine ---
    spine_step = Step(
        step_id="scene_spine",
        prompt_id="autogen.scene_spine",
        output_key="spine",
        build_vars=lambda _c: {
            "title": title, "brief": brief, "mode": mode, "topic": topic,
            "branch_count": _derive_branch_count(experience),
            "depth": _derive_depth(experience),
            "scenes_per_branch": _derive_scenes(experience),
        },
        parse=_parse_spine,
        validate=_validate_spine,
        temperature=0.5,
        max_tokens=800,
    )

    runner = WorkflowRunner(library=lib)
    spine_result = await runner.run(
        workflow="autogen:spine",
        steps=[spine_step],
        context={"title": title, "brief": brief, "mode": mode, "topic": topic},
        on_event=on_event,
    )
    if spine_result.aborted:
        log.warning(
            "autogen_workflow_spine_aborted: %s",
            (spine_result.error or "")[:200],
        )
        return None

    spine: Dict[str, Any] = spine_result.context["spine"]

    # --- Stage 2: per-scene scripts ---
    scripts: Dict[str, Dict[str, str]] = {}
    for idx, scene in enumerate(spine["scenes"]):
        role = _derive_role(scene, spine, idx)
        prev_summary = _prev_summary(scripts, scene, spine)

        script_step = Step(
            step_id=f"script_{scene['id']}",
            prompt_id="autogen.scene_script",
            output_key=f"script_{scene['id']}",
            build_vars=(lambda s=scene, r=role, ps=prev_summary:
                        lambda _c: {
                            "title": title,
                            "brief": brief,
                            "mode": mode,
                            "topic": topic,
                            "scene_kind": s["kind"],
                            "scene_role": r,
                            "prev_summary": ps or "(none)",
                        })(),
            parse=_parse_script,
            validate=_validate_script,
            fallback=_script_fallback_factory(scene, role),
            temperature=0.6,
            max_tokens=220,
        )

        part = await runner.run(
            workflow=f"autogen:script:{scene['id']}",
            steps=[script_step],
            context={
                "title": title, "brief": brief, "mode": mode, "topic": topic,
            },
            on_event=on_event,
        )
        if part.aborted:
            # Script has a fallback, so an abort here means the
            # fallback itself raised (which shouldn't happen) —
            # treat as fatal for the whole generation.
            log.warning(
                "autogen_workflow_script_aborted: %s",
                (part.error or "")[:200],
            )
            return None
        scripts[scene["id"]] = part.context[f"script_{scene['id']}"]

    return _assemble_plan(spine, scripts)


# ── Helpers ────────────────────────────────────────────────────

def _coerce_topic(experience: Experience) -> str:
    """Best effort topic label drawn from the experience payload."""
    for field in ("title", "description", "objective"):
        v = getattr(experience, field, None) or ""
        v = re.sub(r"\s+", " ", str(v)).strip().strip(".")
        if v:
            if len(v) > 80:
                return v[:77].rstrip() + "…"
            return v
    return "Interactive experience"


def _derive_branch_count(experience: Experience) -> int:
    raw = getattr(experience, "branch_count", None)
    try:
        return max(2, min(4, int(raw)))
    except (TypeError, ValueError):
        return 2


def _derive_depth(experience: Experience) -> int:
    raw = getattr(experience, "depth", None)
    try:
        return max(2, min(3, int(raw)))
    except (TypeError, ValueError):
        return 2


def _derive_scenes(experience: Experience) -> int:
    raw = getattr(experience, "scenes_per_branch", None)
    try:
        return max(2, min(4, int(raw)))
    except (TypeError, ValueError):
        return 2


def _derive_role(
    scene: Mapping[str, Any],
    spine: Mapping[str, Any],
    idx: int,
) -> str:
    sid = scene.get("id")
    start = spine.get("start")
    kind = scene.get("kind")
    if sid == start:
        return "opening"
    if kind == "ending":
        return "closing"
    if kind == "decision":
        return "decision"
    return f"branch_{idx}"


def _prev_summary(
    scripts: Mapping[str, Mapping[str, str]],
    scene: Mapping[str, Any],
    spine: Mapping[str, Any],
) -> str:
    """Find any scene whose ``next`` includes this scene, return
    its narration preview so the per-scene prompt can flow from
    the previous beat."""
    target = scene.get("id")
    for prev in spine.get("scenes") or []:
        if target in (prev.get("next") or []):
            prev_script = scripts.get(prev.get("id"))
            if prev_script:
                narr = prev_script.get("narration") or ""
                return narr[:140]
    return ""
