# homepilot/backend/app/llm.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

import httpx

from .config import (
    TOOL_TIMEOUT_S,
    LLM_BASE_URL,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)

ProviderName = Literal["openai_compat", "ollama"]


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


async def chat_ollama(
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 800,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ollama /api/chat adapter -> returns OpenAI-style JSON for orchestrator consistency.
    Ollama expects:
      { model, messages: [{role, content}], stream: false, options: {...} }
    """
    base = (base_url or OLLAMA_BASE_URL).rstrip("/")
    mdl = (model or OLLAMA_MODEL).strip()
    if not mdl:
        # Keep error explicit for UI
        raise RuntimeError("Ollama model not configured. Set OLLAMA_MODEL env var.")

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

    async with httpx.AsyncClient(timeout=_timeout()) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()

    # Normalize to OpenAI-like shape for downstream parsing
    content = ""
    msg = data.get("message")
    if isinstance(msg, dict):
        content = str(msg.get("content") or "")

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
) -> Dict[str, Any]:
    if provider == "ollama":
        return await chat_ollama(messages, temperature=temperature, max_tokens=max_tokens)
    return await chat_openai_compat(messages, temperature=temperature, max_tokens=max_tokens)
