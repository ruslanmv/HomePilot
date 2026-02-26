"""MCP Server Manager — install, uninstall, and lifecycle management.

Manages optional MCP servers as child processes.  Core servers are always
started by agentic-start.sh; optional servers can be installed/uninstalled
via the API.

Install:
  1. Start uvicorn subprocess on the designated port
  2. Wait for /health
  3. Discover tools via JSON-RPC tools/list
  4. Register tools in Context Forge
  5. Trigger a full sync to update virtual server tool associations
  6. Persist to installed.json

Uninstall:
  1. Deactivate tools in Forge (disable, don't delete)
  2. Trigger sync to update virtual server associations
  3. Stop the subprocess (SIGTERM)
  4. Remove from installed.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

logger = logging.getLogger("homepilot.agentic.server_manager")

MCP_TOOL_HOST = os.getenv("MCP_TOOL_HOST", "127.0.0.1")


# ── Server Catalog ────────────────────────────────────────────────────────


def _catalog_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[3] / "agentic" / "forge" / "templates" / "server_catalog.yaml",
        Path("agentic/forge/templates/server_catalog.yaml"),
        Path(os.environ.get("HOMEPILOT_ROOT", ".")) / "agentic" / "forge" / "templates" / "server_catalog.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _load_catalog() -> Dict[str, Any]:
    path = _catalog_path()
    if not path.exists():
        logger.warning("server_catalog.yaml not found at %s", path)
        return {"core": [], "optional": []}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"core": [], "optional": []}


class ServerDef:
    """A server definition from the catalog."""

    def __init__(self, data: Dict[str, Any], is_core: bool = False):
        self.id: str = data["id"]
        self.port: int = data["port"]
        self.module: str = data["module"]
        self.label: str = data.get("label", self.id)
        self.description: str = data.get("description", "")
        self.category: str = data.get("category", "other")
        self.icon: str = data.get("icon", "server")
        self.requires_config: Optional[str] = data.get("requires_config")
        self.is_core: bool = is_core

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "port": self.port,
            "module": self.module,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "requires_config": self.requires_config,
            "is_core": self.is_core,
        }


# ── Installed State Persistence ──────────────────────────────────────────


def _state_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[3] / "agentic" / "forge" / "installed.json",
        Path("agentic/forge/installed.json"),
        Path(os.environ.get("HOMEPILOT_ROOT", ".")) / "agentic" / "forge" / "installed.json",
    ]
    for p in candidates:
        if p.parent.is_dir():
            return p
    return candidates[0]


def _read_installed() -> Dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"installed": []}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"installed": []}


def _write_installed(state: Dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ── Server Manager ───────────────────────────────────────────────────────


class ServerManager:
    """Manages MCP server processes and Forge registration."""

    def __init__(self) -> None:
        catalog = _load_catalog()
        self._core = [ServerDef(d, is_core=True) for d in catalog.get("core", [])]
        self._optional = [ServerDef(d, is_core=False) for d in catalog.get("optional", [])]
        self._all: Dict[str, ServerDef] = {}
        for s in self._core + self._optional:
            self._all[s.id] = s
        # PID tracking for managed (optional) processes
        self._processes: Dict[str, subprocess.Popen] = {}

    @property
    def core_servers(self) -> List[ServerDef]:
        return list(self._core)

    @property
    def optional_servers(self) -> List[ServerDef]:
        return list(self._optional)

    def get_server(self, server_id: str) -> Optional[ServerDef]:
        return self._all.get(server_id)

    def installed_ids(self) -> List[str]:
        state = _read_installed()
        return [e["id"] for e in state.get("installed", []) if e.get("id")]

    def is_installed(self, server_id: str) -> bool:
        return server_id in self.installed_ids()

    def _python_path(self) -> str:
        """Resolve the Python interpreter to use for subprocesses."""
        root = Path(__file__).resolve().parents[3]
        venv_python = root / "backend" / ".venv" / "bin" / "python"
        if venv_python.is_file():
            return str(venv_python)
        return sys.executable

    def _project_root(self) -> str:
        return str(Path(__file__).resolve().parents[3])

    async def _check_health(self, port: int, timeout: int = 10) -> bool:
        for _ in range(timeout):
            try:
                async with httpx.AsyncClient(timeout=2.0) as c:
                    r = await c.get(f"http://{MCP_TOOL_HOST}:{port}/health")
                    if r.status_code == 200:
                        return True
            except Exception:
                pass
            await asyncio.sleep(1)
        return False

    async def _discover_tools(self, port: int) -> List[Dict[str, Any]]:
        url = f"http://{MCP_TOOL_HOST}:{port}/rpc"
        body = {"jsonrpc": "2.0", "id": "mgr-discover", "method": "tools/list"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(url, json=body)
                if r.status_code == 200:
                    return r.json().get("result", {}).get("tools", [])
        except Exception as exc:
            logger.warning("Tool discovery on port %d failed: %s", port, exc)
        return []

    async def _register_tools_in_forge(
        self,
        tools: List[Dict[str, Any]],
        port: int,
        forge_url: str,
        auth_user: str = "admin",
        auth_pass: str = "changeme",
        bearer_token: Optional[str] = None,
    ) -> List[str]:
        """Register discovered tools in Forge. Returns list of registered tool IDs."""
        from .sync_service import _acquire_jwt, _post, _safe_list, _get

        registered_ids: List[str] = []
        async with httpx.AsyncClient(headers={"Content-Type": "application/json"}, timeout=30.0) as client:
            if bearer_token:
                client.headers["Authorization"] = f"Bearer {bearer_token}"
            else:
                token = await _acquire_jwt(client, forge_url, auth_user, auth_pass)
                if token:
                    client.headers["Authorization"] = f"Bearer {token}"
                else:
                    client.auth = httpx.BasicAuth(auth_user, auth_pass)

            # Get existing tools to avoid duplicates (limit=0 bypasses pagination)
            try:
                existing_list = _safe_list(await _get(client, forge_url, "/tools", limit=0))
            except Exception:
                existing_list = []
            existing = {t["name"]: t["id"] for t in existing_list if t.get("name") and t.get("id")}

            for tool_def in tools:
                tname = tool_def.get("name", "")
                if tname in existing:
                    registered_ids.append(existing[tname])
                    continue

                payload = {
                    "tool": {
                        "name": tname,
                        "description": tool_def.get("description", ""),
                        "inputSchema": tool_def.get("inputSchema", {"type": "object", "properties": {}}),
                        "integration_type": "REST",
                        "request_type": "POST",
                        "url": f"http://{MCP_TOOL_HOST}:{port}/rpc",
                        "tags": ["homepilot"],
                    },
                    "team_id": None,
                }
                try:
                    result = await _post(client, forge_url, "/tools", json=payload)
                    tid = result.get("id") or result.get("tool_id") if isinstance(result, dict) else None
                    if tid:
                        registered_ids.append(tid)
                except Exception as exc:
                    logger.warning("Failed to register tool '%s': %s", tname, exc)

        return registered_ids

    async def _deactivate_tools_in_forge(
        self,
        port: int,
        forge_url: str,
        auth_user: str = "admin",
        auth_pass: str = "changeme",
        bearer_token: Optional[str] = None,
    ) -> int:
        """Deactivate tools from this server in Forge. Returns count deactivated."""
        from .sync_service import _acquire_jwt, _safe_list, _get

        deactivated = 0
        expected_url = f"http://{MCP_TOOL_HOST}:{port}/rpc"

        async with httpx.AsyncClient(headers={"Content-Type": "application/json"}, timeout=30.0) as client:
            if bearer_token:
                client.headers["Authorization"] = f"Bearer {bearer_token}"
            else:
                token = await _acquire_jwt(client, forge_url, auth_user, auth_pass)
                if token:
                    client.headers["Authorization"] = f"Bearer {token}"
                else:
                    client.auth = httpx.BasicAuth(auth_user, auth_pass)

            try:
                tools_list = _safe_list(await _get(client, forge_url, "/tools", limit=0))
            except Exception:
                tools_list = []

            for t in tools_list:
                tool_url = str(t.get("url") or "")
                if tool_url == expected_url and t.get("enabled") is not False:
                    tid = t.get("id")
                    if not tid:
                        continue
                    # Deactivate via POST /tools/{id}/state?activate=false
                    try:
                        r = await client.post(
                            f"{forge_url}/tools/{tid}/state?activate=false",
                        )
                        if r.status_code < 400:
                            deactivated += 1
                    except Exception as exc:
                        logger.debug("Failed to deactivate tool %s: %s", tid, exc)

        return deactivated

    def _start_process(self, server: ServerDef) -> Optional[subprocess.Popen]:
        """Start a uvicorn subprocess for the server."""
        python = self._python_path()
        root = self._project_root()
        env = {**os.environ, "PYTHONPATH": root}

        try:
            proc = subprocess.Popen(
                [python, "-m", "uvicorn", server.module,
                 "--host", "127.0.0.1", "--port", str(server.port),
                 "--log-level", "warning"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._processes[server.id] = proc
            logger.info("Started %s (pid=%d, port=%d)", server.id, proc.pid, server.port)
            return proc
        except Exception as exc:
            logger.error("Failed to start %s: %s", server.id, exc)
            return None

    def _stop_process(self, server_id: str) -> bool:
        """Stop a managed subprocess."""
        proc = self._processes.pop(server_id, None)
        if proc is None:
            return False
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        except Exception as exc:
            logger.warning("Error stopping %s: %s", server_id, exc)
        logger.info("Stopped %s", server_id)
        return True

    async def server_healthy(self, server_id: str) -> bool:
        """Check if a server is responding on its port."""
        server = self.get_server(server_id)
        if not server:
            return False
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"http://{MCP_TOOL_HOST}:{server.port}/health")
                return r.status_code == 200
        except Exception:
            return False

    async def install(
        self,
        server_id: str,
        forge_url: str,
        auth_user: str = "admin",
        auth_pass: str = "changeme",
        bearer_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Install an optional MCP server: start process, register tools, update state."""
        server = self.get_server(server_id)
        if not server:
            return {"ok": False, "error": f"Unknown server: {server_id}"}
        if server.is_core:
            return {"ok": False, "error": f"'{server_id}' is a core server (always running)"}
        if self.is_installed(server_id):
            # Already installed — check if healthy
            healthy = await self.server_healthy(server_id)
            if healthy:
                return {"ok": True, "status": "already_installed", "healthy": True}
            # Process died — restart it
            self._stop_process(server_id)

        # 1. Start the process
        proc = self._start_process(server)
        if not proc:
            return {"ok": False, "error": f"Failed to start process for {server_id}"}

        # 2. Wait for health
        healthy = await self._check_health(server.port, timeout=12)
        if not healthy:
            self._stop_process(server_id)
            return {"ok": False, "error": f"Server {server_id} did not become healthy within 12s"}

        # 3. Discover tools
        tools = await self._discover_tools(server.port)

        # 4. Register tools in Forge
        tool_ids = await self._register_tools_in_forge(
            tools, server.port, forge_url, auth_user, auth_pass, bearer_token,
        )

        # 5. Persist installed state
        state = _read_installed()
        ids = {e["id"] for e in state.get("installed", [])}
        if server_id not in ids:
            state.setdefault("installed", []).append({
                "id": server_id,
                "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            _write_installed(state)

        return {
            "ok": True,
            "status": "installed",
            "server_id": server_id,
            "port": server.port,
            "tools_discovered": len(tools),
            "tools_registered": len(tool_ids),
            "healthy": True,
        }

    async def uninstall(
        self,
        server_id: str,
        forge_url: str,
        auth_user: str = "admin",
        auth_pass: str = "changeme",
        bearer_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Uninstall an optional MCP server: deactivate tools, stop process, update state."""
        server = self.get_server(server_id)
        if not server:
            return {"ok": False, "error": f"Unknown server: {server_id}"}
        if server.is_core:
            return {"ok": False, "error": f"'{server_id}' is a core server and cannot be uninstalled"}

        # 1. Deactivate tools in Forge
        deactivated = await self._deactivate_tools_in_forge(
            server.port, forge_url, auth_user, auth_pass, bearer_token,
        )

        # 2. Stop the process
        self._stop_process(server_id)

        # 3. Remove from installed state
        state = _read_installed()
        state["installed"] = [e for e in state.get("installed", []) if e.get("id") != server_id]
        _write_installed(state)

        return {
            "ok": True,
            "status": "uninstalled",
            "server_id": server_id,
            "tools_deactivated": deactivated,
        }

    async def get_available(self) -> List[Dict[str, Any]]:
        """Return all servers with their current status."""
        installed_set = set(self.installed_ids())
        result: List[Dict[str, Any]] = []

        for server in self._core + self._optional:
            healthy = await self.server_healthy(server.id)
            entry = server.to_dict()
            entry["installed"] = server.is_core or server.id in installed_set
            entry["healthy"] = healthy
            entry["status"] = (
                "running" if healthy
                else "installed" if entry["installed"]
                else "available"
            )
            result.append(entry)

        return result

    async def auto_start_core(self) -> List[str]:
        """Start core MCP servers if they aren't already running.

        Core servers are normally started by agentic-start.sh, but if the
        backend is launched independently (e.g. ``uvicorn app.main:app``)
        or if the shell script failed, this ensures they come up.
        """
        started: List[str] = []
        for server in self._core:
            healthy = await self.server_healthy(server.id)
            if healthy:
                continue
            proc = self._start_process(server)
            if proc:
                started.append(server.id)
                logger.info("Auto-started core server %s on port %d", server.id, server.port)
        if started:
            await asyncio.sleep(3)
            # Verify they came up
            for sid in list(started):
                if not await self.server_healthy(sid):
                    logger.warning("Core server %s did not become healthy after auto-start", sid)
        return started

    async def auto_start_installed(self) -> List[str]:
        """Start all previously installed optional servers. Called on backend startup."""
        started: List[str] = []
        for server_id in self.installed_ids():
            server = self.get_server(server_id)
            if not server or server.is_core:
                continue
            # Check if already running (started by agentic-start.sh or another process)
            healthy = await self.server_healthy(server_id)
            if healthy:
                continue
            proc = self._start_process(server)
            if proc:
                started.append(server_id)
        # Brief wait for processes to boot
        if started:
            await asyncio.sleep(2)
        return started

    async def ensure_all_running(self) -> Dict[str, List[str]]:
        """Start all servers that should be running (core + installed optional).

        Called during backend startup to ensure the full agentic stack is up,
        regardless of whether agentic-start.sh ran.
        """
        core_started = await self.auto_start_core()
        optional_started = await self.auto_start_installed()
        if core_started:
            logger.info("Auto-started %d core servers: %s", len(core_started), core_started)
        if optional_started:
            logger.info("Auto-started %d optional servers: %s", len(optional_started), optional_started)
        return {"core": core_started, "optional": optional_started}

    def shutdown_all(self) -> None:
        """Stop all managed subprocesses (called on backend shutdown)."""
        for server_id in list(self._processes.keys()):
            self._stop_process(server_id)


# Module-level singleton
_manager: Optional[ServerManager] = None


def get_server_manager() -> ServerManager:
    global _manager
    if _manager is None:
        _manager = ServerManager()
    return _manager
