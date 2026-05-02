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
from typing import Any, AsyncIterator, Dict, List, Optional

from .config import EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE, EXPERT_SYSTEM_PROMPT
from .router import dispatch, dispatch_stream, extract_dispatch_meta, ProviderName

logger = logging.getLogger("expert.thinking")

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
) -> Dict[str, Any]:
    """
    Run the full analyze → plan → solve pipeline.
    Returns a dict with each step's output plus the final answer.
    """
    def _msg(prompt: str) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": EXPERT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)

    # Step 1: Analyze
    logger.debug("Thinking step 1: analyze")
    raw_analysis = await dispatch(
        _msg(_ANALYZE_PROMPT.format(input=query)), provider, **kw
    )
    analysis = _extract(raw_analysis)
    notices = _collect_notice(raw_analysis)
    fallback_applied = _fallback(raw_analysis)

    # Step 2: Plan
    logger.debug("Thinking step 2: plan")
    raw_plan = await dispatch(
        _msg(_PLAN_PROMPT.format(analysis=analysis)), provider, **kw
    )
    plan = _extract(raw_plan)
    notices.extend(_collect_notice(raw_plan))
    fallback_applied = fallback_applied or _fallback(raw_plan)

    # Step 3: Solve
    logger.debug("Thinking step 3: solve")
    raw_solution = await dispatch(
        _msg(_SOLVE_PROMPT.format(input=query, plan=plan)), provider, **kw
    )
    solution = _extract(raw_solution)
    notices.extend(_collect_notice(raw_solution))
    fallback_applied = fallback_applied or _fallback(raw_solution)

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
            "analysis": analysis,
            "plan": plan,
            "solution": solution,
            **({"critique": critique} if critique else {}),
        },
        "provider": raw_solution.get("provider", provider),
        "model": raw_solution.get("model"),
        "pipeline": "think",
        "fallback_applied": fallback_applied,
        "notices": _dedupe_notices(notices),
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
) -> AsyncIterator[Dict[str, str]]:
    """
    Stream the thinking pipeline step by step.
    Yields dicts with type='step_start'|'token'|'step_end'|'done'.

    The route /v1/expert/stream uses this when thinking_mode='think'.
    The UI can render each step in a collapsible panel.
    """
    def _msg(prompt: str) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": EXPERT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)

    # ── Step 1: Analyze ──────────────────────────────────────────────────────
    yield {"type": "step_start", "step": "analyze", "label": "🔍 Analyzing problem…"}
    analysis_chunks: List[str] = []
    async for chunk in dispatch_stream(_msg(_ANALYZE_PROMPT.format(input=query)), provider, **kw):
        analysis_chunks.append(chunk)
        yield {"type": "token", "step": "analyze", "content": chunk}
    analysis = "".join(analysis_chunks)
    yield {"type": "step_end", "step": "analyze"}

    # ── Step 2: Plan ─────────────────────────────────────────────────────────
    yield {"type": "step_start", "step": "plan", "label": "📋 Building plan…"}
    plan_chunks: List[str] = []
    async for chunk in dispatch_stream(_msg(_PLAN_PROMPT.format(analysis=analysis)), provider, **kw):
        plan_chunks.append(chunk)
        yield {"type": "token", "step": "plan", "content": chunk}
    plan = "".join(plan_chunks)
    yield {"type": "step_end", "step": "plan"}

    # ── Step 3: Solve ────────────────────────────────────────────────────────
    yield {"type": "step_start", "step": "solve", "label": "⚡ Solving…"}
    solve_chunks: List[str] = []
    async for chunk in dispatch_stream(
        _msg(_SOLVE_PROMPT.format(input=query, plan=plan)), provider, **kw
    ):
        solve_chunks.append(chunk)
        yield {"type": "token", "step": "solve", "content": chunk}
    solution_text = "".join(solve_chunks)
    yield {"type": "step_end", "step": "solve"}

    # ── Step 4 (optional): Critique ──────────────────────────────────────────
    if with_critique:
        yield {"type": "step_start", "step": "critique", "label": "🔎 Self-reviewing…"}
        async for chunk in dispatch_stream(
            _msg(_CRITIQUE_PROMPT.format(solution=solution_text)), provider, **kw
        ):
            yield {"type": "token", "step": "critique", "content": chunk}
        yield {"type": "step_end", "step": "critique"}

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
