"""
Stage-1 autoplan via the multi-step workflow runner.

This is the REV-3 replacement for ``autoplan_llm._autoplan_via_llm``.
Instead of one monolithic JSON prompt it asks seven small, focused
questions — each answerable by an 8B (or even 1.5B) model in a
single short completion. The workflow runner handles retries,
timeouts, validation and safe abort.

Why seven prompts instead of one
--------------------------------

Small local LLMs (Qwen3-1.5B, Llama-8B, the ``huihui_ai/
qwen3-abliterated:4b`` model the user runs in Enterprise Settings)
are materially better at single-decision questions than at
producing a sprawling JSON object. Splitting the work gives us:

* Tight per-prompt response_format + validation (enum, small
  JSON, short text) → higher success rate on tiny models.
* Per-prompt retries + safe fallbacks → one flaky response
  doesn't cost the whole form.
* Easy auditing — prompts live on disk in YAML (REV-1), diffed
  independently.
* Cheap: each prompt is < 200 tokens out, so seven calls are
  still faster than one 1500-token JSON monolith on a 4B model.

Dispatch
--------

``autoplan_llm.autoplan`` picks the workflow path when the
feature flag ``INTERACTIVE_AUTOPLAN_WORKFLOW`` is truthy OR when
phase-2 LLM playback is enabled and the legacy flag
``INTERACTIVE_AUTOPLAN_LEGACY`` is unset. REV-7 makes the
workflow path the default and keeps the legacy as an opt-in
escape hatch for one release.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..config import InteractiveConfig
from ..playback.playback_config import PlaybackConfig
from ..prompts import PromptLibrary, default_library
from ..workflows import Step, WorkflowEvent, WorkflowResult, WorkflowRunner
from .audience import resolve_audience
from .intent import parse_prompt
from .presets import get_preset


log = logging.getLogger(__name__)


_ALLOWED_MODES = (
    "sfw_general", "sfw_education", "language_learning",
    "enterprise_training", "social_romantic", "mature_gated",
)
_ALLOWED_LEVELS = ("beginner", "intermediate", "advanced")
_ALLOWED_ROLES = ("viewer", "learner", "trainee", "customer", "lead")


# ── Feature flag ───────────────────────────────────────────────

def workflow_enabled() -> bool:
    """Return True when the new multi-prompt workflow should run.

    REV-7: default is now True. Unconfigured installs run the new
    multi-prompt workflow; operators who want the legacy
    monolithic LLM call set ``INTERACTIVE_AUTOPLAN_LEGACY=true``.
    Explicit ``INTERACTIVE_AUTOPLAN_WORKFLOW=false`` still opts
    out for one release so rollback is a one-env-var flip.
    """
    raw = os.getenv("INTERACTIVE_AUTOPLAN_WORKFLOW", "").strip().lower()
    if raw in {"0", "false", "no", "off", "n"}:
        return False
    if raw in {"1", "true", "yes", "on", "y"}:
        return True
    # Flag unset → look at the explicit legacy override.
    if _bool_env("INTERACTIVE_AUTOPLAN_LEGACY"):
        return False
    return True


def strict_ai_enabled() -> bool:
    """Return True when *all* content must come from the LLM.

    Two kinds of fallback live in this workflow:

      * Structural  — safe defaults for STRUCTURE fields (shape
                      triple, audience role/level/language). These
                      never carry user-facing prose; flipping
                      strict mode still lets them run.
      * Content     — templated prose like "Welcome — <topic>"
                      or preset seed_intents. These show up on
                      screen, so a hardcoded default is what the
                      REV design explicitly calls out as "AI
                      pretending". Strict mode disables them so
                      the route returns a plain error instead.

    Flip ``INTERACTIVE_STRICT_AI=true`` after telemetry confirms
    the LLM reliably answers every prompt. Installs without an
    LLM backend must keep strict mode OFF so heuristic fallbacks
    remain available.
    """
    return _bool_env("INTERACTIVE_STRICT_AI")


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on", "y"}


# ── Parsers ────────────────────────────────────────────────────

def _parse_enum(content: str) -> str:
    """Strip to a single word. Tolerates quotes, punctuation, and
    stray framing like 'Mode: enterprise_training'."""
    s = (content or "").strip().strip("`").strip()
    # If the model wrote "Mode: foo" or similar, take the last token.
    if ":" in s:
        s = s.split(":", 1)[-1].strip()
    # Pick the first identifier-like run.
    m = re.search(r"[A-Za-z_][A-Za-z0-9_]*", s)
    return (m.group(0) if m else "").lower()


def _parse_text(content: str) -> str:
    """Single-line text. Strips outer quotes and collapses whitespace."""
    s = (content or "").strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return re.sub(r"\s+", " ", s).strip()


def _parse_json_text(content: str) -> Any:
    """Pull the first JSON value out of the response. Tolerates
    markdown fences and leading/trailing prose."""
    s = (content or "").strip()
    if s.startswith("```"):
        # Strip fence
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = s.rstrip("`").rstrip()
    # Try the whole thing first.
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        pass
    # Otherwise, find the first {...} or [...] block.
    m = re.search(r"(\{.*\}|\[.*\])", s, re.DOTALL)
    if m is None:
        raise ValueError("no JSON object/array in response")
    return json.loads(m.group(0))


def _parse_string_array(content: str) -> List[str]:
    data = _parse_json_text(content)
    if not isinstance(data, list):
        raise ValueError(f"expected list, got {type(data).__name__}")
    out: List[str] = []
    for item in data:
        if not isinstance(item, str):
            raise ValueError("array must contain strings")
        cleaned = item.strip()
        if cleaned:
            out.append(cleaned)
    return out


def _parse_audience_obj(content: str) -> Dict[str, str]:
    data = _parse_json_text(content)
    if not isinstance(data, dict):
        raise ValueError(f"expected object, got {type(data).__name__}")
    out = {
        "role": str(data.get("role") or "").strip().lower(),
        "level": str(data.get("level") or "").strip().lower(),
        "language": str(data.get("language") or "").strip() or "en",
    }
    return out


def _parse_shape_obj(content: str) -> Dict[str, int]:
    data = _parse_json_text(content)
    if not isinstance(data, dict):
        raise ValueError(f"expected object, got {type(data).__name__}")

    def _pick(key: str) -> int:
        v = data.get(key)
        if isinstance(v, bool):
            raise ValueError(f"{key}: bool not accepted")
        return int(v)  # raises on bad types

    return {
        "branch_count": _pick("branch_count"),
        "depth": _pick("depth"),
        "scenes_per_branch": _pick("scenes_per_branch"),
    }


# ── Validators ─────────────────────────────────────────────────

def _validate_mode(value: str) -> Optional[str]:
    return None if value in _ALLOWED_MODES else f"not in allowed modes: {value!r}"


def _validate_nonempty_text(value: str) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return "empty text"
    return None


def _validate_title_array(value: List[str]) -> Optional[str]:
    if not isinstance(value, list) or len(value) < 1:
        return "need at least one title"
    # Reject obviously bad titles (all same, too short).
    valid = [t for t in value if 3 <= len(t.strip()) <= 80]
    return None if valid else "no title candidate passed 3..80 chars"


def _validate_brief(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return "not a string"
    txt = value.strip()
    if not (30 <= len(txt) <= 600):
        return f"brief length {len(txt)} not in 30..600"
    return None


def _validate_audience_obj(value: Mapping[str, str]) -> Optional[str]:
    role = value.get("role", "")
    level = value.get("level", "")
    lang = value.get("language", "")
    if role not in _ALLOWED_ROLES:
        return f"role {role!r} not allowed"
    if level not in _ALLOWED_LEVELS:
        return f"level {level!r} not allowed"
    if not lang or len(lang) > 12:
        return "language looks wrong"
    return None


def _validate_shape_obj(value: Mapping[str, int]) -> Optional[str]:
    branch = value.get("branch_count")
    depth = value.get("depth")
    scenes = value.get("scenes_per_branch")
    if not isinstance(branch, int) or not (2 <= branch <= 4):
        return f"branch_count {branch} out of 2..4"
    if not isinstance(depth, int) or not (2 <= depth <= 3):
        return f"depth {depth} out of 2..3"
    if not isinstance(scenes, int) or not (2 <= scenes <= 4):
        return f"scenes_per_branch {scenes} out of 2..4"
    return None


def _validate_seed_intents(value: List[str]) -> Optional[str]:
    if not isinstance(value, list) or not (3 <= len(value) <= 6):
        return f"need 3..6 items, got {len(value) if isinstance(value, list) else '?'}"
    # Strict: items must already be lowercase snake_case. The
    # prompt spells this out and small models comply; anything
    # else (e.g. "Greeting" or "ChoosePath") is a sign the model
    # ignored the format rule, so we retry rather than paper over.
    if not all(
        isinstance(s, str) and re.match(r"^[a-z][a-z0-9_]*$", s)
        for s in value
    ):
        return "items must be lowercase snake_case"
    return None


# ── Fallbacks ──────────────────────────────────────────────────

_DEFAULT_AUDIENCE = {"role": "viewer", "level": "intermediate", "language": "en"}
_DEFAULT_SHAPE = {"branch_count": 2, "depth": 2, "scenes_per_branch": 2}


def _audience_fallback(ctx: Mapping[str, Any], token: Optional[str]) -> Dict[str, str]:
    # Prefer the heuristic scan as a middle-ground; fall back to defaults.
    prompt_text = str(ctx.get("idea") or "")
    try:
        heur = resolve_audience(prompt_text, default_language="en")
        return {"role": heur.role, "level": heur.level, "language": heur.language}
    except Exception:  # noqa: BLE001
        return dict(_DEFAULT_AUDIENCE)


def _shape_fallback(ctx: Mapping[str, Any], token: Optional[str]) -> Dict[str, int]:
    return dict(_DEFAULT_SHAPE)


def _topic_fallback(ctx: Mapping[str, Any], token: Optional[str]) -> str:
    # Empty topic is acceptable downstream — heuristic presets fill in.
    return ""


def _seed_intents_fallback(
    ctx: Mapping[str, Any], token: Optional[str],
) -> List[str]:
    """Fall back to the preset seed intents for the picked mode.

    Strict mode treats the preset list as content (it's
    operator-curated prose), so we surface the failure instead
    of silently substituting templated intents. Non-strict mode
    (the default today) lets it through — intents are short
    enough that the UI labels them as "Smart defaults" anyway.
    """
    if strict_ai_enabled():
        from ..workflows import StepFailure  # late
        raise StepFailure(
            step_id="seed_intents",
            prompt_id="autoplan.seed_intents",
            reason="strict_ai: refused to use preset fallback",
            attempts=0,
        )
    mode = str(ctx.get("mode") or "sfw_general")
    preset = get_preset(mode) or get_preset("sfw_general")
    intents = list(preset.seed_intents) if preset and preset.seed_intents else []
    if intents:
        return intents
    return ["greeting", "choose_path", "show_outcome"]


# ── Step builders (pure functions over context) ───────────────

def _vars_classify(ctx: Mapping[str, Any]) -> Dict[str, str]:
    return {"idea": str(ctx["idea"])}


def _vars_topic(ctx: Mapping[str, Any]) -> Dict[str, str]:
    return {"idea": str(ctx["idea"])}


def _vars_title(ctx: Mapping[str, Any]) -> Dict[str, str]:
    return {
        "idea": str(ctx["idea"]),
        "mode": str(ctx["mode"]),
        "topic": str(ctx.get("topic") or ""),
    }


def _vars_brief(ctx: Mapping[str, Any]) -> Dict[str, str]:
    # Pick the first valid title candidate for brief context.
    titles = ctx.get("title_candidates") or []
    picked = next(
        (t for t in titles if isinstance(t, str) and 3 <= len(t.strip()) <= 80),
        "",
    )
    return {
        "idea": str(ctx["idea"]),
        "mode": str(ctx["mode"]),
        "topic": str(ctx.get("topic") or ""),
        "title": picked,
    }


def _vars_audience_or_shape(ctx: Mapping[str, Any]) -> Dict[str, str]:
    return {
        "idea": str(ctx["idea"]),
        "mode": str(ctx["mode"]),
        "topic": str(ctx.get("topic") or ""),
    }


# ── Workflow wiring ────────────────────────────────────────────

def build_autoplan_steps() -> List[Step]:
    """The ordered list of ``Step``s for stage-1 autoplan."""
    return [
        Step(
            step_id="classify_mode",
            prompt_id="autoplan.classify_mode",
            output_key="mode",
            build_vars=_vars_classify,
            parse=_parse_enum,
            validate=_validate_mode,
            temperature=0.0,
            max_tokens=16,
        ),
        Step(
            step_id="extract_topic",
            prompt_id="autoplan.extract_topic",
            output_key="topic",
            build_vars=_vars_topic,
            parse=_parse_text,
            validate=lambda v: None if isinstance(v, str) and len(v) <= 80 else "bad topic",
            fallback=_topic_fallback,
            temperature=0.2,
            max_tokens=40,
        ),
        Step(
            step_id="title",
            prompt_id="autoplan.title",
            output_key="title_candidates",
            build_vars=_vars_title,
            parse=_parse_string_array,
            validate=_validate_title_array,
            temperature=0.5,
            max_tokens=120,
        ),
        Step(
            step_id="brief",
            prompt_id="autoplan.brief",
            output_key="brief",
            build_vars=_vars_brief,
            parse=_parse_text,
            validate=_validate_brief,
            temperature=0.6,
            max_tokens=240,
        ),
        Step(
            step_id="audience",
            prompt_id="autoplan.audience",
            output_key="audience",
            build_vars=_vars_audience_or_shape,
            parse=_parse_audience_obj,
            validate=_validate_audience_obj,
            fallback=_audience_fallback,
            temperature=0.1,
            max_tokens=80,
        ),
        Step(
            step_id="shape",
            prompt_id="autoplan.shape",
            output_key="shape",
            build_vars=_vars_audience_or_shape,
            parse=_parse_shape_obj,
            validate=_validate_shape_obj,
            fallback=_shape_fallback,
            temperature=0.0,
            max_tokens=60,
        ),
        Step(
            step_id="seed_intents",
            prompt_id="autoplan.seed_intents",
            output_key="seed_intents",
            build_vars=_vars_audience_or_shape,
            parse=_parse_string_array,
            validate=_validate_seed_intents,
            fallback=_seed_intents_fallback,
            temperature=0.4,
            max_tokens=120,
        ),
    ]


async def run_autoplan_workflow(
    idea: str,
    *,
    cfg: InteractiveConfig,
    library: Optional[PromptLibrary] = None,
    on_event: Optional[Any] = None,
) -> WorkflowResult:
    """Execute the stage-1 workflow for ``idea``.

    Returns the runner's ``WorkflowResult`` — callers convert to
    ``PlanAutoResult`` via ``workflow_to_plan_result``.
    """
    runner = WorkflowRunner(library=library or default_library())
    return await runner.run(
        workflow="autoplan",
        steps=build_autoplan_steps(),
        context={"idea": idea.strip()},
        on_event=on_event,
    )


# ── Result assembly ────────────────────────────────────────────

def workflow_to_plan_result(
    result: WorkflowResult, *, cfg: InteractiveConfig,
) -> Optional[Any]:
    """Turn a completed ``WorkflowResult`` into a ``PlanAutoResult``.

    Returns ``None`` when the workflow aborted — callers decide
    whether to fall back to the heuristic path or surface the
    error. ``PlanAutoResult`` is imported lazily to avoid a
    circular import with ``autoplan_llm``.
    """
    from .autoplan_llm import PlanAutoResult, PlanForm  # late

    if result.aborted:
        return None

    ctx = result.context
    idea = str(ctx.get("idea") or "").strip() or "Interactive experience"
    mode = str(ctx.get("mode") or "sfw_general")
    if mode not in _ALLOWED_MODES:
        mode = "sfw_general"
    topic = str(ctx.get("topic") or "").strip()
    title = _pick_best_title(ctx.get("title_candidates"), idea)
    brief = str(ctx.get("brief") or "").strip() or title
    audience = ctx.get("audience") or dict(_DEFAULT_AUDIENCE)
    shape = ctx.get("shape") or dict(_DEFAULT_SHAPE)
    seed_intents = list(ctx.get("seed_intents") or [])

    # Apply backend caps on top of the 2-4/2-3/2-4 spec bounds.
    branch = max(2, min(int(shape["branch_count"]), max(2, cfg.max_branches)))
    depth = max(2, min(int(shape["depth"]), max(2, cfg.max_depth)))
    scenes = max(2, min(int(shape["scenes_per_branch"]), 4))

    locale_hint = ""
    if isinstance(audience, Mapping):
        locale_hint = str(audience.get("locale_hint") or "")

    form = PlanForm(
        title=title,
        prompt=brief,
        experience_mode=mode,
        policy_profile_id=mode,
        audience_role=str(audience.get("role") or "viewer"),
        audience_level=str(audience.get("level") or "intermediate"),
        audience_language=str(audience.get("language") or "en"),
        audience_locale_hint=locale_hint,
        branch_count=branch,
        depth=depth,
        scenes_per_branch=scenes,
    )

    # Objective / scheme / success_metric aren't produced by the
    # 7-step workflow (they're cheap to derive from the parsed
    # brief + mode). Keeping parse_prompt here means we don't need
    # an 8th LLM call for decorative metadata.
    intent = parse_prompt(brief or idea, cfg=cfg, mode=mode)

    return PlanAutoResult(
        form=form,
        objective=intent.objective or "",
        topic=topic or (intent.topic or ""),
        scheme=intent.scheme or "xp_level",
        success_metric=intent.success_metric or "",
        seed_intents=list(seed_intents)[:8],
        source="llm",
    )


def _pick_best_title(candidates: Any, idea: str) -> str:
    """Pick the first candidate that's 3..60 chars and not equal
    to the idea verbatim. Falls back to the idea's first sentence
    if nothing passes."""
    if isinstance(candidates, list):
        for c in candidates:
            if not isinstance(c, str):
                continue
            t = c.strip()
            if 3 <= len(t) <= 60 and t.lower() != idea.lower():
                return t
    # Fallback: first sentence of the idea, trimmed.
    cleaned = re.sub(r"\s+", " ", idea.strip())
    head = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    if len(head) > 60:
        head = head[:57].rstrip() + "…"
    return head or "Interactive experience"
