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


# ── Registration (wizard writes new items into Context Forge) ────────────────
#
# These models let the wizard register tools, agents, gateways, and servers
# directly from the UI without needing to use curl or the Forge admin UI.
#


class RegisterToolIn(BaseModel):
    name: str = Field(description="Unique tool name")
    description: str = Field(default="", description="Human-readable description")
    input_schema: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema for tool parameters",
    )
    integration_type: str = Field(default="REST", description="REST | MCP | A2A")
    url: Optional[str] = Field(default=None, description="Tool endpoint URL (for REST tools)")
    request_type: str = Field(default="POST", description="HTTP method for REST tools")
    tags: List[str] = Field(default_factory=list)
    visibility: str = Field(default="public", description="public | team | private")


class RegisterAgentIn(BaseModel):
    name: str = Field(description="Unique agent name")
    description: str = Field(default="", description="Human-readable description")
    endpoint_url: str = Field(description="Agent endpoint URL (required)")
    agent_type: str = Field(default="generic", description="generic | anthropic | openai | custom")
    protocol_version: str = Field(default="1.0")
    tags: List[str] = Field(default_factory=list)
    visibility: str = Field(default="public", description="public | team | private")


class RegisterGatewayIn(BaseModel):
    name: str = Field(description="Unique gateway name")
    url: str = Field(description="MCP server endpoint URL")
    transport: str = Field(default="SSE", description="SSE | STREAMABLEHTTP | HTTP | STDIO")
    description: str = Field(default="")
    tags: List[str] = Field(default_factory=list)
    visibility: str = Field(default="public")
    auto_refresh: bool = Field(default=True, description="Trigger tool refresh after registration")


class CreateServerIn(BaseModel):
    name: str = Field(description="Virtual server name")
    description: str = Field(default="")
    tool_ids: List[str] = Field(default_factory=list, description="Tool IDs to include")
    tags: List[str] = Field(default_factory=list)
    visibility: str = Field(default="public")


class RegisterOut(BaseModel):
    ok: bool = True
    id: str = Field(default="", description="Forge-assigned ID for the new resource")
    name: str = Field(default="")
    detail: str = Field(default="", description="Human-readable status or error message")


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
