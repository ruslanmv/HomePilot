"""Marketplace API routes — proxies to Matrix Hub for MCP server discovery."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from ..auth import require_api_key
from .settings import MARKETPLACE_ENABLED, MATRIXHUB_BASE_URL
from .types import InstallIn, InstallOut, MarketplaceSearchOut, MarketplaceStatusOut
from . import matrixhub_client, service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/marketplace", tags=["marketplace"])


@router.get("/status", response_model=MarketplaceStatusOut)
async def marketplace_status(_key: str = Depends(require_api_key)):
    """Check if marketplace is configured and reachable."""
    if not MARKETPLACE_ENABLED:
        return MarketplaceStatusOut(enabled=False, hub_url="")

    reachable = await matrixhub_client.ping()
    return MarketplaceStatusOut(enabled=reachable, hub_url=MATRIXHUB_BASE_URL)


@router.get("/search", response_model=MarketplaceSearchOut)
async def marketplace_search(
    q: str = Query("", description="Search query"),
    type: str = Query("mcp_server", description="Entity type filter"),
    limit: int = Query(10, ge=1, le=50),
    _key: str = Depends(require_api_key),
):
    """Search Matrix Hub for MCP servers and other entities."""
    if not MARKETPLACE_ENABLED:
        return MarketplaceSearchOut(results=[], total=0, query=q)

    return await service.search_marketplace(q, entity_type=type, limit=limit)


@router.post("/install", response_model=InstallOut)
async def marketplace_install(
    body: InstallIn,
    _key: str = Depends(require_api_key),
):
    """Install an MCP server from Matrix Hub into Context Forge."""
    if not MARKETPLACE_ENABLED:
        return InstallOut(ok=False, detail="Marketplace is not configured")

    return await service.install_from_marketplace(body.entity_id)
