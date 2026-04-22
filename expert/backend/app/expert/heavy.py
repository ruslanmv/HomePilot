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

import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

from .config import EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE, EXPERT_SYSTEM_PROMPT
from .router import dispatch, dispatch_stream, ProviderName

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
    "If correct, say 'VALIDATED' and add any small improvements. "
    "If incorrect, output 'CORRECTION:' followed by the fixed answer."
)

# ─────────────────────────────────────────────────────────────────────────────
# Agent prompts
# ─────────────────────────────────────────────────────────────────────────────

_RESEARCH_PROMPT = "Research this topic comprehensively:\n\n{input}"

_REASON_PROMPT = (
    "Using this research brief, reason step-by-step toward an answer:\n\n"
    "Research:\n{research}\n\nOriginal question: {input}"
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
) -> Dict[str, Any]:
    """
    Run the full 4-agent heavy pipeline.
    Returns final answer + all intermediate agent outputs.
    """

    def _msg(system: str, user: str) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)

    # Agent 1: Research
    logger.debug("Heavy agent 1: researcher")
    p_research = _agent_provider("researcher", provider)
    raw_research = await dispatch(
        _msg(_RESEARCHER_SYSTEM, _RESEARCH_PROMPT.format(input=query)),
        p_research, **kw
    )
    research = _extract(raw_research)

    # Agent 2: Reason
    logger.debug("Heavy agent 2: reasoner")
    p_reason = _agent_provider("reasoner", provider)
    raw_reason = await dispatch(
        _msg(_REASONER_SYSTEM, _REASON_PROMPT.format(research=research, input=query)),
        p_reason, **kw
    )
    reasoning = _extract(raw_reason)

    # Agent 3: Synthesize
    logger.debug("Heavy agent 3: synthesizer")
    p_synth = _agent_provider("synthesizer", provider)
    raw_synth = await dispatch(
        _msg(_SYNTHESIZER_SYSTEM, _SYNTHESIZE_PROMPT.format(input=query, reasoning=reasoning)),
        p_synth, **kw
    )
    synthesis = _extract(raw_synth)

    # Agent 4: Validate
    logger.debug("Heavy agent 4: validator")
    p_valid = _agent_provider("validator", provider)
    raw_valid = await dispatch(
        _msg(_VALIDATOR_SYSTEM, _VALIDATE_PROMPT.format(input=query, synthesis=synthesis)),
        p_valid, **kw
    )
    validation = _extract(raw_valid)

    # If validator found issues, use its corrected version as final answer
    if validation.upper().startswith("CORRECTION:"):
        final_answer = validation[len("CORRECTION:"):].strip()
    else:
        final_answer = synthesis

    return {
        "final_answer": final_answer,
        "agents": {
            "research": research,
            "reasoning": reasoning,
            "synthesis": synthesis,
            "validation": validation,
        },
        "provider": provider,
        "pipeline": "heavy",
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
) -> AsyncIterator[Dict[str, str]]:
    """
    Stream the heavy pipeline agent by agent.
    Each agent's output is streamed live; the UI renders each in a collapsible panel.
    """

    def _msg(system: str, user: str) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    kw = dict(model=model, temperature=temperature, max_tokens=max_tokens)

    # ── Agent 1: Research ────────────────────────────────────────────────────
    p_research = _agent_provider("researcher", provider)
    yield {"type": "step_start", "step": "research", "label": "🔬 Researching deeply…",
           "provider": p_research}
    research_chunks: List[str] = []
    async for chunk in dispatch_stream(
        _msg(_RESEARCHER_SYSTEM, _RESEARCH_PROMPT.format(input=query)),
        p_research, **kw
    ):
        research_chunks.append(chunk)
        yield {"type": "token", "step": "research", "content": chunk}
    research = "".join(research_chunks)
    yield {"type": "step_end", "step": "research"}

    # ── Agent 2: Reason ──────────────────────────────────────────────────────
    p_reason = _agent_provider("reasoner", provider)
    yield {"type": "step_start", "step": "reasoning", "label": "🧠 Reasoning step-by-step…",
           "provider": p_reason}
    reason_chunks: List[str] = []
    async for chunk in dispatch_stream(
        _msg(_REASONER_SYSTEM, _REASON_PROMPT.format(research=research, input=query)),
        p_reason, **kw
    ):
        reason_chunks.append(chunk)
        yield {"type": "token", "step": "reasoning", "content": chunk}
    reasoning = "".join(reason_chunks)
    yield {"type": "step_end", "step": "reasoning"}

    # ── Agent 3: Synthesize ──────────────────────────────────────────────────
    p_synth = _agent_provider("synthesizer", provider)
    yield {"type": "step_start", "step": "synthesis", "label": "✍️ Synthesizing answer…",
           "provider": p_synth}
    synth_chunks: List[str] = []
    async for chunk in dispatch_stream(
        _msg(_SYNTHESIZER_SYSTEM, _SYNTHESIZE_PROMPT.format(input=query, reasoning=reasoning)),
        p_synth, **kw
    ):
        synth_chunks.append(chunk)
        yield {"type": "token", "step": "synthesis", "content": chunk}
    synthesis = "".join(synth_chunks)
    yield {"type": "step_end", "step": "synthesis"}

    # ── Agent 4: Validate ────────────────────────────────────────────────────
    p_valid = _agent_provider("validator", provider)
    yield {"type": "step_start", "step": "validation", "label": "✅ Validating answer…",
           "provider": p_valid}
    async for chunk in dispatch_stream(
        _msg(_VALIDATOR_SYSTEM, _VALIDATE_PROMPT.format(input=query, synthesis=synthesis)),
        p_valid, **kw
    ):
        yield {"type": "token", "step": "validation", "content": chunk}
    yield {"type": "step_end", "step": "validation"}

    yield {"type": "done"}


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _extract(raw: Dict[str, Any]) -> str:
    try:
        return raw["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        return ""
