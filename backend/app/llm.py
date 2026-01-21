# homepilot/backend/app/llm.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Literal

import httpx

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
