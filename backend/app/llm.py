# homepilot/backend/app/llm.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Literal

import httpx


import re


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
) -> Dict[str, Any]:
    """
    OpenAI-compatible chat/completions (vLLM, etc.)
    Returns OpenAI-style JSON with choices[0].message.content.
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

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.post(url, json=payload)
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
    mdl = (model or OLLAMA_MODEL).strip()

    url = f"{base}/api/chat"
    payload = {
        "model": mdl,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": False,
        "options": {
            "temperature": float(temperature),
            # Ollama doesn't use max_tokens exactly the same way; keep best-effort:
            "num_predict": int(max_tokens),
        },
    }

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

        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
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

    # DeepSeek R1 fallback: If content is empty, try to extract from message.thinking
    # BUT validate that it's not placeholder JSON (schema echoed back)
    if not content.strip() and isinstance(msg, dict):
        thinking = str(msg.get("thinking") or "").strip()
        if thinking:
            print(f"[OLLAMA] Content empty, checking thinking field ({len(thinking)} chars)...")
            print(f"[OLLAMA] Thinking (first 500 chars): {thinking[:500]}")

            # Try to extract JSON from thinking field
            candidate = _extract_first_json_object(thinking)
            if candidate:
                print(f"[OLLAMA] Found JSON candidate ({len(candidate)} chars)")
                is_placeholder = _is_placeholder_json(candidate)
                print(f"[OLLAMA] Is placeholder JSON: {is_placeholder}")

                if not is_placeholder:
                    try:
                        json.loads(candidate)  # Validate it's parseable
                        content = candidate
                        print(f"[OLLAMA] SUCCESS: Extracted valid JSON from message.thinking field")
                    except Exception as e:
                        print(f"[OLLAMA] JSON parse failed: {e}")
                else:
                    # Even if it looks like placeholder, if it's long and has real content, use it
                    # This handles cases where schema patterns appear but there's real content too
                    if len(candidate) > 200:
                        try:
                            parsed = json.loads(candidate)
                            # Check if it has meaningful content (not just schema keys)
                            values = str(parsed.values())
                            if len(values) > 100 and "string" not in values.lower()[:50]:
                                content = candidate
                                print(f"[OLLAMA] Using thinking JSON despite placeholder pattern (has real content)")
                        except Exception:
                            pass
            else:
                print(f"[OLLAMA] No JSON object found in thinking field")

    # Debug logging when content is still empty (helps diagnose model-specific issues)
    if not content.strip():
        print(f"[OLLAMA] WARNING: empty extracted content. provider_raw keys: {list(data.keys())}")
        if isinstance(msg, dict):
            print(f"[OLLAMA] message keys: {list(msg.keys())}")

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
