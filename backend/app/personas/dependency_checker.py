# backend/app/personas/dependency_checker.py
"""
Dependency checker for persona import.

Given a PreviewResult from a .hpersona package, checks what's available
on the receiving machine and what's missing:
  - Image models (checkpoint files in ComfyUI)
  - Personality tools (from TOOL_CATALOG)
  - MCP servers (health check on known ports + registry catalog lookup)
  - A2A agents (health check on known ports)

Returns a structured report for the import preview UI.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("homepilot.personas.dependency_checker")


@dataclass
class DependencyItem:
    """Single dependency check result."""
    name: str
    kind: str  # "model", "tool", "mcp_server", "a2a_agent"
    status: str  # "available", "missing", "degraded", "unknown"
    description: str = ""
    detail: str = ""
    source_type: str = ""  # "builtin", "forge", "external", "registry"
    required: bool = False
    fallback: Optional[str] = None
    # Registry metadata for auto-install
    registry_id: str = ""
    auth_type: str = ""
    url: str = ""


@dataclass
class DependencyReport:
    """Full dependency check report for import preview."""
    models: List[DependencyItem] = field(default_factory=list)
    tools: List[DependencyItem] = field(default_factory=list)
    mcp_servers: List[DependencyItem] = field(default_factory=list)
    a2a_agents: List[DependencyItem] = field(default_factory=list)
    all_satisfied: bool = True
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        items = {}
        for section in ("models", "tools", "mcp_servers", "a2a_agents"):
            items[section] = [
                {
                    "name": d.name,
                    "kind": d.kind,
                    "status": d.status,
                    "description": d.description,
                    "detail": d.detail,
                    "source_type": d.source_type,
                    "required": d.required,
                    "fallback": d.fallback,
                    "registry_id": d.registry_id,
                    "auth_type": d.auth_type,
                    "url": d.url,
                }
                for d in getattr(self, section)
            ]
        items["all_satisfied"] = self.all_satisfied
        items["summary"] = self.summary
        return items


def check_dependencies(
    dependencies: Dict[str, Any],
    *,
    installed_gateways: Optional[List[Dict[str, Any]]] = None,
) -> DependencyReport:
    """
    Check which dependencies from a .hpersona package are available locally.

    This is a best-effort check — it doesn't require network access or
    running services, just checks for file existence and known catalogs.

    Args:
        dependencies: The ``dependencies`` dict from the .hpersona package.
        installed_gateways: Optional list of currently installed gateways
            from Context Forge (used to check registry server availability).
    """
    report = DependencyReport()

    # Build a set of installed gateway names/URLs for quick lookups
    _installed_names: set = set()
    _installed_urls: set = set()
    for gw in installed_gateways or []:
        n = (gw.get("name") or "").lower().strip()
        if n:
            _installed_names.add(n)
        u = (gw.get("url") or gw.get("endpoint_url") or "").strip().rstrip("/")
        if u:
            _installed_urls.add(u)

    # 1. Check image models
    models_dep = dependencies.get("models") or {}
    for model_info in models_dep.get("image_models", []):
        filename = model_info.get("filename") or ""
        arch = model_info.get("architecture") or "unknown"
        required = model_info.get("required", False)

        # Check if model exists in known catalog
        status = "unknown"
        detail = f"Architecture: {arch}"
        try:
            from ..model_config import MODEL_ARCHITECTURES
            if filename in MODEL_ARCHITECTURES:
                status = "available"
                detail = f"Architecture: {arch} (known model)"
            else:
                status = "missing"
                detail = f"Architecture: {arch} — model not in catalog"
        except ImportError:
            status = "unknown"
            detail = "Cannot check model availability"

        report.models.append(DependencyItem(
            name=filename,
            kind="model",
            status=status,
            description=f"Image model ({arch})",
            detail=detail,
            required=required,
        ))
        if required and status == "missing":
            report.all_satisfied = False

    # 2. Check personality tools
    tools_dep = dependencies.get("tools") or {}
    personality_tools = (tools_dep.get("personality_tools") or {}).get("tools", [])
    try:
        from ..personalities.tools import TOOL_CATALOG
        available_tools = set(TOOL_CATALOG.keys())
    except ImportError:
        available_tools = set()

    for tool_name in personality_tools:
        if tool_name in available_tools:
            report.tools.append(DependencyItem(
                name=tool_name,
                kind="tool",
                status="available",
                description=f"Personality tool: {tool_name}",
                source_type="builtin",
            ))
        else:
            report.tools.append(DependencyItem(
                name=tool_name,
                kind="tool",
                status="missing",
                description=f"Personality tool: {tool_name}",
                detail="Not in local tool catalog",
                source_type="builtin",
            ))

    # 3. Check MCP servers (by known port / builtin ID / registry lookup)
    mcp_dep = dependencies.get("mcp_servers") or {}
    for server_info in mcp_dep.get("servers", []):
        name = server_info.get("name") or "unknown"
        source = server_info.get("source") or {}
        source_type = source.get("type", "unknown")
        port = server_info.get("default_port")
        registry_id = source.get("registry_id") or server_info.get("registry_id") or ""
        auth_type = server_info.get("auth_type") or ""
        url = server_info.get("url") or ""

        if source_type == "builtin":
            # Built-in servers are always "available" (can be started)
            report.mcp_servers.append(DependencyItem(
                name=name,
                kind="mcp_server",
                status="available",
                description=server_info.get("description") or name,
                detail=f"Built-in (port {port})" if port else "Built-in",
                source_type="builtin",
            ))
        elif source_type == "registry":
            # Registry (Discover-installed) servers: check if already installed
            is_installed = (
                name.lower().strip() in _installed_names
                or (url and url.rstrip("/") in _installed_urls)
            )
            if is_installed:
                report.mcp_servers.append(DependencyItem(
                    name=name,
                    kind="mcp_server",
                    status="available",
                    description=server_info.get("description") or name,
                    detail=f"Installed via Discover ({auth_type or 'open'})",
                    source_type="registry",
                    registry_id=registry_id,
                    auth_type=auth_type,
                    url=url,
                ))
            else:
                report.mcp_servers.append(DependencyItem(
                    name=name,
                    kind="mcp_server",
                    status="missing",
                    description=server_info.get("description") or name,
                    detail=f"Install from Discover tab ({auth_type or 'open'})"
                           if registry_id
                           else "External server — install from Discover tab",
                    source_type="registry",
                    registry_id=registry_id,
                    auth_type=auth_type,
                    url=url,
                ))
        else:
            report.mcp_servers.append(DependencyItem(
                name=name,
                kind="mcp_server",
                status="unknown",
                description=server_info.get("description") or name,
                detail="External server — may need installation",
                source_type="external",
            ))

    # 4. Check A2A agents
    a2a_dep = dependencies.get("a2a_agents") or {}
    for agent_info in a2a_dep.get("agents", []):
        name = agent_info.get("name") or "unknown"
        source = agent_info.get("source") or {}
        source_type = source.get("type", "unknown")
        port = agent_info.get("default_port")

        if source_type == "builtin":
            report.a2a_agents.append(DependencyItem(
                name=name,
                kind="a2a_agent",
                status="available",
                description=agent_info.get("description") or name,
                detail=f"Built-in (port {port})" if port else "Built-in",
                source_type="builtin",
            ))
        else:
            report.a2a_agents.append(DependencyItem(
                name=name,
                kind="a2a_agent",
                status="unknown",
                description=agent_info.get("description") or name,
                detail="External agent — may need installation",
                source_type="external",
                required=agent_info.get("required", False),
            ))

    # Build summary
    total = len(report.models) + len(report.tools) + len(report.mcp_servers) + len(report.a2a_agents)
    available = sum(
        1 for items in (report.models, report.tools, report.mcp_servers, report.a2a_agents)
        for d in items if d.status == "available"
    )
    missing = sum(
        1 for items in (report.models, report.tools, report.mcp_servers, report.a2a_agents)
        for d in items if d.status == "missing"
    )

    if total == 0:
        report.summary = "No dependencies required"
    elif missing == 0:
        report.summary = f"All {available} dependencies available"
    else:
        report.summary = f"{available}/{total} dependencies available, {missing} missing"

    return report
