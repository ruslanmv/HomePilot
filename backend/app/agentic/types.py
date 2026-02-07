"""Pydantic models for the agentic layer.

These are the *only* types the frontend ever sees.
MCP / Context Forge internals never leak into the UI contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Status ───────────────────────────────────────────────────────────────────

class AgenticStatusOut(BaseModel):
    enabled: bool = Field(description="Server-wide feature flag")
    configured: bool = Field(description="CONTEXT_FORGE_URL is set")
    reachable: bool = Field(description="Best-effort health ping succeeded")
    admin_configured: bool = Field(description="Admin UI URL is set")


class AgenticAdminOut(BaseModel):
    admin_url: str


# ── Capabilities (dynamic, derived from tools/agents) ────────────────────────

class Capability(BaseModel):
    id: str = Field(description="Stable capability slug")
    label: str = Field(description="Human label")
    description: str = Field(default="")
    category: str = Field(default="general")
    available: bool = Field(default=True)


class CapabilitiesOut(BaseModel):
    capabilities: List[Capability] = []
    source: str = Field(
        default="built_in",
        description="Where capabilities were discovered: built_in, forge, or mixed",
    )


# ── Catalog (wizard-friendly view of Context Forge) ──────────────────────────
#
# Additive contract: the UI may call /v1/agentic/catalog to render real selectable
# MCP tools / A2A agents (and optionally gateways/servers if available).
#


class CatalogTool(BaseModel):
    id: str = Field(description="Context Forge tool id")
    name: str = Field(description="Tool name")
    description: str = Field(default="")
    enabled: Optional[bool] = Field(default=None)


class CatalogA2AAgent(BaseModel):
    id: str = Field(description="Context Forge A2A agent id")
    name: str = Field(description="Agent name")
    description: str = Field(default="")
    enabled: Optional[bool] = Field(default=None)
    endpoint_url: Optional[str] = Field(default=None)


class CatalogGateway(BaseModel):
    id: str = Field(description="Context Forge gateway id")
    name: str = Field(description="Gateway name")
    url: Optional[str] = Field(default=None)
    transport: Optional[str] = Field(default=None)
    enabled: Optional[bool] = Field(default=None)


class CatalogServer(BaseModel):
    id: str = Field(description="Context Forge virtual server id")
    name: str = Field(description="Virtual server name")
    enabled: Optional[bool] = Field(default=None)
    sse_url: Optional[str] = Field(default=None, description="Best-effort SSE endpoint URL")


class AgenticCatalogOut(BaseModel):
    tools: List[CatalogTool] = Field(default_factory=list)
    a2a_agents: List[CatalogA2AAgent] = Field(default_factory=list)
    gateways: List[CatalogGateway] = Field(default_factory=list)
    servers: List[CatalogServer] = Field(default_factory=list)
    capability_sources: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Map capability_id -> list of tool_ids that could implement it",
    )
    source: str = Field(
        default="forge",
        description="Where the catalog came from: forge (best-effort)",
    )


# ── Invoke ───────────────────────────────────────────────────────────────────

class InvokeIn(BaseModel):
    session_key: str = Field(default="chat:default", description="Scope key")
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    intent: str = Field(description="Capability id to execute")
    args: Dict[str, Any] = Field(default_factory=dict)
    profile: str = Field(default="fast", description="fast|balanced|quality")
    ask_before_acting: bool = Field(default=False)
    nsfwMode: Optional[bool] = Field(default=None, description="NSFW generation toggle")


class InvokeOut(BaseModel):
    ok: bool = True
    conversation_id: str = Field(default="", description="Conversation id (may be new)")
    assistant_text: str = Field(default="")
    media: Optional[Dict[str, Any]] = Field(default=None)
    meta: Optional[Dict[str, Any]] = Field(default=None)
