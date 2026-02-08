"""Capability discovery — maps MCP tools/agents to stable UI capabilities.

The frontend never sees raw MCP tool IDs.  Instead it gets a curated list
of *capabilities* (generate_images, generate_videos, …) that are resolved
here by querying Context Forge and matching against a known catalogue.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from .client import ContextForgeClient
from .types import AgenticCatalogOut, CatalogA2AAgent, CatalogTool, Capability

logger = logging.getLogger("homepilot.agentic.capabilities")

# ── Known-capability catalogue ────────────────────────────────────────────────
# Each entry maps a *pattern* (substring match on tool name) to a UI capability.
# Order matters: first match wins.

_CATALOGUE: List[Dict[str, Any]] = [
    {
        "id": "generate_images",
        "label": "AI Image Generation",
        "description": "Generate images via MCP-connected models",
        "category": "media",
        "patterns": ["imagine", "image", "sdxl", "flux", "dall", "stable_diffusion"],
    },
    {
        "id": "generate_videos",
        "label": "AI Video Generation",
        "description": "Generate videos via MCP-connected models",
        "category": "media",
        "patterns": ["video", "animate", "svd", "wan", "seedream"],
    },
    {
        "id": "code_analysis",
        "label": "Code Analysis",
        "description": "Analyse, refactor, or explain source code",
        "category": "dev",
        "patterns": ["code", "python_sandbox", "sandbox"],
    },
    {
        "id": "data_analysis",
        "label": "Data Analysis",
        "description": "Analyse CSV/data files and generate charts",
        "category": "data",
        "patterns": ["csv", "pandas", "plotly", "data"],
    },
    {
        "id": "web_search",
        "label": "Web Search",
        "description": "Search the web for current information",
        "category": "knowledge",
        "patterns": ["search", "web", "brave", "google"],
    },
    {
        "id": "document_qa",
        "label": "Document Q&A",
        "description": "Ask questions about uploaded documents",
        "category": "knowledge",
        "patterns": ["document", "pdf", "rag", "retrieval"],
    },
    {
        "id": "story_generation",
        "label": "Story Generation",
        "description": "Generate creative stories with illustrations",
        "category": "creative",
        "patterns": ["story", "narrative", "creative"],
    },
    {
        "id": "agent_chat",
        "label": "Agent Chat",
        "description": "Chat with an A2A agent for complex tasks",
        "category": "agent",
        "patterns": ["agent", "a2a", "langchain", "chat"],
    },
]


def _match_tool(tool_name: str) -> str | None:
    """Return the capability id if *tool_name* matches any catalogue pattern."""
    name_lower = tool_name.lower()
    for entry in _CATALOGUE:
        for pat in entry["patterns"]:
            if pat in name_lower:
                return entry["id"]
    return None


def _capability_sources_from_tools(tools: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Build a best-effort map: capability_id -> [tool_id, ...].

    This does NOT change the existing capability list behavior.
    It's additive metadata to help the wizard and later execution wiring.
    """
    out: Dict[str, List[str]] = {}
    for t in tools:
        if not isinstance(t, dict):
            continue
        tool_id = str(t.get("id") or "")
        name = str(t.get("name") or "")
        if not tool_id or not name:
            continue
        cap_id = _match_tool(name)
        if not cap_id:
            continue
        out.setdefault(cap_id, [])
        if tool_id not in out[cap_id]:
            out[cap_id].append(tool_id)
    return out


# ── Built-in capabilities (always available via HomePilot orchestrator) ────────

_BUILTIN_IDS = {"generate_images", "generate_videos"}


def _builtin_capabilities() -> List[Capability]:
    """Return capabilities that HomePilot supports natively (no MCP required)."""
    return [
        Capability(
            id=entry["id"],
            label=entry["label"],
            description=entry["description"],
            category=entry["category"],
            available=True,
        )
        for entry in _CATALOGUE
        if entry["id"] in _BUILTIN_IDS
    ]


async def discover_capabilities(
    client: ContextForgeClient,
) -> Tuple[List[Capability], str]:
    """Query Context Forge and return (capabilities, source).

    Built-in capabilities (generate_images, generate_videos) are always
    included because they use the local HomePilot orchestrator.  Additional
    capabilities are added dynamically from Context Forge tools/agents.

    Returns:
        Tuple of (list of capabilities, source string).
        source is one of: "built_in", "forge", "mixed".
    """
    seen_ids: set[str] = set()
    caps: List[Capability] = []

    # 0. Always include built-in capabilities
    for cap in _builtin_capabilities():
        caps.append(cap)
        seen_ids.add(cap.id)

    forge_contributed = 0

    # 1. Match registered tools → capabilities
    try:
        tools = await client.list_tools()
    except Exception:
        tools = []
    for tool in tools:
        name = tool.get("name", "") if isinstance(tool, dict) else str(tool)
        cap_id = _match_tool(name)
        if cap_id and cap_id not in seen_ids:
            seen_ids.add(cap_id)
            entry = next(e for e in _CATALOGUE if e["id"] == cap_id)
            caps.append(
                Capability(
                    id=entry["id"],
                    label=entry["label"],
                    description=entry["description"],
                    category=entry["category"],
                    available=True,
                )
            )
            forge_contributed += 1

    # 2. If any A2A agents are registered, surface agent_chat
    try:
        agents = await client.list_agents()
    except Exception:
        agents = []
    if agents and "agent_chat" not in seen_ids:
        entry = next(e for e in _CATALOGUE if e["id"] == "agent_chat")
        caps.append(
            Capability(
                id=entry["id"],
                label=entry["label"],
                description=entry["description"],
                category=entry["category"],
                available=True,
            )
        )
        forge_contributed += 1

    # Determine source
    if forge_contributed > 0 and len(caps) > forge_contributed:
        source = "mixed"
    elif forge_contributed > 0:
        source = "forge"
    else:
        source = "built_in"

    logger.info(
        "Discovered %d capabilities (%d from forge, %d built-in) from %d tools + %d agents",
        len(caps), forge_contributed, len(caps) - forge_contributed, len(tools), len(agents),
    )
    return caps, source


# ── Additive: full catalog discovery for the Agent Creation Wizard ───────────


async def discover_catalog(client: ContextForgeClient) -> AgenticCatalogOut:
    """Return a wizard-friendly catalog of *real* Forge objects.

    - tools: raw tool objects (id/name/description/enabled)
    - a2a_agents: raw agent objects (id/name/description/enabled/endpoint_url)
    - capability_sources: capability_id -> tool_ids that match patterns

    Gateways/servers are fetched separately in routes.py (best-effort)
    so this function stays compatible with the existing thin client.
    """
    try:
        tools = await client.list_tools()
    except Exception:
        tools = []

    try:
        agents = await client.list_agents()
    except Exception:
        agents = []

    catalog_tools: List[CatalogTool] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "")
        name = str(t.get("name") or "")
        if not tid or not name:
            continue
        catalog_tools.append(
            CatalogTool(
                id=tid,
                name=name,
                description=str(t.get("description") or ""),
                enabled=t.get("enabled"),
            )
        )

    catalog_agents: List[CatalogA2AAgent] = []
    for a in agents:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or "")
        name = str(a.get("name") or "")
        if not aid or not name:
            continue
        catalog_agents.append(
            CatalogA2AAgent(
                id=aid,
                name=name,
                description=str(a.get("description") or ""),
                enabled=a.get("enabled"),
                endpoint_url=a.get("endpoint_url") or a.get("endpoint") or None,
            )
        )

    return AgenticCatalogOut(
        tools=catalog_tools,
        a2a_agents=catalog_agents,
        gateways=[],
        servers=[],
        capability_sources=_capability_sources_from_tools(tools),
        source="forge",
    )
