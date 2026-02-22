from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid as uuidlib
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Literal
from urllib.parse import urlparse, parse_qs

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import require_api_key
from .model_config import get_model_settings, detect_architecture_from_filename
# Import config and storage as modules so we can patch paths if needed
from . import config, storage, projects, search
from .config import (
    CORS_ORIGINS,
    PUBLIC_BASE_URL,
    UPLOAD_DIR,        # may be a docker path like /app/data
    MAX_UPLOAD_MB,
    DEFAULT_PROVIDER,
    LLM_BASE_URL,
    COMFY_BASE_URL,
    MEDIA_BASE_URL,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    EDIT_SESSION_URL,
)
from .orchestrator import orchestrate, handle_request, clear_conversation_memory
from .providers import provider_info
from .storage import init_db, list_conversations, get_messages, delete_image_url, delete_conversation
from .migrations import run_migrations
from .game_mode import init_game_db, next_variation, get_session_events
from .story_mode import (
    init_story_db,
    start_story,
    continue_story,
    next_scene,
    get_story,
    list_story_sessions,
    delete_story_session,
    delete_scene,
    update_scene_image,
)

# Civitai search support
from .civitai import (
    CivitaiClient,
    CivitaiSearchQuery,
    search_and_normalize,
    get_civitai_cache,
)

# Studio module routes
from .studio.routes import router as studio_router
from .studio.repo import init_studio_db

# Upscale module routes
from .upscale import router as upscale_router

# Enhance module routes
from .enhance import router as enhance_router

# Background module routes
from .background import router as background_router

# Outpaint module routes
from .outpaint import router as outpaint_router

# Capabilities module routes
from .capabilities import router as capabilities_router

# Agentic AI module routes (additive — zero changes to existing code)
from .agentic.routes import router as agentic_router

# Topology 3: Agent-Controlled tool use routes (additive)
from .agent_routes import router as agent_router

# Persona Phase 3 — production hardening (avatar durability, export/import)
from .personas.avatar_assets import commit_persona_avatar, commit_persona_image
from .personas.export_import import export_persona_project, import_persona_package, preview_persona_package
from .personas.dependency_checker import check_dependencies

# Community gallery proxy (Phase 3 — additive)
from .community import router as community_router

# User Profile & Memory (additive)
from .profile import router as profile_router
from .user_memory import router as memory_router

# Multi-User Accounts & Onboarding (additive)
from .users import router as users_router

# Per-User Profile, Secrets & Memory (additive — multi-user aware)
from .user_profile_store import router as user_profile_store_router

# Avatar Studio (additive — persona avatar generation)
from .avatar import router as avatar_router

# Outfit Variations (additive — wardrobe changes for existing avatars)
from .avatar.outfit import router as outfit_router

# Multimodal Vision Layer (additive — on-demand image understanding)
from .multimodal import analyze_image, is_vision_intent, VISION_MODEL_PATTERNS

app = FastAPI(title="HomePilot Orchestrator", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Studio routes (/studio/*)
app.include_router(studio_router)

# Include Upscale routes (/v1/upscale)
app.include_router(upscale_router)

# Include Enhance routes (/v1/enhance)
app.include_router(enhance_router)

# Include Background routes (/v1/background)
app.include_router(background_router)

# Include Outpaint routes (/v1/outpaint)
app.include_router(outpaint_router)

# Include Capabilities routes (/v1/capabilities)
app.include_router(capabilities_router)

# Include Agentic AI routes (/v1/agentic/*)
app.include_router(agentic_router)

# Include Agent Chat routes (/v1/agent/* — Topology 3)
app.include_router(agent_router)

# Include Community Gallery proxy routes (/community/*)
app.include_router(community_router)

# Include User Profile routes (/v1/profile/*)
app.include_router(profile_router)

# Include User Memory routes (/v1/memory/*)
app.include_router(memory_router)

# Include Avatar Studio routes (/v1/avatars/*)
app.include_router(avatar_router)

# Include Outfit Variation routes (/v1/avatars/outfits)
app.include_router(outfit_router)

# Include User Auth & Onboarding routes (/v1/auth/*)
app.include_router(users_router)

# Include Per-User Profile Store routes (/v1/user-profile/*, /v1/user-memory/*)
app.include_router(user_profile_store_router)

# Include Secure File Storage routes (/v1/files/upload, /files/{asset_id})
from .files import router as files_router
app.include_router(files_router)


# ----------------------------
# ComfyUI image proxy
# ----------------------------
@app.get("/comfy/view/{filename:path}")
async def comfy_view_proxy(filename: str, subfolder: str = "", type: str = "output"):
    """Proxy ComfyUI /view requests so the frontend can load generated images."""
    params = {"filename": filename, "type": type}
    if subfolder:
        params["subfolder"] = subfolder
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{COMFY_BASE_URL}/view", params=params)
            r.raise_for_status()
            content_type = r.headers.get("content-type", "image/png")
            return Response(content=r.content, media_type=content_type)
    except Exception as exc:
        return JSONResponse(status_code=502, content={"detail": f"ComfyUI view failed: {exc}"})


# ----------------------------
# Models
# ----------------------------

ProviderName = Literal["openai_compat", "ollama", "openai", "claude", "watsonx"]


class ChatIn(BaseModel):
    message: str = Field(..., description="User message (raw input)")
    conversation_id: Optional[str] = Field(None, description="Conversation id (optional)")
    project_id: Optional[str] = Field(None, description="Project ID context (optional)")
    fun_mode: bool = Field(False, description="Frontend fun mode toggle")
    mode: Optional[str] = Field(None, description="chat|imagine|edit|animate|project")
    provider: Optional[ProviderName] = Field(
        None,
        description="LLM provider selection. If omitted, backend default is used.",
    )
    ollama_base_url: Optional[str] = Field(
        None,
        description="Optional Ollama base URL override (e.g., http://localhost:11434)",
    )
    ollama_model: Optional[str] = Field(
        None,
        description="Optional Ollama model override (e.g., llama3:8b)",
    )
    provider_base_url: Optional[str] = Field(
        None,
        description="Optional base URL override for the selected provider.",
    )
    provider_model: Optional[str] = Field(
        None,
        description="Optional model override for the selected provider.",
    )
    # Backwards-compatible fields for openai_compat (vLLM)
    llm_base_url: Optional[str] = Field(
        None,
        description="Optional OpenAI-compatible (vLLM) base URL override.",
    )
    llm_model: Optional[str] = Field(
        None,
        description="Optional OpenAI-compatible (vLLM) model override.",
    )
    # Custom generation parameters
    textTemperature: Optional[float] = Field(None, description="Text generation temperature (0-2)")
    textMaxTokens: Optional[int] = Field(None, description="Max tokens for text generation")
    imgWidth: Optional[int] = Field(None, description="Image width")
    imgHeight: Optional[int] = Field(None, description="Image height")
    imgAspectRatio: Optional[str] = Field(None, description="Image aspect ratio (1:1, 4:3, 3:4, 16:9, 9:16)")
    imgSteps: Optional[int] = Field(None, description="Image generation steps")
    imgCfg: Optional[float] = Field(None, description="Image CFG scale")
    imgSeed: Optional[int] = Field(None, description="Image generation seed (0 = random)")
    imgModel: Optional[str] = Field(None, description="Image model selection (sdxl, flux-schnell, flux-dev, pony-xl, sd15-uncensored)")
    imgBatchSize: Optional[int] = Field(1, ge=1, le=4, description="Number of images to generate per request (1, 2, or 4)")
    imgPreset: Optional[str] = Field(None, description="Image quality preset (low, med, high, ultra)")
    imgResolutionOverride: Optional[bool] = Field(None, description="When true, imgWidth/imgHeight override preset dims additively")
    vidSeconds: Optional[int] = Field(None, description="Video duration in seconds")
    vidFps: Optional[int] = Field(None, description="Video FPS")
    vidMotion: Optional[str] = Field(None, description="Video motion bucket")
    vidModel: Optional[str] = Field(None, description="Video model selection (svd, wan-2.2, seedream)")
    vidPreset: Optional[str] = Field(None, description="Video quality preset (low, medium, high, ultra)")
    vidAspectRatio: Optional[str] = Field(None, description="Video aspect ratio (16:9, 9:16, 1:1, 4:3, 3:4)")
    vidSteps: Optional[int] = Field(None, description="Override steps for video generation")
    vidCfg: Optional[float] = Field(None, description="Override CFG scale for video generation")
    vidDenoise: Optional[float] = Field(None, description="Override denoise strength for video generation")
    vidSeed: Optional[int] = Field(None, description="Override seed for video generation (0 = random)")
    vidNegativePrompt: Optional[str] = Field(None, description="Custom negative prompt for video generation")
    vidResolutionMode: Optional[str] = Field(None, description="Resolution mode: 'auto' (from preset) or 'override' (use vidWidth/vidHeight)")
    vidWidth: Optional[int] = Field(None, description="Override video width (must be divisible by 32)")
    vidHeight: Optional[int] = Field(None, description="Override video height (must be divisible by 32)")
    nsfwMode: Optional[bool] = Field(None, description="Enable NSFW/uncensored mode")
    memoryEngine: Optional[str] = Field(None, description="Memory engine: off | v1 | v2 (brain-inspired)")
    promptRefinement: Optional[bool] = Field(True, description="Enable AI prompt refinement for image generation (default: True)")
    # ----------------------------
    # Generation Mode (identity-preserving avatar generation)
    # ----------------------------
    generation_mode: Optional[str] = Field(None, description="Generation mode: 'standard' (default) or 'identity' (face-preserving via InstantID)")
    reference_image_url: Optional[str] = Field(None, description="Reference image URL for identity-preserving generation (face to preserve)")
    # ----------------------------
    # Game Mode (Infinite Variations)
    # ----------------------------
    gameMode: Optional[bool] = Field(False, description="Enable game mode (prompt variations)")
    gameSessionId: Optional[str] = Field(None, description="Game session id (keeps variation memory)")
    gameStrength: Optional[float] = Field(0.65, description="Variation strength 0..1")
    gameSpicyStrength: Optional[float] = Field(0.0, description="Spicy variation strength 0..1 (only used when nsfwMode + gameMode)")
    gameLocks: Optional[Dict[str, Any]] = Field(None, description="Lock settings (world/style/etc)")
    gameWorldBible: Optional[str] = Field("", description="Optional world bible text for consistency")
    gameUseGlobalLLMForVariations: Optional[bool] = Field(False, description="Use global chat model for Game Mode variations (default: False)")
    # ----------------------------
    # Reference Image (img2img similar generation)
    # ----------------------------
    imgReference: Optional[str] = Field(None, description="Reference image URL for img2img generation")
    imgRefStrength: Optional[float] = Field(0.35, description="Reference strength 0..1 (0=very similar, 1=more creative)")
    # ----------------------------
    # Voice Mode Personality
    # ----------------------------
    voiceSystemPrompt: Optional[str] = Field(None, description="Custom system prompt for voice mode personalities (legacy)")
    personalityId: Optional[str] = Field(None, description="Backend personality agent id (e.g. 'therapist', 'assistant')")
    # Smart multimodal topology: optional extra context injected into system prompt
    extra_system_context: Optional[str] = Field(
        None,
        description="Optional extra system context (e.g., vision analysis) injected into the next LLM call.",
    )


class ChatOut(BaseModel):
    conversation_id: str
    text: str
    media: Optional[Dict[str, Any]] = None

class ProjectFile(BaseModel):
    name: str
    size: Optional[str] = None
    path: Optional[str] = None

class ProjectCreateIn(BaseModel):
    name: str
    description: Optional[str] = ""
    instructions: Optional[str] = ""
    files: Optional[list] = []
    is_public: Optional[bool] = False
    project_type: Optional[str] = "chat"
    agentic: Optional[dict] = None
    persona_agent: Optional[dict] = None
    persona_appearance: Optional[dict] = None


# ----------------------------
# Helpers
# ----------------------------

def _base_url_from_request(req: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return str(req.base_url).rstrip("/")


def _safe_err(message: str, *, code: str = "error") -> Dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


def _is_photo_intent(msg: str) -> bool:
    """Detect deterministic 'show me your photo' intent for persona projects."""
    m = (msg or "").lower().strip()
    triggers = [
        "show me your photo",
        "show me your picture",
        "show your photo",
        "show your picture",
        "your photo",
        "your picture",
        "what do you look like",
        "how do you look",
    ]
    return any(t in m for t in triggers)


def _compute_upload_dir() -> Path:
    """
    Production-safe upload dir resolution:

    - If UPLOAD_DIR is absolute and writable => use it (e.g. Docker /app/data)
    - Otherwise fall back to a repo-local writable path: backend/data/uploads
    - Supports overriding via env var UPLOAD_DIR (common in docker-compose/k8s)
    """
    env_dir = os.getenv("UPLOAD_DIR")
    cfg_dir = env_dir or (str(UPLOAD_DIR) if UPLOAD_DIR else "")
    candidate = Path(cfg_dir) if cfg_dir else Path()

    # Absolute candidate first (Docker/Prod)
    if candidate.is_absolute():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            testfile = candidate / ".write_test"
            testfile.write_text("ok")
            testfile.unlink(missing_ok=True)
            return candidate
        except Exception:
            # Not writable in this environment (common on local/WSL)
            pass

    # Local dev fallback (always writable)
    backend_dir = Path(__file__).resolve().parents[1]  # .../backend
    fallback = backend_dir / "data" / "uploads"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


UPLOAD_PATH: Path = _compute_upload_dir()


def _ensure_db_path_is_writable():
    """
    Fixes the 'Permission denied: /app/data' error for local development.
    If the configured SQLITE_PATH is not writable, we patch it to use
    the safe local 'data' directory calculated above.
    """
    current_db_path = getattr(config, "SQLITE_PATH", None)
    
    # If no path configured, nothing to fix
    if not current_db_path:
        return

    # Check if we can write to the configured directory
    target_dir = os.path.dirname(current_db_path) or "."
    is_writable = False
    
    try:
        os.makedirs(target_dir, exist_ok=True)
        # Try touching a file to verify real write permissions
        test_file = os.path.join(target_dir, ".perm_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        is_writable = True
    except (OSError, PermissionError):
        is_writable = False

    if not is_writable:
        # Fallback: Use the parent of our safe UPLOAD_PATH (e.g. backend/data/db.sqlite)
        safe_db_path = UPLOAD_PATH.parent / "db.sqlite"
        print(f"INFO: Configured DB path '{current_db_path}' is not writable. Switching to local: {safe_db_path}")
        
        # Monkey-patch the config and storage modules
        # This ensures init_db() uses the new path
        new_path_str = str(safe_db_path)
        
        if hasattr(config, "SQLITE_PATH"):
            config.SQLITE_PATH = new_path_str
        
        # storage.py likely imported SQLITE_PATH, so we must update it there too
        if hasattr(storage, "SQLITE_PATH"):
            storage.SQLITE_PATH = new_path_str


def _ensure_static_mount() -> None:
    """
    Legacy StaticFiles mount replaced by secure files router (backend/app/files.py).
    The files router serves /files/{asset_id} with ownership checks and also
    provides a legacy fallback for /files/{filename} paths.
    UPLOAD_PATH is still created for backward compatibility.
    """
    UPLOAD_PATH.mkdir(parents=True, exist_ok=True)


# ----------------------------
# Startup
# ----------------------------

@app.on_event("startup")
def _startup() -> None:
    # Quieten noisy polling endpoints in uvicorn access logs
    import logging

    class _QuietPollFilter(logging.Filter):
        """Suppress access-log lines for high-frequency polling endpoints."""
        _quiet_paths = ("/v1/avatar-models/download/status",)

        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return not any(p in msg for p in self._quiet_paths)

    uv_access = logging.getLogger("uvicorn.access")
    uv_access.addFilter(_QuietPollFilter())

    # Ensure DB path is valid before initializing
    _ensure_db_path_is_writable()
    # Database
    init_db()
    # Initialize game mode database tables
    init_game_db()
    # Initialize story mode database tables
    init_story_db()
    # Initialize Creator Studio database tables (SQLite persistence)
    init_studio_db()
    # Run migrations
    try:
        run_migrations()
    except Exception as e:
        print(f"Warning: Failed to run migrations: {e}")
    # Files mount
    _ensure_static_mount()


# Ensure local storage is ready even when lifespan events are not executed
# (e.g. Starlette TestClient instantiated without a context manager).
try:
    _ensure_db_path_is_writable()
    init_db()
except Exception:
    pass

# Mount at import-time too (needed for some test setups and for immediate serving)
_ensure_static_mount()


# ----------------------------
# Error handling (prod-safe)
# ----------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception):
    # In real deployments, log `exc` to your logger/observability stack.
    return JSONResponse(
        status_code=500,
        content=_safe_err("Internal server error.", code="internal_error"),
    )


# ----------------------------
# Routes
# ----------------------------

@app.get("/health")
async def health() -> JSONResponse:
    """
    Quick health check with provider availability.
    """
    status = {
        "ok": True,
        "service": "homepilot-backend",
        "version": app.version,
    }

    # Check Ollama
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            ollama_ok = (r.status_code == 200)
    except Exception:
        ollama_ok = False

    # Check OpenAI-compatible (vLLM)
    vllm_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{LLM_BASE_URL.rstrip('/')}/models")
            vllm_ok = (r.status_code == 200)
    except Exception:
        vllm_ok = False

    status["providers"] = {
        "ollama": {"ok": ollama_ok, "base_url": OLLAMA_BASE_URL},
        "openai_compat": {"ok": vllm_ok, "base_url": LLM_BASE_URL},
    }

    return JSONResponse(status_code=200, content=status)


@app.get("/health/detailed")
async def health_detailed() -> JSONResponse:
    """
    Comprehensive health check for all services.
    Tests: Ollama, ComfyUI, vLLM
    """
    health_status = {
        "backend": {"ok": True, "service": "homepilot-backend", "version": app.version},
        "ollama": {"ok": False, "message": "Not tested"},
        "comfyui": {"ok": False, "message": "Not tested"},
        "llm": {"ok": False, "message": "Not tested"},
    }

    # Test Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}")
            if response.status_code == 200:
                health_status["ollama"] = {
                    "ok": True,
                    "url": OLLAMA_BASE_URL,
                    "status": "running"
                }
                # Try to get models
                try:
                    models_response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                    if models_response.status_code == 200:
                        models_data = models_response.json()
                        model_names = [m.get("name") for m in models_data.get("models", [])]
                        health_status["ollama"]["models"] = model_names
                        health_status["ollama"]["model_count"] = len(model_names)
                except Exception:
                    pass
            else:
                health_status["ollama"] = {
                    "ok": False,
                    "url": OLLAMA_BASE_URL,
                    "message": f"HTTP {response.status_code}"
                }
    except Exception as e:
        health_status["ollama"] = {
            "ok": False,
            "url": OLLAMA_BASE_URL,
            "message": f"Connection failed: {str(e)}"
        }

    # Test ComfyUI
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{COMFY_BASE_URL}/system_stats")
            if response.status_code == 200:
                health_status["comfyui"] = {
                    "ok": True,
                    "url": COMFY_BASE_URL,
                    "status": "running"
                }
            else:
                health_status["comfyui"] = {
                    "ok": False,
                    "url": COMFY_BASE_URL,
                    "message": f"HTTP {response.status_code}"
                }
    except Exception as e:
        health_status["comfyui"] = {
            "ok": False,
            "url": COMFY_BASE_URL,
            "message": f"Connection failed: {str(e)}"
        }

    # Test LLM (vLLM)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{LLM_BASE_URL}/models")
            if response.status_code == 200:
                health_status["llm"] = {
                    "ok": True,
                    "url": LLM_BASE_URL,
                    "status": "running"
                }
            else:
                health_status["llm"] = {
                    "ok": False,
                    "url": LLM_BASE_URL,
                    "message": f"HTTP {response.status_code}"
                }
    except Exception as e:
        health_status["llm"] = {
            "ok": False,
            "url": LLM_BASE_URL,
            "message": f"Connection failed: {str(e)}"
        }

    # Test Multimodal (vision models via Ollama)
    multimodal_status = {"ok": False, "status": "not_checked", "vision_models": []}
    try:
        if health_status["ollama"].get("ok"):
            all_models = health_status["ollama"].get("models", [])
            vision_models = [
                m for m in all_models
                if any(p in m.lower() for p in VISION_MODEL_PATTERNS)
            ]
            multimodal_status = {
                "ok": len(vision_models) > 0,
                "status": "available" if vision_models else "no_vision_models",
                "vision_models": vision_models,
                "vision_model_count": len(vision_models),
                "recommended_default": vision_models[0] if vision_models else None,
            }
        else:
            multimodal_status = {
                "ok": False,
                "status": "ollama_unavailable",
                "vision_models": [],
            }
    except Exception as e:
        multimodal_status = {
            "ok": False,
            "status": f"check_failed: {str(e)}",
            "vision_models": [],
        }
    health_status["multimodal"] = multimodal_status

    # Determine overall health
    all_ok = health_status["ollama"]["ok"] or health_status["llm"]["ok"]  # At least one LLM should work

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "ok": all_ok,
            "services": health_status,
            "timestamp": uuidlib.uuid4().hex[:8],  # Simple timestamp
        },
    )


@app.get("/providers")
async def providers() -> JSONResponse:
    info = provider_info()
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "default": DEFAULT_PROVIDER,
            "available": sorted(list(info.keys())),
            "providers": info,
        },
    )


@app.get("/settings")
async def settings(request: Request) -> JSONResponse:
    base = _base_url_from_request(request)
    info = provider_info()
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "default_provider": DEFAULT_PROVIDER,
            "providers": info,
            "public_base_url": base,
            "llm_base_url": LLM_BASE_URL,
            "llm_model": LLM_MODEL,
            "comfy_base_url": COMFY_BASE_URL,
            "media_base_url": MEDIA_BASE_URL,
            "upload_dir": str(UPLOAD_PATH),
            "max_upload_mb": int(MAX_UPLOAD_MB),
        },
    )


@app.get("/video-presets")
async def get_video_presets(
    model: Optional[str] = Query(None, description="Video model type: svd, ltx, wan, hunyuan, mochi, cogvideo"),
    preset: Optional[str] = Query(None, description="Quality preset: low, medium, high, ultra"),
    aspect_ratio: Optional[str] = Query(None, description="Aspect ratio: 16:9, 9:16, 1:1, 4:3, 3:4"),
) -> JSONResponse:
    """
    Get video generation preset values.

    Returns model-specific settings for the selected quality preset.
    If no model is specified, returns base preset values.
    If no preset is specified, returns 'medium' preset.
    If aspect_ratio is specified, includes dimensions for that ratio.

    Example: GET /video-presets?model=ltx&preset=medium&aspect_ratio=16:9
    Returns: { steps: 24, cfg: 4.0, width: 832, height: 480, fps: 24, frames: 49, ... }
    """
    try:
        presets_path = Path(__file__).parent / "video_presets.json"

        if not presets_path.exists():
            return JSONResponse(
                status_code=404,
                content=_safe_err("Video presets file not found", code="presets_not_found"),
            )

        with open(presets_path, "r", encoding="utf-8") as f:
            presets_data = json.load(f)

        # Default to medium preset; normalise common aliases
        _preset_aliases = {"med": "medium"}
        preset_name = _preset_aliases.get(preset or "", preset or "medium")
        if preset_name not in presets_data.get("presets", {}):
            return JSONResponse(
                status_code=400,
                content=_safe_err(
                    f"Unknown preset: {preset_name}. Valid presets: low, medium, high, ultra",
                    code="invalid_preset",
                ),
            )

        preset_config = presets_data["presets"][preset_name]
        base_values = dict(preset_config.get("base", {}))

        # If model specified, merge with model-specific overrides
        if model:
            model_lower = model.lower()
            model_overrides = preset_config.get("model_overrides", {}).get(model_lower, {})
            # Merge base with overrides (overrides take precedence)
            result_values = {**base_values, **model_overrides}
        else:
            result_values = base_values

        # Get dimensions from aspect_ratios if specified
        aspect_ratios_data = presets_data.get("aspect_ratios", {})
        if aspect_ratio and aspect_ratio in aspect_ratios_data:
            ratio_config = aspect_ratios_data[aspect_ratio]
            # Check model compatibility
            compatible = ratio_config.get("compatible_models", [])
            model_lower = (model or "").lower()
            if not model_lower or model_lower in compatible:
                dims = ratio_config.get("dimensions", {}).get(preset_name, {})
                if dims:
                    result_values["width"] = dims.get("width", result_values.get("width"))
                    result_values["height"] = dims.get("height", result_values.get("height"))
        elif aspect_ratio:
            # Default to 16:9 if aspect ratio not found
            ratio_config = aspect_ratios_data.get("16:9", {})
            dims = ratio_config.get("dimensions", {}).get(preset_name, {})
            if dims:
                result_values["width"] = dims.get("width", result_values.get("width"))
                result_values["height"] = dims.get("height", result_values.get("height"))

        # Get model rules if available
        model_rules = {}
        if model:
            model_lower = model.lower()
            model_rules = presets_data.get("model_rules", {}).get(model_lower, {})

        # Get compatible aspect ratios for the model
        compatible_ratios = []
        model_lower = (model or "").lower()
        for ratio_id, ratio_config in aspect_ratios_data.items():
            compatible = ratio_config.get("compatible_models", [])
            if not model_lower or model_lower in compatible:
                all_dims = ratio_config.get("dimensions", {})
                compatible_ratios.append({
                    "id": ratio_id,
                    "label": ratio_config.get("ui_label", ratio_id),
                    # Single-preset dims (backward compat)
                    "dimensions": all_dims.get(preset_name, {}),
                    # ALL preset tiers so the Override grid can show every option
                    "all_dimensions": all_dims,
                })

        # Determine default aspect ratio for the model
        # Priority: model_rules.default_aspect_ratio > first compatible ratio > "16:9"
        default_aspect_ratio = model_rules.get("default_aspect_ratio")
        if not default_aspect_ratio and compatible_ratios:
            default_aspect_ratio = compatible_ratios[0]["id"]
        if not default_aspect_ratio:
            default_aspect_ratio = "16:9"

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "preset": preset_name,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "values": result_values,
                "model_rules": model_rules,
                "ui": preset_config.get("ui", {}),
                "compatible_aspect_ratios": compatible_ratios,
                "default_aspect_ratio": default_aspect_ratio,
            },
        )

    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Invalid JSON in presets file: {str(e)}", code="presets_invalid_json"),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Error loading presets: {str(e)}", code="presets_error"),
        )


@app.get("/image-presets")
async def get_image_presets(
    model: Optional[str] = Query(None, description="Image model architecture: sd15, sdxl, flux_schnell, flux_dev"),
    preset: Optional[str] = Query(None, description="Quality preset: low, med, high, ultra"),
    aspect_ratio: Optional[str] = Query(None, description="Aspect ratio: 1:1, 4:3, 3:4, 16:9, 9:16"),
) -> JSONResponse:
    """
    Get image generation preset values.

    Returns model-specific settings for the selected quality preset.
    If no model is specified, returns base preset values.
    If no preset is specified, returns 'med' preset.

    Example: GET /image-presets?model=sdxl&preset=med&aspect_ratio=16:9
    Returns: { steps: 30, cfg: 5.5, width: 1216, height: 832, ... }
    """
    try:
        presets_path = Path(__file__).parent / "image_presets.json"

        if not presets_path.exists():
            return JSONResponse(
                status_code=404,
                content=_safe_err("Image presets file not found", code="presets_not_found"),
            )

        with open(presets_path, "r", encoding="utf-8") as f:
            presets_data = json.load(f)

        # Default to med preset
        preset_name = preset or "med"
        if preset_name not in presets_data.get("presets", {}):
            return JSONResponse(
                status_code=400,
                content=_safe_err(
                    f"Unknown preset: {preset_name}. Valid presets: low, med, high",
                    code="invalid_preset",
                ),
            )

        preset_config = presets_data["presets"][preset_name]
        base_values = dict(preset_config.get("base_values", {}))

        # If model specified, merge with model-specific overrides
        model_lower = (model or "").lower()
        if model_lower:
            model_overrides = preset_config.get("model_overrides", {}).get(model_lower, {})
            result_values = {**base_values, **model_overrides}
        else:
            result_values = base_values

        # Get dimensions from aspect_ratios if specified
        aspect_ratios_data = presets_data.get("aspect_ratios", {})
        if aspect_ratio and aspect_ratio in aspect_ratios_data:
            ratio_config = aspect_ratios_data[aspect_ratio]
            dims = ratio_config.get("dimensions", {}).get(model_lower or "sdxl", {})
            if dims:
                result_values["width"] = dims.get("width", result_values.get("width"))
                result_values["height"] = dims.get("height", result_values.get("height"))

        # Get model rules if available
        model_rules = {}
        if model_lower:
            model_rules = presets_data.get("model_rules", {}).get(model_lower, {})

        # Get compatible aspect ratios for the model
        compatible_ratios = []
        for ratio_id, ratio_config in aspect_ratios_data.items():
            compatible = ratio_config.get("compatible_models", [])
            if not model_lower or model_lower in compatible:
                dims = ratio_config.get("dimensions", {}).get(model_lower or "sdxl", {})
                compatible_ratios.append({
                    "id": ratio_id,
                    "label": ratio_config.get("ui_label", ratio_id),
                    "dimensions": dims,
                })

        # Determine default aspect ratio for the model
        default_aspect_ratio = model_rules.get("default_aspect_ratio")
        if not default_aspect_ratio and compatible_ratios:
            default_aspect_ratio = compatible_ratios[0]["id"]
        if not default_aspect_ratio:
            default_aspect_ratio = "1:1"

        # Compute resolution for EVERY available preset tier (low/med/high/ultra)
        # for EVERY compatible aspect ratio, using the actual model_config preset
        # system. This gives the frontend the exact WxH that each preset produces.
        available_presets = list(presets_data.get("presets", {}).keys())
        preset_resolutions: Dict[str, Any] = {}  # { aspect_ratio: { preset: {w,h} } }
        if model:
            for cr in compatible_ratios:
                ar_id = cr["id"]
                ar_presets: Dict[str, Any] = {}
                for pr in available_presets:
                    try:
                        settings = get_model_settings(
                            model_filename=model,
                            aspect_ratio=ar_id,
                            preset=pr,
                        )
                        ar_presets[pr] = {
                            "width": settings["width"],
                            "height": settings["height"],
                        }
                    except Exception:
                        pass
                if ar_presets:
                    preset_resolutions[ar_id] = ar_presets

        # Also include UI labels from presets for the resolution grid
        preset_ui = {}
        for pr_name, pr_config in presets_data.get("presets", {}).items():
            preset_ui[pr_name] = pr_config.get("ui", {})

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "preset": preset_name,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "values": result_values,
                "model_rules": model_rules,
                "ui": preset_config.get("ui", {}),
                "compatible_aspect_ratios": compatible_ratios,
                "default_aspect_ratio": default_aspect_ratio,
                "preset_resolutions": preset_resolutions,
                "preset_ui": preset_ui,
                "available_presets": available_presets,
            },
        )

    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Invalid JSON in image presets file: {str(e)}", code="presets_invalid_json"),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Error loading image presets: {str(e)}", code="presets_error"),
        )


# -----------------------------------------------------------------------------
# API Keys Management (Optional - for gated HuggingFace / Civitai models)
# -----------------------------------------------------------------------------

from .api_keys import (
    get_api_keys_status,
    get_api_key,
    set_api_key,
    delete_api_key,
)


class ApiKeySetRequest(BaseModel):
    """Request to set an API key."""
    provider: str = Field(..., description="Provider: 'huggingface' or 'civitai'")
    key: str = Field(..., description="The API key/token")


class ApiKeyTestRequest(BaseModel):
    """Request to test an API key."""
    provider: str = Field(..., description="Provider to test")
    key: Optional[str] = Field(None, description="Key to test (uses stored if not provided)")


@app.get("/settings/api-keys")
async def get_api_keys_endpoint() -> JSONResponse:
    """
    Get status of configured API keys (masked, not actual values).

    API keys are OPTIONAL - HomePilot works without them.
    Keys are only needed for:
    - Gated HuggingFace models (FLUX, SVD XT 1.1)
    - NSFW/restricted Civitai models
    """
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "keys": get_api_keys_status(),
            "note": "API keys are optional. Only needed for gated/restricted models.",
        },
    )


@app.post("/settings/api-keys")
async def set_api_key_endpoint(req: ApiKeySetRequest) -> JSONResponse:
    """Set an API key for a provider (huggingface or civitai)."""
    if req.provider not in ("huggingface", "civitai"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"Unknown provider: {req.provider}. Use 'huggingface' or 'civitai'."},
        )

    set_api_key(req.provider, req.key)  # type: ignore

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "message": f"API key for {req.provider} saved successfully",
            "status": get_api_keys_status()[req.provider],
        },
    )


@app.delete("/settings/api-keys/{provider}")
async def delete_api_key_endpoint(provider: str) -> JSONResponse:
    """Remove a stored API key."""
    if provider not in ("huggingface", "civitai"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"Unknown provider: {provider}. Use 'huggingface' or 'civitai'."},
        )

    deleted = delete_api_key(provider)  # type: ignore

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "deleted": deleted,
            "message": f"API key for {provider} {'removed' if deleted else 'was not set'}",
        },
    )


@app.post("/settings/api-keys/test")
async def test_api_key_endpoint(req: ApiKeyTestRequest) -> JSONResponse:
    """
    Test if an API key is valid by making a test request to the provider.
    If no key is provided in the request, tests the stored/env key.
    """
    if req.provider not in ("huggingface", "civitai"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"Unknown provider: {req.provider}"},
        )

    key = req.key.strip() if req.key else get_api_key(req.provider)  # type: ignore
    if not key:
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "valid": False,
                "message": f"No API key provided or stored for {req.provider}",
            },
        )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            if req.provider == "huggingface":
                # Test HF token by getting user info
                r = await client.get(
                    "https://huggingface.co/api/whoami-v2",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if r.status_code == 200:
                    data = r.json()
                    return JSONResponse(content={
                        "ok": True,
                        "valid": True,
                        "message": f"Authenticated as: {data.get('name', 'unknown')}",
                        "username": data.get("name"),
                    })
                else:
                    return JSONResponse(content={
                        "ok": True,
                        "valid": False,
                        "message": f"Invalid token (HTTP {r.status_code})",
                    })

            elif req.provider == "civitai":
                # Test Civitai key by getting current user
                r = await client.get(
                    "https://civitai.com/api/v1/me",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if r.status_code == 200:
                    data = r.json()
                    return JSONResponse(content={
                        "ok": True,
                        "valid": True,
                        "message": f"Authenticated as: {data.get('username', 'unknown')}",
                        "username": data.get("username"),
                    })
                else:
                    return JSONResponse(content={
                        "ok": True,
                        "valid": False,
                        "message": f"Invalid API key (HTTP {r.status_code})",
                    })

    except Exception as e:
        return JSONResponse(content={
            "ok": True,
            "valid": False,
            "message": f"Connection error: {str(e)}",
        })

    return JSONResponse(content={"ok": True, "valid": False, "message": "Unknown error"})


@app.get("/models")
async def list_models(
    provider: str = Query("openai_compat", description="Provider to list models from"),
    base_url: Optional[str] = Query(None, description="Override base URL for the provider"),
    model_type: Optional[str] = Query(None, description="For ComfyUI: 'image', 'video', or 'edit'"),
) -> JSONResponse:
    """
    List available models from a provider.
    Supports:
      - openai_compat: GET {base}/models   (expects OpenAI-style response)
      - ollama: GET {base}/api/tags
      - openai: OpenAI API
      - claude: Anthropic API
      - watsonx: IBM watsonx.ai
      - comfyui: Returns local image/video models list

    Example: GET /models?provider=ollama&base_url=http://localhost:11434
    Example: GET /models?provider=comfyui&model_type=image
    """
    try:
        # ComfyUI model listing - scan filesystem for installed models
        if provider == "comfyui":
            from .providers import scan_installed_models

            if model_type == "image":
                models = scan_installed_models("image")
            elif model_type == "video":
                models = scan_installed_models("video")
            elif model_type == "edit":
                models = scan_installed_models("edit")
            elif model_type == "enhance":
                models = scan_installed_models("enhance")
            elif model_type == "addons":
                models = scan_installed_models("addons")
            else:
                # Return all if not specified
                models = (
                    scan_installed_models("image")
                    + scan_installed_models("video")
                    + scan_installed_models("edit")
                    + scan_installed_models("enhance")
                    + scan_installed_models("addons")
                )

            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "provider": "comfyui",
                    "model_type": model_type or "all",
                    "models": models,
                    "count": len(models),
                    "message": f"Scanned filesystem - found {len(models)} installed models",
                },
            )

        # Everything else uses the shared model catalog
        from .model_catalog import list_models_for_provider

        # Validate provider string against our ProviderName literal
        if provider not in {"openai_compat", "ollama", "openai", "claude", "watsonx"}:
            return JSONResponse(
                status_code=400,
                content=_safe_err(
                    f"Provider '{provider}' is not supported for model listing.",
                    code="unsupported_provider",
                ),
            )
        prov: ProviderName = provider  # type: ignore

        models, err = await list_models_for_provider(prov, base_url=base_url)
        if err:
            return JSONResponse(status_code=503, content=_safe_err(err, code="models_unavailable"))

        # Filter Ollama models to only vision-capable ones when multimodal type is requested
        if provider == "ollama" and model_type == "multimodal":
            models = [
                m for m in models
                if any(p in m.lower() for p in VISION_MODEL_PATTERNS)
            ]

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "provider": provider,
                "base_url": (base_url or ""),
                "models": models,
                "count": len(models),
            },
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Error listing models: {str(e)}",
                code="models_error",
            ),
        )


@app.get("/model-catalog")
async def get_model_catalog() -> JSONResponse:
    """
    Return the curated model catalog with recommended models for all providers.

    The catalog is read from model_catalog_data.json and includes:
    - Model IDs and labels
    - Recommended flags
    - Model descriptions, sizes, capabilities
    - Download URLs and install paths (for ComfyUI)

    This endpoint provides a static catalog that can be easily maintained by
    editing the JSON file. To add/remove models, simply edit the JSON file.

    Example: GET /model-catalog
    Returns: { "ok": true, "providers": { ... }, "version": "1.0.0" }
    """
    try:
        catalog_path = Path(__file__).parent / "model_catalog_data.json"

        if not catalog_path.exists():
            return JSONResponse(
                status_code=404,
                content=_safe_err(
                    "Model catalog file not found. Please create model_catalog_data.json",
                    code="catalog_not_found",
                ),
            )

        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog_data = json.load(f)

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "version": catalog_data.get("version", "1.0.0"),
                "last_updated": catalog_data.get("last_updated", "unknown"),
                "providers": catalog_data.get("providers", {}),
            },
        )

    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Invalid JSON in model catalog: {str(e)}",
                code="catalog_invalid_json",
            ),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Error loading model catalog: {str(e)}",
                code="catalog_error",
            ),
        )


# ----------------------------
# Civitai Search API
# ----------------------------

class CivitaiSearchRequest(BaseModel):
    """Request model for Civitai search."""
    model_config = {"protected_namespaces": ()}

    query: str = Field(..., min_length=1, max_length=100, description="Search query")
    model_type: str = Field(default="image", description="Model type: 'image' or 'video'")
    nsfw: bool = Field(default=False, description="Include NSFW results (requires API key)")
    limit: int = Field(default=20, ge=1, le=50, description="Results per page")
    page: int = Field(default=1, ge=1, description="Page number")
    sort: str = Field(default="Highest Rated", description="Sort order")


@app.post("/civitai/search")
async def civitai_search(
    req: CivitaiSearchRequest,
    request: Request,
    x_civitai_api_key: Optional[str] = None,
) -> JSONResponse:
    """
    Search Civitai models.

    This is an enterprise-safe backend proxy for Civitai API:
    - API key is OPTIONAL for SFW/public searches
    - For NSFW searches, pass X-Civitai-Api-Key header (optional)
    - Results are cached briefly to reduce upstream rate pressure
    - Responses are normalized to a stable schema

    Example:
        POST /civitai/search
        {
            "query": "anime",
            "model_type": "image",
            "nsfw": false,
            "limit": 20,
            "page": 1
        }
    """
    try:
        # Get API key from header if provided
        api_key = request.headers.get("X-Civitai-Api-Key") or x_civitai_api_key

        # Sanitize query
        query = req.query.strip()[:100]
        if not query:
            return JSONResponse(
                status_code=400,
                content=_safe_err("Query is required", code="invalid_query"),
            )

        # Validate model_type
        if req.model_type not in ("image", "video"):
            return JSONResponse(
                status_code=400,
                content=_safe_err("model_type must be 'image' or 'video'", code="invalid_model_type"),
            )

        # Create client (with optional API key for NSFW)
        # Only pass API key if NSFW is requested
        client = CivitaiClient(api_key=api_key if req.nsfw else None)

        # Build search query
        search_query = CivitaiSearchQuery(
            query=query,
            model_type=req.model_type,
            limit=req.limit,
            page=req.page,
            nsfw=req.nsfw,
            sort=req.sort,
        )

        # Get cache and perform search
        cache = get_civitai_cache()
        results = await search_and_normalize(
            client=client,
            cache=cache,
            query=search_query,
        )

        print(f"[CIVITAI] Search '{query}' returned {len(results.get('items', []))} results")

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "query": query,
                "model_type": req.model_type,
                "nsfw": req.nsfw,
                "items": results.get("items", []),
                "metadata": results.get("metadata", {}),
            },
        )

    except httpx.HTTPStatusError as e:
        error_msg = f"Civitai API error: {e.response.status_code}"
        print(f"[CIVITAI] {error_msg}")
        return JSONResponse(
            status_code=502,
            content=_safe_err(error_msg, code="civitai_api_error"),
        )
    except httpx.TimeoutException:
        print("[CIVITAI] Request timeout")
        return JSONResponse(
            status_code=504,
            content=_safe_err("Civitai API timeout - try again later", code="civitai_timeout"),
        )
    except Exception as e:
        print(f"[CIVITAI] Unexpected error: {e}")
        return JSONResponse(
            status_code=500,
            content=_safe_err("Search failed - please try again", code="civitai_error"),
        )


@app.get("/civitai/search")
async def civitai_search_get(
    request: Request,
    query: str = Query(..., min_length=1, max_length=100, description="Search query"),
    model_type: str = Query(default="image", description="Model type: 'image' or 'video'"),
    nsfw: bool = Query(default=False, description="Include NSFW results"),
    limit: int = Query(default=20, ge=1, le=50, description="Results per page"),
    page: int = Query(default=1, ge=1, description="Page number"),
    sort: str = Query(default="Highest Rated", description="Sort order"),
) -> JSONResponse:
    """
    GET version of Civitai search for easier testing.

    Example: GET /civitai/search?query=anime&model_type=image&limit=10
    """
    req = CivitaiSearchRequest(
        query=query,
        model_type=model_type,
        nsfw=nsfw,
        limit=limit,
        page=page,
        sort=sort,
    )
    return await civitai_search(req, request)


class ModelInstallRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    provider: str = Field(..., description="Provider (ollama, comfyui, civitai)")
    model_type: str = Field(..., description="Model type (chat, image, video, edit)")
    model_id: str = Field(..., description="Model ID to install")
    base_url: Optional[str] = Field(None, description="Optional base URL override")
    civitai_version_id: Optional[str] = Field(None, description="Civitai version ID (for civitai provider)")
    civitai_api_key: Optional[str] = Field(None, description="Optional Civitai API key for restricted/NSFW downloads")


@app.post("/models/install")
async def install_model(req: ModelInstallRequest) -> JSONResponse:
    """
    Install a model using the download.py script.

    Supports:
    - ollama: Uses ollama pull
    - comfyui: Downloads from catalog
    - civitai: Downloads from Civitai by version ID (experimental)
    """
    import logging
    import sys

    logger = logging.getLogger("homepilot.install")
    logger.setLevel(logging.INFO)

    # Ensure we have a handler
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[INSTALL] %(message)s"))
        logger.addHandler(handler)

    try:
        script_path = Path(__file__).parent.parent.parent / "scripts" / "download.py"

        if not script_path.exists():
            logger.error(f"Download script not found at {script_path}")
            return JSONResponse(
                status_code=500,
                content=_safe_err(
                    "Download script not found. Please ensure scripts/download.py exists.",
                    code="script_not_found",
                ),
            )

        logger.info(f"Starting model installation: provider={req.provider}, model={req.model_id}")

        # Build command based on provider
        cmd = ["python3", str(script_path)]

        if req.provider == "civitai":
            # Experimental Civitai download
            if not req.civitai_version_id:
                return JSONResponse(
                    status_code=400,
                    content=_safe_err(
                        "civitai_version_id required for Civitai provider",
                        code="missing_version_id",
                    ),
                )

            cmd.extend([
                "--civitai",
                "--version-id", req.civitai_version_id,
                "--type", req.model_type,
            ])

            if req.model_id:
                cmd.extend(["--output", req.model_id])

        elif req.provider == "ollama":
            # Ollama: Use ollama pull directly
            logger.info(f"Pulling Ollama model: {req.model_id}")
            pull_cmd = ["ollama", "pull", req.model_id]

            # Use Popen to stream output to logs
            process = subprocess.Popen(
                pull_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            output_lines = []
            for line in iter(process.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    logger.info(f"  {line}")
                    output_lines.append(line)
            process.wait()

            if process.returncode == 0:
                logger.info(f"Successfully pulled Ollama model: {req.model_id}")
                return JSONResponse(
                    status_code=200,
                    content={
                        "ok": True,
                        "message": f"Successfully pulled {req.model_id}",
                        "provider": "ollama",
                        "model_id": req.model_id,
                        "output": "\n".join(output_lines),
                    },
                )
            else:
                logger.error(f"Failed to pull Ollama model: {req.model_id}")
                return JSONResponse(
                    status_code=500,
                    content=_safe_err(
                        f"Ollama pull failed: {output_lines[-5:] if output_lines else 'Unknown error'}",
                        code="ollama_pull_failed",
                    ),
                )

        elif req.provider == "comfyui":
            # ComfyUI: Download from catalog
            cmd.extend(["--model", req.model_id])

        else:
            return JSONResponse(
                status_code=400,
                content=_safe_err(
                    f"Unsupported provider: {req.provider}",
                    code="unsupported_provider",
                ),
            )

        # Run download script for comfyui and civitai
        # Pass Civitai API key via environment variable (secure - not visible in process list)
        env = os.environ.copy()
        if req.civitai_api_key and req.provider == "civitai":
            env["CIVITAI_API_KEY"] = req.civitai_api_key

        logger.info(f"Running download script: {' '.join(cmd)}")

        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        output_lines = []
        for line in iter(process.stdout.readline, ""):
            line = line.rstrip()
            if line:
                logger.info(f"  {line}")
                output_lines.append(line)
                # Flush stdout to ensure logs appear immediately
                sys.stdout.flush()

        process.wait()

        if process.returncode == 0:
            logger.info(f"Successfully installed model: {req.model_id}")
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "message": f"Successfully installed {req.model_id}",
                    "provider": req.provider,
                    "model_id": req.model_id,
                    "output": "\n".join(output_lines),
                },
            )
        else:
            logger.error(f"Failed to install model: {req.model_id}")
            # Get last few lines for error message
            error_output = "\n".join(output_lines[-10:]) if output_lines else "Unknown error"
            return JSONResponse(
                status_code=500,
                content=_safe_err(
                    f"Installation failed: {error_output}",
                    code="installation_failed",
                ),
            )

    except subprocess.TimeoutExpired:
        logger.error(f"Installation timed out for model: {req.model_id}")
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                "Installation timed out. Large models may take longer.",
                code="timeout",
            ),
        )
    except Exception as e:
        logger.exception(f"Installation error for model {req.model_id}: {e}")
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Installation error: {str(e)}",
                code="installation_error",
            ),
        )


class ModelDeleteRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    provider: str = Field(..., description="Provider: 'comfyui' or 'ollama'")
    model_id: str = Field(..., description="Model filename / ID to delete")
    model_type: Optional[str] = Field("image", description="Model type for path resolution")


@app.post("/models/delete", dependencies=[Depends(require_api_key)])
async def delete_model(req: ModelDeleteRequest) -> JSONResponse:
    """
    Delete an installed model from disk.

    Protected models (marked in the catalog) cannot be deleted.
    Only supports ComfyUI and Ollama providers.
    """
    if req.provider not in ("comfyui", "ollama"):
        return JSONResponse(status_code=400, content=_safe_err("Only comfyui and ollama models can be deleted"))

    # --- Load catalog and check protection ---
    catalog_path = Path(__file__).parent / "model_catalog_data.json"
    is_protected = False
    install_path_hint = None
    try:
        catalog = json.loads(catalog_path.read_text())
        provider_data = catalog.get("providers", {}).get(req.provider, {})
        for _type_key, entries in provider_data.items():
            if isinstance(entries, list):
                for entry in entries:
                    if entry.get("id") == req.model_id:
                        is_protected = entry.get("protected", False)
                        install_path_hint = entry.get("install_path")
                        break
    except Exception:
        pass

    if is_protected:
        return JSONResponse(
            status_code=403,
            content=_safe_err(
                f"Cannot delete '{req.model_id}': this is a protected default model.",
                code="protected_model",
            ),
        )

    if req.provider == "ollama":
        # Delete Ollama model via CLI
        try:
            result = subprocess.run(
                ["ollama", "rm", req.model_id],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return JSONResponse(content={"ok": True, "message": f"Deleted Ollama model: {req.model_id}"})
            else:
                return JSONResponse(status_code=500, content=_safe_err(f"Ollama rm failed: {result.stderr.strip()}"))
        except FileNotFoundError:
            return JSONResponse(status_code=500, content=_safe_err("Ollama CLI not found"))
        except Exception as e:
            return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete: {e}"))

    # --- ComfyUI: resolve file path and delete ---
    from .providers import get_comfy_models_path
    models_root = get_comfy_models_path()

    # Determine subdirectory from catalog hint or common locations
    search_dirs = []
    if install_path_hint:
        search_dirs.append(models_root / install_path_hint.rstrip("/"))
    # Always search common directories as fallback
    for subdir in ["checkpoints", "unet", "clip", "vae", "controlnet",
                    "upscale_models", "gfpgan", "sams", "rembg", "diffusion_models"]:
        d = models_root / subdir
        if d not in search_dirs:
            search_dirs.append(d)

    deleted_files = []
    for directory in search_dirs:
        candidate = directory / req.model_id
        if candidate.is_file():
            try:
                size_mb = candidate.stat().st_size / (1024 * 1024)
                candidate.unlink()
                deleted_files.append(f"{candidate} ({size_mb:.0f} MB)")
            except OSError as e:
                return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete file: {e}"))

    if not deleted_files:
        return JSONResponse(status_code=404, content=_safe_err(f"Model file not found: {req.model_id}"))

    return JSONResponse(content={
        "ok": True,
        "message": f"Deleted: {', '.join(deleted_files)}",
        "deleted": deleted_files,
    })


@app.get("/models/health")
async def check_models_health(
    model_type: Optional[str] = Query(None, description="Filter by model type: 'image', 'video', 'edit'"),
    provider: Optional[str] = Query(None, description="Filter by provider: 'comfyui', 'civitai'"),
) -> JSONResponse:
    """
    Check health status of all model download URLs.

    Returns health information for each downloadable model including:
    - status: 'healthy', 'unhealthy', 'timeout', 'error'
    - http_status: HTTP response code
    - response_time_ms: Time to check URL
    - error_message: Error details if unhealthy

    Use this to verify model sources before downloading.
    """
    import time
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        # Load catalog
        catalog_path = Path(__file__).parent / "model_catalog_data.json"
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        # Collect models to check
        models_to_check = []
        providers_data = catalog.get("providers", {})

        for prov_name, prov_data in providers_data.items():
            # Skip non-downloadable providers
            if prov_name in ("ollama", "openai", "claude", "openai_compat", "watsonx"):
                continue

            if provider and prov_name != provider:
                continue

            for type_name, model_list in prov_data.items():
                if model_type and type_name != model_type:
                    continue

                if not isinstance(model_list, list):
                    continue

                for model in model_list:
                    download_url = model.get("download_url")
                    if download_url:
                        models_to_check.append({
                            "id": model.get("id"),
                            "label": model.get("label", model.get("id")),
                            "provider": prov_name,
                            "type": type_name,
                            "url": download_url,
                            "size_gb": model.get("size_gb"),
                        })

        def check_single_url(model_info):
            """Check a single URL health."""
            url = model_info["url"]
            start = time.time()
            try:
                resp = requests.head(
                    url,
                    headers={"User-Agent": "HomePilot-HealthCheck/1.0"},
                    timeout=10,
                    allow_redirects=True,
                )
                elapsed_ms = int((time.time() - start) * 1000)

                if resp.status_code < 400:
                    status = "healthy"
                    error = None
                else:
                    status = "unhealthy"
                    error = f"HTTP {resp.status_code}"
                    if "x-error-message" in resp.headers:
                        error += f": {resp.headers['x-error-message']}"

                return {
                    **model_info,
                    "status": status,
                    "http_status": resp.status_code,
                    "response_time_ms": elapsed_ms,
                    "error": error,
                }
            except requests.exceptions.Timeout:
                return {
                    **model_info,
                    "status": "timeout",
                    "http_status": None,
                    "response_time_ms": int((time.time() - start) * 1000),
                    "error": "Request timed out",
                }
            except Exception as e:
                return {
                    **model_info,
                    "status": "error",
                    "http_status": None,
                    "response_time_ms": int((time.time() - start) * 1000),
                    "error": str(e),
                }

        # Run checks concurrently
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(check_single_url, m): m for m in models_to_check}
            for future in as_completed(futures):
                results.append(future.result())

        # Calculate summary
        healthy = len([r for r in results if r["status"] == "healthy"])
        unhealthy = len([r for r in results if r["status"] == "unhealthy"])
        timeout = len([r for r in results if r["status"] == "timeout"])
        errors = len([r for r in results if r["status"] == "error"])

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "summary": {
                    "total": len(results),
                    "healthy": healthy,
                    "unhealthy": unhealthy,
                    "timeout": timeout,
                    "error": errors,
                },
                "results": sorted(results, key=lambda x: (x["status"] != "healthy", x["type"], x["id"])),
            },
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Health check failed: {str(e)}", code="health_check_error"),
        )


def _scoped_user_or_none(authorization: str = "") -> Optional[Dict[str, Any]]:
    """
    Resolve the authenticated user for conversation scoping.
    - Bearer token present -> return that user.
    - No token + single user -> return default user (backward compat).
    - No token + multiple users -> raise 401.
    """
    from .users import ensure_users_tables, _validate_token, get_or_create_default_user, count_users
    ensure_users_tables()
    # Extract token from Authorization header (same logic as get_current_user)
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    user = _validate_token(token) if token else None
    if user:
        return user
    if count_users() > 1:
        raise HTTPException(status_code=401, detail="Authentication required")
    return get_or_create_default_user()


@app.get("/conversations")
async def conversations(
    limit: int = Query(50, ge=1, le=200),
    project_id: Optional[str] = Query(None),
    authorization: str = Header(default=""),
) -> JSONResponse:
    """List saved conversations, scoped per user in multi-user mode."""
    try:
        user = _scoped_user_or_none(authorization=authorization)
        uid = user["id"] if user else None
        items = list_conversations(limit=limit, project_id=project_id, user_id=uid)
        return JSONResponse(status_code=200, content={"ok": True, "conversations": items})
    except HTTPException as he:
        return JSONResponse(status_code=he.status_code, content={"ok": False, "error": he.detail})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to list conversations: {e}", code="conversations_error"))


@app.get("/conversations/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: str,
    limit: int = Query(200, ge=1, le=1000),
    authorization: str = Header(default=""),
) -> JSONResponse:
    """Load full message list for a conversation (scoped per user)."""
    try:
        user = _scoped_user_or_none(authorization=authorization)
        uid = user["id"] if user else None
        msgs = get_messages(conversation_id, limit=limit, user_id=uid)
        return JSONResponse(status_code=200, content={"ok": True, "conversation_id": conversation_id, "messages": msgs})
    except HTTPException as he:
        return JSONResponse(status_code=he.status_code, content={"ok": False, "error": he.detail})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to load conversation: {e}", code="conversation_load_error"))


@app.delete("/conversations/{conversation_id}")
async def delete_conversation_endpoint(
    conversation_id: str,
    authorization: str = Header(default=""),
) -> JSONResponse:
    """Delete a conversation (scoped per user)."""
    try:
        user = _scoped_user_or_none(authorization=authorization)
        uid = user["id"] if user else None
        deleted_count = delete_conversation(conversation_id, user_id=uid)
        clear_conversation_memory(conversation_id)
        return JSONResponse(status_code=200, content={"ok": True, "deleted": deleted_count > 0, "deleted_messages": deleted_count, "conversation_id": conversation_id})
    except HTTPException as he:
        return JSONResponse(status_code=he.status_code, content={"ok": False, "error": he.detail})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete conversation: {e}", code="delete_conversation_error"))


@app.delete("/media/image")
async def delete_image(request: Request) -> JSONResponse:
    """Delete an image URL from all messages in the database."""
    try:
        body = await request.json()
        image_url = body.get("image_url")

        if not image_url:
            return JSONResponse(status_code=400, content=_safe_err("image_url is required", code="missing_image_url"))

        updated_count = delete_image_url(image_url)
        return JSONResponse(status_code=200, content={"ok": True, "deleted": updated_count > 0, "updated_messages": updated_count})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete image: {e}", code="delete_image_error"))


@app.get("/conversations/{conversation_id}/search")
async def search_conversation(
    conversation_id: str,
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100)
) -> JSONResponse:
    """Search within a specific conversation."""
    try:
        results = search.search_conversation_history(
            query=q,
            conversation_id=conversation_id,
            limit=limit
        )
        return JSONResponse(status_code=200, content={
            "ok": True,
            "conversation_id": conversation_id,
            "query": q,
            "results": results,
            "count": len(results)
        })
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Search failed: {e}"))


# ----------------------------
# Persona avatar auto-commit helpers
# ----------------------------


def _resolve_selected_image_url(persona_appearance: Dict[str, Any]) -> Optional[str]:
    """
    Resolve the selected avatar image URL from persona_appearance.

    The wizard stores a selection reference (set_id + image_id) and the
    generated image URLs live in two places:
      - sets[].images[]      (base avatar generation sets)
      - outfits[].images[]   (outfit-specific images)

    Walk both collections to find the matching URL so we can download it
    for durable storage.
    """
    if not isinstance(persona_appearance, dict):
        return None

    selected = persona_appearance.get("selected") or {}
    target_set_id = selected.get("set_id")
    target_image_id = selected.get("image_id")
    if not target_set_id or not target_image_id:
        return None

    # Search both sets and outfits — they share the same image schema
    collections = list(persona_appearance.get("sets") or []) + \
                  list(persona_appearance.get("outfits") or [])

    for s in collections:
        # sets use "set_id", outfits use "id" as their identifier
        entry_id = s.get("set_id") or s.get("id")
        if entry_id != target_set_id:
            continue
        for img in (s.get("images") or []):
            if img.get("id") == target_image_id:
                url = img.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
    return None


async def _download_comfy_image(url: str, upload_root: Path) -> str:
    """
    Download a ComfyUI image into *upload_root*.

    Accepts two URL formats:
      - Absolute: ``http://host:port/view?filename=X.png``
      - Proxy-relative: ``/comfy/view/X.png`` (Avatar Studio stores these)

    Returns the saved filename (basename only).

    Security:
      - For absolute URLs: only allows the configured COMFY_BASE_URL host.
      - For proxy-relative URLs: converts to a direct ComfyUI /view request.
      - Prevents path-traversal in the filename.
    """
    # ── Handle /comfy/view/<filename> proxy URLs ──────────────────────
    # Avatar Studio stores image URLs as "/comfy/view/<filename>" which
    # are served by the backend's own proxy endpoint.  Convert these to
    # direct ComfyUI /view?filename=<filename> requests.
    if url.startswith("/comfy/view/"):
        filename = os.path.basename(url[len("/comfy/view/"):].split("?")[0])
        if filename in ("", ".", ".."):
            raise ValueError("Invalid filename from proxy URL")
        url = f"{COMFY_BASE_URL}/view?filename={filename}&type=output"

    parsed = urlparse(url)
    comfy_parsed = urlparse(COMFY_BASE_URL)

    # Strict host allowlist — only the configured ComfyUI instance
    if parsed.hostname != comfy_parsed.hostname:
        raise ValueError(
            f"Refusing to download from non-ComfyUI host: {parsed.hostname}"
        )

    # Only the /view endpoint serves generated images
    if not parsed.path.rstrip("/").endswith("/view"):
        raise ValueError(
            f"Refusing to download from non-/view path: {parsed.path}"
        )

    qs = parse_qs(parsed.query)
    filename = (qs.get("filename") or [None])[0]
    if not filename:
        raise ValueError("ComfyUI /view URL missing 'filename' parameter")

    # Path-traversal prevention — keep only the basename
    filename = os.path.basename(filename)
    if filename in ("", ".", ".."):
        raise ValueError("Invalid filename from ComfyUI URL")

    dest = upload_root / filename

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)

    return filename


# ----------------------------
# Projects API
# ----------------------------

@app.post("/projects", dependencies=[Depends(require_api_key)])
async def create_project(data: ProjectCreateIn) -> JSONResponse:
    """Create a new project context."""
    try:
        # Convert pydantic model to dict for storage
        project_dict = data.dict()
        result = projects.create_new_project(project_dict)

        # --------------------------------------------------------------
        # Auto-commit persona avatar into project-owned durable storage.
        #
        # The PersonaWizard stores image URLs from ComfyUI and a
        # selection reference, but never commits the binary file into
        # the project directory.  Without this step the export ZIP
        # has no assets/ folder because there are no local files.
        #
        # Non-fatal: if the commit fails (e.g. ComfyUI is unreachable,
        # temp file was cleaned) the project is still created normally.
        # The user can re-commit later via the avatar/commit endpoint.
        # --------------------------------------------------------------
        if result.get("project_type") == "persona":
            try:
                appearance = dict(result.get("persona_appearance") or {})
                project_root = UPLOAD_PATH / "projects" / result["id"]
                dirty = False

                # Skip if avatar already committed (idempotency guard)
                if not appearance.get("selected_filename"):
                    selected_url = _resolve_selected_image_url(appearance)

                    if selected_url:
                        # Download the ComfyUI image into UPLOAD_PATH
                        source_filename = await _download_comfy_image(
                            selected_url, UPLOAD_PATH,
                        )

                        # Commit: copy into project dir + generate thumbnail
                        commit_result = commit_persona_avatar(
                            UPLOAD_PATH, project_root, source_filename,
                        )

                        # Persist the committed paths on the project
                        appearance["selected_filename"] = commit_result.selected_filename
                        appearance["selected_thumb_filename"] = commit_result.thumb_filename
                        dirty = True

                # ----- Commit ALL remaining /comfy/view/ images -----
                # Walk sets[] and outfits[] and download/commit every
                # /comfy/view/ image so they survive ComfyUI cleanup and
                # are included in .hpersona exports.
                for s in list(appearance.get("sets") or []):
                    for img in (s.get("images") or []):
                        url = img.get("url", "")
                        if not url or not url.startswith("/comfy/view/"):
                            continue
                        try:
                            fname = await _download_comfy_image(url, UPLOAD_PATH)
                            rel = commit_persona_image(
                                UPLOAD_PATH, project_root, fname, prefix="avatar",
                            )
                            img["url"] = f"/files/{rel}"
                            dirty = True
                        except Exception as img_err:
                            print(f"[PERSONA] Commit set image skipped ({url}): {img_err}")

                for outfit in list(appearance.get("outfits") or []):
                    for img in (outfit.get("images") or []):
                        url = img.get("url", "")
                        if not url or not url.startswith("/comfy/view/"):
                            continue
                        try:
                            fname = await _download_comfy_image(url, UPLOAD_PATH)
                            rel = commit_persona_image(
                                UPLOAD_PATH, project_root, fname, prefix="outfit",
                            )
                            img["url"] = f"/files/{rel}"
                            dirty = True
                        except Exception as img_err:
                            print(f"[PERSONA] Commit outfit image skipped ({url}): {img_err}")

                if dirty:
                    result = projects.update_project(
                        result["id"], {"persona_appearance": appearance},
                    )
            except Exception as commit_err:
                # Non-fatal — project creation succeeded, avatar commit
                # can be retried later via POST /projects/{id}/persona/avatar/commit
                print(f"[PERSONA] Auto-commit avatar skipped: {commit_err}")

        return JSONResponse(status_code=201, content={"ok": True, "project": result})
    except Exception as e:
        print(f"ERROR creating project: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to create project: {e}"))

@app.get("/projects", dependencies=[Depends(require_api_key)])
async def list_projects() -> JSONResponse:
    """List all available projects."""
    try:
        result = projects.list_all_projects()
        return JSONResponse(status_code=200, content={"ok": True, "projects": result})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to list projects: {e}"))

@app.get("/projects/examples")
async def get_example_projects() -> JSONResponse:
    """Get list of example project templates."""
    try:
        examples = projects.get_example_projects()
        return JSONResponse(status_code=200, content={"ok": True, "examples": examples})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to get examples: {e}"))

@app.post("/projects/from-example/{example_id}", dependencies=[Depends(require_api_key)])
async def create_from_example(example_id: str) -> JSONResponse:
    """Create a new project from an example template."""
    try:
        result = projects.create_project_from_example(example_id)
        if result:
            return JSONResponse(status_code=201, content={"ok": True, "project": result})
        else:
            return JSONResponse(status_code=404, content=_safe_err("Example not found", code="not_found"))
    except Exception as e:
        print(f"ERROR creating project from example: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to create from example: {e}"))

@app.get("/projects/{project_id}")
async def get_project(project_id: str) -> JSONResponse:
    """Get a specific project by ID."""
    try:
        result = projects.get_project_by_id(project_id)
        if not result:
            # Check if it's an example project
            examples = projects.get_example_projects()
            for example in examples:
                if example["id"] == project_id:
                    result = example
                    break

        if not result:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))

        # Add document count if RAG is enabled
        if projects.RAG_ENABLED:
            try:
                doc_count = projects.get_project_document_count(project_id)
                result = {**result, "document_count": doc_count}
            except Exception as e:
                print(f"Error getting document count: {e}")
                result = {**result, "document_count": 0}
        else:
            result = {**result, "document_count": 0}

        # Companion-grade: include session info for persona projects
        if result.get("project_type") == "persona":
            try:
                all_sessions = persona_sessions_mod.list_sessions(project_id, limit=20)
                active_session = persona_sessions_mod.resolve_session(project_id)
                mem_count = persona_ltm_mod.memory_count(project_id)
                result["sessions"] = all_sessions
                result["active_session"] = active_session
                result["memory_count"] = mem_count
            except Exception as e:
                print(f"[COMPANION] Warning: Could not load session info: {e}")

        return JSONResponse(status_code=200, content={"ok": True, "project": result})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to get project: {e}"))

@app.post("/projects/{project_id}/upload", dependencies=[Depends(require_api_key)])
async def upload_to_project(project_id: str, file: UploadFile = File(...)) -> JSONResponse:
    """Upload a file to a project's knowledge base."""
    import time
    try:
        # First, save the file using existing upload logic
        filename = file.filename or "upload.txt"
        ext = os.path.splitext(filename)[1].lower()[:10]

        # Supported file types: documents + images (T4 multimodal knowledge)
        _SUPPORTED_DOC_EXTS = {".pdf", ".txt", ".md"}
        _SUPPORTED_IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        if ext not in _SUPPORTED_DOC_EXTS and ext not in _SUPPORTED_IMG_EXTS:
            return JSONResponse(
                status_code=400,
                content=_safe_err(
                    "Supported file types: PDF, TXT, MD, PNG, JPG, JPEG, WEBP, GIF, BMP",
                    code="invalid_file_type",
                )
            )

        max_bytes = int(MAX_UPLOAD_MB) * 1024 * 1024
        name = f"{uuidlib.uuid4().hex}{ext}"
        path = UPLOAD_PATH / name

        written = 0
        chunk_size = 1024 * 1024  # 1MB

        try:
            with path.open("wb") as f:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        path.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large. Max {MAX_UPLOAD_MB}MB.",
                        )
                    f.write(chunk)
        finally:
            await file.close()

        # Process the file and add to vector database
        try:
            # T4 Multimodal: route images through vision-based indexing
            if ext in _SUPPORTED_IMG_EXTS:
                from .vectordb_images import index_image_to_knowledge
                img_result = await index_image_to_knowledge(
                    project_id=project_id,
                    image_path=path,
                    original_filename=filename,
                )
                chunks_added = img_result.get("chunks_added", 0)
                source_type = "image"
            else:
                from .vectordb import process_and_add_file
                chunks_added = process_and_add_file(project_id, path)
                source_type = "document"

            # Update project metadata with file info
            project = projects.get_project_by_id(project_id)
            if project:
                files_list = project.get("files", [])
                files_list.append({
                    "name": filename,
                    "size": f"{written / 1024 / 1024:.2f} MB",
                    "path": str(path),
                    "chunks": chunks_added,
                    "source_type": source_type,
                })

                # Update project
                db = projects._load_projects_db()
                db[project_id]["files"] = files_list
                db[project_id]["updated_at"] = time.time()
                projects._save_projects_db(db)

            return JSONResponse(status_code=201, content={
                "ok": True,
                "filename": filename,
                "size_bytes": written,
                "chunks_added": chunks_added,
                "source_type": source_type,
                "message": f"File processed and {chunks_added} chunks added to knowledge base"
            })

        except Exception as e:
            # Clean up file if processing failed
            path.unlink(missing_ok=True)
            raise e

    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to upload file: {e}"))

@app.delete("/projects/{project_id}", dependencies=[Depends(require_api_key)])
async def delete_project(project_id: str) -> JSONResponse:
    """Delete a project and its knowledge base."""
    try:
        result = projects.delete_project(project_id)
        if result:
            return JSONResponse(status_code=200, content={"ok": True, "message": "Project deleted successfully"})
        else:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete project: {e}"))

@app.put("/projects/{project_id}", dependencies=[Depends(require_api_key)])
async def update_project(project_id: str, request: Request) -> JSONResponse:
    """Update project details."""
    try:
        data = await request.json()
        result = projects.update_project(project_id, data)
        if result:
            return JSONResponse(status_code=200, content={"ok": True, "project": result})
        else:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to update project: {e}"))

@app.get("/projects/{project_id}/documents", dependencies=[Depends(require_api_key)])
async def list_project_documents(project_id: str) -> JSONResponse:
    """List documents in a project's knowledge base."""
    try:
        project = projects.get_project_by_id(project_id)
        if not project:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))

        documents = project.get("files", [])
        return JSONResponse(status_code=200, content={"ok": True, "documents": documents})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to list documents: {e}"))

@app.delete("/projects/{project_id}/documents/{document_name}", dependencies=[Depends(require_api_key)])
async def delete_project_document(project_id: str, document_name: str) -> JSONResponse:
    """Delete a document from a project's knowledge base."""
    try:
        project = projects.get_project_by_id(project_id)
        if not project:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))

        # Remove from files list
        files_list = project.get("files", [])
        updated_files = [f for f in files_list if f.get("name") != document_name]

        if len(updated_files) == len(files_list):
            return JSONResponse(status_code=404, content=_safe_err("Document not found", code="not_found"))

        # Delete physical file if exists
        for f in files_list:
            if f.get("name") == document_name and f.get("path"):
                try:
                    Path(f["path"]).unlink(missing_ok=True)
                except Exception as e:
                    print(f"Error deleting file: {e}")

        # Update project
        db = projects._load_projects_db()
        db[project_id]["files"] = updated_files
        db[project_id]["updated_at"] = time.time()
        projects._save_projects_db(db)

        # Note: We can't selectively delete chunks from ChromaDB easily
        # So we inform the user that full re-indexing would be needed
        return JSONResponse(status_code=200, content={
            "ok": True,
            "message": "Document removed from project. Note: For full knowledge base update, delete and re-upload all documents."
        })
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete document: {e}"))


# ----------------------------
# Personality Agents API
# ----------------------------

from .personalities import registry as _personality_registry


@app.get("/api/personalities")
async def list_personalities(category: Optional[str] = None):
    """
    List all available personality agents.

    Optional query param:
      ?category=general|kids|wellness|adult

    Returns compact JSON array with id, label, category, and safety info.
    """
    if category:
        agents = _personality_registry.by_category(category)
    else:
        agents = _personality_registry.all()

    return [
        {
            "id": a.id,
            "label": a.label,
            "category": a.category,
            "psychology_approach": a.psychology_approach,
            "voice_style": a.voice_style.model_dump(),
            "response_style": a.response_style.model_dump(),
            "safety": a.safety.model_dump(),
            "dynamics": {
                "initiative": a.dynamics.initiative,
                "depth": a.dynamics.depth,
                "emotional_base": a.dynamics.emotional_base,
            },
            "allowed_tools": a.allowed_tools,
        }
        for a in agents
    ]


@app.get("/api/personalities/{personality_id}")
async def get_personality(personality_id: str):
    """
    Get full details for a single personality agent.
    """
    agent = _personality_registry.get(personality_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Personality '{personality_id}' not found")
    return agent.model_dump()


# ----------------------------
# Persona Sessions & Long-Term Memory (additive — companion-grade)
# ----------------------------

from . import sessions as persona_sessions_mod
from . import ltm as persona_ltm_mod
from . import jobs as persona_jobs_mod


class SessionCreateIn(BaseModel):
    project_id: str = Field(..., description="Persona project ID")
    mode: str = Field("text", description="Session mode: 'voice' or 'text'")
    title: Optional[str] = Field(None, description="Optional session title")


@app.get("/persona/sessions", dependencies=[Depends(require_api_key)])
async def list_persona_sessions(
    project_id: str = Query(..., description="Persona project ID"),
    limit: int = Query(50, ge=1, le=200),
    include_ended: bool = Query(True),
) -> JSONResponse:
    """List all sessions for a persona project."""
    try:
        items = persona_sessions_mod.list_sessions(
            project_id, limit=limit, include_ended=include_ended
        )
        return JSONResponse(status_code=200, content={"ok": True, "sessions": items})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to list sessions: {e}", code="sessions_error"),
        )


@app.post("/persona/sessions", dependencies=[Depends(require_api_key)])
async def create_persona_session(data: SessionCreateIn) -> JSONResponse:
    """Start a new session for a persona project."""
    try:
        session = persona_sessions_mod.create_session(
            project_id=data.project_id,
            mode=data.mode,
            title=data.title,
        )
        return JSONResponse(status_code=201, content={"ok": True, "session": session})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to create session: {e}", code="session_create_error"),
        )


@app.post("/persona/sessions/resolve", dependencies=[Depends(require_api_key)])
async def resolve_persona_session(request: Request) -> JSONResponse:
    """
    Resolve the best session to resume for a persona project.
    Uses the bulletproof resume algorithm.
    Returns existing session or creates a new one.
    """
    try:
        body = await request.json()
        project_id = body.get("project_id")
        mode = body.get("mode", "text")
        if not project_id:
            return JSONResponse(
                status_code=400,
                content=_safe_err("project_id is required", code="missing_project_id"),
            )
        session = persona_sessions_mod.get_or_create_session(project_id, mode=mode)
        return JSONResponse(status_code=200, content={"ok": True, "session": session})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to resolve session: {e}", code="session_resolve_error"),
        )


@app.post("/persona/sessions/{session_id}/end", dependencies=[Depends(require_api_key)])
async def end_persona_session(session_id: str) -> JSONResponse:
    """End a session (marks ended_at, schedules summary + memory extraction jobs)."""
    try:
        ended = persona_sessions_mod.end_session(session_id)
        if ended:
            # Get session to schedule jobs
            session = persona_sessions_mod.get_session(session_id)
            if session:
                persona_jobs_mod.schedule_session_jobs(session["project_id"], session_id)
        return JSONResponse(
            status_code=200,
            content={"ok": True, "ended": ended, "session_id": session_id},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to end session: {e}", code="session_end_error"),
        )


@app.get("/persona/sessions/{session_id}", dependencies=[Depends(require_api_key)])
async def get_persona_session(session_id: str) -> JSONResponse:
    """Get details of a specific session."""
    try:
        session = persona_sessions_mod.get_session(session_id)
        if not session:
            return JSONResponse(
                status_code=404,
                content=_safe_err("Session not found", code="session_not_found"),
            )
        return JSONResponse(status_code=200, content={"ok": True, "session": session})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to get session: {e}", code="session_get_error"),
        )


# --- Long-Term Memory ---

@app.get("/persona/memory", dependencies=[Depends(require_api_key)])
async def get_persona_memory(
    project_id: str = Query(..., description="Persona project ID"),
    category: Optional[str] = Query(None, description="Filter by category"),
    authorization: str = Header(default=""),
) -> JSONResponse:
    """Get all memories for a persona project ('What I know about you')."""
    try:
        _uid = None
        try:
            user = _scoped_user_or_none(authorization=authorization)
            _uid = user["id"] if user else None
        except Exception:
            pass
        memories = persona_ltm_mod.get_memories(project_id, category=category, user_id=_uid)
        count = persona_ltm_mod.memory_count(project_id, user_id=_uid)
        return JSONResponse(
            status_code=200,
            content={"ok": True, "memories": memories, "count": count},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to get memories: {e}", code="memory_error"),
        )


@app.post("/persona/memory", dependencies=[Depends(require_api_key)])
async def upsert_persona_memory(request: Request, authorization: str = Header(default="")) -> JSONResponse:
    """Add or update a memory entry."""
    try:
        body = await request.json()
        _uid = None
        try:
            user = _scoped_user_or_none(authorization=authorization)
            _uid = user["id"] if user else None
        except Exception:
            pass
        result = persona_ltm_mod.upsert_memory(
            project_id=body["project_id"],
            category=body.get("category", "fact"),
            key=body["key"],
            value=body["value"],
            confidence=body.get("confidence", 1.0),
            source_type=body.get("source_type", "user_statement"),
            user_id=_uid,
        )
        return JSONResponse(status_code=200, content={"ok": True, "memory": result})
    except KeyError as e:
        return JSONResponse(
            status_code=400,
            content=_safe_err(f"Missing required field: {e}", code="missing_field"),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to save memory: {e}", code="memory_save_error"),
        )


@app.delete("/persona/memory", dependencies=[Depends(require_api_key)])
async def delete_persona_memory(request: Request, authorization: str = Header(default="")) -> JSONResponse:
    """Delete a specific memory entry or forget all."""
    try:
        body = await request.json()
        project_id = body.get("project_id")
        if not project_id:
            return JSONResponse(
                status_code=400,
                content=_safe_err("project_id is required", code="missing_project_id"),
            )

        _uid = None
        try:
            user = _scoped_user_or_none(authorization=authorization)
            _uid = user["id"] if user else None
        except Exception:
            pass

        # If key is provided, delete specific entry; otherwise forget all
        key = body.get("key")
        category = body.get("category")
        if key and category:
            deleted = persona_ltm_mod.delete_memory(project_id, category, key, user_id=_uid)
            return JSONResponse(
                status_code=200,
                content={"ok": True, "deleted": deleted},
            )
        else:
            count = persona_ltm_mod.forget_all(project_id, user_id=_uid)
            return JSONResponse(
                status_code=200,
                content={"ok": True, "forgotten": count, "message": f"Forgot {count} memories"},
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to delete memory: {e}", code="memory_delete_error"),
        )


# --- Memory Maintenance (V1 hardening) ---

@app.post("/persona/memory/maintenance", dependencies=[Depends(require_api_key)])
async def run_memory_maintenance(request: Request) -> JSONResponse:
    """
    Run maintenance routines: TTL expiry, per-category cap, total cap.
    POST body: { "project_id": "..." }
    """
    try:
        from .ltm_v1_maintenance import run_maintenance, get_memory_stats
        body = await request.json()
        project_id = body.get("project_id")
        if not project_id:
            return JSONResponse(
                status_code=400,
                content=_safe_err("project_id is required", code="missing_project_id"),
            )
        result = run_maintenance(project_id)
        stats = get_memory_stats(project_id)
        return JSONResponse(
            status_code=200,
            content={"ok": True, "maintenance": result, "stats": stats},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Memory maintenance failed: {e}", code="maintenance_error"),
        )


@app.get("/persona/memory/stats", dependencies=[Depends(require_api_key)])
async def get_persona_memory_stats(
    project_id: str = Query(..., description="Persona project ID"),
) -> JSONResponse:
    """Get memory usage statistics for a persona."""
    try:
        from .ltm_v1_maintenance import get_memory_stats
        stats = get_memory_stats(project_id)
        return JSONResponse(status_code=200, content={"ok": True, "stats": stats})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Failed to get memory stats: {e}", code="stats_error"),
        )


# ----------------------------
# Chat & Upload
# ----------------------------

@app.post("/chat", dependencies=[Depends(require_api_key)])
async def chat(inp: ChatIn, authorization: str = Header(default="")) -> JSONResponse:
    """
    Unified chat endpoint with mode-aware routing.
    Stable response schema:
      { conversation_id, text, media }
    """
    # Enterprise: bind conversation to authenticated user (prevents cross-user leakage)
    user = None
    try:
        from .storage import ensure_conversation_owner
        user = _scoped_user_or_none(authorization=authorization)
        if user and inp.conversation_id:
            ensure_conversation_owner(inp.conversation_id, user["id"])
    except HTTPException:
        pass  # Preserve legacy behavior in single-user mode
    except Exception as e:
        print(f"[CHAT] Warning: failed to bind conversation owner: {e}")

    # Debug: Log incoming parameters
    print(f"[CHAT ENDPOINT] imgModel received from frontend: '{inp.imgModel}' (type: {type(inp.imgModel).__name__ if inp.imgModel is not None else 'None'})")
    print(f"[CHAT ENDPOINT] personalityId: {inp.personalityId!r}, ollama_model: {inp.ollama_model!r}")

    # Build payload for mode-aware handler
    payload = {
        "message": inp.message,
        "conversation_id": inp.conversation_id,
        "project_id": inp.project_id,
        "fun_mode": inp.fun_mode,
        "provider": inp.provider,
        "ollama_base_url": inp.ollama_base_url,
        "ollama_model": inp.ollama_model,
        "provider_base_url": inp.provider_base_url,
        "provider_model": inp.provider_model,
        "llm_base_url": inp.llm_base_url,
        "llm_model": inp.llm_model,
        "textTemperature": inp.textTemperature,
        "textMaxTokens": inp.textMaxTokens,
        "imgWidth": inp.imgWidth,
        "imgHeight": inp.imgHeight,
        "imgResolutionOverride": inp.imgResolutionOverride,
        "imgAspectRatio": inp.imgAspectRatio,
        "imgSteps": inp.imgSteps,
        "imgCfg": inp.imgCfg,
        "imgSeed": inp.imgSeed,
        "imgModel": inp.imgModel,
        "imgBatchSize": inp.imgBatchSize,
        "imgPreset": inp.imgPreset,
        "vidSeconds": inp.vidSeconds,
        "vidFps": inp.vidFps,
        "vidMotion": inp.vidMotion,
        "vidModel": inp.vidModel,
        "vidPreset": inp.vidPreset,
        "vidAspectRatio": inp.vidAspectRatio,
        "vidSteps": inp.vidSteps,
        "vidCfg": inp.vidCfg,
        "vidDenoise": inp.vidDenoise,
        "vidSeed": inp.vidSeed,
        "vidNegativePrompt": inp.vidNegativePrompt,
        "vidResolutionMode": inp.vidResolutionMode,
        "vidWidth": inp.vidWidth,
        "vidHeight": inp.vidHeight,
        "nsfwMode": inp.nsfwMode,
        "memoryEngine": inp.memoryEngine,
        "promptRefinement": inp.promptRefinement,
        # Reference image for img2img similar generation
        "imgReference": inp.imgReference,
        "imgRefStrength": inp.imgRefStrength,
        # Identity-preserving generation mode (persona avatar)
        "generation_mode": inp.generation_mode,
        "reference_image_url": inp.reference_image_url,
        # Voice mode personality
        "voiceSystemPrompt": inp.voiceSystemPrompt,
        # Backend personality agent
        "personalityId": inp.personalityId,
        # Smart multimodal topology: optional vision context for system prompt
        "extra_system_context": inp.extra_system_context,
        # Per-user isolation: resolved user id for memory scoping
        "user_id": user["id"] if user else None,
    }

    # ----------------------------
    # Persona photo intent (deterministic — no LLM guessing)
    # If user says "show me your photo" and a committed persona avatar exists,
    # return it immediately in media.images[] without hitting the LLM.
    # ----------------------------
    if inp.project_id and _is_photo_intent(inp.message):
        proj = projects.get_project_by_id(inp.project_id)
        if proj and proj.get("project_type") == "persona":
            appearance = proj.get("persona_appearance") or {}
            sel = appearance.get("selected_filename")
            if isinstance(sel, str) and sel:
                base = _base_url_from_request(
                    # ChatIn doesn't carry a Request; use PUBLIC_BASE_URL fallback
                    type("_R", (), {"base_url": PUBLIC_BASE_URL or "http://localhost:8000/"})()
                )
                cid = inp.conversation_id or str(uuidlib.uuid4())
                return JSONResponse(
                    status_code=200,
                    content={
                        "conversation_id": cid,
                        "text": "Here's my current photo.",
                        "media": {"images": [f"{base}/files/{sel}"]},
                    },
                )

    # ----------------------------
    # Game Mode: Infinite Variations
    # Works independently of promptRefinement - generates variations of user prompt
    # If promptRefinement is also enabled, the variation will be further refined
    # IMPORTANT: Uses timeout to prevent hanging if Ollama is slow/unresponsive
    # ----------------------------
    if (inp.mode == "imagine") and bool(inp.gameMode):
        # Preserve original message for fallback
        original_message = inp.message

        try:
            options = {
                # Use explicit None check to allow 0.0 as a valid value (Preservation Mode)
                "strength": float(inp.gameStrength) if inp.gameStrength is not None else 0.65,
                # Only pass spicy_strength if NSFW mode is enabled (also use None check for 0.0)
                "spicy_strength": float(inp.gameSpicyStrength) if inp.gameSpicyStrength is not None and inp.nsfwMode else 0.0,
                "locks": inp.gameLocks or {},
                "world_bible": inp.gameWorldBible or "",
            }

            # Resolve LLM settings for Game Mode variation generation
            # Default (backward-compatible): ALWAYS use fast local model llama3:8b unless user explicitly opts in.
            use_global_for_variations = bool(getattr(inp, "gameUseGlobalLLMForVariations", False))

            if use_global_for_variations:
                # Fallback chain (global): explicit ollama fields -> provider fields -> llm fields -> config defaults
                game_ollama_url = (
                    inp.ollama_base_url
                    or inp.provider_base_url
                    or inp.llm_base_url
                    or OLLAMA_BASE_URL
                )
                # For model, only use ollama_model or llm_model (NOT provider_model which is image checkpoint)
                game_ollama_model = (
                    inp.ollama_model
                    or inp.llm_model
                    or None  # Let game_mode.py use OLLAMA_MODEL from config
                )
            else:
                # Fast path: keep variations stable + snappy, regardless of global chat model selection
                game_ollama_url = inp.ollama_base_url or OLLAMA_BASE_URL
                game_ollama_model = "llama3:8b"

            print(f"[GAME MODE] use_global_llm_for_variations={use_global_for_variations} | ollama_base_url={game_ollama_url}, ollama_model={game_ollama_model}")

            # Time-box the LLM call to prevent hanging (15s timeout)
            # If Ollama is slow/unavailable, we fall back to original prompt
            vr = await asyncio.wait_for(
                next_variation(
                    base_prompt=inp.message,
                    session_id=inp.gameSessionId,
                    options=options,
                    ollama_base_url=game_ollama_url,
                    ollama_model=game_ollama_model,
                ),
                timeout=15.0,
            )

            print(f"[GAME MODE] variation_prompt={vr.variation_prompt[:100] if vr.variation_prompt else 'None'}...")

            # Replace the message with the variation prompt
            payload["message"] = vr.variation_prompt

            # Attach game info into payload so we can include it in response media
            payload["_game"] = {
                "enabled": True,
                "session_id": vr.session_id,
                "counter": vr.counter,
                "base_prompt": vr.base_prompt,
                "variation_prompt": vr.variation_prompt,
                "tags": vr.tags,
            }

        except asyncio.TimeoutError:
            # LLM took too long - fall back to original prompt so image still generates
            print(f"[GAME MODE] TIMEOUT: LLM took too long, using original prompt")
            payload["message"] = original_message
            payload["_game"] = {
                "enabled": True,
                "error": "Game Mode LLM timeout - using original prompt",
            }

        except Exception as e:
            # Any other error - fall back to original prompt so image still generates
            print(f"[GAME MODE] ERROR: {e}, using original prompt")
            payload["message"] = original_message
            payload["_game"] = {
                "enabled": True,
                "error": str(e),
            }

    # Route through mode-aware handler
    out = await handle_request(mode=inp.mode, payload=payload)

    # T4 additive: feed user text into Memory V2 for cross-topology learning.
    # Non-blocking: failures are silently ignored. Only for chat/voice modes
    # with a project_id (companion/project context).
    # CRITICAL: only run when memory engine is actually set to "v2" / "adaptive"
    _mem_mode = (inp.memoryEngine or "").lower().strip()
    if _mem_mode in ("adaptive", ""):
        _mem_mode = "v2"  # default to v2 when unset
    elif _mem_mode == "basic":
        _mem_mode = "v1"
    if inp.project_id and inp.message and inp.mode in ("chat", "voice") and _mem_mode == "v2":
        try:
            from .memory_v2 import get_memory_v2, ensure_v2_columns
            ensure_v2_columns()
            _uid = user["id"] if user else None
            get_memory_v2().ingest_user_text(inp.project_id, inp.message, user_id=_uid)
        except Exception:
            pass

    # Merge game metadata into media (if present)
    game_meta = payload.get("_game")
    if isinstance(game_meta, dict):
        if out.get("media") is None:
            out["media"] = {}
        if isinstance(out.get("media"), dict):
            out["media"]["game"] = game_meta

    if not isinstance(out, dict):
        out = {}

    cid = out.get("conversation_id") or inp.conversation_id or str(uuidlib.uuid4())

    text = out.get("text")
    if not isinstance(text, str) or not text.strip():
        text = "…"

    media = out.get("media", None)
    if media is not None and not isinstance(media, dict):
        media = None

    return JSONResponse(
        status_code=200,
        content={"conversation_id": cid, "text": text, "media": media},
    )


@app.post("/upload", dependencies=[Depends(require_api_key)])
async def upload(request: Request, file: UploadFile = File(...), authorization: str = Header(default="")) -> JSONResponse:
    """
    Stream uploads to disk (avoid reading entire file in memory).
    Enterprise: registers file as a user-owned asset when auth is available.
    """
    filename = file.filename or "upload.png"
    ext = os.path.splitext(filename)[1].lower()[:10]
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

    max_bytes = int(MAX_UPLOAD_MB) * 1024 * 1024

    # Resolve user for per-user storage
    _uid = None
    try:
        user = _scoped_user_or_none(authorization=authorization)
        _uid = user["id"] if user else None
    except Exception:
        pass

    if _uid:
        # Secure path: store under per-user directory and register asset
        from .files import _ensure_user_dir, _upload_root, insert_asset
        import mimetypes as _mt
        folder = _ensure_user_dir(_uid, "upload")
        name = f"{uuidlib.uuid4().hex}{ext}"
        path = folder / name
    else:
        # Legacy path: flat UPLOAD_PATH
        name = f"{uuidlib.uuid4().hex}{ext}"
        path = UPLOAD_PATH / name

    written = 0
    chunk_size = 1024 * 1024  # 1MB

    try:
        with path.open("wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Max {MAX_UPLOAD_MB}MB.",
                    )
                f.write(chunk)
    finally:
        await file.close()

    base = _base_url_from_request(request)

    if _uid:
        # Register as a secure asset
        from .files import _upload_root, insert_asset
        import mimetypes as _mt
        rel_path = str(path.relative_to(_upload_root()))
        mime = _mt.guess_type(str(path))[0] or "application/octet-stream"
        asset_id = insert_asset(
            user_id=_uid,
            kind="upload",
            rel_path=rel_path,
            mime=mime,
            size_bytes=written,
            original_name=filename,
        )
        return JSONResponse(status_code=201, content={"url": f"{base}/files/{asset_id}"})
    else:
        return JSONResponse(status_code=201, content={"url": f"{base}/files/{name}"})


# ----------------------------
# Game Mode API
# ----------------------------

@app.get("/game/sessions/{session_id}/events", dependencies=[Depends(require_api_key)])
async def game_session_events(session_id: str, limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """
    Fetch variation history for a game session.
    Returns chronological list of generated variations with their tags.
    """
    try:
        events = get_session_events(session_id, limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "session_id": session_id, "events": events})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# ----------------------------
# Story Mode API (Studio)
# ----------------------------

class StoryStartIn(BaseModel):
    premise: str = Field(..., min_length=3, max_length=4000)
    title_hint: str = Field("", max_length=200)
    options: Optional[Dict[str, Any]] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


class StoryNextIn(BaseModel):
    session_id: str
    refine_image_prompt: Optional[bool] = None
    tts_enabled: Optional[bool] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


@app.post("/story/start", dependencies=[Depends(require_api_key)])
async def story_start_endpoint(inp: StoryStartIn) -> JSONResponse:
    """
    Start a story session. Returns session_id + story bible.
    """
    try:
        res = await start_story(
            inp.premise,
            title_hint=inp.title_hint,
            options=inp.options,
            ollama_base_url=inp.ollama_base_url,
            ollama_model=inp.ollama_model,
        )
        return JSONResponse(status_code=200, content=res.model_dump())
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


class StoryContinueIn(BaseModel):
    previous_session_id: str
    title_hint: str = ""
    direction_hint: str = ""
    options: Optional[Dict[str, Any]] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


@app.post("/story/continue", dependencies=[Depends(require_api_key)])
async def story_continue_endpoint(inp: StoryContinueIn) -> JSONResponse:
    """
    Continue a story as the next chapter in a saga.
    Uses the previous story's ending as the starting point.
    Returns new session_id + chapter bible.
    """
    try:
        res = await continue_story(
            inp.previous_session_id,
            title_hint=inp.title_hint,
            direction_hint=inp.direction_hint,
            options=inp.options,
            ollama_base_url=inp.ollama_base_url,
            ollama_model=inp.ollama_model,
        )
        return JSONResponse(status_code=200, content=res.model_dump())
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.post("/story/next", dependencies=[Depends(require_api_key)])
async def story_next_endpoint(inp: StoryNextIn) -> JSONResponse:
    """
    Generate next scene (narration + image prompt).
    Frontend then calls image generation with scene.image_prompt.
    """
    try:
        res = await next_scene(
            session_id=inp.session_id,
            refine_image_prompt=inp.refine_image_prompt,
            tts_enabled=inp.tts_enabled,
            ollama_base_url=inp.ollama_base_url,
            ollama_model=inp.ollama_model,
        )
        return JSONResponse(status_code=200, content=res.model_dump())
    except ValueError as e:
        error_msg = str(e)
        # Check if this is a "story complete" error
        if "Story complete" in error_msg or "scenes have been generated" in error_msg:
            return JSONResponse(
                status_code=200,
                content={"ok": True, "story_complete": True, "message": error_msg}
            )
        return JSONResponse(status_code=400, content={"ok": False, "error": error_msg})
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.get("/story/{session_id}", dependencies=[Depends(require_api_key)])
async def story_get_endpoint(session_id: str) -> JSONResponse:
    """
    Get story bible + scenes so far (for TV playback UI).
    """
    try:
        data = get_story(session_id)
        return JSONResponse(status_code=200, content=data)
    except Exception as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})


@app.get("/story/sessions/list", dependencies=[Depends(require_api_key)])
async def story_list_endpoint(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """
    List all story sessions.
    """
    try:
        sessions = list_story_sessions(limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "sessions": sessions})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.delete("/story/{session_id}", dependencies=[Depends(require_api_key)])
async def story_delete_endpoint(session_id: str) -> JSONResponse:
    """
    Delete a story session and all its scenes.
    """
    try:
        deleted = delete_story_session(session_id)
        return JSONResponse(status_code=200, content={"ok": True, "deleted": deleted})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.delete("/story/{session_id}/scene/{scene_idx}", dependencies=[Depends(require_api_key)])
async def story_delete_scene_endpoint(session_id: str, scene_idx: int) -> JSONResponse:
    """
    Delete a single scene from a story session. Remaining scenes will be re-indexed.
    """
    try:
        deleted = delete_scene(session_id, scene_idx)
        if deleted:
            return JSONResponse(status_code=200, content={"ok": True, "deleted": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Scene not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


class UpdateSceneImageIn(BaseModel):
    session_id: str
    scene_idx: int
    image_url: str


@app.post("/story/scene/image", dependencies=[Depends(require_api_key)])
async def story_update_scene_image(inp: UpdateSceneImageIn) -> JSONResponse:
    """
    Update a scene's image_url after image generation.
    This persists the image URL so it's available after page reload.
    """
    try:
        success = update_scene_image(inp.session_id, inp.scene_idx, inp.image_url)
        if success:
            return JSONResponse(status_code=200, content={"ok": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Scene not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# =============================================================================
# EDIT SESSION PROXY ROUTES
# =============================================================================
# These routes proxy requests to the edit-session sidecar service.
# This allows the frontend to use a single backend URL for all requests.
# =============================================================================

# Create a shared httpx client for edit-session proxy
_edit_session_client: Optional[httpx.AsyncClient] = None


def get_edit_session_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client for edit-session proxy."""
    global _edit_session_client
    if _edit_session_client is None:
        _edit_session_client = httpx.AsyncClient(
            base_url=EDIT_SESSION_URL,
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
    return _edit_session_client


@app.on_event("shutdown")
async def close_edit_session_client():
    """Clean up the httpx client on shutdown."""
    global _edit_session_client
    if _edit_session_client is not None:
        await _edit_session_client.aclose()
        _edit_session_client = None


async def _proxy_to_edit_session(
    request: Request,
    path: str,
    method: str = "GET",
) -> JSONResponse:
    """
    Proxy a request to the edit-session sidecar service.
    Forwards headers, query params, and body to the sidecar.
    """
    client = get_edit_session_client()

    # Build URL with query params
    url = f"/v1/edit-sessions/{path}"
    if request.query_params:
        url += f"?{request.query_params}"

    # Forward relevant headers
    headers = {}
    if "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    if "x-api-key" in request.headers:
        headers["x-api-key"] = request.headers["x-api-key"]
    if "content-type" in request.headers:
        headers["content-type"] = request.headers["content-type"]

    try:
        # Get request body for non-GET requests
        body = None
        if method in ("POST", "PUT", "PATCH"):
            body = await request.body()

        # Make the proxied request
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body,
        )

        # Return the response
        return JSONResponse(
            status_code=response.status_code,
            content=response.json() if response.content else None,
        )

    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "Edit session service unavailable",
                "detail": f"Cannot connect to edit-session service at {EDIT_SESSION_URL}",
                "code": "edit_session_unavailable",
            },
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={
                "ok": False,
                "error": "Edit session service timeout",
                "code": "edit_session_timeout",
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"Edit session proxy error: {str(e)}",
                "code": "edit_session_proxy_error",
            },
        )


@app.get("/v1/edit-sessions/{conversation_id}")
async def get_edit_session(request: Request, conversation_id: str) -> JSONResponse:
    """Get current state of an edit session (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, conversation_id, "GET")


@app.delete("/v1/edit-sessions/{conversation_id}")
async def delete_edit_session(request: Request, conversation_id: str) -> JSONResponse:
    """Delete/clear an edit session (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, conversation_id, "DELETE")


@app.post("/v1/edit-sessions/{conversation_id}/image")
async def upload_edit_image(request: Request, conversation_id: str) -> JSONResponse:
    """
    Upload an image to start/update an edit session (proxied to sidecar).
    Handles multipart form data.
    """
    client = get_edit_session_client()
    url = f"/v1/edit-sessions/{conversation_id}/image"

    # Forward headers
    headers = {}
    if "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    if "x-api-key" in request.headers:
        headers["x-api-key"] = request.headers["x-api-key"]

    try:
        # For file uploads, we need to forward the raw body with content-type
        body = await request.body()
        content_type = request.headers.get("content-type", "")

        response = await client.post(
            url,
            content=body,
            headers={**headers, "content-type": content_type},
        )

        return JSONResponse(
            status_code=response.status_code,
            content=response.json() if response.content else None,
        )

    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "Edit session service unavailable",
                "detail": f"Cannot connect to edit-session service at {EDIT_SESSION_URL}",
                "code": "edit_session_unavailable",
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"Edit session proxy error: {str(e)}",
                "code": "edit_session_proxy_error",
            },
        )


@app.post("/v1/edit-sessions/{conversation_id}/message")
async def send_edit_message(request: Request, conversation_id: str) -> JSONResponse:
    """Send an edit instruction message (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, f"{conversation_id}/message", "POST")


@app.post("/v1/edit-sessions/{conversation_id}/select")
async def select_edit_image(request: Request, conversation_id: str) -> JSONResponse:
    """Select an image from results as the new active image (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, f"{conversation_id}/select", "POST")


@app.post("/v1/edit-sessions/{conversation_id}/revert")
async def revert_edit_session(request: Request, conversation_id: str) -> JSONResponse:
    """Revert to a previous state in the edit session history (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, f"{conversation_id}/revert", "POST")


# ============================================================================
# Persona Phase 3 — Production Hardening Endpoints (additive)
# ============================================================================


@app.post("/projects/{project_id}/persona/avatar/commit", dependencies=[Depends(require_api_key)])
async def persona_commit_avatar(project_id: str, body: dict) -> JSONResponse:
    """
    Commit a selected avatar image into project-owned durable storage.

    Accepts ONE of:
      { "source_filename": "ComfyUI_00042_.png" }
          — file already in UPLOAD_PATH (legacy / direct upload)

      { "source_url": "http://comfy:8188/view?filename=..." }
          — ComfyUI URL; downloaded into UPLOAD_PATH first, then committed.
            Only URLs matching COMFY_BASE_URL host + /view path are allowed.

      { "auto": true }
          — resolve the selected image URL from persona_appearance.sets
            and commit it automatically (repair mode for existing projects).

    The image is copied into:
      projects/<project_id>/persona/appearance/avatar_<name>.<ext>
    and a 256x256 thumbnail is generated:
      projects/<project_id>/persona/appearance/thumb_avatar_<name>.webp

    Updates project.persona_appearance with the committed paths.
    """
    p = projects.get_project_by_id(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    if p.get("project_type") != "persona":
        raise HTTPException(status_code=400, detail="Not a persona project")

    source_filename = body.get("source_filename")
    source_url = body.get("source_url")
    auto_mode = body.get("auto", False)

    # ── Resolve the source file ──────────────────────────────────────────
    try:
        if auto_mode:
            # Auto-resolve: walk persona_appearance.sets to find selected URL
            appearance_data = p.get("persona_appearance") or {}
            resolved_url = _resolve_selected_image_url(appearance_data)
            if not resolved_url:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot auto-resolve: no selected image URL in persona_appearance.sets",
                )
            source_filename = await _download_comfy_image(resolved_url, UPLOAD_PATH)

        elif source_url:
            # Download from explicit ComfyUI URL into UPLOAD_PATH
            if not isinstance(source_url, str) or not source_url.strip():
                raise HTTPException(status_code=400, detail="source_url must be a non-empty string")
            source_filename = await _download_comfy_image(source_url.strip(), UPLOAD_PATH)

        elif source_filename:
            # Legacy path: file already in UPLOAD_PATH
            if not isinstance(source_filename, str) or not source_filename.strip():
                raise HTTPException(status_code=400, detail="source_filename must be a non-empty string")
            source_filename = source_filename.strip()

        else:
            raise HTTPException(
                status_code=400,
                detail="Provide one of: source_filename, source_url, or auto:true",
            )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download image: {e}")

    # ── Commit into project-owned storage ────────────────────────────────
    try:
        project_root = UPLOAD_PATH / "projects" / project_id
        result = commit_persona_avatar(UPLOAD_PATH, project_root, source_filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    appearance = dict(p.get("persona_appearance") or {})
    appearance["selected_filename"] = result.selected_filename
    appearance["selected_thumb_filename"] = result.thumb_filename

    updated = projects.update_project(project_id, {"persona_appearance": appearance})
    return JSONResponse(
        status_code=200,
        content={"ok": True, "project": updated, "selected": appearance},
    )


@app.get("/projects/{project_id}/persona/export", dependencies=[Depends(require_api_key)])
async def persona_export(project_id: str, mode: str = Query("blueprint")) -> Response:
    """
    Export a persona project as a .hpersona package (zip).

    Query params:
      mode: "blueprint" (safe — agent config + avatar) or "full" (with consent)

    Returns the .hpersona file as an attachment download.
    """
    p = projects.get_project_by_id(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")

    # ------------------------------------------------------------------
    # Just-in-time auto-commit: ensure avatar is committed before export.
    #
    # Projects created before the creation-time auto-commit fix (or where
    # that step failed) only have ComfyUI URLs in persona_appearance but
    # no local files.  Attempt to download + commit now so the exported
    # .hpersona actually contains images in assets/.
    #
    # Non-fatal: if ComfyUI is unreachable or the URL is stale, the
    # export proceeds without images (same as the old behaviour).
    # ------------------------------------------------------------------
    if p.get("project_type") == "persona":
        appearance = dict(p.get("persona_appearance") or {})
        project_root = UPLOAD_PATH / "projects" / project_id
        appearance_dir = project_root / "persona" / "appearance"
        dirty = False

        # JIT commit main avatar
        if not appearance.get("selected_filename"):
            try:
                selected_url = _resolve_selected_image_url(appearance)
                if selected_url:
                    source_filename = await _download_comfy_image(
                        selected_url, UPLOAD_PATH,
                    )
                    commit_result = commit_persona_avatar(
                        UPLOAD_PATH, project_root, source_filename,
                    )
                    appearance["selected_filename"] = commit_result.selected_filename
                    appearance["selected_thumb_filename"] = commit_result.thumb_filename
                    dirty = True
            except Exception as jit_err:
                print(f"[PERSONA] Export JIT auto-commit skipped: {jit_err}")

        # JIT download outfit + set images that only exist as ComfyUI URLs
        def _url_to_filename(url: str) -> Optional[str]:
            if not url:
                return None
            if "/comfy/view/" in url:
                return os.path.basename(url.rsplit("/comfy/view/", 1)[-1].split("?")[0])
            if "filename=" in url:
                return os.path.basename(url.split("filename=")[-1].split("&")[0])
            return None

        async def _ensure_image_on_disk(url: str) -> None:
            """Download a ComfyUI image to the appearance dir if not already there."""
            import shutil as _shutil
            fname = _url_to_filename(url)
            if not fname or fname in ("", ".", ".."):
                return
            appearance_dir.mkdir(parents=True, exist_ok=True)
            dest = appearance_dir / fname
            if dest.exists():
                return
            # Also check upload_root (may have been downloaded already)
            if (UPLOAD_PATH / fname).exists():
                _shutil.copy2(UPLOAD_PATH / fname, dest)
                return
            # Download from ComfyUI
            downloaded = await _download_comfy_image(url, UPLOAD_PATH)
            _shutil.copy2(UPLOAD_PATH / downloaded, dest)

        for s in (appearance.get("sets") or []):
            for img in (s.get("images") or []):
                try:
                    await _ensure_image_on_disk(img.get("url", ""))
                except Exception:
                    pass
        for outfit in (appearance.get("outfits") or []):
            for img in (outfit.get("images") or []):
                try:
                    await _ensure_image_on_disk(img.get("url", ""))
                except Exception:
                    pass

        if dirty:
            p = projects.update_project(
                project_id, {"persona_appearance": appearance},
            )

    try:
        out = export_persona_project(UPLOAD_PATH, p, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return Response(
        content=out.data,
        media_type=out.content_type,
        headers={"Content-Disposition": f'attachment; filename="{out.filename}"'},
    )


@app.post("/persona/import", dependencies=[Depends(require_api_key)])
async def persona_import(file: UploadFile = File(...)) -> JSONResponse:
    """
    Import a .hpersona package and create a new persona project.

    Accepts a multipart file upload of a .hpersona file.
    Validates schema version and creates the project with assets.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        created = import_persona_package(UPLOAD_PATH, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")

    return JSONResponse(
        status_code=201,
        content={"ok": True, "project": created},
    )


@app.post("/persona/import/preview", dependencies=[Depends(require_api_key)])
async def persona_import_preview(file: UploadFile = File(...)) -> JSONResponse:
    """
    Preview a .hpersona package without creating a project.

    Returns the package contents (agent, appearance, dependencies)
    plus a dependency check report showing what's available locally.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        preview = preview_persona_package(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {e}")

    # Run dependency check
    dep_report = check_dependencies(preview.dependencies)

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "manifest": preview.manifest,
            "persona_agent": preview.persona_agent,
            "persona_appearance": preview.persona_appearance,
            "agentic": preview.agentic,
            "dependencies": preview.dependencies,
            "has_avatar": preview.has_avatar,
            "asset_names": preview.asset_names,
            "dependency_check": dep_report.to_dict(),
            "avatar_preview_data_url": preview.thumb_data_url,
        },
    )


# ============================================================================
# Multimodal Vision Layer (additive — on-demand image understanding)
# ============================================================================

class MultimodalAnalyzeIn(BaseModel):
    """Request body for /v1/multimodal/analyze."""
    image_url: str = Field(..., description="URL of the image to analyze (local /files/... or remote)")
    conversation_id: Optional[str] = Field(None, description="Conversation ID to store results into")
    project_id: Optional[str] = Field(None, description="Optional project context")
    provider: Optional[str] = Field("ollama", description="Multimodal provider (currently: ollama)")
    base_url: Optional[str] = Field(None, description="Provider base URL override")
    model: Optional[str] = Field(None, description="Multimodal model to use (e.g. moondream, gemma3:4b)")
    mode: Optional[str] = Field("both", description="Analysis mode: caption | ocr | both")
    user_prompt: Optional[str] = Field(None, description="Custom prompt for the vision model")
    nsfw_mode: Optional[bool] = Field(False, description="Enable unrestricted analysis")
    persist: Optional[bool] = Field(
        True,
        description="If true (default), store analysis in conversation history. If false, return only.",
    )


@app.post("/v1/multimodal/analyze", dependencies=[Depends(require_api_key)])
async def multimodal_analyze(inp: MultimodalAnalyzeIn) -> JSONResponse:
    """
    Analyze an image using a multimodal (vision) model.

    This endpoint is additive and does NOT modify any existing chat logic.
    It runs a vision model on the provided image and returns structured text.
    The frontend can then inject this result into the conversation context.

    Flow:
      1. Load image from local /files/ or remote URL
      2. Send to configured vision model (Ollama)
      3. Return analysis text + metadata
      4. Optionally store into conversation history
    """
    try:
        result = await analyze_image(
            image_url=inp.image_url,
            upload_path=UPLOAD_PATH,
            provider=inp.provider or "ollama",
            base_url=inp.base_url,
            model=inp.model,
            user_prompt=inp.user_prompt,
            nsfw_mode=bool(inp.nsfw_mode),
            mode=inp.mode or "both",
        )

        if not result.get("ok"):
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "error": result.get("error", "Unknown multimodal error"),
                    "analysis_text": "",
                    "meta": result.get("meta", {}),
                },
            )

        # Optionally persist into conversation history (skipped when persist=false)
        cid = inp.conversation_id
        if (inp.persist is not False) and cid and result.get("analysis_text"):
            try:
                from .storage import add_message
                # Store the analysis as an assistant message with the image in media
                add_message(
                    cid,
                    "assistant",
                    f"[Image Analysis]\n{result['analysis_text']}",
                    media={"images": [inp.image_url]},
                    project_id=inp.project_id,
                )
            except Exception as e:
                print(f"[MULTIMODAL] Warning: failed to persist analysis to history: {e}")

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "conversation_id": cid,
                "analysis_text": result.get("analysis_text", ""),
                "meta": result.get("meta", {}),
            },
        )

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"Multimodal analysis failed: {str(e)}",
                "analysis_text": "",
                "meta": {},
            },
        )


# ============================================================================
# Multimodal Vision Layer — Attach/Persist (additive)
# ============================================================================

class MultimodalAttachIn(BaseModel):
    """Persist an existing vision analysis into conversation history without re-running the vision model."""
    conversation_id: str = Field(..., description="Conversation ID to attach the analysis into")
    image_url: str = Field(..., description="Image URL to associate with the analysis")
    analysis_text: str = Field(..., description="Vision analysis text to store")
    project_id: Optional[str] = Field(None, description="Optional project context")


@app.post("/v1/multimodal/attach", dependencies=[Depends(require_api_key)])
async def multimodal_attach(inp: MultimodalAttachIn) -> JSONResponse:
    """
    Persist an existing multimodal analysis into conversation history without
    re-running the vision model.  Used by the Smart topology so the vision
    result is saved as a history artifact after the main LLM has responded.

    Additive and safe for production — no existing endpoints are modified.
    """
    try:
        from .storage import add_message
        add_message(
            inp.conversation_id,
            "assistant",
            f"[Image Analysis]\n{inp.analysis_text}",
            media={"images": [inp.image_url]},
            project_id=inp.project_id,
        )
        return JSONResponse(status_code=200, content={"ok": True})
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"Failed to attach multimodal analysis: {str(e)}"},
        )


@app.get("/v1/multimodal/status", dependencies=[Depends(require_api_key)])
async def multimodal_status() -> JSONResponse:
    """
    Check if multimodal capabilities are available.
    Returns info about configured models and provider status.
    """
    # Check if Ollama is reachable and has vision models
    ollama_ok = False
    vision_models: list = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            if r.status_code == 200:
                ollama_ok = True
                data = r.json()
                all_models = [m.get("name", "") for m in data.get("models", [])]
                # Check known vision model patterns (single source of truth)
                vision_models = [
                    m for m in all_models
                    if any(p in m.lower() for p in VISION_MODEL_PATTERNS)
                ]
    except Exception:
        pass

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "multimodal_available": ollama_ok and len(vision_models) > 0,
            "provider": "ollama",
            "provider_reachable": ollama_ok,
            "installed_vision_models": vision_models,
            "recommended_default": vision_models[0] if vision_models else None,
        },
    )