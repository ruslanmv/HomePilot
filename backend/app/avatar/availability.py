"""
Avatar Studio — runtime availability checks.

Determines which avatar modes are usable based on:
  - installed model packs (marker files)
  - actual model presence on disk (auto-detects individually-installed models)
  - ComfyUI health
  - avatar-service health (optional)
"""

from __future__ import annotations

import logging
from typing import List

from .config import CFG
from ..models.packs.registry import list_packs, pack_installed
from ..services.comfyui.client import comfyui_healthy

_log = logging.getLogger(__name__)

# Model IDs that constitute each pack
_BASIC_MODEL_IDS = {"insightface-antelopev2", "instantid-ip-adapter", "instantid-controlnet"}
_STYLEGAN2_MODEL_IDS = {"stylegan2-ffhq-256"}


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


def enabled_modes() -> List[str]:
    """Return sorted list of avatar modes that are currently available."""
    modes: list[str] = []

    basic_ok = pack_installed("avatar-basic")
    if not basic_ok and _models_present(_BASIC_MODEL_IDS):
        basic_ok = True
        _ensure_marker("avatar-basic")

    if comfyui_healthy(CFG.comfyui_url):
        if basic_ok:
            modes += ["studio_reference", "studio_faceswap", "creative"]

    stylegan_ok = pack_installed("avatar-stylegan2")
    if not stylegan_ok and _models_present(_STYLEGAN2_MODEL_IDS):
        stylegan_ok = True
        _ensure_marker("avatar-stylegan2")

    if stylegan_ok:
        modes.append("studio_random")

    return sorted(set(modes))


def packs_status() -> list[dict]:
    """Return list of pack dicts (with ``installed`` flag populated).

    Also auto-detects packs whose models are present on disk even if
    the marker file hasn't been written yet.
    """
    # Trigger enabled_modes() first — it auto-creates missing markers
    # when models are detected on disk.
    enabled_modes()
    return list_packs()
