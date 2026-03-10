"""MCP Server Installer — Enterprise-grade external MCP server provisioning.

Handles the full lifecycle of installing external MCP servers required by
shared personas:

  1. Analyze: scan persona dependencies for required MCP servers
  2. Resolve: check which servers are already running / in catalog
  3. Clone:   fetch from git into community/shared/bundles/ or community/external/
  4. Install: register in server_catalog.yaml, start process, discover tools
  5. Sync:    register tools in Context Forge, update virtual servers
  6. Report:  return structured installation status for the UI

Designed for hundreds of MCP servers and personas — uses async operations,
structured status reporting, and idempotent install steps.

Compatible with:
  - server_manager.py (subprocess lifecycle)
  - sync_service.py (Forge tool registration)
  - dependency_checker.py (pre-import analysis)
  - install_bundle.py (community bundle installation)
  - export_import.py (persona import pipeline)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("homepilot.agentic.mcp_installer")


# ── Status Types ──────────────────────────────────────────────────────────


class InstallPhase(str, Enum):
    ANALYZING = "analyzing"
    CLONING = "cloning"
    REGISTERING = "registering"
    STARTING = "starting"
    DISCOVERING = "discovering"
    SYNCING = "syncing"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ServerInstallStatus:
    """Real-time status for a single MCP server installation."""
    server_name: str
    phase: InstallPhase = InstallPhase.ANALYZING
    progress_pct: int = 0
    message: str = ""
    error: Optional[str] = None
    port: Optional[int] = None
    tools_discovered: int = 0
    tools_registered: int = 0
    source_type: str = ""  # "external", "community_bundle", "builtin", "registry"
    git_url: str = ""
    install_path: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server_name": self.server_name,
            "phase": self.phase.value,
            "progress_pct": self.progress_pct,
            "message": self.message,
            "error": self.error,
            "port": self.port,
            "tools_discovered": self.tools_discovered,
            "tools_registered": self.tools_registered,
            "source_type": self.source_type,
            "git_url": self.git_url,
            "install_path": self.install_path,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class InstallPlan:
    """Full installation plan for a persona's MCP dependencies."""
    persona_name: str = ""
    servers_needed: List[Dict[str, Any]] = field(default_factory=list)
    servers_already_available: List[Dict[str, Any]] = field(default_factory=list)
    servers_to_install: List[Dict[str, Any]] = field(default_factory=list)
    servers_unresolvable: List[Dict[str, Any]] = field(default_factory=list)
    install_statuses: List[ServerInstallStatus] = field(default_factory=list)
    all_satisfied: bool = False
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "persona_name": self.persona_name,
            "servers_needed": self.servers_needed,
            "servers_already_available": self.servers_already_available,
            "servers_to_install": [
                {
                    "name": s.get("name", ""),
                    "description": s.get("description", ""),
                    "source": s.get("source", {}),
                    "tools_provided": s.get("tools_provided", []),
                    "git_url": s.get("source", {}).get("git", ""),
                }
                for s in self.servers_to_install
            ],
            "servers_unresolvable": self.servers_unresolvable,
            "install_statuses": [s.to_dict() for s in self.install_statuses],
            "all_satisfied": self.all_satisfied,
            "summary": self.summary,
        }


# ── Path Resolution ───────────────────────────────────────────────────────


def _project_root() -> Path:
    """Resolve the HomePilot project root."""
    candidates = [
        Path(__file__).resolve().parents[3],
        Path(os.environ.get("HOMEPILOT_ROOT", ".")),
    ]
    for p in candidates:
        if (p / "backend").is_dir() or (p / "agentic").is_dir():
            return p
    return candidates[0]


def _community_external_dir() -> Path:
    """Directory for cloned external MCP servers."""
    d = _project_root() / "community" / "external"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _community_bundles_dir() -> Path:
    return _project_root() / "community" / "shared" / "bundles"


# ── Port Allocator ────────────────────────────────────────────────────────


_EXTERNAL_PORT_START = 8700
_EXTERNAL_PORT_END = 8999


def _allocate_port(server_name: str) -> int:
    """Allocate a port for an external MCP server.

    Checks the port_map.json and installed.json to avoid conflicts.
    Falls back to scanning the 8700-8999 range.
    """
    root = _project_root()

    # Collect already-used ports
    used_ports: set = set()

    # From community port_map
    port_map_path = root / "community" / "shared" / "registry" / "port_map.json"
    if port_map_path.exists():
        try:
            pm = json.loads(port_map_path.read_text())
            for p in pm.get("allocated", {}):
                used_ports.add(int(p))
        except Exception:
            pass

    # From installed.json
    installed_path = root / "agentic" / "forge" / "installed.json"
    if installed_path.exists():
        try:
            inst = json.loads(installed_path.read_text())
            for entry in inst.get("installed", []):
                if entry.get("port"):
                    used_ports.add(int(entry["port"]))
        except Exception:
            pass

    # From server_catalog.yaml
    try:
        import yaml
        catalog_path = root / "agentic" / "forge" / "templates" / "server_catalog.yaml"
        if catalog_path.exists():
            with catalog_path.open("r") as f:
                cat = yaml.safe_load(f) or {}
            for section in ("core", "optional"):
                for s in cat.get(section, []):
                    if s.get("port"):
                        used_ports.add(int(s["port"]))
    except Exception:
        pass

    # From external install registry
    ext_registry = _community_external_dir() / "registry.json"
    if ext_registry.exists():
        try:
            reg = json.loads(ext_registry.read_text())
            for entry in reg.get("servers", []):
                if entry.get("port"):
                    used_ports.add(int(entry["port"]))
        except Exception:
            pass

    # Also include well-known ports
    used_ports.update({8787, 9101, 9102, 9103, 9104, 9105, 9120})

    # Allocate first available in range
    for port in range(_EXTERNAL_PORT_START, _EXTERNAL_PORT_END + 1):
        if port not in used_ports:
            return port

    raise RuntimeError(f"No available ports in range {_EXTERNAL_PORT_START}-{_EXTERNAL_PORT_END}")


# ── External Server Registry ─────────────────────────────────────────────


def _read_external_registry() -> Dict[str, Any]:
    path = _community_external_dir() / "registry.json"
    if not path.exists():
        return {"schema_version": 1, "servers": []}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"schema_version": 1, "servers": []}


def _write_external_registry(registry: Dict[str, Any]) -> None:
    path = _community_external_dir() / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2))


def _find_in_external_registry(server_name: str) -> Optional[Dict[str, Any]]:
    reg = _read_external_registry()
    for entry in reg.get("servers", []):
        if entry.get("name") == server_name:
            return entry
    return None


def _register_external_server(
    server_name: str,
    port: int,
    git_url: str,
    install_path: str,
    tools_discovered: int,
) -> None:
    reg = _read_external_registry()
    # Remove existing entry with same name (update)
    reg["servers"] = [s for s in reg.get("servers", []) if s.get("name") != server_name]
    reg["servers"].append({
        "name": server_name,
        "port": port,
        "git_url": git_url,
        "install_path": install_path,
        "tools_discovered": tools_discovered,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "installed",
    })
    _write_external_registry(reg)


# ── Analysis: Check What's Needed vs Available ────────────────────────────


async def analyze_mcp_dependencies(
    mcp_servers_dep: Dict[str, Any],
    persona_name: str = "",
) -> InstallPlan:
    """Analyze persona MCP server dependencies and build an install plan.

    Checks each required server against:
      1. Core servers (always running, ports 9101-9120)
      2. Optional servers in server_catalog.yaml
      3. Community bundles in shared/bundles/
      4. External servers already cloned into community/external/
      5. Registry (Discover) servers already installed as gateways

    Returns an InstallPlan with servers categorized as available / to_install / unresolvable.
    """
    plan = InstallPlan(persona_name=persona_name)

    servers = mcp_servers_dep.get("servers", [])
    plan.servers_needed = servers

    if not servers:
        plan.all_satisfied = True
        plan.summary = "No MCP servers required"
        return plan

    # Get currently running/installed servers
    from .server_manager import get_server_manager
    try:
        mgr = get_server_manager()
        available_servers = await mgr.get_available()
        available_ids = {s["id"] for s in available_servers}
        running_ids = {s["id"] for s in available_servers if s.get("status") == "running"}
    except Exception:
        available_ids = set()
        running_ids = set()

    # Check external registry
    ext_registry = _read_external_registry()
    ext_names = {s["name"] for s in ext_registry.get("servers", []) if s.get("status") == "installed"}

    # Check which community bundles are present locally
    local_bundle_ids: set = set()
    try:
        bdir = _community_bundles_dir()
        if bdir.is_dir():
            for bd in bdir.iterdir():
                mp = bd / "bundle_manifest.json"
                if mp.exists():
                    bm = json.loads(mp.read_text())
                    sid = (bm.get("mcp_server", {}).get("server_id") or "").lower()
                    if sid:
                        local_bundle_ids.add(sid)
    except Exception:
        pass

    for server_info in servers:
        name = server_info.get("name", "unknown")
        source = server_info.get("source", {})
        source_type = source.get("type", "unknown")
        git_url = source.get("git", "")

        # Check if already available (builtin/installed/running)
        is_available = (
            name in available_ids
            or name in running_ids
            or name in ext_names
            or source_type == "builtin"
        )

        if is_available:
            plan.servers_already_available.append(server_info)
        elif source_type == "community_bundle" and name.lower() in local_bundle_ids:
            # Bundle present locally — installable
            plan.servers_to_install.append(server_info)
        elif source_type == "community_bundle" and git_url:
            # Bundle not local but has git URL — downloadable
            plan.servers_to_install.append(server_info)
        elif source_type == "external" and git_url:
            plan.servers_to_install.append(server_info)
        elif source_type == "registry":
            plan.servers_to_install.append(server_info)
        else:
            plan.servers_unresolvable.append(server_info)

    plan.all_satisfied = (
        len(plan.servers_to_install) == 0
        and len(plan.servers_unresolvable) == 0
    )

    n_available = len(plan.servers_already_available)
    n_install = len(plan.servers_to_install)
    n_unresolvable = len(plan.servers_unresolvable)
    total = len(servers)

    if plan.all_satisfied:
        plan.summary = f"All {n_available} MCP server(s) available"
    elif n_unresolvable > 0:
        plan.summary = f"{n_available}/{total} available, {n_install} can be auto-installed, {n_unresolvable} need manual setup"
    else:
        plan.summary = f"{n_available}/{total} available, {n_install} can be auto-installed"

    return plan


# ── Clone External Server from Git ────────────────────────────────────────


def _clone_server_from_git(
    git_url: str,
    server_name: str,
    ref: str = "master",
    status: Optional[ServerInstallStatus] = None,
) -> Path:
    """Clone an external MCP server from git into community/external/<name>/.

    Returns the path to the cloned directory.
    """
    dest = _community_external_dir() / server_name

    if dest.exists():
        if status:
            status.message = f"Server {server_name} already cloned, updating..."
        # Pull latest instead of re-clone
        try:
            result = subprocess.run(
                ["git", "-C", str(dest), "pull", "--ff-only"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=60,
            )
            if result.returncode != 0:
                logger.warning("git pull failed for %s: %s", server_name, result.stderr)
        except Exception as exc:
            logger.warning("git pull failed for %s: %s", server_name, exc)
        return dest

    if status:
        status.message = f"Cloning {git_url}..."
        status.phase = InstallPhase.CLONING
        status.progress_pct = 20

    tmp = Path(tempfile.mkdtemp(prefix=f"hp-mcp-{server_name}-"))
    try:
        clone_cmd = ["git", "clone", "--depth", "1"]
        if ref:
            clone_cmd += ["--branch", ref]
        clone_cmd += [git_url, str(tmp / "repo")]

        result = subprocess.run(
            clone_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if result.returncode != 0 and ref:
            # Branch not found — retry without --branch to use repo default
            logger.info("Branch '%s' not found for %s, retrying with default branch", ref, server_name)
            fallback_cmd = ["git", "clone", "--depth", "1", git_url, str(tmp / "repo")]
            result = subprocess.run(
                fallback_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
            )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr.strip()}")

        # Move to final location (remove .git for clean storage)
        repo_dir = tmp / "repo"
        git_dir = repo_dir / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        shutil.move(str(repo_dir), str(dest))
        logger.info("Cloned %s to %s", git_url, dest)

    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)

    return dest


# ── Install Python Dependencies ───────────────────────────────────────────


def _install_python_deps(server_dir: Path, status: Optional[ServerInstallStatus] = None) -> bool:
    """Install Python dependencies for a cloned MCP server.

    Creates a dedicated venv inside the server directory so external
    servers don't pollute the HomePilot backend environment.  Falls back
    to the backend venv or ``python -m pip`` if venv creation fails.
    """
    req_file = server_dir / "requirements.txt"
    if not req_file.exists():
        return True  # No deps to install

    if status:
        status.message = "Installing Python dependencies..."
        status.progress_pct = 35

    import sys

    # Create a dedicated venv for this external server
    server_venv = server_dir / ".venv"
    server_pip = server_venv / "bin" / "pip"

    if not server_pip.is_file():
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(server_venv)],
                capture_output=True, encoding="utf-8", errors="replace", timeout=60,
            )
        except Exception as exc:
            logger.debug("venv creation failed for %s: %s", server_dir.name, exc)

    # Resolve pip: server venv → backend venv → python -m pip
    pip_cmd: list[str] = []
    candidates = [
        server_venv / "bin" / "pip",
        _project_root() / "backend" / ".venv" / "bin" / "pip",
        Path(sys.executable).parent / "pip",
    ]
    for c in candidates:
        if c.is_file():
            pip_cmd = [str(c)]
            break
    if not pip_cmd:
        pip_cmd = [sys.executable, "-m", "pip"]

    try:
        result = subprocess.run(
            pip_cmd + ["install", "-r", str(req_file), "--quiet"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=180,
        )
        if result.returncode != 0:
            logger.warning("pip install failed for %s: %s", server_dir.name, result.stderr)
            return False
        return True
    except Exception as exc:
        logger.warning("pip install failed for %s: %s", server_dir.name, exc)
        return False


# ── Start External Server Process ─────────────────────────────────────────


async def _start_external_server(
    server_dir: Path,
    port: int,
    server_name: str,
    status: Optional[ServerInstallStatus] = None,
) -> Optional[subprocess.Popen]:
    """Start an external MCP server process.

    Detects the server type:
      - Python (app/main.py) → python -m app.main --http --port <port>
      - Python (app.py)      → uvicorn app:app --port <port>
      - Node (index.js)      → node index.js --port <port>
    """
    if status:
        status.message = f"Starting server on port {port}..."
        status.phase = InstallPhase.STARTING
        status.progress_pct = 50

    import sys

    # Prefer the server's own venv (created by _install_python_deps),
    # then fall back to the backend venv, then to the current interpreter.
    server_python = server_dir / ".venv" / "bin" / "python"
    backend_python = _project_root() / "backend" / ".venv" / "bin" / "python"
    if server_python.is_file():
        python = server_python
    elif backend_python.is_file():
        python = backend_python
    else:
        python = Path(sys.executable)

    env = {**os.environ, "PYTHONPATH": str(server_dir)}

    # Detect entry point
    main_py = server_dir / "app" / "main.py"
    app_py = server_dir / "app.py"

    if main_py.exists():
        cmd = [str(python), "-m", "app.main", "--http",
               "--host", "127.0.0.1", "--port", str(port)]
    elif app_py.exists():
        cmd = [str(python), "-m", "uvicorn", "app:app",
               "--host", "127.0.0.1", "--port", str(port),
               "--log-level", "warning"]
    else:
        logger.error("Cannot detect entry point for %s", server_name)
        return None

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(server_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Started external server %s (pid=%d, port=%d)", server_name, proc.pid, port)
        return proc
    except Exception as exc:
        logger.error("Failed to start %s: %s", server_name, exc)
        return None


async def _wait_for_health(port: int, timeout: int = 15) -> bool:
    """Wait for a server to become healthy."""
    import httpx
    host = os.getenv("MCP_TOOL_HOST", "127.0.0.1")
    for _ in range(timeout):
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"http://{host}:{port}/health")
                if r.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


# ── Discover & Register Tools ─────────────────────────────────────────────


async def _discover_and_register(
    port: int,
    server_name: str,
    forge_url: str,
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
    status: Optional[ServerInstallStatus] = None,
) -> tuple[int, int]:
    """Discover tools from an MCP server and register them in Forge.

    Returns (tools_discovered, tools_registered).
    """
    import httpx
    host = os.getenv("MCP_TOOL_HOST", "127.0.0.1")

    if status:
        status.message = "Discovering tools..."
        status.phase = InstallPhase.DISCOVERING
        status.progress_pct = 65

    # Discover tools via JSON-RPC
    url = f"http://{host}:{port}/rpc"
    body = {"jsonrpc": "2.0", "id": "install-discover", "method": "tools/list"}
    tools: list = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json=body)
            if r.status_code == 200:
                tools = r.json().get("result", {}).get("tools", [])
    except Exception as exc:
        logger.warning("Tool discovery failed for %s: %s", server_name, exc)

    discovered = len(tools)
    if status:
        status.tools_discovered = discovered
        status.message = f"Found {discovered} tools, registering in Forge..."
        status.phase = InstallPhase.SYNCING
        status.progress_pct = 80

    if not tools:
        return discovered, 0

    # Register in Forge
    from .sync_service import _acquire_jwt, _post, _safe_list, _get

    registered = 0
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

            # Check existing tools
            try:
                existing_list = _safe_list(await _get(client, forge_url, "/tools", limit=0))
            except Exception:
                existing_list = []
            existing = {t["name"]: t["id"] for t in existing_list if t.get("name") and t.get("id")}

            for tool_def in tools:
                tname = tool_def.get("name", "")
                if tname in existing:
                    registered += 1
                    continue

                payload = {
                    "tool": {
                        "name": tname,
                        "description": tool_def.get("description", ""),
                        "inputSchema": tool_def.get("inputSchema", {"type": "object", "properties": {}}),
                        "integration_type": "REST",
                        "request_type": "POST",
                        "url": f"http://{host}:{port}/rpc",
                        "tags": ["homepilot", "external"],
                    },
                    "team_id": None,
                }
                try:
                    result = await _post(client, forge_url, "/tools", json=payload)
                    if isinstance(result, dict) and (result.get("id") or result.get("tool_id")):
                        registered += 1
                except Exception as exc:
                    logger.warning("Failed to register tool '%s': %s", tname, exc)

    except Exception as exc:
        logger.warning("Forge registration failed for %s: %s", server_name, exc)

    if status:
        status.tools_registered = registered

    return discovered, registered


# ── Community Bundle Install ──────────────────────────────────────────────


async def install_community_bundle(
    server_info: Dict[str, Any],
    forge_url: str,
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
) -> ServerInstallStatus:
    """Install a community bundle MCP server.

    Handles both locally-present bundles and git-fetched ones:
      1. Clone from git if not present locally
      2. Create entry point in integrations/
      3. Append YAML catalog entries
      4. Start server process
      5. Discover tools & register in Forge
      6. Sync virtual servers
    """
    name = server_info.get("name", "unknown")
    source = server_info.get("source", {})
    bundle_id = source.get("bundle_id", "")
    git_url = source.get("git", "")
    ref = source.get("ref", "main") or "main"
    port = server_info.get("default_port") or 0

    status = ServerInstallStatus(
        server_name=name,
        source_type="community_bundle",
        git_url=git_url,
    )
    start_time = time.monotonic()

    try:
        bundles_dir = _community_bundles_dir()
        bundle_dir = bundles_dir / bundle_id if bundle_id else None

        # Step 1: If bundle not present locally, clone from git
        if not bundle_dir or not bundle_dir.exists():
            if not git_url:
                status.phase = InstallPhase.FAILED
                status.error = f"Bundle '{bundle_id}' not found locally and no git URL"
                status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return status

            status.phase = InstallPhase.CLONING
            status.progress_pct = 10
            status.message = f"Cloning bundle from {git_url}..."

            tmp = Path(tempfile.mkdtemp(prefix=f"hp-bundle-{name}-"))
            try:
                clone_cmd = ["git", "clone", "--depth", "1"]
                if ref:
                    clone_cmd += ["--branch", ref]
                clone_cmd += [git_url, str(tmp / "repo")]
                result = subprocess.run(clone_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
                if result.returncode != 0:
                    raise RuntimeError(f"git clone failed: {result.stderr.strip()}")

                repo_dir = tmp / "repo"
                git_d = repo_dir / ".git"
                if git_d.exists():
                    shutil.rmtree(git_d)

                # Read manifest to get bundle_id
                manifest_path = repo_dir / "bundle_manifest.json"
                if manifest_path.exists():
                    bm = json.loads(manifest_path.read_text())
                    bundle_id = bm.get("bundle_id", bundle_id)
                    port = bm.get("mcp_server", {}).get("port", port)

                dest = bundles_dir / bundle_id
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(repo_dir), str(dest))
                bundle_dir = dest
                logger.info("Cloned bundle %s to %s", bundle_id, dest)
            finally:
                if tmp.exists():
                    shutil.rmtree(tmp, ignore_errors=True)

        # Step 2: Read bundle manifest for server details
        bm = {}
        manifest_path = bundle_dir / "bundle_manifest.json"
        if manifest_path.exists():
            bm = json.loads(manifest_path.read_text())
            mcp_cfg = bm.get("mcp_server", {})
            port = port or mcp_cfg.get("port", 0)
            name = mcp_cfg.get("server_id", name)

        if not port:
            port = _allocate_port(name)

        status.port = port
        status.install_path = str(bundle_dir)

        # Step 3: Create entry point & register catalog
        status.phase = InstallPhase.REGISTERING
        status.progress_pct = 30
        status.message = "Registering MCP server in catalog..."

        root = _project_root()
        slug = name.replace("hp-community-", "").replace("-", "_")
        mcp_integrations = root / "agentic" / "integrations" / "mcp"
        entry_point = mcp_integrations / f"community_{slug}_server.py"

        if not entry_point.exists() and mcp_integrations.is_dir():
            entry_content = (
                f"# Auto-installed from community/shared/bundles/{bundle_id}\n"
                f"from community.shared.bundles.{bundle_id}.mcp_server.app import app  # noqa: F401\n"
            )
            entry_point.write_text(entry_content)

        # Step 4: Append YAML catalog entries (idempotent)
        forge_templates = root / "agentic" / "forge" / "templates"
        for yaml_name in ("server_catalog_entry.yaml", "gateway_entry.yaml", "virtual_server_entry.yaml"):
            entry_file = bundle_dir / "forge" / yaml_name
            target_name = yaml_name.replace("_entry", "")
            target_path = forge_templates / target_name
            if entry_file.exists() and target_path.exists():
                content = target_path.read_text()
                if name not in content:
                    entry_text = entry_file.read_text().strip()
                    content += f"\n\n  # ── Community: {bundle_id} ──\n"
                    for line in entry_text.split("\n"):
                        if not line.startswith("#"):
                            content += f"  {line}\n"
                    target_path.write_text(content)

        # Step 5: Start server
        status.phase = InstallPhase.STARTING
        status.progress_pct = 50
        status.message = f"Starting server on port {port}..."

        server_dir = bundle_dir / "mcp_server"
        if not server_dir.exists():
            server_dir = bundle_dir

        proc = await _start_external_server(server_dir, port, name, status=status)
        if not proc:
            # Try with uvicorn module path from manifest
            module = bm.get("mcp_server", {}).get("module", "")
            if module:
                python = root / "backend" / ".venv" / "bin" / "python"
                if not python.is_file():
                    import sys as _sys
                    python = Path(_sys.executable)
                env = {**os.environ, "PYTHONPATH": str(root)}
                try:
                    proc = subprocess.Popen(
                        [str(python), "-m", "uvicorn", module,
                         "--host", "127.0.0.1", "--port", str(port),
                         "--log-level", "warning"],
                        env=env, cwd=str(root),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    proc = None

            if not proc:
                status.phase = InstallPhase.FAILED
                status.error = "Failed to start server process"
                status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return status

        # Step 6: Wait for health
        status.progress_pct = 60
        status.message = "Waiting for server health..."
        healthy = await _wait_for_health(port, timeout=15)
        if not healthy:
            proc.terminate()
            status.phase = InstallPhase.FAILED
            status.error = "Server did not become healthy within 15s"
            status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return status

        # Step 7: Discover tools & register in Forge
        discovered, registered = await _discover_and_register(
            port, name, forge_url, auth_user, auth_pass, bearer_token, status=status,
        )

        # Step 8: Track in external registry
        _register_external_server(
            name, port,
            git_url or f"community_bundle:{bundle_id}",
            str(bundle_dir), discovered,
        )

        # Step 9: Sync
        status.phase = InstallPhase.SYNCING
        status.progress_pct = 90
        status.message = "Syncing with Context Forge..."
        try:
            from .sync_service import sync_homepilot
            await sync_homepilot(
                base_url=forge_url, auth_user=auth_user,
                auth_pass=auth_pass, bearer_token=bearer_token,
            )
        except Exception as exc:
            logger.warning("Post-install sync failed for %s: %s", name, exc)

        status.phase = InstallPhase.COMPLETE
        status.progress_pct = 100
        status.message = f"Installed: {discovered} tools discovered, {registered} registered"

    except Exception as exc:
        status.phase = InstallPhase.FAILED
        status.error = str(exc)
        logger.error("Bundle install failed for %s: %s", name, exc, exc_info=True)

    status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
    return status


# ── Full Install Pipeline ─────────────────────────────────────────────────


async def install_external_server(
    server_info: Dict[str, Any],
    forge_url: str,
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
) -> ServerInstallStatus:
    """Install a single external MCP server: clone → deps → start → register → sync.

    Full pipeline with structured status reporting.
    """
    name = server_info.get("name", "unknown")
    source = server_info.get("source", {})
    git_url = source.get("git", "")
    ref = source.get("ref", "master") or "master"

    status = ServerInstallStatus(
        server_name=name,
        source_type=source.get("type", "external"),
        git_url=git_url,
    )
    start_time = time.monotonic()

    try:
        # Check if already installed in external registry
        existing = _find_in_external_registry(name)
        if existing and existing.get("status") == "installed":
            port = existing["port"]
            healthy = await _wait_for_health(port, timeout=3)
            if healthy:
                status.phase = InstallPhase.SKIPPED
                status.progress_pct = 100
                status.message = f"Already installed and running on port {port}"
                status.port = port
                status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return status

        # Step 1: Clone from git
        if not git_url:
            status.phase = InstallPhase.FAILED
            status.error = f"No git URL provided for server '{name}'"
            status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return status

        status.phase = InstallPhase.CLONING
        status.progress_pct = 10
        status.message = f"Cloning {name} from {git_url}..."

        server_dir = _clone_server_from_git(git_url, name, ref=ref, status=status)
        status.install_path = str(server_dir)

        # Step 2: Install Python dependencies
        status.progress_pct = 30
        deps_ok = _install_python_deps(server_dir, status=status)
        if not deps_ok:
            logger.warning("Dependency install had issues for %s, continuing anyway", name)

        # Step 3: Allocate port & start server
        port = server_info.get("default_port") or _allocate_port(name)
        status.port = port
        status.phase = InstallPhase.STARTING
        status.progress_pct = 45
        status.message = f"Starting on port {port}..."

        proc = await _start_external_server(server_dir, port, name, status=status)
        if not proc:
            status.phase = InstallPhase.FAILED
            status.error = f"Failed to start server process"
            status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return status

        # Step 4: Wait for health
        status.message = f"Waiting for server to become healthy..."
        status.progress_pct = 55
        healthy = await _wait_for_health(port, timeout=20)
        if not healthy:
            proc.terminate()
            status.phase = InstallPhase.FAILED
            status.error = f"Server did not become healthy within 20s"
            status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return status

        # Step 5: Discover tools & register in Forge
        discovered, registered = await _discover_and_register(
            port, name, forge_url, auth_user, auth_pass, bearer_token, status=status,
        )

        # Step 6: Register in external server registry
        _register_external_server(name, port, git_url, str(server_dir), discovered)

        # Step 7: Trigger full sync to update virtual servers
        status.phase = InstallPhase.SYNCING
        status.progress_pct = 90
        status.message = "Syncing with Context Forge..."
        try:
            from .sync_service import sync_homepilot
            await sync_homepilot(
                base_url=forge_url,
                auth_user=auth_user,
                auth_pass=auth_pass,
                bearer_token=bearer_token,
            )
        except Exception as exc:
            logger.warning("Post-install sync failed for %s: %s", name, exc)

        # Done!
        status.phase = InstallPhase.COMPLETE
        status.progress_pct = 100
        status.message = f"Installed: {discovered} tools discovered, {registered} registered"

    except Exception as exc:
        status.phase = InstallPhase.FAILED
        status.error = str(exc)
        logger.error("Install failed for %s: %s", name, exc, exc_info=True)

    status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
    return status


async def install_servers_from_plan(
    plan: InstallPlan,
    forge_url: str,
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
) -> InstallPlan:
    """Execute the install plan: install all servers_to_install sequentially.

    Updates the plan's install_statuses in-place for real-time UI feedback.
    Returns the updated plan with statuses.
    """
    for server_info in plan.servers_to_install:
        source_type = server_info.get("source", {}).get("type", "external")
        if source_type == "community_bundle":
            install_status = await install_community_bundle(
                server_info, forge_url, auth_user, auth_pass, bearer_token,
            )
        else:
            install_status = await install_external_server(
                server_info, forge_url, auth_user, auth_pass, bearer_token,
            )
        plan.install_statuses.append(install_status)

    # Re-evaluate satisfaction
    failed = [s for s in plan.install_statuses if s.phase == InstallPhase.FAILED]
    plan.all_satisfied = len(failed) == 0 and len(plan.servers_unresolvable) == 0

    installed_count = sum(1 for s in plan.install_statuses if s.phase in (InstallPhase.COMPLETE, InstallPhase.SKIPPED))
    total = len(plan.servers_needed)
    available = len(plan.servers_already_available) + installed_count

    if plan.all_satisfied:
        plan.summary = f"All {total} MCP server(s) ready"
    else:
        plan.summary = f"{available}/{total} servers ready, {len(failed)} failed"

    return plan


# ── Convenience: Analyze + Optionally Auto-Install ────────────────────────


async def resolve_persona_mcp_deps(
    dependencies: Dict[str, Any],
    persona_name: str = "",
    auto_install: bool = False,
    forge_url: str = "",
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
) -> InstallPlan:
    """One-shot: analyze persona MCP deps and optionally auto-install missing ones.

    This is the main entry point for the import flow:
      1. Parse dependencies/mcp_servers.json
      2. Build install plan (what's needed, what's available, what needs install)
      3. If auto_install=True, install all missing servers
      4. Return the complete plan with statuses

    Used by:
      - POST /persona/import/resolve-deps (preview + plan)
      - POST /persona/import/install-deps (auto-install)
    """
    mcp_dep = dependencies.get("mcp_servers") or {}
    plan = await analyze_mcp_dependencies(mcp_dep, persona_name)

    if auto_install and plan.servers_to_install:
        if not forge_url:
            forge_url = os.getenv("CONTEXT_FORGE_URL", "http://localhost:4444")
        plan = await install_servers_from_plan(
            plan, forge_url, auth_user, auth_pass, bearer_token,
        )

    return plan
