"""
Stage-1 auto-planner — turn a one-sentence idea into a full
wizard form (title, mode, audience, branch shape, policy).

The user types "train new sales reps on pricing" → we return
a complete PlanAutoResult the frontend can drop straight into
its editable preview. No required fields, no 10-character gate.

Two composition paths:

  LLM        ``INTERACTIVE_PLAYBACK_LLM=true`` and chat_ollama
             reachable → structured-JSON call with the strict
             rule set the UX spec defined (SFW by default,
             2–4 branches, 2–3 depth, mode inferred from verbs).
  heuristic  Always available as a fallback. Uses the existing
             ``resolve_audience`` + ``parse_prompt`` + the six
             built-in policy profiles to produce a reasonable
             form without a network hop.

The result carries a ``source`` tag so the UI can tell the
viewer which path produced the preview ("AI suggested" vs
"Smart defaults").
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import InteractiveConfig
from ..playback.playback_config import PlaybackConfig, load_playback_config
from .audience import resolve_audience
from .intent import parse_prompt
from .presets import get_preset


log = logging.getLogger(__name__)


# ── Public shapes ──────────────────────────────────────────────

_ALLOWED_MODES = (
    "sfw_general",
    "sfw_education",
    "language_learning",
    "enterprise_training",
    "social_romantic",
    "mature_gated",
)
_ALLOWED_LEVELS = ("beginner", "intermediate", "advanced")

_FALLBACK_SEEDS = ["greeting", "choose_path", "feedback", "continue"]


@dataclass(frozen=True)
class PlanForm:
    """Pre-filled wizard form values. Shape mirrors the frontend's
    WizardForm so the preview component can drop this straight in."""

    title: str
    prompt: str
    experience_mode: str
    policy_profile_id: str
    audience_role: str
    audience_level: str
    audience_language: str
    audience_locale_hint: str
    branch_count: int
    depth: int
    scenes_per_branch: int


@dataclass(frozen=True)
class PlanAutoResult:
    form: PlanForm
    objective: str
    topic: str
    scheme: str
    success_metric: str
    seed_intents: List[str] = field(default_factory=list)
    source: str = "heuristic"  # 'llm' | 'heuristic'


# ── Entry point ────────────────────────────────────────────────

async def autoplan(
    idea: str,
    *,
    cfg: InteractiveConfig,
    playback_cfg: Optional[PlaybackConfig] = None,
) -> PlanAutoResult:
    """Produce a full wizard pre-fill. Never raises.

    LLM disabled, unreachable, malformed JSON → heuristic path
    engaged, ``source='heuristic'``. Successful LLM call →
    ``source='llm'``.
    """
    text = (idea or "").strip()
    if not text:
        # The route rejects empty input, but we still return a
        # sane default so internal callers don't have to handle
        # None. ``source='heuristic'`` makes the fallback visible.
        return _heuristic_result(text, cfg)

    pcfg = playback_cfg or load_playback_config()
    if pcfg.llm_enabled:
        llm_result = await _autoplan_via_llm(text, cfg=cfg, pcfg=pcfg)
        if llm_result is not None:
            return llm_result
    return _heuristic_result(text, cfg)


# ── Heuristic composer ─────────────────────────────────────────

# Verb / keyword → experience_mode. First match wins.
_MODE_KEYWORDS = (
    (re.compile(r"\b(train|onboard|compliance|certification|new hire)\b", re.I),
     "enterprise_training"),
    (re.compile(r"\b(teach|lesson|tutorial|explain|demonstrate|course)\b", re.I),
     "sfw_education"),
    (re.compile(r"\b(spanish|french|german|english|italian|japanese|mandarin|practice|cefr|a1|a2|b1|b2|c1|c2)\b", re.I),
     "language_learning"),
    (re.compile(r"\b(date|flirt|romance|romantic|companion)\b", re.I),
     "social_romantic"),
)


def _guess_mode(text: str) -> str:
    for pattern, mode in _MODE_KEYWORDS:
        if pattern.search(text):
            return mode
    return "sfw_general"


def _smart_title(text: str) -> str:
    """Title-case the first meaningful phrase. Short, clean."""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return "Interactive experience"
    first_sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    if len(first_sentence) > 60:
        first_sentence = first_sentence[:57].rstrip() + "…"
    # Title-case unless the user already has proper nouns.
    if first_sentence.islower():
        first_sentence = first_sentence[:1].upper() + first_sentence[1:]
    return first_sentence or "Interactive experience"


def _heuristic_result(text: str, cfg: InteractiveConfig) -> PlanAutoResult:
    mode = _guess_mode(text)
    preset = get_preset(mode) or get_preset("sfw_general")
    audience = resolve_audience(text, default_language="en")
    intent = parse_prompt(text or "an interactive experience", cfg=cfg, mode=mode)

    # Clamp structure to UX spec bounds (2–4, 2–3, 2–4).
    branch = max(2, min(4, int(intent.branch_count)))
    depth = max(2, min(3, int(intent.depth)))
    scenes_per_branch = max(2, min(4, int(intent.scenes_per_branch)))

    locale_hint = audience.locale_hint or _guess_locale(text)
    prompt_expanded = _expand_prompt(text, mode, audience.level)

    form = PlanForm(
        title=_smart_title(text),
        prompt=prompt_expanded,
        experience_mode=mode,
        policy_profile_id=mode,
        audience_role=audience.role,
        audience_level=audience.level,
        audience_language=audience.language,
        audience_locale_hint=locale_hint,
        branch_count=branch,
        depth=depth,
        scenes_per_branch=scenes_per_branch,
    )
    seed_intents = list(preset.seed_intents) if preset else list(_FALLBACK_SEEDS)
    return PlanAutoResult(
        form=form,
        objective=intent.objective or "",
        topic=intent.topic or "",
        scheme=intent.scheme or "xp_level",
        success_metric=intent.success_metric or "",
        seed_intents=seed_intents,
        source="heuristic",
    )


def _guess_locale(text: str) -> str:
    hits = re.findall(r"\b(us|uk|eu|italy|spain|france|germany|japan|china)\b", text, re.I)
    return hits[0].lower() if hits else ""


def _expand_prompt(idea: str, mode: str, level: str) -> str:
    """Grow a one-liner into a workable paragraph — still short,
    still editable, but enough for the planner downstream."""
    idea = idea.strip().rstrip(".")
    if not idea:
        return "Interactive experience."
    hint = {
        "enterprise_training":
            "Guide the viewer through key decision points, with short quizzes after each step.",
        "sfw_education":
            "Explain the topic in clear steps, with brief viewer prompts to keep them engaged.",
        "language_learning":
            "Offer short conversational practice with viewer choices and gentle corrections.",
        "social_romantic":
            "Keep the conversation natural and mood-aware, branching on viewer tone.",
        "mature_gated":
            "Require explicit viewer consent up front; keep the flow respectful.",
    }.get(mode, "Keep scenes short and interactive, with one clear choice per decision point.")
    return (
        f"{idea[:1].upper() + idea[1:]}. "
        f"Target {level}-level viewers. {hint}"
    )


# ── LLM composer ───────────────────────────────────────────────

async def _autoplan_via_llm(
    text: str, *, cfg: InteractiveConfig, pcfg: PlaybackConfig,
) -> Optional[PlanAutoResult]:
    """Ask the configured LLM to fill the whole form at once.

    Returns None on any failure — callers fall back to heuristic.
    Guardrails are enforced after parsing: mode whitelist, branch
    clamps, locale length cap, etc.
    """
    from ...llm import chat_ollama  # late import

    messages = _build_messages(text, cfg=cfg)
    try:
        response = await asyncio.wait_for(
            chat_ollama(
                messages,
                temperature=max(0.2, min(pcfg.llm_temperature, 0.7)),
                max_tokens=max(pcfg.llm_max_tokens, 500),
                response_format="json",
            ),
            timeout=pcfg.llm_timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning("autoplan_llm_timeout after %.1fs", pcfg.llm_timeout_s)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("autoplan_llm_error: %s", str(exc)[:400])
        return None

    content = _extract_content(response)
    if not content:
        log.warning("autoplan_llm_empty_content")
        return None

    payload = _parse_json(content)
    if payload is None:
        log.warning(
            "autoplan_llm_malformed_json — first 200 chars: %r",
            content[:200],
        )
        return None

    return _payload_to_result(payload, cfg=cfg)


def _build_messages(text: str, *, cfg: InteractiveConfig) -> List[Dict[str, Any]]:
    system = (
        "You are an AI Interactive Video Planner. Turn the user's short "
        "idea into a COMPLETE project configuration. Respond with ONLY a "
        "JSON object that matches this schema exactly:\n"
        "{\n"
        '  "title": str,               # 3-60 chars, descriptive\n'
        '  "prompt": str,              # 1-3 sentences expanding the idea\n'
        '  "experience_mode": str,     # one of: '
        f"{', '.join(_ALLOWED_MODES)}\n"
        '  "policy_profile_id": str,   # usually matches experience_mode\n'
        '  "audience_role": str,       # viewer | learner | trainee | customer | lead\n'
        '  "audience_level": str,      # beginner | intermediate | advanced\n'
        '  "audience_language": str,   # BCP-47, default "en"\n'
        '  "audience_locale_hint": str,# short region cue or empty string\n'
        '  "branch_count": int,        # 2-4\n'
        '  "depth": int,               # 2-3\n'
        '  "scenes_per_branch": int,   # 2-4\n'
        '  "objective": str,           # one-line goal\n'
        '  "topic": str,               # short noun phrase\n'
        '  "scheme": str,              # xp_level | mastery | cefr | affinity_tier | certification\n'
        '  "success_metric": str,      # e.g. "correct answers" or ""\n'
        '  "seed_intents": [str]       # 3-6 short intent codes\n'
        "}\n\n"
        "Rules:\n"
        "- Infer mode from verbs: train/onboard → enterprise_training, "
        "teach/lesson → sfw_education, language/CEFR → language_learning, "
        "date/flirt/companion → social_romantic, else sfw_general.\n"
        "- Never pick mature_gated unless the user explicitly asked for it.\n"
        "- Keep structure small (2-4 branches, 2-3 depth, 2-4 scenes).\n"
        "- Audience role: training → trainee, teaching → learner, "
        "product → customer, sales → lead, otherwise viewer.\n"
        "- seed_intents use lowercase snake_case (e.g. greeting, quiz, "
        "feedback, choose_path, continue).\n"
        "- No prose, no markdown fences. Strict JSON."
    )
    user = f"Idea: {text.strip()}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── Parsing + validation ───────────────────────────────────────

def _extract_content(response: Dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices or not isinstance(choices, list):
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message") or {}
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    return ""


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(content: str) -> Optional[Dict[str, Any]]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    match = _JSON_BLOCK.search(stripped)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n


def _str_or_default(value: Any, default: str, *, max_len: int = 200) -> str:
    if not isinstance(value, str):
        return default
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return default
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def _payload_to_result(
    payload: Dict[str, Any], *, cfg: InteractiveConfig,
) -> Optional[PlanAutoResult]:
    mode = _str_or_default(payload.get("experience_mode"), "sfw_general", max_len=32)
    if mode not in _ALLOWED_MODES:
        mode = "sfw_general"

    level = _str_or_default(payload.get("audience_level"), "beginner", max_len=16).lower()
    if level not in _ALLOWED_LEVELS:
        level = "beginner"

    profile = _str_or_default(payload.get("policy_profile_id"), mode, max_len=32)
    if profile not in _ALLOWED_MODES:
        profile = mode

    seeds_raw = payload.get("seed_intents")
    if isinstance(seeds_raw, list):
        seeds = [
            re.sub(r"\s+", "_", s.strip().lower())[:40]
            for s in seeds_raw
            if isinstance(s, str) and s.strip()
        ][:8]
    else:
        seeds = list(_FALLBACK_SEEDS)

    # Title + prompt are genuinely required — treat a missing /
    # empty value as a malformed response so the caller falls
    # back to heuristic rather than emit a placeholder form.
    raw_title = payload.get("title")
    raw_prompt = payload.get("prompt")
    if not isinstance(raw_title, str) or not raw_title.strip():
        return None
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        return None
    title = _str_or_default(raw_title, "Interactive experience", max_len=80)
    prompt = _str_or_default(raw_prompt, title, max_len=600)

    form = PlanForm(
        title=title,
        prompt=prompt,
        experience_mode=mode,
        policy_profile_id=profile,
        audience_role=_str_or_default(payload.get("audience_role"), "viewer", max_len=32),
        audience_level=level,
        audience_language=_str_or_default(payload.get("audience_language"), "en", max_len=8),
        audience_locale_hint=_str_or_default(payload.get("audience_locale_hint"), "", max_len=32),
        branch_count=_clamp_int(payload.get("branch_count"), 2, max(2, min(4, cfg.max_branches)), 3),
        depth=_clamp_int(payload.get("depth"), 2, max(2, min(3, cfg.max_depth)), 3),
        scenes_per_branch=_clamp_int(payload.get("scenes_per_branch"), 2, 4, 3),
    )
    return PlanAutoResult(
        form=form,
        objective=_str_or_default(payload.get("objective"), "", max_len=200),
        topic=_str_or_default(payload.get("topic"), "", max_len=80),
        scheme=_str_or_default(payload.get("scheme"), "xp_level", max_len=32),
        success_metric=_str_or_default(payload.get("success_metric"), "", max_len=120),
        seed_intents=seeds,
        source="llm",
    )
