"""
Compute provider selection (Wave A — Batch 6 / HP-1 + HP-2).

Resolves which ComputeProvider serves generation, per
``config.HOMEPILOT_COMPUTE_MODE``:

  * ``local``            → LocalComputeProvider (today's behaviour; the default)
  * ``ollabridge_cloud`` → OllaBridgeCloudComputeProvider
  * ``auto``             → local GPU when healthy, else a linked OllaBridge
                           device, else local (offline — status says so)

``compute_status()`` backs the plain-language status UX (HP-2): normal users see
"Using this PC — Private GPU" or an honest "your PC is offline" message, never
endpoint/API-key configuration.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import ComputeProvider, GeneratedMedia
from .local import LocalComputeProvider
from .ollabridge_cloud import OllaBridgeCloudComputeProvider

__all__ = [
    "ComputeProvider",
    "GeneratedMedia",
    "LocalComputeProvider",
    "OllaBridgeCloudComputeProvider",
    "get_compute_provider",
    "resolve_mode",
    "compute_status",
]


def _build_cloud() -> Optional[OllaBridgeCloudComputeProvider]:
    from app.config import (
        OLLABRIDGE_CLOUD_IMAGE_MODEL,
        OLLABRIDGE_CLOUD_TIMEOUT,
        OLLABRIDGE_CLOUD_TOKEN,
        OLLABRIDGE_CLOUD_URL,
        OLLABRIDGE_CLOUD_VIDEO_MODEL,
    )
    if not OLLABRIDGE_CLOUD_URL:
        return None
    return OllaBridgeCloudComputeProvider(
        OLLABRIDGE_CLOUD_URL,
        OLLABRIDGE_CLOUD_TOKEN,
        image_model=OLLABRIDGE_CLOUD_IMAGE_MODEL,
        video_model=OLLABRIDGE_CLOUD_VIDEO_MODEL,
        timeout=OLLABRIDGE_CLOUD_TIMEOUT,
    )


def _configured_mode() -> str:
    from app.config import HOMEPILOT_COMPUTE_MODE
    mode = (HOMEPILOT_COMPUTE_MODE or "local").strip().lower()
    return mode if mode in ("local", "ollabridge_cloud", "auto") else "local"


def _cloud_configured() -> bool:
    """A cloud link is usable only when both a URL and a token are set —
    without a token the job API would 401."""
    from app.config import OLLABRIDGE_CLOUD_TOKEN, OLLABRIDGE_CLOUD_URL
    return bool(OLLABRIDGE_CLOUD_URL and OLLABRIDGE_CLOUD_TOKEN)


def _burst_allowed() -> bool:
    """Whether `auto` may burst to a cloud GPU when the local one is offline.
    Free for everyone unless the operator gates it to premium (MB6). The local
    GPU is never affected."""
    from app.config import COMPUTE_BURST_REQUIRES_PREMIUM, PREMIUM_COMPUTE_ENABLED
    return (not COMPUTE_BURST_REQUIRES_PREMIUM) or PREMIUM_COMPUTE_ENABLED


async def resolve_mode() -> str:
    """Resolve the effective mode (never returns ``auto``)."""
    configured = _configured_mode()
    if configured in ("local", "ollabridge_cloud"):
        return configured

    # auto: prefer the local GPU, then — if bursting is allowed — a *configured*
    # linked OllaBridge device.
    if await LocalComputeProvider().available():
        return "local"
    if _burst_allowed():
        cloud = _build_cloud()
        if cloud is not None and _cloud_configured() and await cloud.available():
            return "ollabridge_cloud"
    return "local"  # offline (or burst-gated) — compute_status() explains


async def get_compute_provider(mode: str | None = None) -> ComputeProvider:
    """Return the provider for the given (or resolved) mode."""
    mode = mode or await resolve_mode()
    if mode == "ollabridge_cloud":
        cloud = _build_cloud()
        if cloud is not None:
            return cloud
    return LocalComputeProvider()


async def compute_status() -> dict[str, Any]:
    """Backs the HP-2 status UX — plain language, no infrastructure jargon."""
    from app.config import (
        OLLABRIDGE_CLOUD_TOKEN,
        OLLABRIDGE_CLOUD_URL,
        PREMIUM_COMPUTE_ENABLED,
    )

    local_ok = await LocalComputeProvider().available()
    cloud = _build_cloud()
    cloud_configured = bool(OLLABRIDGE_CLOUD_URL and OLLABRIDGE_CLOUD_TOKEN)
    cloud_ok = await cloud.available() if cloud is not None else False
    mode = await resolve_mode()
    configured = _configured_mode()

    # Burst = we're on cloud because the local GPU is offline (auto fallback).
    burst = mode == "ollabridge_cloud" and configured == "auto" and not local_ok
    # Burst-gated = local offline + a reachable cloud we could use, but premium is
    # required and not granted.
    burst_gated = (
        configured == "auto"
        and not local_ok
        and cloud_configured
        and cloud_ok
        and not _burst_allowed()
    )

    if mode == "local" and local_ok:
        label = "Private GPU"
        message = "Compute: Connected — Using this PC — Mode: Private GPU"
    elif mode == "ollabridge_cloud" and cloud_ok:
        label = "OllaBridge Cloud"
        message = (
            "Your PC is offline — running on a cloud GPU (premium)."
            if burst
            else "Compute: Connected — Using your paired GPU via OllaBridge Cloud"
        )
    elif burst_gated:
        label = "Offline"
        message = "Your PC is offline — upgrade to premium to run on a cloud GPU, or wait for your PC."
    else:
        label = "Offline"
        message = (
            "Your PC is offline — wait for it to come back, use the free cloud "
            "queue, or use a premium GPU."
        )

    return {
        "mode": mode,
        "configured_mode": configured,
        "local_gpu_available": local_ok,
        "cloud_configured": cloud_configured,
        "cloud_reachable": cloud_ok,
        "premium": PREMIUM_COMPUTE_ENABLED,
        "burst": burst,
        "burst_gated": burst_gated,
        "label": label,
        "message": message,
    }
