"""Catalog types for the wizard-friendly catalog endpoint.

These are additive types that provide richer metadata than the existing
AgenticCatalogOut model.  They include:
  - ForgeStatus (health + base_url)
  - last_updated timestamp
  - raw dicts for forward-compatibility
  - tool_ids on servers (for allow-list enforcement)

Existing types in types.py are NOT modified.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ForgeStatus(BaseModel):
    base_url: str
    healthy: bool = True
    error: Optional[str] = None


class CatalogTool(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: Optional[bool] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class CatalogA2AAgent(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: Optional[bool] = None
    endpoint_url: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class CatalogGateway(BaseModel):
    id: str
    name: str
    enabled: Optional[bool] = None
    url: Optional[str] = None
    transport: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class CatalogServer(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: Optional[bool] = None
    tool_ids: List[str] = Field(default_factory=list)
    sse_url: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class AgenticCatalog(BaseModel):
    source: str = "forge"
    last_updated: str
    forge: ForgeStatus

    servers: List[CatalogServer] = Field(default_factory=list)
    tools: List[CatalogTool] = Field(default_factory=list)
    a2a_agents: List[CatalogA2AAgent] = Field(default_factory=list)
    gateways: List[CatalogGateway] = Field(default_factory=list)

    capability_sources: Dict[str, List[str]] = Field(default_factory=dict)
