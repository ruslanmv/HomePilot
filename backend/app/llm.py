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
        raise RuntimeError("Ollama model not configured. Set OLLAMA_MODEL env var or provide ollama_model in request.")

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
    return await chat_openai_compat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=base_url,
        model=model,
    )
