from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

from .client import ContextForgeClient


Json = Dict[str, Any]


async def fetch_catalog(client: ContextForgeClient) -> Json:
    """Fetch tools, gateways, virtual servers, and A2A agents from Context Forge.

    The frontend uses this to populate the agent creation wizard.
    """

    tools, agents, gateways, servers = await asyncio.gather(
        client.list_tools(),
        client.list_agents(),
        client.list_gateways(),
        client.list_servers(),
    )

    now = datetime.now(timezone.utc).isoformat()
    return {
        "last_updated": now,
        "tools": tools,
        "a2a_agents": agents,
        "gateways": gateways,
        "virtual_servers": servers,
    }
