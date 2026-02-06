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
