"""
HomePilot Avatar Service — optional StyleGAN2 face generation microservice.

Non-destructive startup:
  - If STYLEGAN_ENABLED=true and weights are found, loads the model at startup.
  - If loading fails or is disabled, runs in placeholder mode (original behavior).
  - The /v1/avatars/capabilities endpoint reports current status.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import CFG
from .router import router

_log = logging.getLogger(__name__)

app = FastAPI(
    title="HomePilot Avatar Service",
    version="0.2.0",
    description="Optional StyleGAN2 face generation microservice for Avatar Studio.",
)
app.include_router(router, prefix="/v1")

# Serve generated avatar images as static files
_output_dir = CFG.avatar_output_dir or "../backend/data/avatars"
os.makedirs(_output_dir, exist_ok=True)
app.mount("/static/avatars", StaticFiles(directory=_output_dir), name="avatars")


@app.on_event("startup")
async def _startup_load_stylegan() -> None:
    """Attempt to load StyleGAN2 weights at startup.

    Graceful: if anything fails, the service continues in placeholder mode.
    This is intentionally non-destructive — the default behaviour (placeholders)
    is preserved unless the model loads successfully.
    """
    if not CFG.stylegan_enabled:
        _log.info(
            "StyleGAN disabled (STYLEGAN_ENABLED=false). "
            "Running in placeholder mode."
        )
        return

    if not CFG.stylegan_weights_path:
        _log.warning(
            "STYLEGAN_ENABLED=true but STYLEGAN_WEIGHTS_PATH not set. "
            "Running in placeholder mode."
        )
        return

    if not CFG.model_exists:
        _log.warning(
            "STYLEGAN_ENABLED=true but model not found at %s. "
            "Running in placeholder mode.",
            CFG.stylegan_weights_path,
        )
        return

    try:
        from .stylegan.loader import load_model

        load_model(
            weights_path=CFG.stylegan_weights_path,
            device=CFG.stylegan_device,
        )
        _log.info("StyleGAN2 model loaded successfully — real inference enabled.")
    except Exception as exc:
        _log.warning(
            "Failed to load StyleGAN2 model: %s. Running in placeholder mode.",
            exc,
        )
