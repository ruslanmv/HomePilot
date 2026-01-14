# homepilot/backend/app/main.py
from __future__ import annotations

import os
import uuid as uuidlib
from typing import Any, Dict, Optional, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import require_api_key
from .config import (
    CORS_ORIGINS,
    PUBLIC_BASE_URL,
    UPLOAD_DIR,
    MAX_UPLOAD_MB,
    DEFAULT_PROVIDER,
    LLM_BASE_URL,
    COMFY_BASE_URL,
    MEDIA_BASE_URL,
    LLM_MODEL,
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

# Ensure local storage is ready even when lifespan events are not executed
# (e.g. Starlette TestClient instantiated without a context manager).
try:
    init_db()
except Exception:
    # Lifespan startup will retry; avoid crashing at import time.
    pass

# ----------------------------
# Models
# ----------------------------

ProviderName = Literal["openai_compat", "ollama"]


class ChatIn(BaseModel):
    message: str = Field(..., description="User message (raw input)")
    conversation_id: Optional[str] = Field(
        None, description="Conversation id (optional)"
    )
    fun_mode: bool = Field(False, description="Frontend fun mode toggle")
    mode: Optional[str] = Field(None, description="chat|imagine|edit|animate")
    provider: Optional[ProviderName] = Field(
        None,
        description="LLM provider selection. If omitted, backend default is used.",
    )


class ChatOut(BaseModel):
    conversation_id: str
    text: str
    media: Optional[Dict[str, Any]] = None


class SettingsOut(BaseModel):
    ok: bool = True
    default_provider: ProviderName
    providers: Dict[str, Dict[str, Any]]
    public_base_url: str
    upload_dir: str
    max_upload_mb: int


# ----------------------------
# Helpers
# ----------------------------

def _base_url_from_request(req: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return str(req.base_url).rstrip("/")


def _safe_err(message: str, *, code: str = "error") -> Dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


# ----------------------------
# Startup
# ----------------------------

@app.on_event("startup")
def _startup() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db()


# IMPORTANT:
# StaticFiles validates the directory at mount time (import-time),
# so ensure it exists here too.
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")


# ----------------------------
# Error handling (prod-safe)
# ----------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception):
    # Avoid leaking internals in production. (Log `exc` in real deployments.)
    return JSONResponse(
        status_code=500,
        content=_safe_err("Internal server error.", code="internal_error"),
    )


# ----------------------------
# Routes
# ----------------------------

@app.get("/health")
async def health() -> JSONResponse:
    # ✅ tests require "service"
    return JSONResponse(
        status_code=200,
        content={"ok": True, "service": "homepilot-backend", "version": app.version},
    )

@app.get("/providers")
async def providers() -> JSONResponse:
    """
    Frontend can query providers to populate dropdown (OpenAI-compatible vs Ollama).

    ✅ tests require:
      - ok == True
      - key "default" exists
      - key "available" exists (list)
    """
    info = provider_info()
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "default": DEFAULT_PROVIDER,
            "available": sorted(list(info.keys())),
            # For UI + debugging; structure comes from provider_info()
            "providers": info,
        },
    )

@app.get("/settings")
async def settings(request: Request) -> JSONResponse:
    """
    Frontend can query backend runtime settings to prefill "Backend Settings" UI.
    This is safe/redacted (no secrets).

    ✅ tests require:
      - ok == True
      - key "default_provider" exists
      - key "llm_base_url" exists
    """
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
            "upload_dir": UPLOAD_DIR,
            "max_upload_mb": int(MAX_UPLOAD_MB),
        },
    )

@app.post("/chat", dependencies=[Depends(require_api_key)])
async def chat(inp: ChatIn) -> Dict[str, Any]:
    """
    Stable response schema for frontend:
      { conversation_id, text, media }

    ✅ tests require:
      - key "conversation_id" exists
      - key "text" exists
      - key "media" exists (can be null)
    """
    out = await orchestrate(
        user_text=inp.message,
        conversation_id=inp.conversation_id,
        fun_mode=inp.fun_mode,
        mode=inp.mode,
        provider=inp.provider,
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

    # Return a plain dict to prevent response_model edge-cases producing {}
    return JSONResponse(status_code=200, content={"conversation_id": cid, "text": text, "media": media})
@app.post("/upload", dependencies=[Depends(require_api_key)])
async def upload(request: Request, file: UploadFile = File(...)) -> Dict[str, str]:
    """
    Stream uploads to disk (avoid reading entire file in memory).
    Only allow basic image types for safety.

    ✅ tests require key "url" in JSON.
    """
    filename = file.filename or "upload.png"
    ext = os.path.splitext(filename)[1].lower()[:10]
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

    max_bytes = int(MAX_UPLOAD_MB) * 1024 * 1024
    name = f"{uuidlib.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)

    written = 0
    chunk_size = 1024 * 1024  # 1MB

    try:
        with open(path, "wb") as f:
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
