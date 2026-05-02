# expert/providers.py
# All new LLM provider adapters for the Expert module.
# Pattern mirrors backend/app/llm.py — returns OpenAI-compatible dicts.
# Streaming variants yield raw SSE chunks for the /expert/stream endpoint.
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from .config import (
    GROK_API_KEY, GROK_BASE_URL, GROK_MODEL,
    GROQ_API_KEY, GROQ_BASE_URL, GROQ_MODEL,
    GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_MODEL,
    EXPERT_OLLAMA_URL, EXPERT_LOCAL_MODEL, EXPERT_LOCAL_FAST_MODEL,
    EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE,
)

_TIMEOUT = httpx.Timeout(timeout=120.0, connect=15.0)
_STREAM_TIMEOUT = httpx.Timeout(timeout=300.0, connect=15.0)

# If the configured EXPERT_LOCAL_MODEL / EXPERT_LOCAL_FAST_MODEL isn't pulled,
# fall back to whatever Ollama has locally. Set to "false" to disable and get
# a hard error instead — useful in production where the deployed model must
# match exactly.
_LOCAL_AUTO_FALLBACK = os.getenv("EXPERT_LOCAL_AUTO_FALLBACK", "true").lower() != "false"


async def _ollama_pulled_models() -> List[str]:
    """Return the list of model tags currently pulled in Ollama. Empty on error."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            r = await client.get(f"{EXPERT_OLLAMA_URL}/api/tags")
            r.raise_for_status()
            data = r.json()
        return [m.get("name") or m.get("model") for m in data.get("models", []) if isinstance(m, dict)]
    except Exception:
        return []


async def _resolve_local_model(requested: str) -> str:
    """Return ``requested`` if Ollama has it pulled, otherwise either fall back
    to the first available model or raise a clear error describing how to pull
    it. Behavior controlled by ``EXPERT_LOCAL_AUTO_FALLBACK``."""
    pulled = await _ollama_pulled_models()
    if not pulled:
        raise RuntimeError(
            f"Ollama at {EXPERT_OLLAMA_URL} has no models pulled. "
            f"Run `ollama pull {requested}` (or set EXPERT_LOCAL_MODEL / "
            f"EXPERT_LOCAL_FAST_MODEL to a pulled model) and retry."
        )
    if requested in pulled:
        return requested
    if not _LOCAL_AUTO_FALLBACK:
        raise RuntimeError(
            f"Expert local model '{requested}' is not pulled. "
            f"Available: {pulled}. Run `ollama pull {requested}` to fix."
        )
    # Prefer an exact stem match (handles ':latest' vs ':Q4_K_M' variants).
    stem = requested.split(":")[0]
    for m in pulled:
        if m and m.split(":")[0] == stem:
            return m
    return pulled[0]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _openai_wrap(content: str, model: str, provider: str) -> Dict[str, Any]:
    """Wrap a plain text response into OpenAI-like schema for orchestrator consistency."""
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "model": model,
        "provider": provider,
    }


def _extract_content(data: Dict[str, Any]) -> str:
    """Extract text content from OpenAI-style response dict."""
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# xAI Grok  (OpenAI-compatible — reuses same wire format)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_grok(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> Dict[str, Any]:
    """xAI Grok via OpenAI-compatible /v1/chat/completions."""
    if not GROK_API_KEY:
        raise RuntimeError("GROK_API_KEY not set — cannot use Grok provider.")
    mdl = model or GROK_MODEL
    url = f"{GROK_BASE_URL}/chat/completions"
    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {GROK_API_KEY}"},
        )
        r.raise_for_status()
        data = r.json()
    data["provider"] = "grok"
    return data


async def stream_grok(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """Stream tokens from Grok, yielding SSE-ready delta strings."""
    if not GROK_API_KEY:
        raise RuntimeError("GROK_API_KEY not set.")
    mdl = model or GROK_MODEL
    url = f"{GROK_BASE_URL}/chat/completions"
    payload = {
        "model": mdl, "messages": messages, "stream": True,
        "temperature": float(temperature), "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream(
            "POST", url, json=payload,
            headers={"Authorization": f"Bearer {GROK_API_KEY}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


# ─────────────────────────────────────────────────────────────────────────────
# Groq  (ultra-fast, free tier, open models: Llama 3.3 70B, Mixtral, etc.)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_groq(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> Dict[str, Any]:
    """Groq inference API — OpenAI-compatible, blazing fast."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set — cannot use Groq provider.")
    mdl = model or GROQ_MODEL
    url = f"{GROQ_BASE_URL}/chat/completions"
    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        )
        r.raise_for_status()
        data = r.json()
    data["provider"] = "groq"
    return data


async def stream_groq(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """Stream tokens from Groq."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set.")
    mdl = model or GROQ_MODEL
    url = f"{GROQ_BASE_URL}/chat/completions"
    payload = {
        "model": mdl, "messages": messages, "stream": True,
        "temperature": float(temperature), "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream(
            "POST", url, json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


# ─────────────────────────────────────────────────────────────────────────────
# Google Gemini  (via OpenAI-compatible endpoint — available since Gemini 1.5)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_gemini(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> Dict[str, Any]:
    """Google Gemini via its OpenAI-compatible REST endpoint."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set — cannot use Gemini provider.")
    mdl = model or GEMINI_MODEL
    url = f"{GEMINI_BASE_URL}/chat/completions"
    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {GEMINI_API_KEY}"},
        )
        r.raise_for_status()
        data = r.json()
    data["provider"] = "gemini"
    return data


async def stream_gemini(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """Stream tokens from Gemini."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set.")
    mdl = model or GEMINI_MODEL
    url = f"{GEMINI_BASE_URL}/chat/completions"
    payload = {
        "model": mdl, "messages": messages, "stream": True,
        "temperature": float(temperature), "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream(
            "POST", url, json=payload,
            headers={"Authorization": f"Bearer {GEMINI_API_KEY}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


# ─────────────────────────────────────────────────────────────────────────────
# Local Ollama  (free, on-premises, no API key needed)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_local(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    fast: bool = False,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> Dict[str, Any]:
    """Ollama local inference — zero cost, fully sovereign."""
    requested = model or (EXPERT_LOCAL_FAST_MODEL if fast else EXPERT_LOCAL_MODEL)
    mdl = await _resolve_local_model(requested)
    url = f"{EXPERT_OLLAMA_URL}/api/chat"
    payload = {
        "model": mdl,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": False,
        "options": {
            "temperature": float(temperature),
            "num_predict": int(max_tokens),
        },
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(url, json=payload)
        if r.status_code == 404:
            raise RuntimeError(
                f"Ollama rejected model '{mdl}' with 404. Run "
                f"`ollama pull {mdl}` and retry (or set EXPERT_LOCAL_MODEL)."
            )
        r.raise_for_status()
        data = r.json()

    content = data.get("message", {}).get("content", "")
    return _openai_wrap(content, mdl, "local")


async def stream_local(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    fast: bool = False,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """Stream tokens from Ollama."""
    requested = model or (EXPERT_LOCAL_FAST_MODEL if fast else EXPERT_LOCAL_MODEL)
    mdl = await _resolve_local_model(requested)
    url = f"{EXPERT_OLLAMA_URL}/api/chat"
    payload = {
        "model": mdl,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": True,
        "options": {"temperature": float(temperature), "num_predict": int(max_tokens)},
    }
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Ollama rejected model '{mdl}' with 404. Run "
                    f"`ollama pull {mdl}` and retry (or set EXPERT_LOCAL_MODEL)."
                )
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
