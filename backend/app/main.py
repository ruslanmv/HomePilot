from __future__ import annotations

import json
import os
import subprocess
import uuid as uuidlib
import traceback
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
)
from .orchestrator import orchestrate, handle_request
from .providers import provider_info
from .storage import init_db, list_conversations, get_messages, delete_image_url, delete_conversation
from .migrations import run_migrations

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
    imgSteps: Optional[int] = Field(None, description="Image generation steps")
    imgCfg: Optional[float] = Field(None, description="Image CFG scale")
    imgSeed: Optional[int] = Field(None, description="Image generation seed (0 = random)")
    imgModel: Optional[str] = Field(None, description="Image model selection (sdxl, flux-schnell, flux-dev, pony-xl, sd15-uncensored)")
    vidSeconds: Optional[int] = Field(None, description="Video duration in seconds")
    vidFps: Optional[int] = Field(None, description="Video FPS")
    vidMotion: Optional[str] = Field(None, description="Video motion bucket")
    vidModel: Optional[str] = Field(None, description="Video model selection (svd, wan-2.2, seedream)")
    nsfwMode: Optional[bool] = Field(None, description="Enable NSFW/uncensored mode")
    promptRefinement: Optional[bool] = Field(True, description="Enable AI prompt refinement for image generation (default: True)")


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
    model_type: Optional[str] = Query(None, description="For ComfyUI: 'image' or 'video'"),
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
            else:
                # Return both if not specified
                models = scan_installed_models("image") + scan_installed_models("video")

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


class ModelInstallRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    provider: str = Field(..., description="Provider (ollama, comfyui, civitai)")
    model_type: str = Field(..., description="Model type (chat, image, video)")
    model_id: str = Field(..., description="Model ID to install")
    base_url: Optional[str] = Field(None, description="Optional base URL override")
    civitai_version_id: Optional[str] = Field(None, description="Civitai version ID (for civitai provider)")


@app.post("/models/install")
async def install_model(req: ModelInstallRequest) -> JSONResponse:
    """
    Install a model using the download.py script.

    Supports:
    - ollama: Uses ollama pull
    - comfyui: Downloads from catalog
    - civitai: Downloads from Civitai by version ID (experimental)
    """
    try:
        script_path = Path(__file__).parent.parent.parent / "scripts" / "download.py"

        if not script_path.exists():
            return JSONResponse(
                status_code=500,
                content=_safe_err(
                    "Download script not found. Please ensure scripts/download.py exists.",
                    code="script_not_found",
                ),
            )

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
            pull_cmd = ["ollama", "pull", req.model_id]
            result = subprocess.run(pull_cmd, capture_output=True, text=True, timeout=300)

            if result.returncode == 0:
                return JSONResponse(
                    status_code=200,
                    content={
                        "ok": True,
                        "message": f"Successfully pulled {req.model_id}",
                        "provider": "ollama",
                        "model_id": req.model_id,
                    },
                )
            else:
                return JSONResponse(
                    status_code=500,
                    content=_safe_err(
                        f"Ollama pull failed: {result.stderr}",
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode == 0:
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "message": f"Successfully installed {req.model_id}",
                    "provider": req.provider,
                    "model_id": req.model_id,
                    "output": result.stdout,
                },
            )
        else:
            return JSONResponse(
                status_code=500,
                content=_safe_err(
                    f"Installation failed: {result.stderr or result.stdout}",
                    code="installation_failed",
                ),
            )

    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                "Installation timed out. Large models may take longer.",
                code="timeout",
            ),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Installation error: {str(e)}",
                code="installation_error",
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


@app.delete("/conversations/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: str) -> JSONResponse:
    """Delete all messages from a specific conversation."""
    try:
        deleted_count = delete_conversation(conversation_id)
        return JSONResponse(status_code=200, content={"ok": True, "deleted": deleted_count > 0, "deleted_messages": deleted_count, "conversation_id": conversation_id})
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
# Projects API
# ----------------------------

@app.post("/projects", dependencies=[Depends(require_api_key)])
async def create_project(data: ProjectCreateIn) -> JSONResponse:
    """Create a new project context."""
    try:
        # Convert pydantic model to dict for storage
        project_dict = data.dict()
        result = projects.create_new_project(project_dict)
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

        if ext not in {".pdf", ".txt", ".md"}:
            return JSONResponse(
                status_code=400,
                content=_safe_err("Only PDF, TXT, and MD files are supported", code="invalid_file_type")
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
            from .vectordb import process_and_add_file
            chunks_added = process_and_add_file(project_id, path)

            # Update project metadata with file info
            project = projects.get_project_by_id(project_id)
            if project:
                files_list = project.get("files", [])
                files_list.append({
                    "name": filename,
                    "size": f"{written / 1024 / 1024:.2f} MB",
                    "path": str(path),
                    "chunks": chunks_added
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
                "message": f"File processed and {chunks_added} chunks added to knowledge base"
            })

        except Exception as e:
            # Clean up file if processing failed
            path.unlink(missing_ok=True)
            raise e

    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to upload file: {e}"))


# ----------------------------
# Chat & Upload
# ----------------------------

@app.post("/chat", dependencies=[Depends(require_api_key)])
async def chat(inp: ChatIn) -> JSONResponse:
    """
    Unified chat endpoint with mode-aware routing.
    Stable response schema:
      { conversation_id, text, media }
    """
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
        "imgSteps": inp.imgSteps,
        "imgCfg": inp.imgCfg,
        "imgSeed": inp.imgSeed,
        "imgModel": inp.imgModel,
        "vidSeconds": inp.vidSeconds,
        "vidFps": inp.vidFps,
        "vidMotion": inp.vidMotion,
        "vidModel": inp.vidModel,
        "nsfwMode": inp.nsfwMode,
        "promptRefinement": inp.promptRefinement,
    }

    # Route through mode-aware handler
    out = await handle_request(mode=inp.mode, payload=payload)

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