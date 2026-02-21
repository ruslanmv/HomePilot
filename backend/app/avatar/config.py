"""
Avatar Studio configuration — reads from environment variables with safe defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AvatarConfig:
    """Immutable config read once at import time."""

    enabled: bool = field(
        default_factory=lambda: os.getenv("AVATAR_ENABLED", "true").lower() == "true"
    )
    default_mode: str = field(
        default_factory=lambda: os.getenv("AVATAR_DEFAULT_MODE", "studio_reference")
    )
    comfyui_url: str = field(
        default_factory=lambda: os.getenv("COMFYUI_URL", os.getenv("COMFY_BASE_URL", "http://localhost:8188"))
    )
    avatar_service_url: str = field(
        default_factory=lambda: os.getenv("AVATAR_SERVICE_URL", "http://localhost:8020")
    )
    allow_non_commercial: bool = field(
        default_factory=lambda: os.getenv("ALLOW_NON_COMMERCIAL_MODELS", "true").lower() == "true"
    )
    storage_root: str = field(
        default_factory=lambda: os.getenv("AVATAR_STORAGE_ROOT", "data/avatars")
    )


CFG = AvatarConfig()
