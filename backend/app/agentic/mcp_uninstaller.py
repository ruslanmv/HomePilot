"""MCP Server Uninstaller — Safe removal of external MCP servers.

Handles the complete uninstall lifecycle with persona-awareness:

  1. Pre-check:  scan all personas/projects for MCP server dependencies
  2. Warn:       return affected personas so the UI can show a confirmation
  3. Disable:    deactivate tools in Forge, stop process, mark as uninstalled
  4. Record:     save which tools were disabled so reinstall can re-enable them
  5. Sync:       trigger full sync to update virtual servers in Context Forge

On **reinstall** (persona re-import or manual server install):
  6. Re-enable:  reactivate previously disabled tools
  7. Re-sync:    update virtual server tool associations

The module is additive — never deletes server files from disk.  External
servers are marked ``status="uninstalled"`` in the registry so they can be
reinstalled later with full history preserved.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("homepilot.agentic.mcp_uninstaller")


# ── Types ────────────────────────────────────────────────────────────────


@dataclass
class AffectedPersona:
    """A persona that depends on the MCP server being uninstalled."""
    project_id: str
    project_name: str
    tools_affected: List[str]  # tool names provided by this server
    is_active: bool = True     # currently loaded / in use

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "tools_affected": self.tools_affected,
            "is_active": self.is_active,
        }


@dataclass
class UninstallPreview:
    """Preview of what will happen if the server is uninstalled."""
    server_name: str
    server_port: Optional[int] = None
    tools_to_deactivate: List[str] = field(default_factory=list)
    affected_personas: List[AffectedPersona] = field(default_factory=list)
    has_dependents: bool = False
    warning: str = ""
    can_uninstall: bool = True  # always True — we warn but don't block

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server_name": self.server_name,
            "server_port": self.server_port,
            "tools_to_deactivate": self.tools_to_deactivate,
            "affected_personas": [p.to_dict() for p in self.affected_personas],
            "has_dependents": self.has_dependents,
            "warning": self.warning,
            "can_uninstall": self.can_uninstall,
        }


@dataclass
class UninstallResult:
    """Result of an uninstall operation."""
    ok: bool = True
    server_name: str = ""
    tools_deactivated: int = 0
    personas_affected: int = 0
    disabled_tools_recorded: bool = False
    sync_completed: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "ok": self.ok,
            "server_name": self.server_name,
            "status": "uninstalled" if self.ok else "failed",
            "tools_deactivated": self.tools_deactivated,
            "personas_affected": self.personas_affected,
            "disabled_tools_recorded": self.disabled_tools_recorded,
            "sync_completed": self.sync_completed,
        }
        if self.error:
            d["error"] = self.error
        return d


# ── Disabled Tools Registry ──────────────────────────────────────────────
# Records which tools were disabled per server so reinstall can re-enable them.
# Stored at community/external/disabled_tools.json


def _disabled_tools_path() -> Path:
    from .mcp_installer import _community_external_dir
    return _community_external_dir() / "disabled_tools.json"


def _read_disabled_tools() -> Dict[str, Any]:
    path = _disabled_tools_path()
    if not path.exists():
        return {"schema_version": 1, "servers": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"schema_version": 1, "servers": {}}


def _write_disabled_tools(data: Dict[str, Any]) -> None:
    path = _disabled_tools_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def record_disabled_tools(
    server_name: str,
    port: int,
    tool_ids: List[str],
    tool_names: List[str],
    affected_personas: List[AffectedPersona],
) -> None:
    """Record which tools were disabled so reinstall can re-enable them."""
    data = _read_disabled_tools()
    data["servers"][server_name] = {
        "port": port,
        "tool_ids": tool_ids,
        "tool_names": tool_names,
        "affected_personas": [p.to_dict() for p in affected_personas],
        "disabled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_disabled_tools(data)
    logger.info(
        "Recorded %d disabled tools for server %s (affects %d personas)",
        len(tool_ids), server_name, len(affected_personas),
    )


def get_disabled_tools(server_name: str) -> Optional[Dict[str, Any]]:
    """Get the disabled tools record for a server (if it was previously uninstalled)."""
    data = _read_disabled_tools()
    return data.get("servers", {}).get(server_name)


def clear_disabled_tools(server_name: str) -> None:
    """Remove the disabled tools record after successful reinstall + re-enable."""
    data = _read_disabled_tools()
    if server_name in data.get("servers", {}):
        del data["servers"][server_name]
        _write_disabled_tools(data)
        logger.info("Cleared disabled tools record for %s", server_name)


# ── Persona Dependency Scanner ───────────────────────────────────────────


def scan_affected_personas(
    server_name: str,
    server_port: Optional[int] = None,
    tools_provided: Optional[List[str]] = None,
) -> List[AffectedPersona]:
    """Scan all projects/personas to find those that depend on this MCP server.

    Checks two sources of dependency:
      1. The persona's ``dependencies/mcp_servers.json`` (server name match)
      2. The persona's ``agentic.tool_details`` (tool URL matches server port)
    """
    from ..projects import list_all_projects

    affected: List[AffectedPersona] = []

    try:
        projects = list_all_projects()
    except Exception as exc:
        logger.warning("Failed to list projects for dependency scan: %s", exc)
        return affected

    # Normalize the server's tool URL for matching
    rpc_url = f"http://127.0.0.1:{server_port}/rpc" if server_port else None
    tools_set = set(tools_provided or [])

    for project in projects:
        if project.get("project_type") not in ("persona", "agent"):
            continue

        project_id = project.get("id", "")
        project_name = project.get("name", "unknown")
        agentic_data = project.get("agentic") or {}
        matched_tools: List[str] = []

        # Method 1: Check tool_details for tools pointing at this server's port
        raw_tool_details = agentic_data.get("tool_details") or {}
        # tool_details may be a list (of dicts) or a dict keyed by tool id
        if isinstance(raw_tool_details, list):
            tool_details: dict = {}
            for entry in raw_tool_details:
                if isinstance(entry, dict):
                    key = entry.get("id") or entry.get("name") or str(len(tool_details))
                    tool_details[key] = entry
        else:
            tool_details = raw_tool_details

        for tool_id, detail in tool_details.items():
            if not isinstance(detail, dict):
                continue
            tool_url = detail.get("url", "")
            tool_name = detail.get("name", tool_id)
            if rpc_url and tool_url == rpc_url:
                matched_tools.append(tool_name)
            elif tool_name in tools_set:
                matched_tools.append(tool_name)

        # Method 2: Check tool_ids list against known tool names
        tool_ids = agentic_data.get("tool_ids") or []
        for tid in tool_ids:
            td = tool_details.get(tid, {})
            name_from_id = (td.get("name") or tid) if isinstance(td, dict) else tid
            if name_from_id in tools_set and name_from_id not in matched_tools:
                matched_tools.append(name_from_id)

        # Method 3: Check the project directory for mcp_servers.json dep file
        if not matched_tools:
            matched_tools = _check_project_dep_file(project_id, server_name)

        if matched_tools:
            affected.append(AffectedPersona(
                project_id=project_id,
                project_name=project_name,
                tools_affected=matched_tools,
                is_active=True,
            ))

    return affected


def _check_project_dep_file(project_id: str, server_name: str) -> List[str]:
    """Check the project's persisted mcp_servers.json dependency file."""
    from .mcp_installer import _project_root

    dep_path = (
        _project_root() / "backend" / "projects" / project_id
        / "persona" / "dependencies" / "mcp_servers.json"
    )
    if not dep_path.exists():
        return []

    try:
        dep_data = json.loads(dep_path.read_text())
        for srv in dep_data.get("servers", []):
            if srv.get("name") == server_name:
                return srv.get("tools_provided", [server_name])
    except Exception:
        pass

    return []


# ── Pre-Uninstall Preview ───────────────────────────────────────────────


async def preview_uninstall(
    server_name: str,
    server_port: Optional[int] = None,
    forge_url: str = "",
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
) -> UninstallPreview:
    """Preview what will happen if this server is uninstalled.

    Returns affected personas, tools that will be deactivated, and warnings.
    Does NOT perform any changes — safe to call at any time.
    """
    import httpx
    from .sync_service import _acquire_jwt, _safe_list, _get

    preview = UninstallPreview(server_name=server_name, server_port=server_port)

    # Find tools registered in Forge that point at this server
    if server_port:
        import os
        host = os.getenv("MCP_TOOL_HOST", "127.0.0.1")
        expected_url = f"http://{host}:{server_port}/rpc"
        try:
            async with httpx.AsyncClient(
                headers={"Content-Type": "application/json"}, timeout=30.0,
            ) as client:
                if bearer_token:
                    client.headers["Authorization"] = f"Bearer {bearer_token}"
                else:
                    token = await _acquire_jwt(client, forge_url, auth_user, auth_pass)
                    if token:
                        client.headers["Authorization"] = f"Bearer {token}"
                    else:
                        client.auth = httpx.BasicAuth(auth_user, auth_pass)

                tools_list = _safe_list(await _get(client, forge_url, "/tools", limit=0))
                for t in tools_list:
                    if str(t.get("url") or "") == expected_url:
                        preview.tools_to_deactivate.append(t.get("name", t.get("id", "?")))
        except Exception as exc:
            logger.warning("Failed to query Forge tools for preview: %s", exc)

    # Scan personas for dependencies
    preview.affected_personas = scan_affected_personas(
        server_name,
        server_port=server_port,
        tools_provided=preview.tools_to_deactivate,
    )
    preview.has_dependents = len(preview.affected_personas) > 0

    if preview.has_dependents:
        names = ", ".join(p.project_name for p in preview.affected_personas[:5])
        count = len(preview.affected_personas)
        extra = f" and {count - 5} more" if count > 5 else ""
        preview.warning = (
            f"Uninstalling {server_name} will disable "
            f"{len(preview.tools_to_deactivate)} tool(s) used by "
            f"{count} persona(s): {names}{extra}. "
            f"You can re-enable them by reinstalling the server or re-importing the persona."
        )

    return preview


# ── Full Uninstall ───────────────────────────────────────────────────────


async def uninstall_external_server(
    server_name: str,
    forge_url: str,
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
    force: bool = False,
) -> UninstallResult:
    """Full uninstall lifecycle for an external MCP server.

    Steps:
      1. Preview: find affected personas and tools
      2. Deactivate tools in Forge
      3. Stop process
      4. Record disabled tools (for re-enable on reinstall)
      5. Mark as uninstalled in registry
      6. Sync with Forge to update virtual servers

    The ``force`` flag skips the preview step (for programmatic use).
    """
    import httpx
    import os
    from .mcp_installer import _read_external_registry, _write_external_registry, install_logger
    from .sync_service import _acquire_jwt, _safe_list, _get
    from .server_manager import get_server_manager

    ilog = install_logger
    result = UninstallResult(server_name=server_name)

    ilog.info(server_name, "uninstall", "=" * 60)
    ilog.info(server_name, "uninstall", f"Starting uninstall of external MCP server: {server_name}")

    # Read registry to find server info
    reg = _read_external_registry()
    entry = next((s for s in reg.get("servers", []) if s.get("name") == server_name), None)
    if not entry:
        ilog.error(server_name, "uninstall", "Server not found in external registry")
        result.ok = False
        result.error = f"External server '{server_name}' not found in registry"
        return result

    port = entry.get("port")
    ilog.info(server_name, "uninstall", f"Found in registry: port={port}, status={entry.get('status')}")

    # Step 1: Preview — find affected personas
    ilog.info(server_name, "uninstall", "Step 1/6: Scanning for affected personas")
    preview = await preview_uninstall(
        server_name, server_port=port,
        forge_url=forge_url, auth_user=auth_user, auth_pass=auth_pass,
        bearer_token=bearer_token,
    )

    if preview.has_dependents:
        ilog.warning(server_name, "uninstall", preview.warning)
        result.personas_affected = len(preview.affected_personas)

    # Step 2: Deactivate tools in Forge & collect their IDs
    ilog.info(server_name, "uninstall", f"Step 2/6: Deactivating {len(preview.tools_to_deactivate)} tools in Forge")
    deactivated = 0
    deactivated_tool_ids: List[str] = []
    if port:
        host = os.getenv("MCP_TOOL_HOST", "127.0.0.1")
        expected_url = f"http://{host}:{port}/rpc"
        try:
            async with httpx.AsyncClient(
                headers={"Content-Type": "application/json"}, timeout=30.0,
            ) as client:
                if bearer_token:
                    client.headers["Authorization"] = f"Bearer {bearer_token}"
                else:
                    token = await _acquire_jwt(client, forge_url, auth_user, auth_pass)
                    if token:
                        client.headers["Authorization"] = f"Bearer {token}"
                    else:
                        client.auth = httpx.BasicAuth(auth_user, auth_pass)

                tools_list = _safe_list(await _get(client, forge_url, "/tools", limit=0))
                for t in tools_list:
                    if str(t.get("url") or "") == expected_url:
                        tid = t.get("id")
                        if not tid:
                            continue
                        try:
                            r = await client.post(
                                f"{forge_url}/tools/{tid}/state?activate=false",
                            )
                            if r.status_code < 400:
                                deactivated += 1
                                deactivated_tool_ids.append(tid)
                                ilog.info(server_name, "uninstall",
                                          f"Deactivated tool: {t.get('name', tid)}")
                        except Exception as exc:
                            ilog.warning(server_name, "uninstall",
                                         f"Failed to deactivate tool {tid}: {exc}")
        except Exception as exc:
            ilog.warning(server_name, "uninstall", f"Failed to deactivate tools: {exc}")

    result.tools_deactivated = deactivated

    # Step 3: Stop the process
    ilog.info(server_name, "uninstall", "Step 3/6: Stopping server process")
    mgr = get_server_manager()
    mgr._stop_process(server_name)

    # Step 4: Record disabled tools for re-enable on reinstall
    ilog.info(server_name, "uninstall", "Step 4/6: Recording disabled tools for future re-enable")
    if deactivated_tool_ids or preview.affected_personas:
        record_disabled_tools(
            server_name=server_name,
            port=port or 0,
            tool_ids=deactivated_tool_ids,
            tool_names=preview.tools_to_deactivate,
            affected_personas=preview.affected_personas,
        )
        result.disabled_tools_recorded = True

    # Step 5: Mark as uninstalled in registry
    ilog.info(server_name, "uninstall", "Step 5/6: Marking as uninstalled in registry")
    for s in reg.get("servers", []):
        if s.get("name") == server_name:
            s["status"] = "uninstalled"
            s["uninstalled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            break
    _write_external_registry(reg)

    # Step 6: Sync with Forge to update virtual servers
    ilog.info(server_name, "uninstall", "Step 6/6: Syncing with Context Forge")
    try:
        from .sync_service import sync_homepilot
        await sync_homepilot(
            base_url=forge_url,
            auth_user=auth_user,
            auth_pass=auth_pass,
            bearer_token=bearer_token,
        )
        result.sync_completed = True
        ilog.info(server_name, "uninstall", "Forge sync completed")
    except Exception as exc:
        ilog.warning(server_name, "uninstall", f"Post-uninstall sync failed: {exc}")

    ilog.info(server_name, "uninstall",
              f"Uninstall complete: {deactivated} tools deactivated, "
              f"{result.personas_affected} personas affected")
    ilog.info(server_name, "uninstall", "=" * 60)

    return result


# ── Re-enable on Reinstall ───────────────────────────────────────────────


async def reenable_after_reinstall(
    server_name: str,
    new_port: int,
    forge_url: str,
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-enable tools that were disabled during a previous uninstall.

    Called automatically after a server is reinstalled (either via persona
    re-import or manual install).  Looks up the disabled_tools.json record,
    finds the matching tools in Forge, and reactivates them.

    Returns summary of what was re-enabled.
    """
    import httpx
    from .sync_service import _acquire_jwt, _safe_list, _get
    from .mcp_installer import install_logger

    ilog = install_logger
    record = get_disabled_tools(server_name)

    if not record:
        ilog.info(server_name, "reenable", "No previous disabled tools record — nothing to re-enable")
        return {"reenabled": 0, "server_name": server_name}

    old_tool_ids = record.get("tool_ids", [])
    old_tool_names = set(record.get("tool_names", []))
    old_port = record.get("port", 0)
    affected_personas = record.get("affected_personas", [])

    ilog.info(server_name, "reenable", "=" * 60)
    ilog.info(server_name, "reenable",
              f"Re-enabling {len(old_tool_ids)} tools previously disabled for {server_name}")
    ilog.info(server_name, "reenable",
              f"Old port: {old_port}, New port: {new_port}")
    if affected_personas:
        names = ", ".join(p.get("project_name", "?") for p in affected_personas[:5])
        ilog.info(server_name, "reenable", f"Personas to restore: {names}")

    reenabled = 0
    try:
        import os
        host = os.getenv("MCP_TOOL_HOST", "127.0.0.1")
        new_url = f"http://{host}:{new_port}/rpc"

        async with httpx.AsyncClient(
            headers={"Content-Type": "application/json"}, timeout=30.0,
        ) as client:
            if bearer_token:
                client.headers["Authorization"] = f"Bearer {bearer_token}"
            else:
                token = await _acquire_jwt(client, forge_url, auth_user, auth_pass)
                if token:
                    client.headers["Authorization"] = f"Bearer {token}"
                else:
                    client.auth = httpx.BasicAuth(auth_user, auth_pass)

            tools_list = _safe_list(await _get(client, forge_url, "/tools", limit=0))

            for t in tools_list:
                tid = t.get("id", "")
                tname = t.get("name", "")
                tool_url = str(t.get("url") or "")

                # Match by: original tool ID, tool name, or URL pointing at new port
                should_reenable = (
                    tid in old_tool_ids
                    or tname in old_tool_names
                    or tool_url == new_url
                )

                if should_reenable and t.get("enabled") is False:
                    try:
                        r = await client.post(
                            f"{forge_url}/tools/{tid}/state?activate=true",
                        )
                        if r.status_code < 400:
                            reenabled += 1
                            ilog.info(server_name, "reenable", f"Re-enabled tool: {tname or tid}")
                    except Exception as exc:
                        ilog.warning(server_name, "reenable",
                                     f"Failed to re-enable tool {tid}: {exc}")

                # If port changed, update the tool URL in Forge
                if should_reenable and old_port != new_port and tool_url and old_port:
                    old_url = f"http://{host}:{old_port}/rpc"
                    if tool_url == old_url:
                        try:
                            r = await client.put(
                                f"{forge_url}/tools/{tid}",
                                json={"tool": {"url": new_url}},
                            )
                            if r.status_code < 400:
                                ilog.info(server_name, "reenable",
                                          f"Updated tool URL: {old_url} → {new_url}")
                        except Exception:
                            pass  # non-critical — tool still works if port unchanged

    except Exception as exc:
        ilog.warning(server_name, "reenable", f"Re-enable failed: {exc}")

    # Clear the disabled tools record now that we've re-enabled them
    if reenabled > 0:
        clear_disabled_tools(server_name)

    ilog.info(server_name, "reenable",
              f"Re-enabled {reenabled}/{len(old_tool_ids)} tools")
    ilog.info(server_name, "reenable", "=" * 60)

    return {
        "reenabled": reenabled,
        "server_name": server_name,
        "new_port": new_port,
        "personas_restored": [p.get("project_name") for p in affected_personas],
    }
