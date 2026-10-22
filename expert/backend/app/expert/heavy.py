# expert/heavy.py
# Multi-agent "heavy" pipeline for the most complex queries.
#
# Runs 4 specialized agents sequentially, each with a distinct role:
#
#   Agent 1 — RESEARCHER:  Deep information gathering + context building
#   Agent 2 — REASONER:    Logical inference and chain-of-thought over research
#   Agent 3 — SYNTHESIZER: Condense into a clear, well-structured answer
#   Agent 4 — VALIDATOR:   Final sanity check + quality gate
#
# Each agent can use a different provider (e.g. Groq for fast research,
# Grok for deep reasoning) if configured via HEAVY_*_PROVIDER env vars.
# Falls back to the caller's selected provider for all agents.
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from .config import EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE, EXPERT_SYSTEM_PROMPT
from .router import (
    dispatch, dispatch_stream, extract_dispatch_meta, step_messages, stream_provider_events, ProviderName,
)
from .tool_loop import ThinkFilter, run_with_tools, stream_with_tools, strip_think

logger = logging.getLogger("expert.heavy")

# ─────────────────────────────────────────────────────────────────────────────
# Per-agent provider overrides (optional — falls back to caller's provider)
# ─────────────────────────────────────────────────────────────────────────────

def _agent_provider(agent: str, default: ProviderName) -> ProviderName:
    env_key = f"HEAVY_{agent.upper()}_PROVIDER"
    val = os.getenv(env_key, "").strip()
    return val if val else default  # type: ignore[return-value]


# ─────────────────────────────────────────────────────────────────────────────
# Agent system prompts
# ─────────────────────────────────────────────────────────────────────────────

_RESEARCHER_SYSTEM = (
    "You are a deep research agent. Your role is to gather all relevant "
    "context, background knowledge, related concepts, and potential edge cases "
    "for a given topic. Be exhaustive and precise. Cite what you know."
)

_REASONER_SYSTEM = (
    "You are a logical reasoning agent. Given a research brief, your job is to "
    "reason step-by-step to conclusions. Use deductive and inductive logic. "
    "Identify cause-and-effect relationships. Expose hidden assumptions."
)

_SYNTHESIZER_SYSTEM = (
    "You are a synthesis agent. Given detailed research and reasoning, produce "
    "a clear, well-structured, concise final answer. Use headers if helpful. "
    "Prioritize clarity and actionability. Eliminate redundancy."
)

_VALIDATOR_SYSTEM = (
    "You are a validation agent. Your job is to review a synthesized answer "
    "for accuracy, completeness, and logical consistency. "
    "Reply with JSON only, in this shape: "
    '{"verdict": "validated" | "corrected" | "needs_review", '
    '"issues": [{"severity": "high" | "medium" | "low", "text": "..."}], '
    '"corrected_answer": "the full corrected answer, only when verdict is corrected" | null, '
    '"method": "model review", "limitations": "what you could not verify"}. '
    "Use \"corrected\" only when you can supply the complete corrected answer; use "
    "\"needs_review\" when something important is doubtful but you cannot fix it; "
    "use \"validated\" when the answer holds."
)

VERDICTS = ("validated", "corrected", "needs_review", "reviewed")

# ─────────────────────────────────────────────────────────────────────────────
# Agent prompts
# ─────────────────────────────────────────────────────────────────────────────

_RESEARCH_PROMPT = "Research this topic comprehensively:\n\n{input}"

_REASON_PROMPT = (
    "Using this research brief, reason step-by-step toward an answer:\n\n"
    "Research:\n{research}\n\nOriginal question: {input}"
)

_REASON_DIRECT_PROMPT = (
    "Reason step-by-step toward an answer. Use your tools when a fact, a figure or a current "
    "detail matters.\n\nQuestion: {input}"
)

_SYNTHESIZE_PROMPT = (
    "Synthesize a final answer from this reasoning:\n\n"
    "Question: {input}\n\n"
    "Reasoning:\n{reasoning}"
)

_VALIDATE_PROMPT = (
    "Validate this answer for the given question:\n\n"
    "Question: {input}\n\n"
    "Answer:\n{synthesis}"
)


def _role(system: str, operator: Optional[str]) -> str:
    """An agent's role prompt, plus the operator's (persona or user) instructions when given."""
    if operator and operator.strip():
        return f"{system}\n\nOperator instructions for this assistant:\n{operator.strip()}"
    return system


_NOTES = {
    "validated": "The validator confirmed the answer.",
    "corrected": "The validator found issues and corrected the answer.",
    "needs_review": "The validator raised doubts it could not resolve; read the answer with care.",
    "reviewed": "The validator reviewed the answer without a clear verdict.",
}


def _issues(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str) and item.strip():
            out.append({"severity": "medium", "text": item.strip()})
        elif isinstance(item, dict) and str(item.get("text") or item.get("issue") or "").strip():
            severity = str(item.get("severity") or "medium").lower()
            out.append({"severity": severity if severity in ("high", "medium", "low") else "medium",
                        "text": str(item.get("text") or item.get("issue")).strip()})
    return out[:12]


def verdict_detail(validation: str, synthesis: str) -> Dict[str, Any]:
    """The validator's structured result: ``verdict`` (validated / corrected / needs_review /
    reviewed), ``final_answer``, ``note``, ``issues``, ``method``, ``limitations``.

    JSON first (what the prompt asks for); the older prose shape as a fallback. A correction
    without text, or a "validated" with a high-severity issue, is a disagreement: needs_review."""
    text = (validation or "").strip()
    data: Optional[Dict[str, Any]] = None
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            data = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            data = None
    if data is not None:
        verdict = str(data.get("verdict") or "").strip().lower().replace(" ", "_")
        if verdict not in VERDICTS:
            verdict = "reviewed"
        issues = _issues(data.get("issues"))
        corrected = str(data.get("corrected_answer") or "").strip()
        method = str(data.get("method") or "model review").strip()
        limitations = str(data.get("limitations") or "").strip()
        if verdict == "corrected" and not corrected:
            verdict = "needs_review"
        if verdict == "validated" and any(i["severity"] == "high" for i in issues):
            verdict = "needs_review"
        final = corrected if verdict == "corrected" else synthesis
        return {"verdict": verdict, "final_answer": final, "note": _NOTES[verdict], "issues": issues,
                "method": method, "limitations": limitations, "structured": True}

    upper = text.upper()
    at = upper.find("CORRECTION:")
    if 0 <= at <= 40:
        corrected = text[at + len("CORRECTION:"):].lstrip(" *#:-—\n").strip()
        if corrected:
            return {"verdict": "corrected", "final_answer": corrected, "note": _NOTES["corrected"], "issues": [],
                    "method": "model review", "limitations": "", "structured": False}
    if "VALIDATED" in upper[:160]:
        return {"verdict": "validated", "final_answer": synthesis, "note": _NOTES["validated"], "issues": [],
                "method": "model review", "limitations": "", "structured": False}
    return {"verdict": "reviewed", "final_answer": synthesis, "note": _NOTES["reviewed"], "issues": [],
            "method": "model review", "limitations": "", "structured": False}


def verdict_of(validation: str, synthesis: str) -> Tuple[str, str, str]:
    """``(verdict, final_answer, note)`` — the short form of :func:`verdict_detail`."""
    d = verdict_detail(validation, synthesis)
    return d["verdict"], d["final_answer"], d["note"]


# ─────────────────────────────────────────────────────────────────────────────
# Sync heavy pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def heavy(
    query: str,
    provider: ProviderName = "auto",
    *,
    history: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    system_prompt: Optional[str] = None,
    forced_tools: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
    research: bool = True,
    registry: Any = None,
    tool_rounds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run the heavy pipeline: research (when ``research``; else the reasoner gets the tools) →
    reason → synthesize → validate.
    Returns final answer + all intermediate agent outputs, the validator's structured
    verdict, and the tool trace and sources. ``system_prompt``: operator instructions added
    to every agent's role prompt; ``registry``: the request's tool set.
    """

    # Each agent keeps its own role prompt and gets the recent conversation ahead of its
    # brief (see step_messages).
    def _msg(system: str, user: str) -> List[Dict[str, str]]:
        return step_messages(user, system_prompt=_role(system, system_prompt), history=history)

    kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)
    # A model that cannot call tools still gets grounded: HomePilot searches the question for it.
    assist = [("hp_web_search", {"query": query})]
    loop_kw = dict(call=dispatch, forced=forced_tools, registry=registry, max_rounds=tool_rounds, assist=assist)
    notices: List[str] = []
    fallback_applied = False
    research_text = ""
    tooled: Dict[str, Any] = {}

    researched = research
    if research:
        # Agent 1: Research — with the tool loop (web search, workspace, notes)
        logger.debug("Heavy agent 1: researcher")
        p_research = _agent_provider("researcher", provider)
        try:
            tooled = await run_with_tools(
                _msg(_RESEARCHER_SYSTEM, _RESEARCH_PROMPT.format(input=query)), p_research, **loop_kw, **kw
            )
        except Exception as exc:  # noqa: BLE001 - one agent down is not the turn down
            researched = False
            logger.warning("Heavy research agent failed; reasoning directly instead: %s", exc)
            notices.append(_agent_down("research agent", exc))
        else:
            research_text = tooled.get("content") or ""
            notices.extend(tooled.get("notices", []))
            fallback_applied = bool(tooled.get("fallback_applied"))

    # Agent 2: Reason (with the tools itself when no research agent ran)
    logger.debug("Heavy agent 2: reasoner")
    p_reason = _agent_provider("reasoner", provider)
    if researched:
        raw_reason = await dispatch(
            _msg(_REASONER_SYSTEM, _REASON_PROMPT.format(research=research_text, input=query)),
            p_reason, **kw
        )
        reasoning = _extract(raw_reason)
        notices.extend(_collect_notice(raw_reason))
        fallback_applied = fallback_applied or _fallback(raw_reason)
    else:
        tooled = await run_with_tools(
            _msg(_REASONER_SYSTEM, _REASON_DIRECT_PROMPT.format(input=query)), p_reason, **loop_kw, **kw
        )
        reasoning = tooled.get("content") or ""
        notices.extend(tooled.get("notices", []))
        fallback_applied = fallback_applied or bool(tooled.get("fallback_applied"))

    # Agent 3: Synthesize
    logger.debug("Heavy agent 3: synthesizer")
    p_synth = _agent_provider("synthesizer", provider)
    raw_synth = await dispatch(
        _msg(_SYNTHESIZER_SYSTEM, _SYNTHESIZE_PROMPT.format(input=query, reasoning=reasoning)),
        p_synth, **kw
    )
    synthesis = _extract(raw_synth)
    notices.extend(_collect_notice(raw_synth))
    fallback_applied = fallback_applied or _fallback(raw_synth)

    # Agent 4: Validate
    logger.debug("Heavy agent 4: validator")
    p_valid = _agent_provider("validator", provider)
    validation_skipped = ""
    try:
        raw_valid = await dispatch(
            _msg(_VALIDATOR_SYSTEM, _VALIDATE_PROMPT.format(input=query, synthesis=synthesis)),
            p_valid, **kw
        )
    except Exception as exc:  # noqa: BLE001 - the answer exists; a missing check is said, not fatal
        raw_valid, validation = {}, ""
        validation_skipped = _agent_down("validator", exc)
        logger.warning("Heavy validator failed; answer returned unverified: %s", exc)
        notices.append(validation_skipped)
    else:
        validation = _extract(raw_valid)
        notices.extend(_collect_notice(raw_valid))
        fallback_applied = fallback_applied or _fallback(raw_valid)

    synthesis, validation = strip_think(synthesis), strip_think(validation)
    detail = verdict_detail(validation, synthesis)
    if validation_skipped:
        detail["note"] = "Not validated: the validator could not run. Read the answer with care."
        detail["limitations"] = validation_skipped

    return {
        "final_answer": detail["final_answer"],
        "agents": {
            **({"research": research_text} if research else {}),
            "reasoning": reasoning,
            "synthesis": synthesis,
            "validation": validation,
        },
        "verdict": detail["verdict"],
        "verdict_note": detail["note"],
        "verdict_detail": {k: detail[k] for k in ("verdict", "note", "issues", "method", "limitations", "structured")},
        "researched": research,
        "provider": raw_valid.get("provider", provider),
        "pipeline": "heavy",
        "fallback_applied": fallback_applied,
        "notices": _dedupe_notices(notices),
        "tool_trace": tooled.get("tool_trace", []),
        "sources": tooled.get("sources", []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Streaming heavy pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def stream_heavy(
    query: str,
    provider: ProviderName = "auto",
    *,
    history: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    system_prompt: Optional[str] = None,
    forced_tools: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
    research: bool = True,
    registry: Any = None,
    tool_rounds: Optional[int] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Stream the heavy pipeline agent by agent (the research agent only when ``research``;
    otherwise the reasoner has the tools).
    Each agent's output is streamed live; the UI renders each in a collapsible panel.
    Besides step_start/token/step_end the stream carries the tool events, then ``verdict``
    (the validator's structured call), ``final`` (the answer after validation), ``done``.
    """

    def _msg(system: str, user: str) -> List[Dict[str, str]]:
        return step_messages(user, system_prompt=_role(system, system_prompt), history=history)

    kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)
    assist = [("hp_web_search", {"query": query})]
    loop_kw = dict(stream=stream_provider_events, forced=forced_tools, registry=registry, max_rounds=tool_rounds, assist=assist)
    research_text = ""

    researched = research
    if research:
        # ── Agent 1: Research — with the tool loop ───────────────────────────
        p_research = _agent_provider("researcher", provider)
        yield {"type": "step_start", "step": "research", "label": "🔬 Researching deeply…",
               "provider": p_research, "role": "work"}
        try:
            async for ev in stream_with_tools(
                _msg(_RESEARCHER_SYSTEM, _RESEARCH_PROMPT.format(input=query)), p_research, **loop_kw, **kw
            ):
                if ev["type"] == "token":
                    yield {"type": "token", "step": "research", "content": ev["content"]}
                elif ev["type"] == "done":
                    research_text = ev.get("content") or ""
                else:
                    yield {**ev, "step": "research"}
        except Exception as exc:  # noqa: BLE001 - one agent down is not the turn down
            researched = False
            logger.warning("Heavy research agent failed; reasoning directly instead: %s", exc)
            yield {"type": "notice", "text": _agent_down("research agent", exc)}
        yield {"type": "step_end", "step": "research"}

    # ── Agent 2: Reason (with the tools itself when no research agent ran) ───
    p_reason = _agent_provider("reasoner", provider)
    yield {"type": "step_start", "step": "reasoning", "label": "🧠 Reasoning step-by-step…",
           "provider": p_reason, "role": "work"}
    reason_chunks: List[str] = []
    if researched:
        async for chunk in dispatch_stream(
            _msg(_REASONER_SYSTEM, _REASON_PROMPT.format(research=research_text, input=query)), p_reason, **kw
        ):
            reason_chunks.append(chunk)
            yield {"type": "token", "step": "reasoning", "content": chunk}
    else:
        async for ev in stream_with_tools(
            _msg(_REASONER_SYSTEM, _REASON_DIRECT_PROMPT.format(input=query)), p_reason, **loop_kw, **kw
        ):
            if ev["type"] == "token":
                reason_chunks.append(ev["content"])
                yield {"type": "token", "step": "reasoning", "content": ev["content"]}
            elif ev["type"] == "done":
                reason_chunks = [ev.get("content") or ""]
            else:
                yield {**ev, "step": "reasoning"}
    reasoning = "".join(reason_chunks)
    yield {"type": "step_end", "step": "reasoning"}

    # ── Agent 3: Synthesize ──────────────────────────────────────────────────
    p_synth = _agent_provider("synthesizer", provider)
    yield {"type": "step_start", "step": "synthesis", "label": "✍️ Synthesizing answer…",
           "provider": p_synth, "role": "answer"}
    synth_chunks: List[str] = []
    thinking = ThinkFilter()                      # the synthesis is the reply: no reasoning tags in it
    try:
        async for chunk in dispatch_stream(
            _msg(_SYNTHESIZER_SYSTEM, _SYNTHESIZE_PROMPT.format(input=query, reasoning=reasoning)),
            p_synth, **kw
        ):
            clean = thinking.feed(chunk)
            if clean:
                synth_chunks.append(clean)
                yield {"type": "token", "step": "synthesis", "content": clean}
    except Exception as exc:  # noqa: BLE001 - the reasoning already answers the question
        if not reasoning.strip() or synth_chunks:
            raise
        logger.warning("Heavy synthesizer failed; answering from the reasoning: %s", exc)
        yield {"type": "notice", "text": _agent_down("synthesizer", exc)}
        fallback = strip_think(reasoning)
        synth_chunks.append(fallback)
        yield {"type": "token", "step": "synthesis", "content": fallback}
    tail = thinking.flush()
    if tail:
        synth_chunks.append(tail)
        yield {"type": "token", "step": "synthesis", "content": tail}
    synthesis = "".join(synth_chunks)
    yield {"type": "step_end", "step": "synthesis"}

    # ── Agent 4: Validate ────────────────────────────────────────────────────
    p_valid = _agent_provider("validator", provider)
    yield {"type": "step_start", "step": "validation", "label": "✅ Validating answer…",
           "provider": p_valid, "role": "work"}
    validation_chunks: List[str] = []
    validation_skipped = ""
    try:
        async for chunk in dispatch_stream(
            _msg(_VALIDATOR_SYSTEM, _VALIDATE_PROMPT.format(input=query, synthesis=synthesis)),
            p_valid, **kw
        ):
            validation_chunks.append(chunk)
            yield {"type": "token", "step": "validation", "content": chunk}
    except Exception as exc:  # noqa: BLE001 - the answer exists; a missing check is said, not fatal
        validation_skipped = _agent_down("validator", exc)
        logger.warning("Heavy validator failed; answer returned unverified: %s", exc)
        yield {"type": "notice", "text": validation_skipped}
    yield {"type": "step_end", "step": "validation"}

    # The verdict decides what the reply is: the synthesis, or the validator's correction.
    detail = verdict_detail(strip_think("".join(validation_chunks)), synthesis)
    if validation_skipped:
        detail["note"] = "Not validated: the validator could not run. Read the answer with care."
        detail["limitations"] = validation_skipped
    yield {"type": "verdict", "verdict": detail["verdict"], "note": detail["note"],
           "detail": {k: detail[k] for k in ("issues", "method", "limitations", "structured")}}
    yield {"type": "final", "content": detail["final_answer"]}
    yield {"type": "done"}


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _extract(raw: Dict[str, Any]) -> str:
    try:
        return raw["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        return ""


def _agent_down(agent: str, exc: Exception) -> str:
    """The notice for an agent that could not run (a provider rate limit past its retries, an
    outage): the turn goes on without it, and the reader is told what is missing."""
    reason = " ".join(str(exc).split())[:160] or type(exc).__name__
    return f"Heavy's {agent} could not run ({reason}); the answer was produced without it."


def _fallback(raw: Dict[str, Any]) -> bool:
    return bool(extract_dispatch_meta(raw).get("fallback_applied"))


def _collect_notice(raw: Dict[str, Any]) -> List[str]:
    notice = extract_dispatch_meta(raw).get("notice")
    return [notice] if isinstance(notice, str) and notice else []


def _dedupe_notices(notices: List[str]) -> List[str]:
    return list(dict.fromkeys(notices))
