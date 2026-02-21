"""
Avatar Studio — runtime availability checks.

Determines which avatar modes are usable based on:
  - installed model packs (marker files)
  - ComfyUI health
  - avatar-service health (optional)
"""

from __future__ import annotations

from typing import List

from .config import CFG
from ..models.packs.registry import list_packs, pack_installed
from ..services.comfyui.client import comfyui_healthy


def enabled_modes() -> List[str]:
    """Return sorted list of avatar modes that are currently available."""
    modes: list[str] = []

    if comfyui_healthy(CFG.comfyui_url):
        if pack_installed("avatar-basic"):
            modes += ["studio_reference", "studio_faceswap", "creative"]

    if pack_installed("avatar-stylegan2"):
        modes.append("studio_random")

    return sorted(set(modes))


def packs_status() -> list[dict]:
    """Return list of pack dicts (with ``installed`` flag populated)."""
    return list_packs()
