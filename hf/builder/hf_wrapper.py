"""
HomePilot — HF Spaces wrapper.

Imports the HomePilot FastAPI app and adds:
  1. Static file serving for the pre-built React frontend.
  2. A catch-all route that serves index.html for client-side routing.
  3. A /setup endpoint for the first-run installer wizard.

This avoids modifying HomePilot's main.py while adding the HF-specific
frontend serving layer on top.
"""

import os
import sys
from pathlib import Path

import uvicorn
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Ensure the app module is importable.
sys.path.insert(0, "/app")

# Import the real HomePilot app.
from app.main import app  # noqa: E402

# ── Frontend serving ─────────────────────────────────────

FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", "/app/frontend"))
FRONTEND_INDEX = FRONTEND_DIR / "index.html"

CHATA_PERSONAS_DIR = Path("/app/chata-personas")
PERSONAS_DATA_DIR = Path("/tmp/homepilot/data/personas")

# Mount Vite's built assets (JS, CSS, images).
if FRONTEND_DIR.exists():
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend_assets")


# ── Setup / installer endpoint ───────────────────────────

@app.get("/setup/status")
def setup_status():
    """Check installation status for the wizard UI."""
    import subprocess

    # Check Ollama
    ollama_ok = False
    ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
    try:
        import requests
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        if r.ok:
            tags = r.json()
            models = [m.get("name", "") for m in tags.get("models", [])]
            ollama_ok = any(ollama_model in m for m in models)
    except Exception:
        pass

    # Check personas
    personas_imported = Path("/tmp/homepilot/data/.personas_imported").exists()
    persona_count = 0
    if PERSONAS_DATA_DIR.exists():
        persona_count = len([d for d in PERSONAS_DATA_DIR.iterdir() if d.is_dir()])

    # Check DB
    db_path = Path(os.environ.get("SQLITE_PATH", "/tmp/homepilot/data/homepilot.db"))
    db_ready = db_path.exists()

    return {
        "status": "ready" if (ollama_ok and personas_imported) else "setup",
        "ollama": {"online": ollama_ok, "model": ollama_model},
        "personas": {"imported": personas_imported, "count": persona_count},
        "database": {"ready": db_ready, "path": str(db_path)},
        "environment": "huggingface",
    }


# ── Catch-all for React client-side routing ──────────────

RESERVED = ("api/", "v1/", "ws", "docs", "openapi.json", "redoc",
            "health", "community/", "settings/", "setup/", "files/",
            "personas/", "studio/", "agentic/", "teams/", "assets/")


@app.get("/{full_path:path}")
def frontend_catchall(full_path: str, request: Request):
    """Serve the React frontend for any non-API path."""
    if full_path.startswith(RESERVED):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if not FRONTEND_INDEX.exists():
        return JSONResponse({
            "detail": "Frontend not built. Visit /docs for the API.",
            "setup": "/setup/status",
        })

    # Direct file match (e.g. /favicon.ico, /logo.svg)
    candidate = FRONTEND_DIR / full_path
    try:
        resolved = candidate.resolve()
        if str(resolved).startswith(str(FRONTEND_DIR.resolve())) and resolved.is_file():
            return FileResponse(resolved)
    except (OSError, ValueError):
        pass

    # All other paths → index.html (React Router handles them)
    return FileResponse(FRONTEND_INDEX)


# ── Run ──────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        workers=1,
        timeout_keep_alive=120,
        log_level="info",
    )
