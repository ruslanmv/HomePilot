"""
Interactive LLM router — one-call resolver that binds a
``RenderedPrompt`` + ``PromptPolicy`` to the Enterprise Settings
chat model selected by the operator at runtime.

Why this exists
---------------

Before REV-1 every interactive LLM call hit ``app.llm.chat_ollama``
directly with the hardcoded ``OLLAMA_MODEL`` env var captured at
import time. When the operator changes the Enterprise Settings
model (e.g. swaps in ``huihui_ai/qwen3-abliterated:4b``) the
backend has to restart to pick it up, and there's no single
place to audit "what model actually answered this prompt".

``resolve_current_chat_model()`` reads ``os.environ`` live on
every call — Enterprise Settings writes to env at runtime, so
the new model is picked up on the next invocation without a
restart. ``call_prompt()`` wraps that resolver around the
generic ``app.llm.chat`` dispatcher so a caller only has to
supply a ``RenderedPrompt`` and its ``PromptPolicy``.

This module is deliberately thin. No retries, no validation,
no fallbacks — those belong to the workflow runner (REV-2),
which decides whether a failed call should retry, abort, or
use a declared fallback. Keeping those concerns one layer up
makes each layer testable on its own.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .prompts import PromptPolicy, RenderedPrompt


log = logging.getLogger(__name__)


# ── Resolved model snapshot ────────────────────────────────────

@dataclass(frozen=True)
class ChatModel:
    """The provider + model string + base URL trio used for one
    LLM call. Immutable snapshot so callers can log/replay it.
    """

    provider: str
    model: str
    base_url: Optional[str]

    def describe(self) -> str:
        """Compact label for log lines and telemetry."""
        return f"{self.provider}:{self.model}"


# ── Resolution ─────────────────────────────────────────────────

def resolve_current_chat_model(
    *,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
    base_url_override: Optional[str] = None,
) -> ChatModel:
    """Return the chat model the Enterprise Settings UI has
    currently selected. Values are read live from ``os.environ``
    (not frozen at import time) so changes propagate without a
    backend restart.

    Resolution order for each field:

      1. explicit override argument (tests, admin overrides)
      2. interactive-scoped env (``INTERACTIVE_LLM_*``) so ops can
         force a smaller/cheaper model here without touching the
         chat provider the rest of the app uses
      3. HomePilot-wide env (``DEFAULT_PROVIDER``, ``OLLAMA_MODEL``,
         ``LLM_MODEL``, ``LLM_BASE_URL``, ``OLLAMA_BASE_URL``)
      4. built-in safe defaults

    The function never raises — if nothing is configured the
    returned ``ChatModel`` still carries a plausible provider
    string, and the eventual LLM call surfaces the real error.
    """
    # 1/2: override args, then interactive-scoped env overrides.
    provider = (
        provider_override
        or _nonempty(os.getenv("INTERACTIVE_LLM_PROVIDER"))
        or _nonempty(os.getenv("DEFAULT_PROVIDER"))
        or _default_provider()
    )
    provider = provider.strip().lower()

    # Model + base URL depend on provider.
    if provider == "ollama":
        model = (
            model_override
            or _nonempty(os.getenv("INTERACTIVE_LLM_MODEL"))
            or _nonempty(os.getenv("OLLAMA_MODEL"))
            or "llama3:8b"
        )
        base_url = (
            base_url_override
            or _nonempty(os.getenv("INTERACTIVE_LLM_BASE_URL"))
            or _nonempty(os.getenv("OLLAMA_BASE_URL"))
            or "http://localhost:11434"
        )
    elif provider == "openai_compat":
        model = (
            model_override
            or _nonempty(os.getenv("INTERACTIVE_LLM_MODEL"))
            or _nonempty(os.getenv("LLM_MODEL"))
            or "local-model"
        )
        base_url = (
            base_url_override
            or _nonempty(os.getenv("INTERACTIVE_LLM_BASE_URL"))
            or _nonempty(os.getenv("LLM_BASE_URL"))
        )
    elif provider == "openai":
        model = (
            model_override
            or _nonempty(os.getenv("INTERACTIVE_LLM_MODEL"))
            or _nonempty(os.getenv("OPENAI_MODEL"))
            or "gpt-4o-mini"
        )
        base_url = (
            base_url_override
            or _nonempty(os.getenv("INTERACTIVE_LLM_BASE_URL"))
            or _nonempty(os.getenv("OPENAI_BASE_URL"))
        )
    elif provider == "claude":
        model = (
            model_override
            or _nonempty(os.getenv("INTERACTIVE_LLM_MODEL"))
            or _nonempty(os.getenv("ANTHROPIC_MODEL"))
            or "claude-3-5-sonnet-20240620"
        )
        base_url = (
            base_url_override
            or _nonempty(os.getenv("INTERACTIVE_LLM_BASE_URL"))
            or _nonempty(os.getenv("ANTHROPIC_BASE_URL"))
        )
    else:
        # Unknown provider — fall through to ollama defaults so
        # downstream still has something to try; the actual
        # provider router will emit the real error.
        model = model_override or "llama3:8b"
        base_url = base_url_override

    return ChatModel(provider=provider, model=str(model).strip(), base_url=base_url)


def _default_provider() -> str:
    """Best guess provider when nothing is configured.

    Matches ``app.config``'s behaviour: if we're inside a Docker
    container, assume the vLLM sidecar (``openai_compat``);
    otherwise assume a local Ollama install.
    """
    in_docker = (
        os.path.exists("/.dockerenv")
        or os.getenv("DOCKER_CONTAINER", "").lower() == "true"
    )
    return "openai_compat" if in_docker else "ollama"


def _nonempty(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = v.strip()
    return s if s else None


# ── Call helper ────────────────────────────────────────────────

async def call_prompt(
    prompt: RenderedPrompt,
    policy: PromptPolicy,
    *,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
    base_url_override: Optional[str] = None,
    temperature: float = 0.4,
    max_tokens: int = 350,
) -> Dict[str, Any]:
    """Dispatch one rendered prompt to the Enterprise Settings
    chat model, respecting the per-prompt policy for timeout
    and ``response_format``.

    Returns the raw provider response (OpenAI-style envelope as
    normalised by ``app.llm``). Response parsing + validation
    live in the caller because they depend on the prompt shape
    (enum vs JSON array vs free text).

    Does NOT retry — the workflow runner owns retry/fallback
    semantics so every prompt's behaviour is visible in one
    place (the runner loop).
    """
    from .. import llm as llm_mod  # late import to avoid cycles

    model = resolve_current_chat_model(
        provider_override=provider_override,
        model_override=model_override,
        base_url_override=base_url_override,
    )

    messages = prompt.to_messages()
    log.info(
        "interactive.llm %s prompt=%s v=%s timeout=%.1fs",
        model.describe(), prompt.prompt_id, prompt.version, policy.timeout_s,
    )

    # Ollama is the only provider in app.llm that exposes a
    # structured-output switch (``format="json"``). For every
    # other provider we call the generic dispatcher and let
    # downstream validation handle non-JSON output.
    coro: Any
    if model.provider == "ollama":
        coro = llm_mod.chat_ollama(
            messages,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            base_url=model.base_url,
            model=model.model,
            response_format=policy.response_format,
        )
    else:
        kwargs: Dict[str, Any] = {
            "provider": model.provider,
            "model": model.model,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if model.base_url:
            kwargs["base_url"] = model.base_url
        coro = llm_mod.chat(messages, **kwargs)

    try:
        response = await asyncio.wait_for(coro, timeout=policy.timeout_s)
    except asyncio.TimeoutError:
        log.warning(
            "interactive.llm_timeout prompt=%s after %.1fs",
            prompt.prompt_id, policy.timeout_s,
        )
        raise
    return response


__all__ = [
    "ChatModel",
    "call_prompt",
    "resolve_current_chat_model",
]
