"""Pydantic models for the marketplace module."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Status ────────────────────────────────────────────────────────────────────

class MarketplaceStatusOut(BaseModel):
    enabled: bool = Field(description="Whether marketplace is configured and reachable")
    hub_url: str = Field(default="", description="Matrix Hub base URL (empty if not configured)")


# ── Search ────────────────────────────────────────────────────────────────────

class MarketplaceItem(BaseModel):
    id: str = Field(description="Entity ID from Matrix Hub")
    name: str = Field(default="")
    description: str = Field(default="")
    author: str = Field(default="")
    install_url: Optional[str] = Field(default=None, description="Manifest URL for installation")
    tags: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict, description="Full raw entity from Hub")


class MarketplaceSearchOut(BaseModel):
    results: List[MarketplaceItem] = Field(default_factory=list)
    total: int = Field(default=0)
    query: str = Field(default="")


# ── Install ───────────────────────────────────────────────────────────────────

class InstallIn(BaseModel):
    entity_id: str = Field(description="Matrix Hub entity ID to install")


class InstallOut(BaseModel):
    ok: bool = True
    detail: str = Field(default="")
    gateway_id: str = Field(default="", description="Forge gateway ID if registered")
