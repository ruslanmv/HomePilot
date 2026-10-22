# expert/router.py
# Smart multi-provider routing: score query complexity → pick optimal provider.
# Fallback chain ensures resilience: if preferred provider fails, try next tier.
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from .config import (
    GROK_API_KEY, GROQ_API_KEY, GEMINI_API_KEY,
    EXPERT_LOCAL_THRESHOLD, EXPERT_GROQ_THRESHOLD,
    EXPERT_SYSTEM_PROMPT, EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE, EXPERT_PROVIDER_TIMEOUT_S,
    EXPERT_HISTORY_MAX_TURNS, EXPERT_HISTORY_MAX_CHARS,
    available_expert_providers,
)
from .providers import (
    chat_grok, stream_grok,
    chat_groq, stream_groq,
    chat_gemini, stream_gemini,
    chat_local, stream_local, stream_local_events,
    chat_openai_compat, stream_openai_compat_events,
    ToolsUnsupported,
)
from . import compaction
from . import grounding
from . import target as target_mod

logger = logging.getLogger("expert.router")

ProviderName = Literal["local", "groq", "grok", "gemini", "claude", "openai", "auto"]


def _attach_dispatch_meta(
    raw: Dict[str, Any],
    *,
    requested_provider: ProviderName,
    fallback_applied: bool,
    notice: Optional[str] = None,
) -> Dict[str, Any]:
    provider_used = raw.get("provider", requested_provider)
    raw["__expert_meta"] = {
        "requested_provider": requested_provider,
        "provider_used": provider_used,
        "fallback_applied": fallback_applied,
        "notice": notice,
    }
    return raw


def extract_dispatch_meta(raw: Dict[str, Any]) -> Dict[str, Any]:
    meta = raw.get("__expert_meta")
    if isinstance(meta, dict):
        return meta
    provider = raw.get("provider", "local")
    return {
        "requested_provider": provider,
        "provider_used": provider,
        "fallback_applied": False,
        "notice": None,
    }


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


# ─────────────────────────────────────────────────────────────────────────────
# Conversation history
# ─────────────────────────────────────────────────────────────────────────────

# Prefixed to a pipeline step's instruction when earlier turns precede it, so the step reads
# the user's latest question against them rather than as a question from nowhere.
CONTINUATION_NOTE = (
    "The task below continues the conversation above. Resolve references in it (\"it\", "
    "\"the second option\", \"as before\"), keep the constraints already agreed, and answer "
    "in the conversation's language.\n\n"
)


def clean_turns(history: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """User and assistant turns with text, in order; everything else dropped."""
    return [
        {"role": str(m.get("role")), "content": str(m.get("content"))}
        for m in (history or [])
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and str(m.get("content") or "").strip()
    ]


def history_window(
    history: Optional[List[Dict[str, Any]]],
    *,
    max_turns: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> List[Dict[str, str]]:
    """The recent conversation as clean chat turns: user and assistant messages with text,
    the newest that fit the turn and character budgets, opening on a user turn (providers
    that enforce role alternation accept the window as it is). The turns before the window
    are not lost: compaction.py carries them as a note."""
    max_turns = EXPERT_HISTORY_MAX_TURNS if max_turns is None else max_turns
    max_chars = EXPERT_HISTORY_MAX_CHARS if max_chars is None else max_chars
    clean = clean_turns(history)
    kept: List[Dict[str, str]] = []
    used = 0
    for m in reversed(clean):
        if len(kept) >= max_turns or used + len(m["content"]) > max_chars:
            break
        kept.append(m)
        used += len(m["content"])
    kept.reverse()
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return kept


def build_messages(
    user_query: str,
    history: Optional[List[Dict[str, str]]] = None,
    system_prompt: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Assemble the messages list: system prompt, the recent conversation as role-tagged
    turns, then the new query as the newest user turn — the shape chat models are trained on."""
    messages: List[Dict[str, str]] = [{
        "role": "system",
        "content": compaction.apply(grounding.apply(system_prompt or EXPERT_SYSTEM_PROMPT)),
    }]
    messages.extend(history_window(history))
    messages.append({"role": "user", "content": user_query})
    return messages


def step_messages(
    instruction: str,
    *,
    system_prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Messages for one call of a multi-step pipeline (think, heavy). Every step sees the
    conversation the question came from — so a follow-up ("and for the second one?") is
    understood in the analysis and the final answer matches the thread — while the step's
    own instruction stays the newest user turn, told that it continues that conversation."""
    turns = history_window(history)
    if turns:
        instruction = CONTINUATION_NOTE + instruction
    return build_messages(instruction, history=turns, system_prompt=system_prompt)


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
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Call the selected provider and return an OpenAI-compatible response dict.
    Includes one fallback level: if provider fails, try local Ollama.
    ``tools`` (OpenAI shape) reach the local/target path — Ollama and OpenAI-compatible
    endpoints; the response message then carries ``tool_calls`` when the model used them.
    """
    try:
        raw = await asyncio.wait_for(
            _call_provider(messages, provider, model=model, temperature=temperature, max_tokens=max_tokens, tools=tools),
            timeout=EXPERT_PROVIDER_TIMEOUT_S,
        )
        return _attach_dispatch_meta(raw, requested_provider=provider, fallback_applied=False)
    except ToolsUnsupported:
        raise
    except Exception as e:
        logger.warning("Provider '%s' failed (%s), falling back to local.", provider, e)
        if provider != "local":
            # "local" is the user's chosen chat model when there is one (see target.py) —
            # called directly, so the fallback never re-enters the path that just failed.
            raw = await asyncio.wait_for(
                _call_local(messages, model=model, temperature=temperature, max_tokens=max_tokens, tools=tools),
                timeout=EXPERT_PROVIDER_TIMEOUT_S,
            )
            return _attach_dispatch_meta(
                raw,
                requested_provider=provider,
                fallback_applied=True,
                notice="Requested provider failed; used local fallback.",
            )
        raise


async def _call_provider(
    messages: List[Dict[str, str]],
    provider: ProviderName,
    *,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
    tools: Optional[List[Dict[str, Any]]] = None,
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
    return await _call_local(messages, tools=tools, **kwargs)


async def _call_local(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """The chat model the user picked (target.py), else local Ollama."""
    kwargs = dict(model=model, temperature=temperature, max_tokens=max_tokens, tools=tools)
    chosen = target_mod.current()
    if chosen is not None:
        return await _call_target(messages, chosen, **kwargs)
    return await chat_local(messages, **kwargs)


async def _call_target(
    messages: List[Dict[str, str]],
    chosen: "target_mod.ChatTarget",
    *,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Answer from the user's chosen chat model: an Ollama model, or an OpenAI-compatible
    endpoint such as an OllaBridge gateway (``http://localhost:11435/v1``) or the Cloud relay.
    """
    if chosen.is_ollama:
        return await chat_local(
            messages,
            model=chosen.model or model,
            base_url=chosen.base_url or None,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )
    return await chat_openai_compat(
        messages,
        base_url=chosen.base_url,
        model=chosen.model or model or "",
        api_key=chosen.api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        provider_label=chosen.label,
        tools=tools,
    )


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
            async for chunk in _stream_provider(messages, "local", model=model,
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
        chosen = target_mod.current()
        if chosen is not None and chosen.is_ollama:
            async for c in stream_local(messages, model=chosen.model or model,
                                        base_url=chosen.base_url or None,
                                        temperature=temperature, max_tokens=max_tokens):
                yield c
        elif chosen is not None:
            # Real streaming from the OpenAI-compatible endpoint; a gateway that cannot stream
            # answers in one chunk, the way Claude and OpenAI are streamed above.
            yielded = False
            try:
                async for ev in stream_openai_compat_events(
                    messages, base_url=chosen.base_url, model=chosen.model or model or "",
                    api_key=chosen.api_key, temperature=temperature, max_tokens=max_tokens,
                ):
                    if "delta" in ev:
                        yielded = True
                        yield ev["delta"]
            except Exception:
                if yielded:
                    raise
                resp = await _call_target(messages, chosen, **kwargs)
                yield resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        else:
            async for c in stream_local(messages, **kwargs): yield c


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch — streaming with structure (tokens and tool calls)
# ─────────────────────────────────────────────────────────────────────────────

async def stream_provider_events(
    messages: List[Dict[str, Any]],
    provider: ProviderName,
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream ``{"delta": text}`` / ``{"tool_calls": [...]}`` events, with the same local
    fallback as :func:`dispatch_stream` (announced as a ``{"notice": ..., "fallback": True}``
    event). ``tools`` reach the local/target path — Ollama and OpenAI-compatible endpoints;
    the other providers stream text only. A ToolsUnsupported refusal is passed through so the
    caller can retry without tools."""
    try:
        async for ev in _stream_provider_events(messages, provider, tools=tools, model=model,
                                                temperature=temperature, max_tokens=max_tokens):
            yield ev
    except ToolsUnsupported:
        raise
    except Exception as e:
        if provider == "local":
            logger.warning("Streaming provider 'local' failed: %s", e)
            raise
        logger.warning("Streaming provider '%s' failed (%s), falling back to local.", provider, e)
        yield {"notice": "Requested provider failed; used local fallback.", "fallback": True}
        async for ev in _stream_provider_events(messages, "local", tools=tools, model=model,
                                                temperature=temperature, max_tokens=max_tokens):
            yield ev


async def _stream_provider_events(
    messages: List[Dict[str, Any]],
    provider: ProviderName,
    *,
    tools: Optional[List[Dict[str, Any]]],
    model: Optional[str],
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[Dict[str, Any]]:
    if provider in ("grok", "groq", "gemini", "claude", "openai"):
        async for c in _stream_provider(messages, provider, model=model, temperature=temperature, max_tokens=max_tokens):
            yield {"delta": c}
        return
    chosen = target_mod.current()
    kwargs = dict(temperature=temperature, max_tokens=max_tokens, tools=tools)
    if chosen is not None and not chosen.is_ollama:
        # Real streaming from the OpenAI-compatible endpoint; when the stream fails before its
        # first event, the plain request is tried once (a gateway that cannot stream still
        # answers that). A refusal of the tools field passes through for the retry without.
        yielded = False
        try:
            async for ev in stream_openai_compat_events(
                messages, base_url=chosen.base_url, model=chosen.model or model or "", api_key=chosen.api_key, **kwargs,
            ):
                yielded = True
                yield ev
        except ToolsUnsupported:
            raise
        except Exception:
            if yielded:
                raise
            raw = await _call_target(messages, chosen, model=model, temperature=temperature, max_tokens=max_tokens, tools=tools)
            message = ((raw.get("choices") or [{}])[0] or {}).get("message") or {}
            if message.get("content"):
                yield {"delta": message["content"]}
            if message.get("tool_calls"):
                yield {"tool_calls": message["tool_calls"]}
    elif chosen is not None:
        async for ev in stream_local_events(messages, model=chosen.model or model, base_url=chosen.base_url or None, **kwargs):
            yield ev
    else:
        async for ev in stream_local_events(messages, model=model, **kwargs):
            yield ev
