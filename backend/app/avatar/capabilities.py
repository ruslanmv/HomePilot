"""
Avatar engine capabilities — additive module.

Reports which generation engines (ComfyUI, StyleGAN) are currently available.
Used by the UI to show/hide engine options and display informative status.

Non-destructive: does not modify any existing module.  The default engine
remains ComfyUI.  StyleGAN availability is probed via the avatar-service
microservice (optional — if unreachable, it's marked as unavailable).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from .config import CFG

_log = logging.getLogger(__name__)


async def get_capabilities() -> Dict[str, Any]:
    """Return engine availability for the UI.

    Probes:
      - ComfyUI health (already checked by ``availability.enabled_modes()``)
      - avatar-service ``/v1/avatars/capabilities`` (optional)

    Returns a dict matching the ``AvatarCapabilitiesResponse`` shape so the
    router can return it directly.
    """
    from .availability import enabled_modes as _enabled_modes
    from ..services.comfyui.client import comfyui_healthy

    # ComfyUI
    comfyui_ok = comfyui_healthy(CFG.comfyui_url)
    comfyui_cap = {
        "available": comfyui_ok,
        "reason": None if comfyui_ok else "unreachable",
        "details": None if comfyui_ok else f"ComfyUI at {CFG.comfyui_url} not responding.",
    }

    # StyleGAN — probe the avatar-service microservice
    stylegan_cap = await _probe_stylegan()

    # Enabled modes (existing logic)
    modes = _enabled_modes()

    # StyleGAN pack installation status (cascading: 1024 → 256)
    from .availability import stylegan_status as _stylegan_status
    sg_status = _stylegan_status()

    # OpenPose ControlNet availability (for Pose Guided body generation)
    openpose_ok = False
    if comfyui_ok:
        try:
            from ..comfy import openpose_available as _openpose_available
            openpose_ok = _openpose_available()
        except Exception:
            pass

    return {
        "default_engine": "comfyui",
        "engines": {
            "comfyui": comfyui_cap,
            "stylegan": stylegan_cap,
        },
        "enabled_modes": modes,
        "stylegan_status": sg_status,
        "openpose_available": openpose_ok,
    }


async def _probe_stylegan() -> Dict[str, Any]:
    """Probe the avatar-service for StyleGAN availability.

    This is intentionally lenient — if the service is down or misconfigured,
    we simply report it as unavailable without failing.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{CFG.avatar_service_url}/v1/avatars/capabilities"
            )
            r.raise_for_status()
            data = r.json()

        st = data.get("engines", {}).get("stylegan", {})
        return {
            "available": bool(st.get("available", False)),
            "reason": st.get("reason"),
            "details": st.get("details"),
        }
    except httpx.ConnectError:
        return {
            "available": False,
            "reason": "service_offline",
            "details": f"Avatar service at {CFG.avatar_service_url} is not running.",
        }
    except Exception as exc:
        _log.debug("StyleGAN probe failed: %s", exc)
        return {
            "available": False,
            "reason": "probe_failed",
            "details": str(exc),
        }
