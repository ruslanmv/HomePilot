"""
API Keys Management for HomePilot

Securely stores and retrieves API keys for:
- Hugging Face (for gated model downloads)
- Civitai (for NSFW/restricted model downloads)

Keys are stored in .env.json with restricted permissions.
Environment variables take precedence over stored keys.

This module is OPTIONAL - HomePilot works without API keys configured.
Keys are only needed for:
- Gated HuggingFace models (FLUX, SVD XT 1.1)
- NSFW/restricted Civitai models
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Dict, Literal

# Supported providers
ApiKeyProvider = Literal["huggingface", "civitai"]

# Storage location (same directory as other data files)
_DATA_DIR = Path(os.getenv("DATA_DIR", "")) or Path(__file__).parent.parent / "data"
ENV_JSON_FILE = _DATA_DIR / ".env.json"


def _load_keys() -> Dict[str, str]:
    """Load API keys from storage file."""
    if not ENV_JSON_FILE.exists():
        return {}
    try:
        with open(ENV_JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Keys are stored under "api_keys" namespace
            return data.get("api_keys", {})
    except (json.JSONDecodeError, IOError):
        return {}


def _save_keys(keys: Dict[str, str]) -> None:
    """Save API keys to storage file with secure permissions."""
    ENV_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data to preserve other settings
    existing_data = {}
    if ENV_JSON_FILE.exists():
        try:
            with open(ENV_JSON_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Update api_keys namespace
    existing_data["api_keys"] = keys

    with open(ENV_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2)

    # Set restrictive permissions (owner read/write only)
    try:
        os.chmod(ENV_JSON_FILE, 0o600)
    except OSError:
        pass  # Windows doesn't support chmod the same way


def get_api_key(provider: ApiKeyProvider) -> Optional[str]:
    """
    Get API key for a provider.
    Priority: Environment variable > Stored key

    Returns None if no key is configured (this is normal - keys are optional).
    """
    # Environment variables take precedence
    env_map = {
        "huggingface": "HF_TOKEN",
        "civitai": "CIVITAI_API_KEY",
    }
    env_var = env_map.get(provider, "")
    env_key = os.getenv(env_var, "").strip()
    if env_key:
        return env_key

    # Fall back to stored key
    keys = _load_keys()
    stored_key = keys.get(provider, "").strip()
    return stored_key if stored_key else None


def set_api_key(provider: ApiKeyProvider, key: str) -> None:
    """Store an API key for a provider."""
    keys = _load_keys()
    key = key.strip()
    if key:
        keys[provider] = key
    elif provider in keys:
        # Empty key means delete
        del keys[provider]
    _save_keys(keys)


def delete_api_key(provider: ApiKeyProvider) -> bool:
    """Remove an API key. Returns True if key existed."""
    keys = _load_keys()
    if provider in keys:
        del keys[provider]
        _save_keys(keys)
        return True
    return False


def get_api_keys_status() -> Dict[str, Dict]:
    """
    Get status of all API keys (for UI display).
    Returns masked keys and source (env/stored/none).
    Never returns actual key values.
    """
    result = {}
    providers = ["huggingface", "civitai"]
    env_map = {"huggingface": "HF_TOKEN", "civitai": "CIVITAI_API_KEY"}

    for provider in providers:
        env_key = os.getenv(env_map[provider], "").strip()
        stored_keys = _load_keys()
        stored_key = stored_keys.get(provider, "").strip()

        if env_key:
            result[provider] = {
                "configured": True,
                "source": "environment",
                "masked": _mask_key(env_key),
                "env_var": env_map[provider],
            }
        elif stored_key:
            result[provider] = {
                "configured": True,
                "source": "stored",
                "masked": _mask_key(stored_key),
                "env_var": env_map[provider],
            }
        else:
            result[provider] = {
                "configured": False,
                "source": "none",
                "masked": None,
                "env_var": env_map[provider],
            }

    return result


def _mask_key(key: str) -> str:
    """Mask API key for display (show first 4 and last 4 chars)."""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]
