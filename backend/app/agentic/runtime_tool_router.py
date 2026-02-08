"""Runtime tool router: resolves capability -> tool_id and enforces allow-lists.

Additive helper that will be called by /invoke when a project has a
tool_source configured.  It keeps placeholders/legacy behavior working
by returning mode='fallback' if tool_source is missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .catalog_service import AgenticCatalogService
from .client import ContextForgeClient
from .tool_policy import ToolScope, allowed_tool_ids, pick_tool_for_capability

logger = logging.getLogger("homepilot.agentic.runtime_tool_router")


@dataclass
class ToolRouteDecision:
    mode: str  # fallback | none | all | server
    resolved_tool_id: Optional[str]
    reason: str


class RuntimeToolRouter:
    """Resolve and invoke tools safely within a configured scope."""

    def __init__(self, catalog_service: AgenticCatalogService, client: ContextForgeClient):
        self.catalog_service = catalog_service
        self.client = client

    async def resolve(
        self,
        intent: str,
        tool_source: Optional[str],
    ) -> ToolRouteDecision:
        catalog = await self.catalog_service.get_cached(self.client)
        allow, mode = allowed_tool_ids(catalog, ToolScope(tool_source=tool_source))

        if mode == "fallback":
            return ToolRouteDecision(
                mode=mode,
                resolved_tool_id=None,
                reason="No tool_source set; keep legacy placeholder behavior.",
            )
        if mode == "none":
            return ToolRouteDecision(
                mode=mode,
                resolved_tool_id=None,
                reason="Agent configured with no tools.",
            )
        if not allow:
            return ToolRouteDecision(
                mode=mode,
                resolved_tool_id=None,
                reason="No allowed tools available (server missing or empty).",
            )

        tool_id = pick_tool_for_capability(intent, catalog, allow)
        if not tool_id:
            return ToolRouteDecision(
                mode=mode,
                resolved_tool_id=None,
                reason=f"No tool matched capability '{intent}' within allowed set.",
            )
        return ToolRouteDecision(
            mode=mode,
            resolved_tool_id=tool_id,
            reason="Resolved capability to allowed tool.",
        )

    async def invoke(
        self,
        tool_id: str,
        args: Dict[str, Any],
    ) -> Any:
        """Invoke a tool by ID via the existing client."""
        return await self.client.invoke_tool(tool_id, args)
