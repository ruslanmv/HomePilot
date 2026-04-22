# expert/router.py
# Smart multi-provider routing: score query complexity → pick optimal provider.
# Fallback chain ensures resilience: if preferred provider fails, try next tier.
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from .config import (
    GROK_API_KEY, GROQ_API_KEY, GEMINI_API_KEY,
    EXPERT_LOCAL_THRESHOLD, EXPERT_GROQ_THRESHOLD,
    EXPERT_SYSTEM_PROMPT, EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE,
    available_expert_providers,
)
from .providers import (
    chat_grok, stream_grok,
    chat_groq, stream_groq,
    chat_gemini, stream_gemini,
    chat_local, stream_local,
)

logger = logging.getLogger("expert.router")

ProviderName = Literal["local", "groq", "grok", "gemini", "claude", "openai", "auto"]


# ─────────────────────────────────────────────────────────────────────────────
# Complexity scorer
# ─────────────────────────────────────────────────────────────────────────────

_COMPLEX_KEYWORDS = {
    "analyze", "analyse", "compare", "reason", "explain", "prove",
    "research", "summarize", "summarise", "evaluate", "critique",
    "code", "debug", "implement", "design", "architecture",
    "math", "calculate", "derive", "equation",
    "write", "draft", "essay", "report",
}

_SIMPLE_KEYWORDS = {
    "what is", "who is", "when", "where", "define", "list",
    "how many", "translate", "hi", "hello", "thanks",
}


def score_complexity(query: str) -> int:
    """
    Score query complexity 0–10.
    0–3  → local fast model  (simple factual, greetings)
    4–6  → Groq 70B          (moderate reasoning, explanations)
    7–10 → Grok / Gemini     (deep reasoning, long-form, code)
    """
    score = 0
    q = query.lower().strip()

    # Length signals
    words = len(q.split())
    if words > 100:
        score += 3
    elif words > 40:
        score += 2
    elif words > 15:
        score += 1

    # Complexity keywords
    if any(kw in q for kw in _COMPLEX_KEYWORDS):
        score += 3

    # Simple keywords (penalise complexity)
    if any(kw in q for kw in _SIMPLE_KEYWORDS):
        score = max(0, score - 2)

    # Multi-sentence questions suggest depth
    sentences = [s.strip() for s in q.split(".") if s.strip()]
    if len(sentences) > 3:
        score += 1

    # Code blocks or backticks
    if "```" in query or "`" in query:
        score += 2

    # Multiple questions
    if query.count("?") > 1:
        score += 1

    return min(score, 10)


# ─────────────────────────────────────────────────────────────────────────────
# Provider selection
# ─────────────────────────────────────────────────────────────────────────────

def select_provider(query: str, preferred: ProviderName = "auto") -> ProviderName:
    """
    Select best available provider for this query.

    If preferred == 'auto', use complexity-based routing.
    Otherwise, use the requested provider if available, else fallback to auto.
    """
    available = available_expert_providers()

    if preferred != "auto":
        if preferred in available:
            return preferred
        logger.warning("Provider '%s' not available, falling back to auto routing.", preferred)

    complexity = score_complexity(query)
    logger.debug("Query complexity score: %d", complexity)

    if complexity <= EXPERT_LOCAL_THRESHOLD:
        return "local"

    if complexity <= EXPERT_GROQ_THRESHOLD:
        if "groq" in available:
            return "groq"
        if "local" in available:
            return "local"

    # High complexity — best available cloud
    for p in ("grok", "gemini", "claude", "openai", "groq", "local"):
        if p in available:
            return p

    return "local"  # ultimate fallback


def build_messages(
    user_query: str,
    history: Optional[List[Dict[str, str]]] = None,
    system_prompt: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Assemble the messages list with system prompt + history + new query."""
    messages: List[Dict[str, str]] = []
    messages.append({
        "role": "system",
        "content": system_prompt or EXPERT_SYSTEM_PROMPT,
    })
    for msg in (history or []):
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_query})
    return messages


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch — sync
# ─────────────────────────────────────────────────────────────────────────────

async def dispatch(
    messages: List[Dict[str, str]],
    provider: ProviderName,
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> Dict[str, Any]:
    """
    Call the selected provider and return an OpenAI-compatible response dict.
    Includes one fallback level: if provider fails, try local Ollama.
    """
    try:
        return await _call_provider(messages, provider, model=model,
                                    temperature=temperature, max_tokens=max_tokens)
    except Exception as e:
        logger.warning("Provider '%s' failed (%s), falling back to local.", provider, e)
        if provider != "local":
            return await chat_local(messages, model=model, temperature=temperature,
                                    max_tokens=max_tokens)
        raise


async def _call_provider(
    messages: List[Dict[str, str]],
    provider: ProviderName,
    *,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    kwargs = dict(model=model, temperature=temperature, max_tokens=max_tokens)
    if provider == "grok":
        return await chat_grok(messages, **kwargs)
    if provider == "groq":
        return await chat_groq(messages, **kwargs)
    if provider == "gemini":
        return await chat_gemini(messages, **kwargs)
    if provider == "claude":
        # Delegate to existing HomePilot llm.py to reuse ANTHROPIC_API_KEY
        from ..llm import chat_claude
        return await chat_claude(messages, **{k: v for k, v in kwargs.items() if v is not None})
    if provider == "openai":
        from ..llm import chat_openai
        return await chat_openai(messages, **{k: v for k, v in kwargs.items() if v is not None})
    # Default: local Ollama
    return await chat_local(messages, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch — streaming
# ─────────────────────────────────────────────────────────────────────────────

async def dispatch_stream(
    messages: List[Dict[str, str]],
    provider: ProviderName,
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """
    Stream tokens from selected provider.
    Falls back to local if cloud provider fails on first chunk.
    """
    try:
        async for chunk in _stream_provider(messages, provider, model=model,
                                             temperature=temperature, max_tokens=max_tokens):
            yield chunk
    except Exception as e:
        logger.warning("Streaming provider '%s' failed (%s), falling back to local.", provider, e)
        if provider != "local":
            async for chunk in stream_local(messages, model=model,
                                            temperature=temperature, max_tokens=max_tokens):
                yield chunk
        else:
            raise


async def _stream_provider(
    messages: List[Dict[str, str]],
    provider: ProviderName,
    *,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[str]:
    kwargs = dict(model=model, temperature=temperature, max_tokens=max_tokens)
    if provider == "grok":
        async for c in stream_grok(messages, **kwargs): yield c
    elif provider == "groq":
        async for c in stream_groq(messages, **kwargs): yield c
    elif provider == "gemini":
        async for c in stream_gemini(messages, **kwargs): yield c
    elif provider in ("claude", "openai"):
        # Cloud providers without dedicated stream adapter: fall back to non-streaming
        # and emit the full response as one chunk — transparent to the client
        resp = await _call_provider(messages, provider, **kwargs)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        yield content
    else:
        async for c in stream_local(messages, **kwargs): yield c
