from __future__ import annotations

"""Provider model catalog.

The frontend should never hardcode model names. This module provides a single
place to list models for supported providers.

Notes:
* OpenAI / Anthropic listing requires API keys configured on the backend.
* Watsonx listing uses IBM's public foundation model specs endpoint and does
  not require an API key for IBM-managed models.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import (
    ANTHROPIC_BASE_URL,
    OPENAI_BASE_URL,
    OLLAMA_BASE_URL,
    ProviderName,
)


# --- Watsonx.ai public endpoint (no key required for IBM-managed models) ------

WATSONX_BASE_URLS = [
    "https://us-south.ml.cloud.ibm.com",
    "https://eu-de.ml.cloud.ibm.com",
    "https://jp-tok.ml.cloud.ibm.com",
    "https://au-syd.ml.cloud.ibm.com",
]

WATSONX_ENDPOINT = "/ml/v1/foundation_model_specs"
WATSONX_PARAMS = {
    "version": "2024-09-16",
    "filters": "!function_embedding,!lifecycle_withdrawn",
}


def _today() -> str:
    return datetime.today().strftime("%Y-%m-%d")


def _is_deprecated_or_withdrawn(lifecycle: List[Dict[str, Any]]) -> bool:
    today = _today()
    for entry in lifecycle:
        if entry.get("id") in {"deprecated", "withdrawn"} and entry.get("start_date", "") <= today:
            return True
    return False


async def list_models_for_provider(
    provider: ProviderName,
    *,
    base_url: Optional[str] = None,
) -> Tuple[List[str], Optional[str]]:
    """Return (models, error)."""

    if provider == "ollama":
        url_base = (base_url or OLLAMA_BASE_URL).rstrip("/")
        url = f"{url_base}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            models = sorted({m.get("name", "") for m in data.get("models", []) if m.get("name")})
            return models, None
        except Exception as e:
            return [], f"Error listing Ollama models from {url}: {e}"

    if provider == "openai_compat":
        url_base = (base_url or os.getenv("LLM_BASE_URL", "")).rstrip("/")
        if not url_base:
            return [], "LLM_BASE_URL not configured"
        url = f"{url_base}/models"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            models = sorted({m.get("id", "") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")})
            return models, None
        except Exception as e:
            return [], f"Error listing OpenAI-compatible models from {url}: {e}"

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return [], "OpenAI API key not configured (OPENAI_API_KEY)"
        url_base = (base_url or OPENAI_BASE_URL).rstrip("/")
        url = f"{url_base}/models"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
                r.raise_for_status()
                data = r.json()
            models = sorted({m.get("id", "") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")})
            return models, None
        except Exception as e:
            return [], f"Error listing OpenAI models: {e}"

    if provider == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return [], "Claude (Anthropic) API key not configured (ANTHROPIC_API_KEY)"
        url_base = (base_url or ANTHROPIC_BASE_URL).rstrip("/")
        url = f"{url_base}/v1/models"
        anthropic_version = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    url,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": anthropic_version,
                    },
                )
                r.raise_for_status()
                data = r.json()
            models = sorted({m.get("id", "") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")})
            return models, None
        except Exception as e:
            return [], f"Error listing Claude models: {e}"

    if provider == "watsonx":
        all_models: set[str] = set()
        async with httpx.AsyncClient(timeout=10.0) as client:
            for base in WATSONX_BASE_URLS:
                url = f"{base}{WATSONX_ENDPOINT}"
                try:
                    r = await client.get(url, params=WATSONX_PARAMS)
                    r.raise_for_status()
                    resources = r.json().get("resources", [])
                    for m in resources:
                        if _is_deprecated_or_withdrawn(m.get("lifecycle", [])):
                            continue
                        mid = m.get("model_id")
                        if mid:
                            all_models.add(mid)
                except Exception:
                    continue
        if not all_models:
            return [], "No Watsonx models found (public specs call failed for all regions?)"
        return sorted(all_models), None

    return [], f"Unsupported provider: {provider}"
