# homepilot/backend/app/llm.py
from __future__ import annotations

import json
import os
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Literal

import httpx

from .tracing import log_event

# Request-scoped provider credential (additive). The /chat endpoint sets this
# from ChatIn.provider_api_key so that EVERY openai_compat call made while
# serving that request (main generation, prompt refiners, etc.) authenticates
# to the remote provider — e.g. the OllaBridge Cloud relay, which resolves the
# bearer to a user and routes inference to that user's own GPU node. Using a
# ContextVar avoids threading an api_key parameter through every orchestrator
# call site; asyncio gives each request its own context, so no cross-request
# leakage is possible. Empty string = no auth header (existing behavior).
PROVIDER_API_KEY: ContextVar[str] = ContextVar("hp_provider_api_key", default="")


import re


# Patterns that identify thinking/reasoning models (DeepSeek R1, QwQ, Qwen3, etc.)
# These models emit <think>...</think> tags and need extra tokens for voice mode.
THINKING_MODEL_PATTERNS = [
    "deepseek-r1", "deepseek-reasoner", "qwq", "qwen3",
    "reflection", "reasoning", "think",
]

# Match all common reasoning tag formats emitted by thinking models
_THINK_RE = re.compile(
    r"<(?:think|thinking|reasoning|reflection)>.*?</(?:think|thinking|reasoning|reflection)>",
    re.DOTALL | re.IGNORECASE,
)


def is_thinking_model(model_name: str) -> bool:
    """Detect if a model is a thinking/reasoning model that emits <think> tags."""
    if not model_name:
        return False
    lower = model_name.lower()
    return any(p in lower for p in THINKING_MODEL_PATTERNS)


def _short_debug_text(value: Any, limit: int = 160) -> str:
    """Single-line, bounded text for debug logs without dumping full prompts."""
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


# Phrases that indicate leaked reasoning / self-instructions, NOT spoken dialogue.
# Used to filter the thinking-field recovery so meta-text never reaches the user.
_REASONING_PREFIXES = (
    "Let me", "I need to", "I should", "The user", "So I", "Also,",
    "First,", "Now,", "Next,", "Maybe", "Perhaps", "Since they",
    "Keep the response", "Make sure", "I will", "I'll",
    "Their ", "They ", "This means", "Based on",
    "Alternatively", "However,", "But since", "In this case",
    "Given that", "Okay,", "Alright,", "Hmm,", "Wait,",
    "Looking at", "Considering", "To respond",
    "So, the", "So the response", "So, I",
)
# Single phrases that are strong indicators of leaked reasoning (any match → reasoning)
_REASONING_PHRASES = [
    "previous interactions",
    "matching their",
    "as if I",
    "I'm a real",
    "to show my",
    "to leave a lasting",
    "to the point",
    "avoid any hesitation",
    "the user wants",
    "the user asked",
    "the user just",
    "the user's last",
    "the user said",
    "connect it to",
    "use phrases like",
    "use exclamation",
    "let me check",
    "maintain consistency",
    "fits well",
    "could be effective",
    "might be better",
    "a good response",
    "respond with",
    "my response",
    "previous response",
    "previous message",
    "in character",
    "stay in character",
    "break character",
    "system prompt",
    "instructions say",
    "the response should",
    "response should be",
    "should respond",
    "connects to their",
    "their previous interest",
    "provides an interesting",
    "something like:",
    "would be something like",
    "i would say",
]
# Scoring-based indicators: each match adds 1 point, threshold ≥ 3 = reasoning
# Only clearly meta-commentary signals — removed natural-speech phrases
# ("make sure", "let me", "because the", "keep it", etc.) that cause
# false positives in cooking/planning/casual conversation.
_REASONING_SIGNALS = [
    "the user",           # 3rd person reference
    "their message",      # 3rd person reference
    "the human",          # 3rd person reference
    "i should",           # self-instruction
    "i need to",          # self-instruction
    "i'll respond",       # response planning
    "direct question",    # meta-commentary
    "a metaphor",         # meta-commentary about technique
    "double entendre",    # meta-commentary about technique
    "since they",         # analysis (about 3rd person)
]


def _is_reasoning_text(text: str) -> bool:
    """
    Return True if text looks like leaked model reasoning, not spoken dialogue.

    Uses a three-layer approach:
      1. Prefix check — text starts with reasoning starters
      2. Phrase check — text contains strong reasoning indicators
      3. Scoring check — multiple weak signals together confirm reasoning
    """
    if not text:
        return False
    stripped = text.strip()
    # Layer 1: Prefix patterns (model talking to itself)
    if stripped.startswith(_REASONING_PREFIXES):
        return True
    lower = stripped.lower()
    # Layer 2: Strong reasoning phrases (any single match = reasoning)
    if any(phrase in lower for phrase in _REASONING_PHRASES):
        return True
    # Layer 3: Scoring — accumulate weak signals, threshold ≥ 3
    score = sum(1 for signal in _REASONING_SIGNALS if signal in lower)
    return score >= 3


# Regex to extract a quoted "actual response" from leaked reasoning.
# Matches: something like: "actual text" or "actual text" at end
_QUOTED_RESPONSE_RE = re.compile(
    r'(?:something like|should be|respond with|would say)[:\s]*["\u201c](.+?)["\u201d]',
    re.DOTALL | re.IGNORECASE,
)


def recover_from_reasoning(text: str) -> str | None:
    """Try to extract the intended spoken response from leaked reasoning text.

    Thinking models sometimes output reasoning like:
      'So, the response should be something like: "Hey! Did you know..."'

    Instead of discarding everything and falling back to a generic reply,
    we attempt to extract the quoted spoken response.  Returns None if
    no recoverable response is found.
    """
    if not text:
        return None
    m = _QUOTED_RESPONSE_RE.search(text)
    if m:
        candidate = m.group(1).strip()
        # Sanity: extracted text should be dialogue, not more reasoning
        if candidate and len(candidate) >= 8 and not _is_reasoning_text(candidate):
            return candidate
    return None


def strip_think_tags(text: str) -> str:
    """Strip reasoning blocks (<think>, <thinking>, <reasoning>, <reflection>) from model output."""
    if not text:
        return text
    lower = text.lower()
    if not any(tag in lower for tag in ("<think>", "<thinking>", "<reasoning>", "<reflection>")):
        return text
    cleaned = _THINK_RE.sub("", text).strip()
    return cleaned if cleaned else text  # keep original if everything was inside think tags


def _extract_first_json_object(text: str) -> str:
    """
    Extract the first balanced JSON object from text.
    Handles cases where JSON is embedded in extra text (e.g., "thinking" field).
    Returns empty string if no valid balanced object found.
    """
    s = (text or "").strip()
    if not s:
        return ""

    start = s.find("{")
    if start == -1:
        return ""

    depth = 0
    in_str = False
    esc = False

    for i in range(start, len(s)):
        ch = s[i]

        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]

    return ""  # incomplete/truncated


def _is_placeholder_json(text: str) -> bool:
    """
    Detect if extracted JSON contains placeholder values from schema examples.
    DeepSeek R1 sometimes echoes the schema instead of generating actual content.
    """
    if not text or len(text) < 20:
        return True

    # Common placeholder patterns that indicate schema was echoed
    placeholder_patterns = [
        r'"variation_prompt"\s*:\s*"string"',
        r'"title"\s*:\s*"string"',
        r'"logline"\s*:\s*"string"',
        r'"narration"\s*:\s*"string"',
        r'"image_prompt"\s*:\s*"string"',
        r':\s*"\.\.\."',
        r':\s*"<[^>]+>"',  # Matches "<YOUR TEXT HERE>" patterns
    ]

    text_lower = text.lower()
    for pattern in placeholder_patterns:
        if re.search(pattern, text_lower):
            return True

    return False


from .config import (
    TOOL_TIMEOUT_S,
    LLM_MODEL,
    LLM_BASE_URL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL,
)

ProviderName = Literal["openai_compat", "ollama", "openai", "claude", "watsonx"]


def _timeout() -> httpx.Timeout:
    # Keep connect reasonable; total bounded by TOOL_TIMEOUT_S
    return httpx.Timeout(timeout=TOOL_TIMEOUT_S, connect=30.0)


async def chat_openai_compat(
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 800,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    OpenAI-compatible chat/completions (vLLM, OllaBridge Cloud relay, etc.)
    Returns OpenAI-style JSON with choices[0].message.content.

    Auth: explicit ``api_key`` wins, else the request-scoped PROVIDER_API_KEY
    contextvar (set by /chat from ChatIn.provider_api_key). When present it is
    sent as a Bearer token — the OllaBridge Cloud relay resolves it to a user
    and routes the completion to that user's own GPU node.
    """
    base = (base_url or LLM_BASE_URL).rstrip("/")
    mdl = (model or LLM_MODEL).strip()

    url = f"{base}/chat/completions"
    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    key = (api_key or PROVIDER_API_KEY.get() or "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()


async def chat_openai(
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 800,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """OpenAI Chat Completions API."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OpenAI API key not configured (OPENAI_API_KEY).")

    base = (base_url or OPENAI_BASE_URL).rstrip("/")
    # OPENAI_BASE_URL is expected to include /v1
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    mdl = (model or OPENAI_MODEL).strip()

    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"})
        r.raise_for_status()
        return r.json()


async def chat_claude(
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 800,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Anthropic Messages API adapter returning OpenAI-like schema."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Claude (Anthropic) API key not configured (ANTHROPIC_API_KEY).")

    base = (base_url or ANTHROPIC_BASE_URL).rstrip("/")
    url = f"{base}/v1/messages"
    anthropic_version = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
    mdl = (model or ANTHROPIC_MODEL).strip()

    # Anthropic wants a separate system string + user/assistant turns.
    system_msg = ""
    chat_msgs = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            system_msg = f"{system_msg}\n{content}".strip() if system_msg else str(content)
        elif role in {"user", "assistant"}:
            chat_msgs.append({"role": role, "content": str(content)})

    payload = {
        "model": mdl,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "messages": chat_msgs,
    }
    if system_msg:
        payload["system"] = system_msg

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.post(
            url,
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": anthropic_version,
                "content-type": "application/json",
            },
        )
        r.raise_for_status()
        data = r.json()

    # Convert to OpenAI-like response.
    content_text = ""
    blocks = data.get("content")
    if isinstance(blocks, list):
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                content_text += str(b.get("text") or "")

    return {
        "choices": [{"message": {"content": content_text}}],
        "provider_raw": data,
    }


async def chat_watsonx(*_: Any, **__: Any) -> Dict[str, Any]:
    raise RuntimeError(
        "Watsonx chat is not configured in this build. "
        "Model listing is available, but chat requires IBM IAM token flow + project/space configuration."
    )


async def chat_ollama(
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 800,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    response_format: Optional[str] = None,
    stop: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Ollama /api/chat adapter -> returns OpenAI-style JSON for orchestrator consistency.
    Ollama expects:
      { model, messages: [{role, content}], stream: false, options: {...} }
    """
    base = (base_url or OLLAMA_BASE_URL).rstrip("/")
    requested_model = (model or "").strip() or None
    mdl = (model or OLLAMA_MODEL).strip()

    url = f"{base}/api/chat"
    request_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    thinking_disabled = False
    if is_thinking_model(mdl) and not response_format:
        # Qwen3/R1-style local models can spend minutes in hidden reasoning for
        # simple companion turns. Disable reasoning when the Ollama build/model
        # supports it and also add the Qwen3 /no_think control token as a
        # harmless prompt-level fallback for older servers. This keeps ordinary
        # chat/voice turns responsive while preserving the user-selected model.
        thinking_disabled = True
        for m in reversed(request_messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                if "/no_think" not in m["content"].lower():
                    m["content"] = f'{m["content"]}\n/no_think'
                break

    payload = {
        "model": mdl,
        "messages": request_messages,
        "stream": False,
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "options": {
            "temperature": float(temperature),
            # Ollama doesn't use max_tokens exactly the same way; keep best-effort:
            "num_predict": int(max_tokens),
        },
    }
    if thinking_disabled:
        payload["think"] = False

    # If supported by your Ollama build/model, this enforces JSON-only output at decode-time.
    # Values commonly supported: "json".
    if response_format:
        payload["format"] = str(response_format)

    # Optional stop sequences (Ollama supports stop inside options).
    if stop:
        payload.setdefault("options", {})["stop"] = list(stop)

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        if not mdl:
            # Auto-pick first available model (prod-friendly default)
            try:
                tags_r = await client.get(f"{base}/api/tags")
                if tags_r.status_code == 200:
                    tags_data = tags_r.json()
                    models = tags_data.get("models", [])
                    if models:
                        mdl = str(models[0].get("name") or "").strip()
            except Exception:
                pass

        if not mdl:
            raise RuntimeError(
                "Ollama has no model selected and none were found. "
                "Run 'ollama pull llama3:8b' (or another model) and refresh the UI."
            )

        # Ensure payload uses the final model name
        payload["model"] = mdl

        prompt_chars = sum(len(str(m.get("content") or "")) for m in request_messages)
        log_event(
            "llm.request",
            provider="ollama",
            requested_model=requested_model,
            selected_model=mdl,
            base_url=base,
            message_count=len(request_messages),
            prompt_chars=prompt_chars,
            max_tokens=max_tokens,
            think=payload.get("think"),
            keep_alive=payload.get("keep_alive"),
        )
        print(
            "[OLLAMA] request model=%r base=%s messages=%d prompt_chars=%d "
            "num_predict=%s think=%r keep_alive=%r last_user=%r"
            % (
                mdl,
                base,
                len(request_messages),
                prompt_chars,
                payload.get("options", {}).get("num_predict"),
                payload.get("think"),
                payload.get("keep_alive"),
                _short_debug_text(next((m.get("content") for m in reversed(request_messages) if m.get("role") == "user"), "")),
            )
        )
        started = time.perf_counter()
        try:
            r = await client.post(url, json=payload)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            r.raise_for_status()
            data = r.json()
            log_event(
                "llm.response",
                provider="ollama",
                selected_model=mdl,
                status=r.status_code,
                elapsed_ms=elapsed_ms,
                done_reason=data.get("done_reason"),
                prompt_eval_count=data.get("prompt_eval_count"),
                eval_count=data.get("eval_count"),
            )
            print(
                "[OLLAMA] response model=%r status=%s elapsed_ms=%d done_reason=%r "
                "load_ms=%s prompt_eval_count=%s prompt_eval_ms=%s eval_count=%s eval_ms=%s"
                % (
                    mdl,
                    r.status_code,
                    elapsed_ms,
                    data.get("done_reason"),
                    int(data.get("load_duration", 0) / 1_000_000) if data.get("load_duration") is not None else None,
                    data.get("prompt_eval_count"),
                    int(data.get("prompt_eval_duration", 0) / 1_000_000) if data.get("prompt_eval_duration") is not None else None,
                    data.get("eval_count"),
                    int(data.get("eval_duration", 0) / 1_000_000) if data.get("eval_duration") is not None else None,
                )
            )
        except httpx.HTTPStatusError as e:
            # Better error handling for 404 model not found
            if e.response.status_code == 404:
                error_msg = f"Ollama model '{mdl}' not found"

                # Try to fetch available models
                try:
                    tags_r = await client.get(f"{base}/api/tags")
                    if tags_r.status_code == 200:
                        tags_data = tags_r.json()
                        models = tags_data.get("models", [])
                        if models:
                            model_names = [m.get("name", "") for m in models if m.get("name")]
                            error_msg += f". Available models: {', '.join(model_names)}"
                            # Provide a simple suggestion if a close llama tag exists
                            if mdl.startswith("llama") and "llama3:8b" in model_names and mdl != "llama3:8b":
                                error_msg += " (Did you mean llama3:8b?)"
                        else:
                            error_msg += ". No models are currently available. Run 'ollama pull <model-name>' to download a model."
                    else:
                        error_msg += f". Could not fetch available models. Please run 'ollama pull {mdl}' to download it."
                except Exception:
                    error_msg += f". Please run 'ollama pull {mdl}' to download it."

                raise RuntimeError(error_msg) from e
            else:
                # Re-raise other HTTP errors
                raise RuntimeError(f"Ollama HTTP {e.response.status_code}: {e.response.text}") from e

    # Normalize to OpenAI-like shape for downstream parsing
    content = ""
    msg = data.get("message")

    # Primary: /api/chat schema returns message.content
    if isinstance(msg, dict):
        content = msg.get("content") or ""

    # Fallback: Ollama /api/generate uses "response" key
    if not content:
        content = data.get("response") or ""

    # Fallback: Some wrappers may return "content" at top-level
    if not content:
        content = data.get("content") or ""

    content = str(content or "")

    # Strip <think>...</think> tags that may leak into content (DeepSeek R1, QwQ, etc.)
    content = strip_think_tags(content)

    # Thinking model fallback: if content is empty, try to recover from message.thinking
    if not content.strip() and isinstance(msg, dict):
        thinking = str(msg.get("thinking") or "").strip()
        if thinking:
            print(f"[OLLAMA] Content empty, checking thinking field ({len(thinking)} chars)...")
            print(f"[OLLAMA] Thinking (first 500 chars): {thinking[:500]}")

            # Strategy 1: Try to extract JSON from thinking (for structured endpoints)
            candidate = _extract_first_json_object(thinking)
            if candidate:
                print(f"[OLLAMA] Found JSON candidate ({len(candidate)} chars)")
                is_placeholder = _is_placeholder_json(candidate)
                if not is_placeholder:
                    try:
                        json.loads(candidate)
                        content = candidate
                        print(f"[OLLAMA] SUCCESS: Extracted JSON from thinking field")
                    except Exception as e:
                        print(f"[OLLAMA] JSON parse failed: {e}")
                elif len(candidate) > 200:
                    try:
                        parsed = json.loads(candidate)
                        values = str(parsed.values())
                        if len(values) > 100 and "string" not in values.lower()[:50]:
                            content = candidate
                            print(f"[OLLAMA] Using thinking JSON despite placeholder pattern")
                    except Exception:
                        pass

            # Strategy 2: Plain text fallback (for voice/chat — thinking ran out of tokens)
            # The model put its reasoning in thinking but never produced content.
            # Extract the last meaningful lines as the response.
            if not content.strip():
                # Strip any <think> tags that may be in the thinking text itself
                clean_thinking = strip_think_tags(thinking)
                lines = [ln.strip() for ln in clean_thinking.split("\n") if ln.strip()]
                if lines:
                    # Use the last 1-2 non-empty lines (most likely the final answer)
                    tail = " ".join(lines[-2:])
                    # Only use if it looks like a spoken response, NOT reasoning meta-text.
                    # Reasoning leaks contain self-instructions / third-person user refs.
                    if len(tail) > 5 and not _is_reasoning_text(tail):
                        content = tail
                        print(f"[OLLAMA] Recovered plain text from thinking tail: '{content[:100]}'")
                    else:
                        # Walk backwards through lines to find the first non-reasoning line
                        for ln in reversed(lines):
                            if len(ln) > 5 and not _is_reasoning_text(ln):
                                content = ln
                                print(f"[OLLAMA] Recovered non-reasoning line: '{content[:100]}'")
                                break
                        if not content.strip():
                            # Last resort: use the very last line regardless
                            content = lines[-1]
                            print(f"[OLLAMA] Last-resort recovery from thinking: '{content[:100]}'")

    # Debug logging when content is still empty
    if not content.strip():
        log_event(
            "llm.empty_content",
            provider="ollama",
            selected_model=mdl,
            done_reason=data.get("done_reason"),
            eval_count=data.get("eval_count"),
            prompt_eval_count=data.get("prompt_eval_count"),
        )
        print(
            "[OLLAMA] WARNING: empty content after normalization. "
            f"done_reason={data.get('done_reason')!r} eval_count={data.get('eval_count')!r} "
            f"prompt_eval_count={data.get('prompt_eval_count')!r} total_ms="
            f"{int(data.get('total_duration', 0) / 1_000_000) if data.get('total_duration') is not None else None} "
            f"raw_keys={list(data.keys())}"
        )
        if isinstance(msg, dict):
            print(f"[OLLAMA] message keys: {list(msg.keys())} content_preview={_short_debug_text(msg.get('content'))!r}")

    return {
        "choices": [{"message": {"content": content}}],
        "provider_raw": data,
    }


async def chat(
    messages: List[Dict[str, Any]],
    *,
    provider: ProviderName = "openai_compat",
    temperature: float = 0.7,
    max_tokens: int = 800,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    if provider == "ollama":
        return await chat_ollama(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=base_url,
            model=model,
        )
    if provider == "openai":
        return await chat_openai(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=base_url,
            model=model,
        )
    if provider == "claude":
        return await chat_claude(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=base_url,
            model=model,
        )
    if provider == "watsonx":
        return await chat_watsonx(messages)

    return await chat_openai_compat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=base_url,
        model=model,
    )
