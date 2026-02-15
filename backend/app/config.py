from __future__ import annotations

import os
import pathlib
from typing import List, Literal

API_KEY = os.getenv("API_KEY", "").strip()

"""Runtime configuration.

This project runs in two very different network environments:

1) Docker compose / k8s: services address each other by container DNS names
   (e.g. http://llm:8001/v1, http://comfyui:8188)
2) Local dev (make start / uvicorn): services are typically on localhost
   (e.g. http://localhost:11434 for Ollama)

For production readiness we must not ship Docker-only hostnames as defaults
when running locally.
"""


# Detect if we're running in a Docker container
_IS_DOCKER = pathlib.Path("/.dockerenv").exists() or os.getenv("DOCKER_CONTAINER", "").lower() == "true"


# Providers:
# - openai_compat: vLLM / OpenAI-compatible API
# - ollama: Ollama local server
# - openai: OpenAI API
# - claude: Anthropic API
# - watsonx: IBM watsonx.ai (model listing supported; chat optional)
ProviderName = Literal["openai_compat", "ollama", "openai", "claude", "watsonx"]

# If running locally, default to Ollama (most users installing this repo have it).
# In Docker/prod, default to openai_compat (vLLM container).
DEFAULT_PROVIDER: ProviderName = os.getenv(
    "DEFAULT_PROVIDER",
    "openai_compat" if _IS_DOCKER else "ollama",
).strip()  # type: ignore


# OpenAI-compatible LLM (vLLM)
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL",
    "http://llm:8001/v1" if _IS_DOCKER else "http://localhost:8001/v1",
).rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "local-model").strip()

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()  # empty => backend can auto-pick

# OpenAI / Anthropic base URLs (keys come from env)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620").strip()

# ComfyUI + Media services
COMFY_BASE_URL = os.getenv(
    "COMFY_BASE_URL",
    "http://comfyui:8188" if _IS_DOCKER else "http://localhost:8188",
).rstrip("/")
MEDIA_BASE_URL = os.getenv(
    "MEDIA_BASE_URL",
    "http://media:8002" if _IS_DOCKER else "http://localhost:8002",
).rstrip("/")

# Image/Video Generation Models
# Available image models (ComfyUI workflows)
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "sdxl").strip()  # sdxl, flux-schnell, flux-dev, pony-xl
# Available video models
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "svd").strip()  # svd, wan-2.2, seedream

# NSFW Mode (enables uncensored generation)
NSFW_MODE = os.getenv("NSFW_MODE", "false").lower() == "true"

# Edit Session Sidecar Service
# The edit-session service runs as a sidecar on port 8010
EDIT_SESSION_URL = os.getenv(
    "EDIT_SESSION_URL",
    "http://edit-session:8010" if _IS_DOCKER else "http://localhost:8010",
).rstrip("/")

# Storage
#
# When developing locally (especially on Windows/WSL), paths like /app/... may not exist.
# If DATA_DIR is set, default to storing DB/uploads under that directory unless the
# more specific vars are provided.
#
# For local development: Use ./backend/data
# For Docker: Use /app/data
DATA_DIR = os.getenv("DATA_DIR", "").strip()

_is_docker = _IS_DOCKER

if DATA_DIR:
    _default_data_root = DATA_DIR
elif _is_docker:
    _default_data_root = "/app/data"
else:
    # Local development: use relative path
    _backend_dir = pathlib.Path(__file__).parent.parent  # backend/
    _default_data_root = str(_backend_dir / "data")

SQLITE_PATH = os.getenv("SQLITE_PATH", os.path.join(_default_data_root, "homepilot.db"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(_default_data_root, "uploads"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/outputs" if _is_docker else os.path.join(_default_data_root, "outputs"))

# Upload constraints
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))

# Timeouts / polling
TOOL_TIMEOUT_S = float(os.getenv("TOOL_TIMEOUT_S", "300"))
COMFY_POLL_INTERVAL_S = float(os.getenv("COMFY_POLL_INTERVAL_S", "1.0"))
# Increased from 240s to 360s (6 minutes) for bigger models like SDXL
COMFY_POLL_MAX_S = float(os.getenv("COMFY_POLL_MAX_S", "360"))

def _parse_csv(value: str) -> List[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]

# FIX: Added http://localhost:5173 and http://127.0.0.1:5173 for local Vite development
# Also added port 3001 for alternate dev setups
CORS_ORIGINS = _parse_csv(os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:3001"))

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

# Agentic AI / MCP Context Forge
AGENTIC_ENABLED = os.getenv("AGENTIC_ENABLED", "true").lower() in ("1", "true", "yes")
CONTEXT_FORGE_URL = os.getenv("CONTEXT_FORGE_URL", "http://localhost:4444").rstrip("/")
CONTEXT_FORGE_ADMIN_URL = os.getenv("CONTEXT_FORGE_ADMIN_URL", "http://localhost:4444/admin").rstrip("/")
CONTEXT_FORGE_TOKEN = os.getenv("CONTEXT_FORGE_TOKEN", "").strip()

# Community Gallery — Cloudflare Worker (production, edge-cached, no rate limits)
# Primary upstream for registry, previews, cards, and packages.
# Works out-of-the-box; override via COMMUNITY_GALLERY_URL env var or set "" to disable.
_DEFAULT_GALLERY_URL = "https://homepilot-persona-gallery.cloud-data.workers.dev"
COMMUNITY_GALLERY_URL = os.getenv("COMMUNITY_GALLERY_URL", _DEFAULT_GALLERY_URL).strip().rstrip("/")

# Community Gallery — R2 Direct Access (fallback, rate-limited by Cloudflare)
# Used only when COMMUNITY_GALLERY_URL is not set.
# Priority: COMMUNITY_GALLERY_URL (Worker) > R2_PUBLIC_URL (direct R2).
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "").strip().rstrip("/")
