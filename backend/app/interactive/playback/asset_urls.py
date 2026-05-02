"""
Asset URL resolver for the live-play surface.

``resolve_asset_url(asset_id)`` takes a registered asset id and
returns a URL the player can point a ``<video>`` or ``<img>`` at.
Stub ids (``ixa_stub_*``) return ``None`` — the phase-1 backdrop
stays rendered when there's no real clip.

Keeping this separate from ``render_adapter`` means read-only
paths (``/pending``) don't pull in the render pipeline's imports.
"""
from __future__ import annotations

import logging
from typing import Optional


log = logging.getLogger(__name__)


_STUB_PREFIX = "ixa_stub_"
_PLAYBACK_PREFIX = "ixa_playback_"


def _absolutize_comfy_view_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("/files/"):
        return raw
    if raw.startswith("/view?") or raw.startswith("view?"):
        try:
            from ..media_router import resolve_current_comfy_base_url  # late import
            base = str(resolve_current_comfy_base_url() or "").strip()
        except Exception:
            base = ""
        if base:
            suffix = raw if raw.startswith("/") else f"/{raw}"
            return f"{base.rstrip('/')}{suffix}"
    return raw


def resolve_asset_url(asset_id: str) -> Optional[str]:
    """Look up the durable URL (or file path) for an asset id.

    Returns None for stubs, unknown ids, and any registry errors —
    the player treats None as "keep the idle backdrop".
    """
    if not asset_id:
        return None
    if asset_id.startswith(_STUB_PREFIX):
        return None

    lookup_id = asset_id
    if asset_id.startswith(_PLAYBACK_PREFIX):
        # The playback namespace is a prefix wrapped around the
        # registry's real id; strip it so the registry lookup hits
        # the correct row.
        candidate = asset_id[len(_PLAYBACK_PREFIX):]
        if candidate:
            lookup_id = candidate

    try:
        from ...asset_registry import get_asset  # late import
        record = get_asset(lookup_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("playback_asset_lookup_failed", extra={"asset_id": asset_id, "error": str(exc)[:200]})
        return None

    if not record:
        return None
    storage_key = str(record.get("storage_key") or "").strip()
    if not storage_key:
        return None
    return _absolutize_comfy_view_url(storage_key) or None
