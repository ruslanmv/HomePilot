# backend/app/teams/crewai_llm.py
"""
Map HomePilot provider configuration to a CrewAI ``LLM`` instance.

CrewAI supports Ollama through LiteLLM using ``model="ollama/<name>"``
and a ``base_url`` parameter.  For OpenAI-compatible servers, the prefix
is ``openai/<model>``.

This module reads the same config knobs as ``llm_adapter.py`` so
enterprise settings (env-vars, UI overrides) are respected.
"""
from __future__ import annotations

from typing import Optional

from ..config import (
    DEFAULT_PROVIDER,
    LLM_BASE_URL,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL,
)


def make_crewai_llm(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 800,
):
    """Create a CrewAI ``LLM`` instance from HomePilot provider config.

    Imports ``crewai.LLM`` lazily so that this module doesn't fail at
    import-time when CrewAI is not installed (the runner handles the
    ``ImportError`` gracefully).
    """
    from crewai import LLM  # lazy — only when CrewAI is installed

    prov = (provider or DEFAULT_PROVIDER).strip()

    if prov == "ollama":
        mdl = (model or OLLAMA_MODEL or "llama3").strip()
        url = (base_url or OLLAMA_BASE_URL).rstrip("/")
        return LLM(
            model=f"ollama/{mdl}",
            base_url=url,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if prov == "openai_compat":
        # OpenAI-compatible server (vLLM, text-generation-inference, etc.)
        mdl = (model or LLM_MODEL or "local-model").strip()
        url = (base_url or LLM_BASE_URL).rstrip("/")
        return LLM(
            model=f"openai/{mdl}",
            base_url=url,
            api_key="sk-local",
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if prov == "openai":
        mdl = (model or OPENAI_MODEL).strip()
        url = (base_url or OPENAI_BASE_URL).rstrip("/")
        return LLM(
            model=f"openai/{mdl}",
            base_url=url,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if prov == "claude":
        mdl = (model or ANTHROPIC_MODEL).strip()
        url = (base_url or ANTHROPIC_BASE_URL).rstrip("/")
        return LLM(
            model=f"anthropic/{mdl}",
            base_url=url,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # Fallback: try raw model string (LiteLLM will attempt to route it)
    mdl = (model or LLM_MODEL or OLLAMA_MODEL or "llama3").strip()
    url = (base_url or LLM_BASE_URL or OLLAMA_BASE_URL).rstrip("/")
    return LLM(
        model=mdl,
        base_url=url,
        temperature=temperature,
        max_tokens=max_tokens,
    )
