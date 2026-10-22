# expert/thinking.py
# Multi-step chain-of-thought pipeline for Expert "think" mode.
#
# Instead of a single prompt → response, this pipeline runs 3 sequential
# LLM calls that mirror how a human expert actually solves hard problems:
#
#   Step 1 — ANALYZE:    Decompose the problem, identify what's being asked
#   Step 2 — PLAN:       Create a step-by-step strategy
#   Step 3 — SOLVE:      Execute the plan into a final answer
#
# Each step is streamed individually so the UI can show progress.
# The pipeline reuses the same dispatch layer — provider-agnostic.
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from .config import EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE, EXPERT_SYSTEM_PROMPT
from .router import (
    dispatch, dispatch_stream, extract_dispatch_meta, step_messages, stream_provider_events, ProviderName,
)
from .tool_loop import run_with_tools, stream_with_tools

logger = logging.getLogger("expert.thinking")

# Standard effort: the analysis is written (and shown), then answered from — no separate plan.
_SOLVE_FROM_ANALYSIS_PROMPT = """You are an expert solver. Using the analysis below, give a final, complete answer to the original problem. Speak to the user directly; do not repeat the analysis.

Original problem:
{input}

Analysis:
{analysis}

Final answer:"""


def _solve_prompt(query: str, *, plan: bool, plan_text: str, analyze: bool, analysis: str) -> str:
    """The solve step's instruction for the stages that ran before it."""
    if plan:
        return _SOLVE_PROMPT.format(input=query, plan=plan_text)
    if analyze and analysis.strip():
        return _SOLVE_FROM_ANALYSIS_PROMPT.format(input=query, analysis=analysis.strip())
    return _SOLVE_DIRECT_PROMPT.format(input=query)

# ─────────────────────────────────────────────────────────────────────────────
# Step prompts
# ─────────────────────────────────────────────────────────────────────────────

_ANALYZE_PROMPT = """\
You are an analytical reasoning engine. Your job is ONLY to decompose and analyze the following problem.

Do NOT attempt to solve it yet. Instead:
1. Identify what is actually being asked (restate it precisely)
2. Identify the domain(s) involved
3. Identify what information or reasoning is needed
4. Flag any ambiguities or unstated assumptions

Problem:
{input}

Analysis:"""

_PLAN_PROMPT = """\
You are a strategic planner. Based on the following analysis, create a clear step-by-step plan to solve the original problem.

Each step should be concrete and actionable. Do NOT solve yet — only plan.

Analysis:
{analysis}

Step-by-step plan:"""

_SOLVE_PROMPT = """\
You are an expert solver. Execute the following plan to produce a final, complete answer to the original problem.

Be thorough, accurate, and clear. Show your work where relevant.

Original problem: {input}

Plan to execute:
{plan}

Final answer:"""

_SOLVE_DIRECT_PROMPT = """\
You are an expert solver. Produce a complete, accurate answer to the following problem; show your work where it helps.

Problem: {input}

Final answer:"""

_CRITIQUE_PROMPT = """\
You are a rigorous critic. Review the following answer and check for:
- Factual errors
- Logical gaps
- Missing edge cases
- Clarity issues

If the answer is correct and complete, say so briefly. Otherwise, provide a corrected version.

Answer to review:
{solution}

Review:"""


# ─────────────────────────────────────────────────────────────────────────────
# Sync thinking pipeline (returns full result + steps for inspection)
# ─────────────────────────────────────────────────────────────────────────────

async def think(
    query: str,
    provider: ProviderName = "auto",
    *,
    history: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    with_critique: bool = False,
    system_prompt: Optional[str] = None,
    forced_tools: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
    plan: bool = True,
    analyze: bool = False,
    registry: Any = None,
    tool_rounds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run the analyze → plan → solve pipeline, or solve alone when ``plan`` is False (a request
    below the planning threshold, see policies.effort_for).
    Returns a dict with each step's output plus the final answer.
    ``system_prompt`` (the persona's or the user's instructions) replaces the Expert default;
    ``forced_tools`` run before the solve step asks the model anything; ``registry`` is the
    request's tool set (the shared one when None).
    """
    base = system_prompt or EXPERT_SYSTEM_PROMPT

    # Each step gets the recent conversation ahead of its instruction (see step_messages).
    def _msg(prompt: str) -> List[Dict[str, str]]:
        return step_messages(prompt, system_prompt=base, history=history)

    kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)
    notices: List[str] = []
    fallback_applied = False
    analysis = plan_text = ""

    if plan or analyze:
        # Step 1: Analyze — the visible reasoning (also alone, at standard effort)
        logger.debug("Thinking step 1: analyze")
        raw_analysis = await dispatch(_msg(_ANALYZE_PROMPT.format(input=query)), provider, **kw)
        analysis = _extract(raw_analysis)
        notices.extend(_collect_notice(raw_analysis))
        fallback_applied = _fallback(raw_analysis)

    if plan:
        # Step 2: Plan
        logger.debug("Thinking step 2: plan")
        raw_plan = await dispatch(_msg(_PLAN_PROMPT.format(analysis=analysis)), provider, **kw)
        plan_text = _extract(raw_plan)
        notices.extend(_collect_notice(raw_plan))
        fallback_applied = fallback_applied or _fallback(raw_plan)

    # Step 3: Solve — with the per-turn tool loop, so the answer can check facts
    logger.debug("Thinking step 3: solve")
    solve_prompt = _solve_prompt(query, plan=plan, plan_text=plan_text, analyze=analyze, analysis=analysis)
    solved = await run_with_tools(
        _msg(solve_prompt), provider, call=dispatch, forced=forced_tools, registry=registry,
        max_rounds=tool_rounds, **kw
    )
    solution = solved.get("content") or ""
    notices.extend(solved.get("notices", []))
    fallback_applied = fallback_applied or bool(solved.get("fallback_applied"))

    # Step 4 (optional): Self-critique
    critique = None
    if with_critique:
        logger.debug("Thinking step 4: critique")
        raw_critique = await dispatch(
            _msg(_CRITIQUE_PROMPT.format(solution=solution)), provider, **kw
        )
        critique = _extract(raw_critique)
        notices.extend(_collect_notice(raw_critique))
        fallback_applied = fallback_applied or _fallback(raw_critique)

    return {
        "final_answer": solution,
        "steps": {
            **({"analysis": analysis} if (plan or analyze) else {}),
            **({"plan": plan_text} if plan else {}),
            "solution": solution,
            **({"critique": critique} if critique else {}),
        },
        "planned": plan,
        "provider": provider,
        "model": model,
        "pipeline": "think",
        "fallback_applied": fallback_applied,
        "notices": _dedupe_notices(notices),
        "tool_trace": solved.get("tool_trace", []),
        "sources": solved.get("sources", []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Streaming thinking pipeline — yields step labels + tokens
# ─────────────────────────────────────────────────────────────────────────────

async def stream_think(
    query: str,
    provider: ProviderName = "auto",
    *,
    history: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    with_critique: bool = False,
    system_prompt: Optional[str] = None,
    forced_tools: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
    plan: bool = True,
    analyze: bool = False,
    registry: Any = None,
    tool_rounds: Optional[int] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Stream the thinking pipeline step by step (solve alone when ``plan`` is False).
    Yields dicts with type='step_start'|'token'|'step_end'|'final'|'done', plus the tool
    loop's events (tool_start, tool_end, sources, reset, notice) tagged with their step.
    A step_start carries role='work' or role='answer' (the step whose text is the reply).

    The route /v1/expert/stream uses this when thinking_mode='think'.
    The UI can render each step in a collapsible panel.
    """
    base = system_prompt or EXPERT_SYSTEM_PROMPT

    def _msg(prompt: str) -> List[Dict[str, str]]:
        return step_messages(prompt, system_prompt=base, history=history)

    kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)
    analysis = plan_text = ""

    if plan or analyze:
        # ── Step 1: Analyze — the visible reasoning, shown as ChatGPT and Claude show theirs
        yield {"type": "step_start", "step": "analyze", "label": "🔍 Analyzing problem…", "role": "work"}
        analysis_chunks: List[str] = []
        async for chunk in dispatch_stream(_msg(_ANALYZE_PROMPT.format(input=query)), provider, **kw):
            analysis_chunks.append(chunk)
            yield {"type": "token", "step": "analyze", "content": chunk}
        analysis = "".join(analysis_chunks)
        yield {"type": "step_end", "step": "analyze"}

    if plan:
        # ── Step 2: Plan ─────────────────────────────────────────────────────
        yield {"type": "step_start", "step": "plan", "label": "📋 Building plan…", "role": "work"}
        plan_chunks: List[str] = []
        async for chunk in dispatch_stream(_msg(_PLAN_PROMPT.format(analysis=analysis)), provider, **kw):
            plan_chunks.append(chunk)
            yield {"type": "token", "step": "plan", "content": chunk}
        plan_text = "".join(plan_chunks)
        yield {"type": "step_end", "step": "plan"}

    # ── Step 3: Solve — with the per-turn tool loop ─────────────────────────
    yield {"type": "step_start", "step": "solve", "label": "⚡ Solving…" if plan else "⚡ Answering…", "role": "answer"}
    solution_text = ""
    solve_prompt = _solve_prompt(query, plan=plan, plan_text=plan_text, analyze=analyze, analysis=analysis)
    async for ev in stream_with_tools(
        _msg(solve_prompt), provider,
        stream=stream_provider_events, forced=forced_tools, registry=registry, max_rounds=tool_rounds, **kw
    ):
        if ev["type"] == "token":
            yield {"type": "token", "step": "solve", "content": ev["content"]}
        elif ev["type"] == "done":
            solution_text = ev.get("content") or ""
        else:
            yield {**ev, "step": "solve"}
    yield {"type": "step_end", "step": "solve"}

    # ── Step 4 (optional): Critique ──────────────────────────────────────────
    if with_critique:
        yield {"type": "step_start", "step": "critique", "label": "🔎 Self-reviewing…", "role": "work"}
        async for chunk in dispatch_stream(
            _msg(_CRITIQUE_PROMPT.format(solution=solution_text)), provider, **kw
        ):
            yield {"type": "token", "step": "critique", "content": chunk}
        yield {"type": "step_end", "step": "critique"}

    yield {"type": "final", "content": solution_text}
    yield {"type": "done"}


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _extract(raw: Dict[str, Any]) -> str:
    try:
        return raw["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        return ""


def _fallback(raw: Dict[str, Any]) -> bool:
    return bool(extract_dispatch_meta(raw).get("fallback_applied"))


def _collect_notice(raw: Dict[str, Any]) -> List[str]:
    notice = extract_dispatch_meta(raw).get("notice")
    return [notice] if isinstance(notice, str) and notice else []


def _dedupe_notices(notices: List[str]) -> List[str]:
    return list(dict.fromkeys(notices))
