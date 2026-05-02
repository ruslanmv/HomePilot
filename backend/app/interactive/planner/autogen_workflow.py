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


# ── Helpers ────────────────────────────────────────────────────

def _to_scene_id(raw: Any) -> str:
    """Canonicalize scene ids to backend-safe snake_case ≤ 24 chars.

    Small LLMs routinely emit prose-style ids like ``"Show Interest
    In Her Life"`` that trip the validator's ``^[a-z][a-z0-9_]{0,23}$``
    regex. We coerce those into the required shape rather than
    losing an otherwise-valid payload:

      * lowercase everything
      * non-alphanumeric runs → single underscore
      * strip leading/trailing underscores
      * ensure the first char is a letter (prefix ``s_`` if not)
      * truncate to 24 chars (re-trim trailing underscore)
      * empty results fall back to the literal ``"scene"``
    """
    base = str(raw or "").strip().lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        base = "scene"
    if not re.match(r"^[a-z]", base):
        base = f"s_{base}"
    return base[:24].rstrip("_") or "scene"


def _dedupe_scene_id(base: str, used: set) -> str:
    """Pick a unique snake_case id given a set of already-used ones.

    Reserves up to 3 trailing chars for a ``_NN`` suffix so the
    result stays within the 24-char cap even after disambiguation.
    """
    if base not in used:
        return base
    stem = base[:21].rstrip("_") or "scene"
    i = 2
    while True:
        cand = f"{stem}_{i}"
        if cand not in used:
            return cand
        i += 1


# ── Feature flag ───────────────────────────────────────────────

def workflow_enabled() -> bool:
    """True when the stage-2 workflow should run instead of the
    legacy monolithic LLM call.

    REV-7: default is now True, matching autoplan. Explicit
    ``INTERACTIVE_AUTOGEN_WORKFLOW=false`` or
    ``INTERACTIVE_AUTOGEN_LEGACY=true`` flips back to legacy for
    one release.
    """
    raw = os.getenv("INTERACTIVE_AUTOGEN_WORKFLOW", "").strip().lower()
    if raw in {"0", "false", "no", "off", "n"}:
        return False
    if raw in {"1", "true", "yes", "on", "y"}:
        return True
    if _bool_env("INTERACTIVE_AUTOGEN_LEGACY"):
        return False
    return True


def strict_ai_enabled() -> bool:
    """True when per-scene templated fallbacks must NOT run.

    Shares the ``INTERACTIVE_STRICT_AI`` switch with the stage-1
    workflow so ops flip a single flag to enforce "LLM output or
    a visible error" across both stages.
    """
    return _bool_env("INTERACTIVE_STRICT_AI")


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

    # Forgiving normalisation — small LLMs frequently drop the
    # array wrapper when a field "should" hold a single string
    # (``"next": "end_a"`` instead of ``"next": ["end_a"]``) AND
    # emit prose-style ids like "Show Interest In Her Life" that
    # trip the validator's snake_case regex. Both get fixed here
    # rather than at the validator so authors don't lose a whole
    # workflow to a punctuation slip.

    # 1) Canonicalise scene ids and record the old → new rewrite
    #    map so we can patch ``next`` pointers + the ``start`` ref
    #    to match. Deduped so collapsed ids ("Path A" / "path a")
    #    don't collide.
    id_map: Dict[str, str] = {}
    used_ids: set = set()
    for idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        old_id = str(scene.get("id") or f"scene_{idx + 1}")
        new_id = _dedupe_scene_id(_to_scene_id(old_id), used_ids)
        used_ids.add(new_id)
        id_map[old_id] = new_id
        scene["id"] = new_id
        # Best-effort alias: if another scene refers to this one
        # via its pre-normalised form, that lookup should still hit.
        id_map.setdefault(_to_scene_id(old_id), new_id)

    # 2) Normalise edge-shape fields and rewrite id references.
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        # next: str → [str]; missing → []
        nxt = scene.get("next")
        if isinstance(nxt, str):
            scene["next"] = [nxt] if nxt else []
        elif nxt is None and (scene.get("kind") or "").lower() != "ending":
            scene["next"] = []
        if isinstance(scene.get("next"), list):
            scene["next"] = [
                id_map.get(
                    str(target),
                    id_map.get(_to_scene_id(target), str(target)),
                )
                for target in scene["next"]
                if str(target).strip()
            ]
        # choice_labels: str → [str]
        labels = scene.get("choice_labels")
        if isinstance(labels, str):
            scene["choice_labels"] = [labels] if labels else []

    # 3) ``start`` may reference the pre-normalised id; rewrite it.
    start_raw = str(start)
    data["start"] = id_map.get(
        start_raw, id_map.get(_to_scene_id(start_raw), start_raw),
    )
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

    Strict mode (``INTERACTIVE_STRICT_AI=true``) raises
    ``StepFailure`` instead of returning a template so the whole
    generation aborts and the user sees a real error rather than
    hardcoded "Welcome — <topic>" prose.
    """
    sid = str(scene.get("id") or "scene")
    kind = str(scene.get("kind") or "scene")

    def _fallback(ctx: Mapping[str, Any], _token: Optional[str]) -> Dict[str, str]:
        if strict_ai_enabled():
            from ..workflows import StepFailure  # late
            raise StepFailure(
                step_id=f"script_{sid}",
                prompt_id="autogen.scene_script",
                reason="strict_ai: refused to use templated scene script",
                attempts=0,
            )
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

    # Per-experience LLM override (Mature gated). Applied to every
    # step in the workflow so the spine and per-scene scripts both
    # route through the operator's chosen abliterated model. Empty
    # string is the wire equivalent of "use the default" — the
    # runner won't pass a model_override.
    ap_for_llm = getattr(experience, "audience_profile", None) or {}
    step_model = ""
    if isinstance(ap_for_llm, dict):
        step_model = str(ap_for_llm.get("adult_llm") or "").strip()

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
        model=step_model,
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
            model=step_model,
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
