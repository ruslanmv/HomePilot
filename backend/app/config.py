from __future__ import annotations

import os
from typing import List, Literal

API_KEY = os.getenv("API_KEY", "").strip()

# Providers:
# - openai_compat: vLLM / OpenAI-compatible API
# - ollama: Ollama local server
ProviderName = Literal["openai_compat", "ollama"]

DEFAULT_PROVIDER: ProviderName = os.getenv("DEFAULT_PROVIDER", "openai_compat").strip()  # type: ignore

# OpenAI-compatible LLM (vLLM)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://llm:8001/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "local-model").strip()

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()  # empty => backend will require client to set or fallback

# ComfyUI + Media services
COMFY_BASE_URL = os.getenv("COMFY_BASE_URL", "http://comfyui:8188").rstrip("/")
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "http://media:8002").rstrip("/")

# Storage
#
# When developing locally (especially on Windows/WSL), paths like /app/... may not exist.
# If DATA_DIR is set, default to storing DB/uploads under that directory unless the
# more specific vars are provided.
DATA_DIR = os.getenv("DATA_DIR", "").strip()

_default_data_root = DATA_DIR or "/app/data"
SQLITE_PATH = os.getenv("SQLITE_PATH", os.path.join(_default_data_root, "homepilot.db"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(_default_data_root, "uploads"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/outputs")

# Upload constraints
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))

# Timeouts / polling
TOOL_TIMEOUT_S = float(os.getenv("TOOL_TIMEOUT_S", "300"))
COMFY_POLL_INTERVAL_S = float(os.getenv("COMFY_POLL_INTERVAL_S", "1.0"))
COMFY_POLL_MAX_S = float(os.getenv("COMFY_POLL_MAX_S", "240"))

def _parse_csv(value: str) -> List[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]

CORS_ORIGINS = _parse_csv(os.getenv("CORS_ORIGINS", "http://localhost:3000"))

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
