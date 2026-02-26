"""HTTP client for Matrix Hub API.

This is a thin wrapper over httpx that handles:
- Search queries  (GET /catalog/search)
- Entity details  (GET /catalog/entities/{id})
- Manifest fetch  (GET <manifest_url>)

The client is stateless and does not cache results.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .settings import MATRIXHUB_BASE_URL, MATRIXHUB_TIMEOUT


async def search(
    query: str,
    entity_type: str = "mcp_server",
    limit: int = 10,
    timeout: float = MATRIXHUB_TIMEOUT,
) -> Dict[str, Any]:
    """Search Matrix Hub catalog.  Returns raw JSON response."""
    if not MATRIXHUB_BASE_URL:
        return {"results": [], "total": 0}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{MATRIXHUB_BASE_URL}/catalog/search",
            params={"q": query, "type": entity_type, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()


async def get_entity(
    entity_id: str,
    timeout: float = MATRIXHUB_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """Fetch a single entity from Matrix Hub."""
    if not MATRIXHUB_BASE_URL:
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{MATRIXHUB_BASE_URL}/catalog/entities/{entity_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


async def fetch_manifest(
    manifest_url: str,
    timeout: float = MATRIXHUB_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """Fetch the MCP server manifest from a given URL."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(manifest_url)
        if resp.status_code != 200:
            return None
        return resp.json()


async def ping(timeout: float = 3.0) -> bool:
    """Check if Matrix Hub is reachable."""
    if not MATRIXHUB_BASE_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{MATRIXHUB_BASE_URL}/health")
            return resp.status_code == 200
    except Exception:
        return False
