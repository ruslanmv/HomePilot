# backend/app/teams/llm_adapter.py
"""
Teams LLM adapter — routes persona LLM calls through the same provider
infrastructure as the main chat, respecting user Enterprise Settings.

Features:
  - Reads DEFAULT_PROVIDER from config (not hardcoded "openai_compat")
  - Accepts runtime overrides for provider, model, base_url from /react body
  - Concurrency semaphore limits parallel Ollama/LLM calls (configurable)
  - Logs target provider/model/base_url for every call (debug-level)
  - Returns clean error messages instead of raw httpx.ConnectError
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..config import (
    DEFAULT_PROVIDER,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    LLM_BASE_URL,
    TEAMS_MAX_CONCURRENT_LLM,
)
from ..llm import chat as llm_chat

logger = logging.getLogger("homepilot.teams.llm_adapter")

# ── Concurrency limiter ──────────────────────────────────────────────────
# Prevents overwhelming a single Ollama instance with parallel requests.
# Default: 1 (sequential). Configurable via TEAMS_MAX_CONCURRENT_LLM env var
# or the frontend "Teams Concurrent LLM Calls" setting.
_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore(max_concurrent: Optional[int] = None) -> asyncio.Semaphore:
    """Lazily create (or recreate) the global semaphore."""
    global _semaphore
    limit = max_concurrent or TEAMS_MAX_CONCURRENT_LLM
    if _semaphore is None or _semaphore._value != limit:  # type: ignore[attr-defined]
        _semaphore = asyncio.Semaphore(limit)
    return _semaphore


def _resolve_provider_settings(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple:
    """Resolve provider, model, and base_url from overrides + config defaults.

    Priority: explicit override > config env var > sensible default.
    """
    prov = provider or DEFAULT_PROVIDER

    if prov == "ollama":
        mdl = model or OLLAMA_MODEL or "llama3:8b"
        url = base_url or OLLAMA_BASE_URL
    elif prov == "openai_compat":
        mdl = model or LLM_MODEL
        url = base_url or LLM_BASE_URL
    else:
        # openai, claude, watsonx — use whatever was passed
        mdl = model or LLM_MODEL
        url = base_url  # let llm.py use its own defaults

    return prov, mdl, url


class LLMConnectionError(Exception):
    """Raised when the LLM provider is unreachable."""
    def __init__(self, provider: str, base_url: str, detail: str = ""):
        self.provider = provider
        self.base_url = base_url
        self.detail = detail
        super().__init__(
            f"LLM provider unreachable: {provider} at {base_url}. "
            f"{detail} "
            "Check that the service is running and the URL is correct."
        )


async def llm_text(
    messages: List[Dict[str, Any]],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 800,
    max_concurrent: Optional[int] = None,
) -> str:
    """
    Call the configured LLM and return the assistant reply as a string.

    This is the ``llm_fn`` that meeting_engine / orchestrator expects:
        async callable(messages) -> str

    Args:
        messages: OpenAI-style message list
        provider: Override provider (e.g. "ollama", "openai_compat")
        model: Override model (e.g. "llama3:8b")
        base_url: Override base URL (e.g. "http://localhost:11434")
        temperature: Sampling temperature
        max_tokens: Max tokens in response
        max_concurrent: Override concurrent call limit (None = use config)
    """
    prov, mdl, url = _resolve_provider_settings(
        provider=provider, model=model, base_url=base_url,
    )

    logger.info(
        "Teams LLM call → provider=%s, model=%s, base_url=%s, max_tokens=%d",
        prov, mdl, url or "(default)", max_tokens,
    )

    sem = _get_semaphore(max_concurrent)

    async with sem:
        try:
            kwargs: Dict[str, Any] = {
                "provider": prov,
                "model": mdl,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if url:
                kwargs["base_url"] = url

            resp = await llm_chat(messages, **kwargs)
        except Exception as exc:
            exc_str = str(exc).lower()
            if "connect" in exc_str or "connection" in exc_str or "refused" in exc_str:
                raise LLMConnectionError(
                    provider=prov,
                    base_url=url or "(default)",
                    detail=str(exc),
                ) from exc
            raise

    try:
        return (resp["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        logger.warning("Unexpected LLM response shape: %s", resp)
        return ""
