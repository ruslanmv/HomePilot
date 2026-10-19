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

# Where Ollama may live besides EXPERT_OLLAMA_URL: loopback, and the Windows /
# Docker host when this service runs inside WSL or a container. The first URL
# that answers /api/tags with models wins and is remembered for a short time
# (same rules as HomePilot's backend/app/model_resolver.py; this service is
# deliberately isolated, so the 40 lines are copied rather than imported).
_OLLAMA_CACHE: Dict[str, Any] = {"url": "", "ts": 0.0, "models": []}
_OLLAMA_CACHE_TTL_S = 30.0


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def _host_gateway_ips() -> List[str]:
    out: List[str] = []
    for line in _read_text("/proc/net/route").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "00000000":
            try:
                raw = int(parts[2], 16)
                out.append(".".join(str((raw >> (8 * i)) & 0xFF) for i in range(4)))
            except ValueError:
                pass
    for line in _read_text("/etc/resolv.conf").splitlines():
        p = line.split()
        if len(p) >= 2 and p[0] == "nameserver" and p[1].count(".") == 3 and p[1] not in out:
            out.append(p[1])
    return [ip for ip in out if not ip.startswith("127.")]


def _ollama_candidates() -> List[str]:
    urls = [EXPERT_OLLAMA_URL, "http://127.0.0.1:11434", "http://localhost:11434"]
    in_wsl = bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in _read_text("/proc/version").lower()
    if in_wsl:
        urls += [f"http://{ip}:11434" for ip in _host_gateway_ips()]
    if os.path.exists("/.dockerenv"):
        urls += ["http://host.docker.internal:11434", "http://172.17.0.1:11434"]
    seen: List[str] = []
    for u in urls:
        u = (u or "").rstrip("/")
        if u and u not in seen:
            seen.append(u)
    return seen


def _ollama_base() -> str:
    """Runtime URL the last successful probe found (EXPERT_OLLAMA_URL until then)."""
    return _OLLAMA_CACHE["url"] or EXPERT_OLLAMA_URL


async def _ollama_pulled_models() -> List[str]:
    """Model tags of the first reachable Ollama among ``_ollama_candidates()``
    that has models. Remembers which URL answered so chat_local/stream_local
    talk to the same runtime. Empty when nothing answers."""
    import time as _time
    now = _time.monotonic()
    if _OLLAMA_CACHE["url"] and _OLLAMA_CACHE["models"] and now - _OLLAMA_CACHE["ts"] < _OLLAMA_CACHE_TTL_S:
        return list(_OLLAMA_CACHE["models"])
    best_url, best_models = "", []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            for url in _ollama_candidates():
                try:
                    r = await client.get(f"{url}/api/tags")
                    r.raise_for_status()
                    data = r.json()
                except Exception:
                    continue
                models = [m.get("name") or m.get("model") for m in data.get("models", []) if isinstance(m, dict)]
                if models:
                    best_url, best_models = url, models
                    break
                if not best_url:
                    best_url = url
    except Exception:
        pass
    if best_url:
        _OLLAMA_CACHE.update(url=best_url, ts=now, models=best_models)
    return best_models


async def _resolve_local_model(requested: str) -> str:
    """Return ``requested`` if Ollama has it pulled, otherwise either fall back
    to the first available model or raise a clear error describing how to pull
    it. Behavior controlled by ``EXPERT_LOCAL_AUTO_FALLBACK``."""
    pulled = await _ollama_pulled_models()
    if not pulled:
        probed = ", ".join(_ollama_candidates())
        raise RuntimeError(
            f"No Ollama with models answered (tried {probed}). Open Settings → Models in "
            f"HomePilot to download one, or run `ollama pull {requested}`. If Ollama runs on "
            f"Windows and this service runs in WSL, enable WSL mirrored networking."
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
    url = f"{_ollama_base()}/api/chat"
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
    url = f"{_ollama_base()}/api/chat"
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
