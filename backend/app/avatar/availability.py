"""
Avatar Studio — runtime availability checks.

Determines which avatar modes are usable based on:
  - installed model packs (marker files)
  - actual model presence on disk (auto-detects individually-installed models)
  - ComfyUI health
  - avatar-service health (optional)

StyleGAN cascading priority:
  1. avatar-stylegan2-1024 (FFHQ 1024 — highest quality)
  2. avatar-stylegan2      (FFHQ 256  — faster, lower VRAM)
  3. placeholder fallback  (built-in, always works)
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .config import CFG
from ..models.packs.registry import list_packs, pack_installed
from ..services.comfyui.client import comfyui_healthy

_log = logging.getLogger(__name__)

# Model IDs that constitute each pack
_BASIC_MODEL_IDS = {"insightface-antelopev2", "instantid-ip-adapter", "instantid-controlnet"}
_STYLEGAN2_256_MODEL_IDS = {"stylegan2-ffhq-256"}
_STYLEGAN2_1024_MODEL_IDS = {"stylegan2-ffhq-1024"}


def _models_present(required_ids: set[str]) -> bool:
    """Check whether all *required_ids* are installed on disk."""
    try:
        from ..edit_models import get_all_models, ModelCategory

        installed = {
            m.id for m in get_all_models(ModelCategory.AVATAR_GENERATION) if m.installed
        }
        return required_ids.issubset(installed)
    except Exception:
        return False


def _ensure_marker(pack_id: str) -> None:
    """Write a missing pack marker so subsequent checks are instant."""
    try:
        from ..capabilities import ensure_pack_marker

        ensure_pack_marker(pack_id)
        _log.info("Auto-created pack marker for '%s' (models detected on disk)", pack_id)
    except Exception:
        pass


def stylegan_status() -> dict:
    """Return StyleGAN installation status for the UI.

    Returns a dict with:
      - ``installed``: bool — whether any StyleGAN model is available
      - ``active_pack``: str | None — which pack is active (highest priority)
      - ``resolution``: int | None — native resolution of the active model
      - ``packs``: dict — per-pack installation status
    """
    # Check FFHQ 1024 (highest priority)
    has_1024 = pack_installed("avatar-stylegan2-1024")
    if not has_1024 and _models_present(_STYLEGAN2_1024_MODEL_IDS):
        has_1024 = True
        _ensure_marker("avatar-stylegan2-1024")

    # Check FFHQ 256 (fallback)
    has_256 = pack_installed("avatar-stylegan2")
    if not has_256 and _models_present(_STYLEGAN2_256_MODEL_IDS):
        has_256 = True
        _ensure_marker("avatar-stylegan2")

    active_pack = None
    resolution = None
    if has_1024:
        active_pack = "avatar-stylegan2-1024"
        resolution = 1024
    elif has_256:
        active_pack = "avatar-stylegan2"
        resolution = 256

    return {
        "installed": has_1024 or has_256,
        "active_pack": active_pack,
        "resolution": resolution,
        "packs": {
            "avatar-stylegan2-1024": {"installed": has_1024, "resolution": 1024},
            "avatar-stylegan2": {"installed": has_256, "resolution": 256},
        },
    }


def enabled_modes() -> List[str]:
    """Return sorted list of avatar modes that are currently available."""
    modes: list[str] = []

    basic_ok = pack_installed("avatar-basic")
    if not basic_ok and _models_present(_BASIC_MODEL_IDS):
        basic_ok = True
        _ensure_marker("avatar-basic")

    comfy_ok = comfyui_healthy(CFG.comfyui_url)
    _log.info(
        "[Availability] comfyui_healthy=%s (url=%s), basic_pack=%s",
        comfy_ok, CFG.comfyui_url, basic_ok,
    )

    if comfy_ok and basic_ok:
        modes += ["studio_reference", "studio_faceswap", "creative",
                  "hybrid_outfit"]  # InstantID + empty latent for angle control

    # StyleGAN cascading: prefer 1024, fallback to 256
    sg = stylegan_status()
    _log.info(
        "[Availability] stylegan_status: installed=%s, active_pack=%s, resolution=%s",
        sg["installed"], sg["active_pack"], sg["resolution"],
    )

    if sg["installed"]:
        modes.append("studio_random")

    # studio_random is always available via built-in placeholder fallback
    # even when avatar-service (StyleGAN) is not running.
    if "studio_random" not in modes:
        modes.append("studio_random")

    final = sorted(set(modes))
    _log.info("[Availability] enabled_modes=%s", final)
    return final


def packs_status() -> list[dict]:
    """Return list of pack dicts (with ``installed`` flag populated).

    Also auto-detects packs whose models are present on disk even if
    the marker file hasn't been written yet.
    """
    # Trigger enabled_modes() first — it auto-creates missing markers
    # when models are detected on disk.
    enabled_modes()
    return list_packs()
