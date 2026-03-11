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
import datetime
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

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


# ── Installation Log ─────────────────────────────────────────────────────


@dataclass
class InstallLogEntry:
    """A single log line from an installation process."""
    timestamp: str
    server_name: str
    phase: str
    level: str  # "info", "warning", "error", "debug"
    message: str
    detail: str = ""  # optional extended info (command output, etc.)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "server_name": self.server_name,
            "phase": self.phase,
            "level": self.level,
            "message": self.message,
        }
        if self.detail:
            d["detail"] = self.detail
        return d


class InstallLogger:
    """Captures detailed step-by-step installation logs.

    Stores logs in memory (ring buffer) and optionally writes to a log file
    under ``community/external/install_logs/``.  The API can stream or poll
    these entries so the frontend can display real-time installation progress.
    """

    _MAX_ENTRIES = 2000  # per-server ring buffer cap

    def __init__(self) -> None:
        # server_name → deque of entries
        self._logs: Dict[str, Deque[InstallLogEntry]] = {}
        self._log_dir: Optional[Path] = None

    def _ensure_log_dir(self) -> Path:
        if self._log_dir is None:
            self._log_dir = _community_external_dir() / "install_logs"
            self._log_dir.mkdir(parents=True, exist_ok=True)
        return self._log_dir

    def _ts(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")

    def log(
        self,
        server_name: str,
        phase: str,
        level: str,
        message: str,
        detail: str = "",
    ) -> None:
        entry = InstallLogEntry(
            timestamp=self._ts(),
            server_name=server_name,
            phase=phase,
            level=level,
            message=message,
            detail=detail,
        )
        if server_name not in self._logs:
            self._logs[server_name] = deque(maxlen=self._MAX_ENTRIES)
        self._logs[server_name].append(entry)

        # Also emit to Python logger for backend console
        log_fn = getattr(logger, level, logger.info)
        log_fn("[%s/%s] %s%s", server_name, phase, message,
               f" | {detail[:200]}" if detail else "")

        # Append to per-server log file (non-blocking best-effort)
        try:
            log_path = self._ensure_log_dir() / f"{server_name}.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{entry.timestamp}] [{level.upper():7s}] [{phase}] {message}")
                if detail:
                    f.write(f"\n  └─ {detail[:500]}")
                f.write("\n")
        except Exception:
            pass  # non-critical — memory log is authoritative

    def info(self, server_name: str, phase: str, message: str, detail: str = "") -> None:
        self.log(server_name, phase, "info", message, detail)

    def warning(self, server_name: str, phase: str, message: str, detail: str = "") -> None:
        self.log(server_name, phase, "warning", message, detail)

    def error(self, server_name: str, phase: str, message: str, detail: str = "") -> None:
        self.log(server_name, phase, "error", message, detail)

    def debug(self, server_name: str, phase: str, message: str, detail: str = "") -> None:
        self.log(server_name, phase, "debug", message, detail)

    def get_logs(self, server_name: str, since_idx: int = 0) -> List[Dict[str, Any]]:
        """Return log entries for a server, optionally starting from an index."""
        entries = self._logs.get(server_name, deque())
        return [e.to_dict() for e in list(entries)[since_idx:]]

    def get_all_servers(self) -> List[str]:
        """Return names of all servers that have logs."""
        return list(self._logs.keys())

    def get_log_file(self, server_name: str) -> Optional[str]:
        """Return path to the persistent log file, if it exists."""
        p = self._ensure_log_dir() / f"{server_name}.log"
        return str(p) if p.exists() else None


# Global install logger singleton
install_logger = InstallLogger()


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
    force_reinstall: bool = False,
) -> Path:
    """Clone an external MCP server from git into community/external/<name>/.

    Returns the path to the cloned directory.

    If *force_reinstall* is ``True`` (or the existing install is detected as
    broken), the old directory is purged and a fresh clone is performed.
    """
    import shutil
    dest = _community_external_dir() / server_name
    ilog = install_logger

    if dest.exists():
        # Detect broken installs: no venv or missing key files
        venv_ok = (dest / ".venv" / "bin" / "python").is_file()
        has_pyproject = (dest / "pyproject.toml").is_file()
        is_broken = not venv_ok or not has_pyproject

        if force_reinstall or is_broken:
            reason = "force_reinstall requested" if force_reinstall else "detected broken install (missing venv or pyproject.toml)"
            ilog.info(server_name, "clone", f"Purging old install at {dest}: {reason}")
            if status:
                status.message = f"Reinstalling {server_name} (purging old clone)..."
            shutil.rmtree(dest, ignore_errors=True)
        else:
            if status:
                status.message = f"Server {server_name} already cloned, updating..."
            ilog.info(server_name, "clone", f"Directory exists at {dest}, pulling latest")
            # Pull latest instead of re-clone
            try:
                result = subprocess.run(
                    ["git", "-C", str(dest), "pull", "--ff-only"],
                    capture_output=True, encoding="utf-8", errors="replace", timeout=60,
                )
                if result.returncode != 0:
                    ilog.warning(server_name, "clone", "git pull failed", result.stderr.strip())
                else:
                    ilog.info(server_name, "clone", "git pull succeeded", result.stdout.strip())
            except Exception as exc:
                ilog.warning(server_name, "clone", f"git pull exception: {exc}")
            return dest

    if status:
        status.message = f"Cloning {git_url}..."
        status.phase = InstallPhase.CLONING
        status.progress_pct = 20

    ilog.info(server_name, "clone", f"Cloning repository: {git_url} (ref={ref})")
    ilog.info(server_name, "clone", f"Target directory: {dest}")
    print(f"\n{'='*60}")
    print(f"[{server_name}] Cloning {git_url} (ref={ref})")
    print(f"[{server_name}] Target: {dest}")
    print(f"{'='*60}", flush=True)

    tmp = Path(tempfile.mkdtemp(prefix=f"hp-mcp-{server_name}-"))
    try:
        clone_cmd = ["git", "clone", "--depth", "1"]
        if ref:
            clone_cmd += ["--branch", ref]
        clone_cmd += [git_url, str(tmp / "repo")]

        ilog.info(server_name, "clone", f"Running: {' '.join(clone_cmd)}")
        print(f"[{server_name}] Running: {' '.join(clone_cmd)}", flush=True)
        result = subprocess.run(
            clone_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if result.returncode != 0 and ref:
            # Branch not found — retry without --branch to use repo default
            ilog.warning(server_name, "clone",
                         f"Branch '{ref}' not found, retrying with default branch",
                         result.stderr.strip())
            print(f"[{server_name}] Branch '{ref}' not found, retrying with default branch...", flush=True)
            fallback_cmd = ["git", "clone", "--depth", "1", git_url, str(tmp / "repo")]
            ilog.info(server_name, "clone", f"Running: {' '.join(fallback_cmd)}")
            print(f"[{server_name}] Running: {' '.join(fallback_cmd)}", flush=True)
            result = subprocess.run(
                fallback_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
            )
        if result.returncode != 0:
            ilog.error(server_name, "clone", "git clone failed", result.stderr.strip())
            print(f"[{server_name}] git clone FAILED: {result.stderr.strip()}")
            raise RuntimeError(f"git clone failed: {result.stderr.strip()}")

        ilog.info(server_name, "clone", "Clone succeeded, cleaning up .git directory")
        print(f"[{server_name}] Clone succeeded", flush=True)

        # Move to final location (remove .git for clean storage)
        repo_dir = tmp / "repo"
        git_dir = repo_dir / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        shutil.move(str(repo_dir), str(dest))
        ilog.info(server_name, "clone", f"Repository cloned to {dest}")

        # Log discovered files for debugging
        try:
            top_files = sorted(f.name for f in dest.iterdir())[:20]
            ilog.info(server_name, "clone", f"Top-level files: {', '.join(top_files)}")
        except Exception:
            pass

    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)

    return dest


# ── Install Python Dependencies ───────────────────────────────────────────


def _find_uv() -> Optional[str]:
    """Find the ``uv`` binary if available."""
    uv = shutil.which("uv")
    if uv:
        return uv
    # Check common locations
    for candidate in ("/usr/local/bin/uv", str(Path.home() / ".local" / "bin" / "uv"),
                      str(Path.home() / ".cargo" / "bin" / "uv")):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _stream_subprocess(cmd: list[str], name: str, label: str, **kwargs: Any) -> tuple[int, list[str]]:
    """Run a subprocess, streaming output to terminal and returning (returncode, lines)."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
        **kwargs,
    )
    output_lines: list[str] = []
    for line in proc.stdout:  # type: ignore[union-attr]
        line_stripped = line.rstrip()
        output_lines.append(line_stripped)
        print(f"[{name}/{label}] {line_stripped}", flush=True)
    proc.wait()
    return proc.returncode, output_lines


def _install_python_deps(server_dir: Path, status: Optional[ServerInstallStatus] = None) -> bool:
    """Install Python dependencies for a cloned MCP server.

    Creates a dedicated venv inside the server directory so external
    servers don't pollute the HomePilot backend environment.

    Prefers ``uv`` (much faster) when available, falls back to pip.
    """
    ilog = install_logger
    name = server_dir.name

    # Check for pyproject.toml or requirements.txt
    pyproject = server_dir / "pyproject.toml"
    req_file = server_dir / "requirements.txt"
    has_pyproject = pyproject.exists()
    has_requirements = req_file.exists()

    # Warn if pyproject.toml is missing [build-system]; the upstream MCP
    # server should declare it — we no longer patch third-party files.
    if has_pyproject:
        content = pyproject.read_text(encoding="utf-8")
        if "[build-system]" not in content:
            ilog.warning(
                name, "deps",
                "pyproject.toml is missing [build-system]; "
                "pip install -e . may fail — please fix the upstream project",
            )

    if not has_pyproject and not has_requirements:
        ilog.info(name, "deps", "No requirements.txt or pyproject.toml found, skipping dependency install")
        return True

    if status:
        status.message = "Installing Python dependencies..."
        status.progress_pct = 35

    ilog.info(name, "deps", f"Found: {'pyproject.toml' if has_pyproject else ''} {'requirements.txt' if has_requirements else ''}".strip())

    import sys

    uv_bin = _find_uv()
    use_uv = uv_bin is not None
    server_venv = server_dir / ".venv"
    server_python = server_venv / "bin" / "python"

    # ── Step 1: Create virtual environment ──────────────────────────────
    if not server_python.is_file():
        print(f"\n{'='*60}")
        if use_uv:
            ilog.info(name, "deps", f"Creating virtual environment with uv at {server_venv}")
            print(f"[{name}] Creating virtual environment with uv (fast)...")
            venv_cmd = [uv_bin, "venv", str(server_venv), "--python", sys.executable]
        else:
            ilog.info(name, "deps", f"Creating virtual environment at {server_venv}")
            print(f"[{name}] Creating virtual environment with python -m venv...")
            venv_cmd = [sys.executable, "-m", "venv", str(server_venv)]
        print(f"[{name}] Command: {' '.join(venv_cmd)}")
        print(f"{'='*60}", flush=True)
        try:
            rc, _ = _stream_subprocess(venv_cmd, name, "venv")
            if rc == 0:
                ilog.info(name, "deps", "Virtual environment created successfully")
                print(f"[{name}] Virtual environment created successfully")
            else:
                ilog.warning(name, "deps", f"venv creation failed (exit code {rc})")
                print(f"[{name}] venv creation failed (exit code {rc})")
                # If uv failed, try stdlib venv as fallback
                if use_uv:
                    ilog.info(name, "deps", "Falling back to python -m venv...")
                    print(f"[{name}] Falling back to python -m venv...", flush=True)
                    fallback_venv_cmd = [sys.executable, "-m", "venv", str(server_venv)]
                    rc2, _ = _stream_subprocess(fallback_venv_cmd, name, "venv")
                    if rc2 != 0:
                        ilog.warning(name, "deps", "stdlib venv also failed")
                        print(f"[{name}] stdlib venv also failed")
        except Exception as exc:
            ilog.warning(name, "deps", f"venv creation failed: {exc}")
            print(f"[{name}] venv creation failed: {exc}")
    else:
        ilog.info(name, "deps", f"Using existing virtual environment at {server_venv}")
        print(f"[{name}] Using existing virtual environment at {server_venv}")

    # ── Step 2: Try `make install` first (preferred) ───────────────────
    # Repos that ship a Makefile with an `install` target can handle
    # repo-specific setup (env files, playwright, extra deps, etc.).
    makefile = server_dir / "Makefile"
    has_makefile_install = False
    if makefile.is_file():
        try:
            mk_text = makefile.read_text(encoding="utf-8", errors="replace")
            # Match a line starting with "install:" (Makefile target)
            has_makefile_install = any(
                line.split("#")[0].strip().startswith("install:")
                for line in mk_text.splitlines()
            )
        except OSError:
            pass

    if has_makefile_install:
        make_bin = shutil.which("make") or "make"
        make_cmd = [make_bin, "-C", str(server_dir), "install"]
        ilog.info(name, "deps", f"Found Makefile with install target — running make install")
        print(f"\n{'='*60}")
        print(f"[{name}] Installing dependencies with make install (preferred)...")
        print(f"[{name}] Command: {' '.join(make_cmd)}")
        print(f"{'='*60}", flush=True)
        try:
            rc, output_lines = _stream_subprocess(make_cmd, name, "make")
            if rc == 0:
                ilog.info(name, "deps", "make install succeeded")
                print(f"[{name}] Dependencies installed successfully via make install")
                return True
            else:
                full_output = "\n".join(output_lines[-20:])
                ilog.warning(name, "deps", f"make install failed (exit {rc}), falling back to pip/uv", full_output[:1000])
                print(f"[{name}] make install FAILED (exit code {rc}), falling back to pip/uv...")
        except subprocess.TimeoutExpired:
            ilog.warning(name, "deps", "make install timed out, falling back to pip/uv")
            print(f"[{name}] make install TIMED OUT, falling back to pip/uv...")
        except Exception as exc:
            ilog.warning(name, "deps", f"make install exception: {exc}, falling back to pip/uv")
            print(f"[{name}] make install exception: {exc}, falling back to pip/uv...")

    # ── Step 3: Fallback — uv pip install / pip install ──────────────
    # base_cmd includes the full prefix up to the package specifier, e.g.:
    #   uv:  ["uv", "pip", "install", "--python", "/path/to/python"]
    #   pip: ["/path/to/pip", "install"]
    if use_uv:
        base_cmd = [uv_bin, "pip", "install", "--python", str(server_venv / "bin" / "python")]
        pkg_manager = "uv"
        ilog.info(name, "deps", f"Using uv for package installation: {uv_bin}")
    else:
        # Resolve pip: server venv → backend venv → python -m pip
        server_pip = server_venv / "bin" / "pip"
        candidates = [
            server_pip,
            _project_root() / "backend" / ".venv" / "bin" / "pip",
            Path(sys.executable).parent / "pip",
        ]
        base_cmd = []
        for c in candidates:
            if c.is_file():
                base_cmd = [str(c), "install"]
                ilog.info(name, "deps", f"Using pip: {c}")
                break
        if not base_cmd:
            base_cmd = [sys.executable, "-m", "pip", "install"]
            ilog.info(name, "deps", f"Using fallback pip: {' '.join(base_cmd)}")
        pkg_manager = "pip"

    # Prefer pyproject.toml, fall back to requirements.txt
    if has_pyproject:
        install_cmd = base_cmd + [str(server_dir)]
        ilog.info(name, "deps", f"Installing via pyproject.toml: {pkg_manager} install {server_dir}")
    else:
        install_cmd = base_cmd + ["-r", str(req_file)]
        ilog.info(name, "deps", f"Installing via requirements.txt: {pkg_manager} install -r {req_file}")

    # ── Step 4: Run pip/uv install ───────────────────────────────────
    try:
        ilog.info(name, "deps", f"Running: {' '.join(install_cmd)}")
        print(f"\n{'='*60}")
        print(f"[{name}] Installing dependencies with {pkg_manager}...")
        print(f"[{name}] Command: {' '.join(install_cmd)}")
        print(f"{'='*60}", flush=True)

        rc, output_lines = _stream_subprocess(install_cmd, name, pkg_manager)

        if rc != 0:
            full_output = "\n".join(output_lines[-20:])
            ilog.warning(name, "deps", f"Primary {pkg_manager} install failed", full_output[:1000])
            print(f"[{name}] {pkg_manager} install FAILED (exit code {rc})")

            # Fallback: if pyproject.toml install failed, try requirements.txt
            if has_pyproject and has_requirements:
                ilog.info(name, "deps", "Falling back to requirements.txt")
                fallback_cmd = base_cmd + ["-r", str(req_file)]
                ilog.info(name, "deps", f"Running: {' '.join(fallback_cmd)}")
                print(f"\n[{name}] Falling back to requirements.txt...")
                print(f"[{name}] Command: {' '.join(fallback_cmd)}", flush=True)
                rc2, _ = _stream_subprocess(fallback_cmd, name, pkg_manager)
                if rc2 == 0:
                    ilog.info(name, "deps", "Fallback requirements.txt install succeeded")
                    print(f"[{name}] Fallback requirements.txt install succeeded")
                    return True
                else:
                    ilog.error(name, "deps", "Fallback requirements.txt also failed")
                    print(f"[{name}] Fallback requirements.txt also FAILED")

            return False
        ilog.info(name, "deps", f"Dependencies installed successfully via {pkg_manager}")
        print(f"[{name}] Dependencies installed successfully via {pkg_manager}")
        return True
    except subprocess.TimeoutExpired:
        ilog.error(name, "deps", f"{pkg_manager} install timed out after 300s")
        print(f"[{name}] {pkg_manager} install TIMED OUT after 300s")
        return False
    except Exception as exc:
        ilog.error(name, "deps", f"{pkg_manager} install exception: {exc}")
        print(f"[{name}] {pkg_manager} install EXCEPTION: {exc}")
        return False


# ── Auto-populate .env for external servers ───────────────────────────────


def _auto_populate_env(server_dir: Path, server_name: str, env: dict) -> None:
    """Auto-create a .env file from .env.example if missing.

    Generates secure values for known sensitive keys (e.g. Fernet token keys)
    and injects them into the process env dict so the server can start.
    """
    ilog = install_logger
    env_file = server_dir / ".env"
    env_example = server_dir / ".env.example"

    if env_file.exists():
        # .env already exists — parse and inject into env dict
        ilog.info(server_name, "env", f"Found existing .env at {env_file}")
        _inject_env_file(env_file, env, server_name)
        return

    if not env_example.exists():
        return

    ilog.info(server_name, "env", "No .env found — generating from .env.example")

    lines: list[str] = []
    for raw_line in env_example.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        # Comments and blank lines: keep as-is
        if not line or line.startswith("#"):
            lines.append(raw_line)
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Auto-generate Fernet keys for known patterns
        if "TOKEN_KEY" in key or "FERNET_KEY" in key or "ENCRYPTION_KEY" in key:
            if value in ("", "PLEASE_SET_A_FERNET_KEY", "YOUR_KEY_HERE"):
                try:
                    from cryptography.fernet import Fernet
                    generated = Fernet.generate_key().decode("utf-8")
                except ImportError:
                    import base64
                    generated = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8")
                lines.append(f"{key}={generated}")
                env[key] = generated
                ilog.info(server_name, "env", f"Generated Fernet key for {key}")
                continue

        # Keep the example value (may be a placeholder)
        lines.append(raw_line)
        # Inject non-empty, non-placeholder values into env
        if value and not value.startswith("YOUR_"):
            env[key] = value

    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ilog.info(server_name, "env", f"Created .env at {env_file}")


def _inject_env_file(env_file: Path, env: dict, server_name: str) -> None:
    """Parse a .env file and inject values into the env dict."""
    ilog = install_logger
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and value:
            env[key] = value
    ilog.info(server_name, "env", "Injected .env values into server environment")


# ── Detect Entry Point from pyproject.toml ────────────────────────────────


def _detect_pyproject_app(server_dir: Path, server_name: str) -> Optional[str]:
    """Try to detect the ASGI app module path from pyproject.toml.

    Looks for ``[project.scripts]`` entries that reference a module,
    then constructs a ``module.main:app`` style string for uvicorn.

    For example, teams-mcp-server defines:
        [project.scripts]
        teams-mcp = "teams_mcp.main:run"

    We extract ``teams_mcp.main:app`` from this.
    """
    pyproject_path = server_dir / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    try:
        content = pyproject_path.read_text(encoding="utf-8")
    except Exception:
        return None

    # Simple TOML parsing for [project.scripts] section
    # Look for lines like: name = "module.path:function"
    in_scripts = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts:
            if stripped.startswith("["):
                break  # next section
            if "=" in stripped and not stripped.startswith("#"):
                _, _, val = stripped.partition("=")
                val = val.strip().strip('"').strip("'")
                if ":" in val:
                    module_path, _ = val.rsplit(":", 1)
                    # Convert "teams_mcp.main" → "teams_mcp.main:app"
                    return f"{module_path}:app"

    # Fallback: look for src/<package>/main.py pattern
    src_dir = server_dir / "src"
    if src_dir.is_dir():
        for pkg in src_dir.iterdir():
            if pkg.is_dir() and (pkg / "main.py").exists() and (pkg / "__init__.py").exists():
                return f"{pkg.name}.main:app"

    return None


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
    ilog = install_logger

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
        ilog.info(server_name, "start", f"Using server venv Python: {python}")
    elif backend_python.is_file():
        python = backend_python
        ilog.info(server_name, "start", f"Using backend venv Python: {python}")
    else:
        python = Path(sys.executable)
        ilog.info(server_name, "start", f"Using system Python: {python}")

    # Build PYTHONPATH: include both the server root and src/ for src-layout packages
    pythonpath_parts = [str(server_dir)]
    src_dir = server_dir / "src"
    if src_dir.is_dir():
        pythonpath_parts.append(str(src_dir))
    existing_pp = os.environ.get("PYTHONPATH", "")
    if existing_pp:
        pythonpath_parts.append(existing_pp)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(pythonpath_parts)}

    # Detect entry point — check multiple patterns in priority order:
    #   1. app/main.py             (HomePilot builtin style)
    #   2. pyproject.toml scripts  (pip-installed CLI, e.g. teams-mcp-server)
    #   3. app.py                  (simple uvicorn app)
    main_py = server_dir / "app" / "main.py"
    app_py = server_dir / "app.py"
    pyproject_toml = server_dir / "pyproject.toml"
    cmd: list[str] = []

    if main_py.exists():
        cmd = [str(python), "-m", "app.main", "--http",
               "--host", "127.0.0.1", "--port", str(port)]
        ilog.info(server_name, "start", f"Entry point: app/main.py (HomePilot module style)")
    elif pyproject_toml.exists():
        # For pip-installed packages, use uvicorn with the module's app object
        # Try to detect the module name from pyproject.toml
        module_app = _detect_pyproject_app(server_dir, server_name)
        if module_app:
            cmd = [str(python), "-m", "uvicorn", module_app,
                   "--host", "127.0.0.1", "--port", str(port),
                   "--log-level", "info"]
            ilog.info(server_name, "start", f"Entry point: pyproject.toml → uvicorn {module_app}")
            # Set port env var for pydantic-settings based servers
            env[f"{server_name.upper().replace('-', '_')}_PORT"] = str(port)
            env["TEAMS_MCP_PORT"] = str(port)  # specific for teams-mcp-server
            env["TEAMS_MCP_HOST"] = "127.0.0.1"
            # Auto-generate TEAMS_MCP_TOKEN_KEY if not already set
            if "TEAMS_MCP_TOKEN_KEY" not in env:
                try:
                    from cryptography.fernet import Fernet
                    env["TEAMS_MCP_TOKEN_KEY"] = Fernet.generate_key().decode()
                    ilog.info(server_name, "start", "Auto-generated TEAMS_MCP_TOKEN_KEY (cryptography)")
                except Exception:
                    # cryptography may not be in the backend venv; generate
                    # a url-safe base64 key that Fernet accepts (32 bytes).
                    import base64
                    env["TEAMS_MCP_TOKEN_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
                    ilog.info(server_name, "start", "Auto-generated TEAMS_MCP_TOKEN_KEY (os.urandom fallback)")
        else:
            ilog.warning(server_name, "start", "pyproject.toml found but could not detect app entry point")
    elif app_py.exists():
        cmd = [str(python), "-m", "uvicorn", "app:app",
               "--host", "127.0.0.1", "--port", str(port),
               "--log-level", "warning"]
        ilog.info(server_name, "start", f"Entry point: app.py (uvicorn style)")

    # Auto-populate .env from .env.example if missing
    _auto_populate_env(server_dir, server_name, env)

    if not cmd:
        ilog.error(server_name, "start", "Cannot detect entry point — no app/main.py, pyproject.toml scripts, or app.py found")
        return None

    # Capture server output to a log file for debugging
    log_dir = _community_external_dir() / "install_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / f"{server_name}.stdout.log"
    stderr_log = log_dir / f"{server_name}.stderr.log"

    try:
        ilog.info(server_name, "start", f"Command: {' '.join(cmd)}")
        ilog.info(server_name, "start", f"Working directory: {server_dir}")
        ilog.info(server_name, "start", f"Server stdout → {stdout_log}")
        ilog.info(server_name, "start", f"Server stderr → {stderr_log}")

        stdout_f = open(stdout_log, "w", encoding="utf-8")
        stderr_f = open(stderr_log, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(server_dir),
            stdout=stdout_f,
            stderr=stderr_f,
        )
        ilog.info(server_name, "start", f"Process started (pid={proc.pid}, port={port})")
        return proc
    except Exception as exc:
        ilog.error(server_name, "start", f"Failed to start process: {exc}")
        return None


async def _wait_for_health(port: int, timeout: int = 15, server_name: str = "") -> bool:
    """Wait for a server to become healthy."""
    import httpx
    ilog = install_logger
    host = os.getenv("MCP_TOOL_HOST", "127.0.0.1")
    url = f"http://{host}:{port}/health"
    sn = server_name or f"port-{port}"
    ilog.info(sn, "health", f"Polling {url} (timeout={timeout}s)")
    print(f"[{sn}] Health check: polling {url} (timeout={timeout}s)", flush=True)
    for attempt in range(timeout):
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(url)
                if r.status_code == 200:
                    ilog.info(sn, "health", f"Server healthy after {attempt + 1}s", r.text[:200])
                    print(f"[{sn}] Server HEALTHY after {attempt + 1}s", flush=True)
                    return True
                ilog.info(sn, "health", f"Attempt {attempt + 1}/{timeout}: HTTP {r.status_code}")
                if attempt % 5 == 4:
                    print(f"[{sn}] Health check attempt {attempt + 1}/{timeout}: HTTP {r.status_code}", flush=True)
        except Exception as exc:
            ilog.info(sn, "health", f"Attempt {attempt + 1}/{timeout}: {type(exc).__name__}")
            if attempt % 5 == 4:
                print(f"[{sn}] Health check attempt {attempt + 1}/{timeout}: {type(exc).__name__}", flush=True)
        await asyncio.sleep(1)
    ilog.error(sn, "health", f"Server not healthy after {timeout}s")
    print(f"[{sn}] Server NOT HEALTHY after {timeout}s", flush=True)
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
                result = r.json().get("result", {})
                # MCP servers may return {"result": {"tools": [...]}}
                # or {"result": [...]} (tools list directly).
                if isinstance(result, list):
                    tools = result
                elif isinstance(result, dict):
                    tools = result.get("tools", [])
                else:
                    tools = []
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
    ref = source.get("ref", "master") or "master"
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
    force_reinstall: bool = False,
) -> ServerInstallStatus:
    """Install a single external MCP server: clone → deps → start → register → sync.

    Full pipeline with structured status reporting.
    """
    name = server_info.get("name", "unknown")
    source = server_info.get("source", {})
    git_url = source.get("git", "")
    ref = source.get("ref", "master") or "master"
    ilog = install_logger

    status = ServerInstallStatus(
        server_name=name,
        source_type=source.get("type", "external"),
        git_url=git_url,
    )
    start_time = time.monotonic()

    ilog.info(name, "install", "=" * 60)
    ilog.info(name, "install", f"Starting installation of external MCP server: {name}")
    ilog.info(name, "install", f"Source: {git_url} (ref={ref})")
    ilog.info(name, "install", "=" * 60)
    print(f"\n{'#'*60}")
    print(f"# Installing MCP server: {name}")
    print(f"# Source: {git_url} (ref={ref})")
    print(f"{'#'*60}", flush=True)

    try:
        # Check if already installed in external registry
        existing = _find_in_external_registry(name)
        if existing and existing.get("status") == "installed" and not force_reinstall:
            port = existing["port"]
            ilog.info(name, "install", f"Found in registry as installed (port={port}), checking health...")
            healthy = await _wait_for_health(port, timeout=3, server_name=name)
            if healthy:
                ilog.info(name, "install", f"Already running and healthy — skipping reinstall")
                status.phase = InstallPhase.SKIPPED
                status.progress_pct = 100
                status.message = f"Already installed and running on port {port}"
                status.port = port
                status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return status
            ilog.info(name, "install", "Registered but not healthy — proceeding with reinstall")
        elif force_reinstall and existing:
            ilog.info(name, "install", "force_reinstall=True — purging and reinstalling")

        # Step 1: Clone from git
        if not git_url:
            ilog.error(name, "install", f"No git URL provided for server '{name}'")
            status.phase = InstallPhase.FAILED
            status.error = f"No git URL provided for server '{name}'"
            status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return status

        print(f"[{name}] Step 1/7: Cloning from {git_url}", flush=True)
        ilog.info(name, "clone", f"Step 1/7: Cloning from {git_url}")
        status.phase = InstallPhase.CLONING
        status.progress_pct = 10
        status.message = f"Cloning {name} from {git_url}..."

        server_dir = _clone_server_from_git(git_url, name, ref=ref, status=status, force_reinstall=force_reinstall)
        status.install_path = str(server_dir)

        # Step 2: Install Python dependencies
        print(f"\n[{name}] Step 2/7: Installing Python dependencies", flush=True)
        ilog.info(name, "deps", "Step 2/7: Installing Python dependencies")
        status.progress_pct = 30
        deps_ok = _install_python_deps(server_dir, status=status)
        if not deps_ok:
            ilog.warning(name, "deps", "Dependency install had issues, continuing anyway")
            print(f"[{name}] WARNING: Dependency install had issues, continuing anyway")

        # Step 3: Allocate port & start server
        port = server_info.get("default_port") or _allocate_port(name)
        status.port = port
        print(f"\n[{name}] Step 3/7: Starting server on port {port}", flush=True)
        ilog.info(name, "start", f"Step 3/7: Allocated port {port}")
        status.phase = InstallPhase.STARTING
        status.progress_pct = 45
        status.message = f"Starting on port {port}..."

        proc = await _start_external_server(server_dir, port, name, status=status)
        if not proc:
            ilog.error(name, "start", "Failed to start server process — aborting")
            print(f"[{name}] FAILED to start server process — aborting")
            status.phase = InstallPhase.FAILED
            status.error = f"Failed to start server process"
            status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return status

        # Step 4: Wait for health
        print(f"\n[{name}] Step 4/7: Waiting for server health check...", flush=True)
        ilog.info(name, "health", "Step 4/7: Waiting for server health check")
        status.message = f"Waiting for server to become healthy..."
        status.progress_pct = 55
        healthy = await _wait_for_health(port, timeout=20, server_name=name)
        if not healthy:
            proc.terminate()
            ilog.error(name, "health", "Server did not become healthy within 20s — aborting")
            print(f"[{name}] FAILED: Server did not become healthy within 20s")
            # Try to capture stderr for diagnostics
            stderr_log = _community_external_dir() / "install_logs" / f"{name}.stderr.log"
            if stderr_log.exists():
                try:
                    tail = stderr_log.read_text(encoding="utf-8", errors="replace")[-1000:]
                    ilog.error(name, "health", "Server stderr (tail):", tail)
                    print(f"[{name}] Server stderr:\n{tail}")
                except Exception:
                    pass
            status.phase = InstallPhase.FAILED
            status.error = f"Server did not become healthy within 20s"
            status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return status

        # Step 5: Discover tools & register in Forge
        print(f"\n[{name}] Step 5/7: Discovering tools via RPC...", flush=True)
        ilog.info(name, "discover", "Step 5/7: Discovering tools via RPC")
        discovered, registered = await _discover_and_register(
            port, name, forge_url, auth_user, auth_pass, bearer_token, status=status,
        )
        ilog.info(name, "discover", f"Discovered {discovered} tools, registered {registered} in Forge")
        print(f"[{name}] Discovered {discovered} tools, registered {registered} in Forge")

        # Step 6: Register in external server registry
        print(f"[{name}] Step 6/7: Registering in external server registry", flush=True)
        ilog.info(name, "registry", "Step 6/7: Registering in external server registry")
        _register_external_server(name, port, git_url, str(server_dir), discovered)

        # Step 7: Trigger full sync to update virtual servers
        print(f"[{name}] Step 7/7: Syncing with Context Forge...", flush=True)
        ilog.info(name, "sync", "Step 7/7: Syncing with Context Forge")
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
            ilog.info(name, "sync", "Forge sync completed successfully")
            print(f"[{name}] Forge sync completed")
        except Exception as exc:
            ilog.warning(name, "sync", f"Post-install sync failed: {exc}")
            print(f"[{name}] WARNING: Post-install sync failed: {exc}")

        # Step 8: Re-enable previously disabled tools (if this is a reinstall)
        try:
            from .mcp_uninstaller import reenable_after_reinstall, get_disabled_tools
            if get_disabled_tools(name):
                ilog.info(name, "reenable", "Step 8: Re-enabling tools disabled during previous uninstall")
                reenable_result = await reenable_after_reinstall(
                    name, new_port=port,
                    forge_url=forge_url, auth_user=auth_user,
                    auth_pass=auth_pass, bearer_token=bearer_token,
                )
                reenabled = reenable_result.get("reenabled", 0)
                if reenabled:
                    ilog.info(name, "reenable", f"Re-enabled {reenabled} tools for previously affected personas")
        except Exception as exc:
            ilog.warning(name, "reenable", f"Re-enable step failed (non-critical): {exc}")

        # Done!
        elapsed = int((time.monotonic() - start_time) * 1000)
        status.phase = InstallPhase.COMPLETE
        status.progress_pct = 100
        status.message = f"Installed: {discovered} tools discovered, {registered} registered"
        ilog.info(name, "install", f"Installation complete in {elapsed}ms")
        ilog.info(name, "install", f"Summary: port={port}, tools={discovered}, registered={registered}")
        ilog.info(name, "install", "=" * 60)
        print(f"\n{'='*60}")
        print(f"[{name}] INSTALLATION COMPLETE in {elapsed}ms")
        print(f"[{name}] Port: {port} | Tools: {discovered} | Registered: {registered}")
        print(f"{'='*60}", flush=True)

    except Exception as exc:
        status.phase = InstallPhase.FAILED
        status.error = str(exc)
        ilog.error(name, "install", f"Installation failed: {exc}")
        print(f"\n[{name}] INSTALLATION FAILED: {exc}")

    status.elapsed_ms = int((time.monotonic() - start_time) * 1000)
    return status


async def install_servers_from_plan(
    plan: InstallPlan,
    forge_url: str,
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
    force_reinstall: bool = False,
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
                force_reinstall=force_reinstall,
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
    force_reinstall: bool = False,
) -> InstallPlan:
    """One-shot: analyze persona MCP deps and optionally auto-install missing ones.

    This is the main entry point for the import flow:
      1. Parse dependencies/mcp_servers.json
      2. Build install plan (what's needed, what's available, what needs install)
      3. If auto_install=True, install all missing servers
      4. Return the complete plan with statuses

    When *force_reinstall* is ``True``, servers that are already installed
    are moved into ``servers_to_install`` so they get purged and reinstalled.

    Used by:
      - POST /persona/import/resolve-deps (preview + plan)
      - POST /persona/import/install-deps (auto-install)
      - POST /persona/import/atomic (one-click)
    """
    mcp_dep = dependencies.get("mcp_servers") or {}
    plan = await analyze_mcp_dependencies(mcp_dep, persona_name)

    # When force-reinstalling, move already-available servers back into
    # the install queue so they get purged and freshly cloned.
    if force_reinstall and plan.servers_already_available:
        reinstallable = [
            s for s in plan.servers_already_available
            if s.get("source", {}).get("type") in ("external", "community_bundle")
        ]
        for s in reinstallable:
            plan.servers_already_available.remove(s)
            plan.servers_to_install.append(s)

    if auto_install and plan.servers_to_install:
        if not forge_url:
            forge_url = os.getenv("CONTEXT_FORGE_URL", "http://localhost:4444")
        plan = await install_servers_from_plan(
            plan, forge_url, auth_user, auth_pass, bearer_token,
            force_reinstall=force_reinstall,
        )

    return plan
