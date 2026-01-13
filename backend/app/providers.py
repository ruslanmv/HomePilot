# homepilot/backend/app/providers.py
from __future__ import annotations

from typing import Dict, Any, List

from .config import (
    DEFAULT_PROVIDER,
    LLM_BASE_URL,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)

def available_providers() -> List[str]:
    out = ["openai_compat"]
    # Ollama is "available" if base URL exists (always) — model may be empty but UI can set it.
    out.append("ollama")
    return out

def provider_info() -> Dict[str, Dict[str, Any]]:
    """
    Safe info for frontend settings UI (no secrets).
    """
    return {
        "openai_compat": {
            "label": "OpenAI-compatible (vLLM)",
            "base_url": LLM_BASE_URL,
            "model": LLM_MODEL,
        },
        "ollama": {
            "label": "Ollama",
            "base_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL or "(set in env OLLAMA_MODEL)",
        },
    }
