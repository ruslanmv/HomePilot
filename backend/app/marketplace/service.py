"""Business logic for marketplace operations.

Orchestrates: Matrix Hub search → manifest fetch → Forge gateway registration.
"""

from __future__ import annotations

import logging
from typing import Optional

from . import matrixhub_client
from .converters.mcp_server_to_forge_gateway import manifest_to_gateway
from .normalize import normalize_search_results
from .types import InstallOut, MarketplaceItem, MarketplaceSearchOut

logger = logging.getLogger(__name__)


async def search_marketplace(
    query: str,
    entity_type: str = "mcp_server",
    limit: int = 10,
) -> MarketplaceSearchOut:
    """Search Matrix Hub and return normalized results."""
    raw = await matrixhub_client.search(query, entity_type=entity_type, limit=limit)
    items = normalize_search_results(raw)
    return MarketplaceSearchOut(
        results=items,
        total=raw.get("total", len(items)),
        query=query,
    )


async def install_from_marketplace(entity_id: str) -> InstallOut:
    """Install an MCP server from Matrix Hub into Context Forge.

    Flow:
    1. Fetch entity details from Matrix Hub
    2. Get the manifest URL and fetch it
    3. Convert manifest → gateway registration payload
    4. Register gateway in Context Forge via ContextForgeClient (direct call)
    """
    # Lazy import to avoid circular dependencies with agentic module
    from ..agentic.client import ContextForgeClient
    from ..agentic.routes import _client

    # Step 1: Get entity from Matrix Hub
    entity = await matrixhub_client.get_entity(entity_id)
    if not entity:
        return InstallOut(ok=False, detail=f"Entity {entity_id} not found in Matrix Hub")

    entity_name = entity.get("name", entity_id)

    # Step 2: Get manifest URL
    manifest_url = entity.get("manifest_url") or entity.get("install_url")
    if not manifest_url:
        return InstallOut(ok=False, detail=f"No manifest URL found for {entity_name}")

    # Step 3: Fetch and parse manifest
    manifest = await matrixhub_client.fetch_manifest(manifest_url)
    if not manifest:
        return InstallOut(ok=False, detail=f"Failed to fetch manifest from {manifest_url}")

    # Step 4: Convert to gateway payload
    gateway_def = manifest_to_gateway(manifest, entity_name)
    if not gateway_def:
        return InstallOut(
            ok=False,
            detail=f"Manifest for {entity_name} does not contain MCP server registration info",
        )

    # Step 5: Register in Context Forge directly (no self-referencing HTTP call)
    try:
        forge_client = _client()
        result = await forge_client.register_gateway(gateway_def)
        gw_id = result.get("id", "")

        # Auto-refresh tools
        if gw_id:
            try:
                await forge_client.refresh_gateway(gw_id)
            except Exception as e:
                logger.warning("Gateway registered but tool refresh failed: %s", e)

        return InstallOut(
            ok=True,
            detail=f"Installed {entity_name} as gateway",
            gateway_id=gw_id,
        )
    except Exception as e:
        logger.error("Failed to register gateway for %s: %s", entity_name, e)
        return InstallOut(ok=False, detail=f"Forge registration failed: {e}")
