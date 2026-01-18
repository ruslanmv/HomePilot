from __future__ import annotations

import os
import uuid as uuidlib
from pathlib import Path
from typing import Any, Dict, Optional, Literal

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import require_api_key
# Import config and storage as modules so we can patch paths if needed
from . import config, storage 
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
)
from .orchestrator import orchestrate
from .providers import provider_info
from .storage import init_db

app = FastAPI(title="HomePilot Orchestrator", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Models
# ----------------------------

ProviderName = Literal["openai_compat", "ollama"]


class ChatIn(BaseModel):
    message: str = Field(..., description="User message (raw input)")
    conversation_id: Optional[str] = Field(None, description="Conversation id (optional)")
    fun_mode: bool = Field(False, description="Frontend fun mode toggle")
    mode: Optional[str] = Field(None, description="chat|imagine|edit|animate")
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
        description="Optional Ollama model override (e.g., llama3.1:8b)",
    )
    # Custom generation parameters
    textTemperature: Optional[float] = Field(None, description="Text generation temperature (0-2)")
    textMaxTokens: Optional[int] = Field(None, description="Max tokens for text generation")
    imgWidth: Optional[int] = Field(None, description="Image width")
    imgHeight: Optional[int] = Field(None, description="Image height")
    imgSteps: Optional[int] = Field(None, description="Image generation steps")
    imgCfg: Optional[float] = Field(None, description="Image CFG scale")
    imgSeed: Optional[int] = Field(None, description="Image generation seed (0 = random)")
    vidSeconds: Optional[int] = Field(None, description="Video duration in seconds")
    vidFps: Optional[int] = Field(None, description="Video FPS")
    vidMotion: Optional[str] = Field(None, description="Video motion bucket")


class ChatOut(BaseModel):
    conversation_id: str
    text: str
    media: Optional[Dict[str, Any]] = None


# ----------------------------
# Helpers
# ----------------------------

def _base_url_from_request(req: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return str(req.base_url).rstrip("/")


def _safe_err(message: str, *, code: str = "error") -> Dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


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
    StaticFiles validates the directory at mount time,
    so mount only after ensuring the directory exists.
    """
    # idempotent mount
    for route in app.router.routes:
        if getattr(route, "name", None) == "files":
            return
    app.mount("/files", StaticFiles(directory=str(UPLOAD_PATH)), name="files")


# ----------------------------
# Startup
# ----------------------------

@app.on_event("startup")
def _startup() -> None:
    # Ensure DB path is valid before initializing
    _ensure_db_path_is_writable()
    # Database
    init_db()
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


@app.get("/models")
async def list_models(
    provider: str = Query("openai_compat", description="Provider to list models from"),
    base_url: Optional[str] = Query(None, description="Override base URL for the provider"),
) -> JSONResponse:
    """
    List available models from a provider.
    Supports:
      - openai_compat: GET {base}/models   (expects OpenAI-style response)
      - ollama: GET {base}/api/tags

    Example: GET /models?provider=openai_compat&base_url=http://localhost:8001/v1
    """
    try:
        if provider == "ollama":
            ollama_url = (base_url or OLLAMA_BASE_URL).rstrip("/")

            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    response = await client.get(f"{ollama_url}/api/tags")
                    response.raise_for_status()
                    data = response.json()

                    models = data.get("models", [])
                    model_names = sorted([m.get("name", "") for m in models if m.get("name")])

                    return JSONResponse(
                        status_code=200,
                        content={
                            "ok": True,
                            "provider": "ollama",
                            "base_url": ollama_url,
                            "models": model_names,
                            "count": len(model_names),
                        },
                    )
                except httpx.HTTPError as e:
                    return JSONResponse(
                        status_code=503,
                        content=_safe_err(
                            f"Failed to connect to Ollama at {ollama_url}: {str(e)}. "
                            "Make sure Ollama is running (ollama serve).",
                            code="ollama_unavailable",
                        ),
                    )

        if provider == "openai_compat":
            llm_url = (base_url or LLM_BASE_URL).rstrip("/")
            # LLM_BASE_URL defaults to http://llm:8001/v1, so /models is http://.../v1/models
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.get(f"{llm_url}/models")
                    resp.raise_for_status()
                    data = resp.json()
                    arr = data.get("data", [])
                    model_names = sorted([m.get("id", "") for m in arr if isinstance(m, dict) and m.get("id")])

                    return JSONResponse(
                        status_code=200,
                        content={
                            "ok": True,
                            "provider": "openai_compat",
                            "base_url": llm_url,
                            "models": model_names,
                            "count": len(model_names),
                        },
                    )
                except httpx.HTTPError as e:
                    return JSONResponse(
                        status_code=503,
                        content=_safe_err(
                            f"Failed to connect to OpenAI-compatible LLM at {llm_url}: {str(e)}. "
                            "Check vLLM container or service.",
                            code="openai_compat_unavailable",
                        ),
                    )

        return JSONResponse(
            status_code=400,
            content=_safe_err(
                f"Provider '{provider}' is not supported for model listing.",
                code="unsupported_provider",
            ),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Error listing models: {str(e)}",
                code="models_error",
            ),
        )




@app.get("/conversations")
async def conversations(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """List saved conversations (History/Today sidebar)."""
    try:
        items = list_conversations(limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "conversations": items})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to list conversations: {e}", code="conversations_error"))


@app.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str, limit: int = Query(200, ge=1, le=1000)) -> JSONResponse:
    """Load full message list for a conversation."""
    try:
        msgs = get_messages(conversation_id, limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "conversation_id": conversation_id, "messages": msgs})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to load conversation: {e}", code="conversation_load_error"))

@app.post("/chat", dependencies=[Depends(require_api_key)])
async def chat(inp: ChatIn) -> JSONResponse:
    """
    Stable response schema:
      { conversation_id, text, media }
    """
    out = await orchestrate(
        user_text=inp.message,
        conversation_id=inp.conversation_id,
        fun_mode=inp.fun_mode,
        mode=inp.mode,
        provider=inp.provider,
        ollama_base_url=inp.ollama_base_url,
        ollama_model=inp.ollama_model,
        text_temperature=inp.textTemperature,
        text_max_tokens=inp.textMaxTokens,
        img_width=inp.imgWidth,
        img_height=inp.imgHeight,
        img_steps=inp.imgSteps,
        img_cfg=inp.imgCfg,
        img_seed=inp.imgSeed,
        vid_seconds=inp.vidSeconds,
        vid_fps=inp.vidFps,
        vid_motion=inp.vidMotion,
    )

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
async def upload(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """
    Stream uploads to disk (avoid reading entire file in memory).
    """
    filename = file.filename or "upload.png"
    ext = os.path.splitext(filename)[1].lower()[:10]
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

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
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Max {MAX_UPLOAD_MB}MB.",
                    )
                f.write(chunk)
    finally:
        await file.close()

    base = _base_url_from_request(request)
    return JSONResponse(status_code=201, content={"url": f"{base}/files/{name}"})