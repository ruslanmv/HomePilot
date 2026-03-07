"""
Avatar-service configuration — environment-driven with safe defaults.

This microservice is OPTIONAL.  By default it runs placeholder generation.
Enable real StyleGAN2 inference by setting:

    STYLEGAN_ENABLED=true
    STYLEGAN_WEIGHTS_PATH=/models/stylegan2-ffhq-256.pkl

Non-destructive: if deps or weights are missing the service falls back
to placeholders automatically and reports warnings in responses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable config read once at import time."""

    # StyleGAN feature gate — disabled by default (placeholder mode)
    stylegan_enabled: bool = _bool("STYLEGAN_ENABLED", False)

    # Path to .pkl or .pt model weights
    stylegan_weights_path: str = os.getenv("STYLEGAN_WEIGHTS_PATH", "")

    # Device for inference: "auto" (GPU if available), "cuda", or "cpu"
    stylegan_device: str = os.getenv("STYLEGAN_DEVICE", "auto")

    # Where generated PNGs are saved (shared with backend via volume mount)
    avatar_output_dir: str = os.getenv("AVATAR_OUTPUT_DIR", "../backend/data/avatars")

    # Service port
    port: int = int(os.getenv("AVATAR_SERVICE_PORT", "8020"))

    @property
    def model_exists(self) -> bool:
        if not self.stylegan_weights_path:
            return False
        return Path(self.stylegan_weights_path).exists()


CFG = Settings()
