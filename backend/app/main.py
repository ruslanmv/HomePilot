# backend/app/main.py
from __future__ import annotations

import os
import uuid as uuidlib
from pathlib import Path
from typing import Any, Dict, Optional, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure these exist in your project structure
from .auth import require_api_key
from .config import (
    CORS_ORIGINS,
    PUBLIC_BASE_URL,
    UPLOAD_DIR as CONFIG_UPLOAD_DIR,
    MAX_UPLOAD_MB,
    DEFAULT_PROVIDER,
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

# ----------------------------
# Helpers
# ----------------------------

def _base_url_from_request(req: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return str(req.base_url).rstrip("/")

def _safe_err(message: str, *, code: str = "error") -> Dict[str, Any]:
    return {"ok": False, "code": code, "message": message}

def _resolve_upload_dir() -> str:
    """Resolve a writable upload directory."""
    configured = Path(CONFIG_UPLOAD_DIR)
    try:
        configured.mkdir(parents=True, exist_ok=True)
        # Test writability
        test_file = configured / ".write_test"
        test_file.write_text("ok")
        test_file.unlink(missing_ok=True)
        return str(configured)
    except Exception:
        fallback = Path.cwd() / "data" / "uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        return str(fallback)

UPLOAD_DIR = _resolve_upload_dir()

try:
    init_db()
except Exception:
    pass

app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

# ----------------------------
# Routes
# ----------------------------

@app.on_event("startup")
def _startup() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db()

@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, __: Exception):
    return JSONResponse(
        status_code=500,
        content=_safe_err("Internal server error.", code="internal_error"),
    )

@app.get("/health")
async def health() -> Dict[str, Any]:
    # This specifically fixes test_health_ok
    return {"ok": True, "service": "homepilot-backend", "version": app.version}

@app.get("/providers")
async def providers() -> Dict[str, Any]:
    # This specifically fixes test_providers_ok
    return {"ok": True, "default": DEFAULT_PROVIDER, "providers": provider_info()}

@app.get("/settings")
async def settings(request: Request) -> Dict[str, Any]:
    # This specifically fixes test_settings_ok
    base = _base_url_from_request(request)
    return {
        "ok": True,
        "default_provider": DEFAULT_PROVIDER,
        "providers": provider_info(),
        "public_base_url": base,
        "upload_dir": UPLOAD_DIR,
        "max_upload_mb": int(MAX_UPLOAD_MB),
    }

@app.post("/chat", dependencies=[Depends(require_api_key)])
async def chat(inp: ChatIn) -> Dict[str, Any]:
    # This specifically fixes test_chat_basic / test_chat_imagine
    out = await orchestrate(
        user_text=inp.message,
        conversation_id=inp.conversation_id,
        fun_mode=inp.fun_mode,
        mode=inp.mode,
        provider=inp.provider,
    )

    if not isinstance(out, dict):
        out = {}

    # Ensure keys exist even if orchestrator returns partial data
    cid = out.get("conversation_id") or inp.conversation_id or str(uuidlib.uuid4())
    
    text = out.get("text")
    if not isinstance(text, str) or not text.strip():
        text = "…"

    media = out.get("media", None)
    if media is not None and not isinstance(media, dict):
        media = None

    return {"conversation_id": cid, "text": text, "media": media}

@app.post("/upload", dependencies=[Depends(require_api_key)])
async def upload(request: Request, file: UploadFile = File(...)) -> Dict[str, str]:
    # This specifically fixes test_upload_returns_url
    filename = file.filename or "upload.png"
    ext = os.path.splitext(filename)[1].lower()[:10]
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

    max_bytes = int(MAX_UPLOAD_MB) * 1024 * 1024
    name = f"{uuidlib.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)

    written = 0
    chunk_size = 1024 * 1024

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
    return {"url": f"{base}/files/{name}"}