"""
Caches ComfyUI ``/object_info`` results.

ComfyUI node availability only changes when the server restarts or custom
nodes are added/removed, so a short TTL cache (default 60 s) is sufficient.
The cache is thread-safe (simple read/write of scalars on CPython).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx


class ComfyObjectInfoCache:
    """
    Thin HTTP cache around ``GET <comfy_base_url>/object_info``.

    Usage::

        cache = ComfyObjectInfoCache("http://localhost:8188")
        nodes = cache.get_available_nodes()       # list[str]
        raw   = cache.get_raw()                    # full dict or None
    """

    def __init__(self, base_url: str, ttl_seconds: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self._expires_at: float = 0.0
        self._nodes: Optional[List[str]] = None
        self._raw: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_available_nodes(self, *, force: bool = False) -> List[str]:
        """Return a list of registered ComfyUI node class names."""
        self._refresh(force=force)
        return list(self._nodes) if self._nodes else []

    def get_raw(self, *, force: bool = False) -> Optional[Dict[str, Any]]:
        """Return the raw /object_info dict, or None if unreachable."""
        self._refresh(force=force)
        return self._raw

    def invalidate(self) -> None:
        """Force next call to re-fetch."""
        self._expires_at = 0.0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and self._nodes is not None and now < self._expires_at:
            return  # cache hit

        url = f"{self.base_url}/object_info"
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                r = client.get(url)
                r.raise_for_status()
                raw = r.json()
        except Exception:
            # Can't reach ComfyUI — keep stale data if any, otherwise empty
            return

        self._raw = raw
        self._nodes = list(raw.keys()) if isinstance(raw, dict) else []
        self._expires_at = now + self.ttl_seconds
