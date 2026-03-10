#!/usr/bin/env python3
"""
install_bundle.py — Install a shared persona bundle into HomePilot.

Performs a non-destructive, additive installation:
  1. (Optional) Clone bundle from a Git URL into bundles/
  2. Copies MCP server code to agentic/integrations/mcp/
  3. Appends server_catalog.yaml entry (if not present)
  4. Appends gateways.yaml entry (if not present)
  5. Appends virtual_servers.yaml entry (if not present)
  6. Builds .hpersona package ready for import

Does NOT modify existing entries — only appends new ones.

Usage:
  # Install a local bundle
  python community/shared/scripts/install_bundle.py hello_world_greeter

  # Install from GitHub (clone + install in one step)
  python community/shared/scripts/install_bundle.py --from-git https://github.com/someone/hp-bundle-weather

  # List / uninstall
  python community/shared/scripts/install_bundle.py --list
  python community/shared/scripts/install_bundle.py --uninstall hello_world_greeter

Compatible with:
  - HomePilot server_manager.py (catalog-driven install/uninstall)
  - Context Forge (tool discovery via tools/list, virtual server prefix matching)
  - .hpersona v2 import pipeline (export_import.py)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_DIR = SCRIPT_DIR.parent
BUNDLES_DIR = SHARED_DIR / "bundles"
PROJECT_ROOT = SHARED_DIR.parents[1]  # HomePilot/

MCP_DIR = PROJECT_ROOT / "agentic" / "integrations" / "mcp"
FORGE_TEMPLATES = PROJECT_ROOT / "agentic" / "forge" / "templates"
CATALOG_PATH = FORGE_TEMPLATES / "server_catalog.yaml"
GATEWAYS_PATH = FORGE_TEMPLATES / "gateways.yaml"
VIRTUAL_SERVERS_PATH = FORGE_TEMPLATES / "virtual_servers.yaml"


REGISTRY_DIR = SHARED_DIR / "registry"
PORT_MAP_PATH = REGISTRY_DIR / "port_map.json"


# ── Git fetch ─────────────────────────────────────────────────────────────


def fetch_from_git(git_url: str, ref: str | None = None) -> str:
    """
    Clone a bundle repo from Git into community/shared/bundles/<bundle_id>/.

    Expects the repo root to contain bundle_manifest.json.
    Returns the bundle_id extracted from the manifest.

    Supports:
      - Full URL:    https://github.com/someone/hp-bundle-weather
      - With ref:    --ref v1.0.0  (branch, tag, or commit)
      - Subdirectory repos are NOT supported yet (entire repo = one bundle)
    """
    # Clone to a temp directory first, then move into bundles/
    import tempfile

    print(f"Fetching bundle from: {git_url}")
    if ref:
        print(f"  Ref: {ref}")

    tmp = Path(tempfile.mkdtemp(prefix="hp-bundle-"))
    try:
        # Clone (shallow for speed)
        clone_cmd = ["git", "clone", "--depth", "1"]
        if ref:
            clone_cmd += ["--branch", ref]
        clone_cmd += [git_url, str(tmp / "repo")]

        result = subprocess.run(clone_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: git clone failed:\n{result.stderr}")
            sys.exit(1)

        repo_dir = tmp / "repo"

        # Read manifest to get bundle_id
        manifest_path = repo_dir / "bundle_manifest.json"
        if not manifest_path.exists():
            print(f"ERROR: No bundle_manifest.json found in repo root")
            print(f"  Expected: {git_url} → bundle_manifest.json")
            sys.exit(1)

        with manifest_path.open("r") as f:
            manifest = json.load(f)

        bundle_id = manifest.get("bundle_id")
        if not bundle_id:
            print(f"ERROR: bundle_manifest.json has no 'bundle_id' field")
            sys.exit(1)

        dest = BUNDLES_DIR / bundle_id
        if dest.exists():
            print(f"  Bundle '{bundle_id}' already exists locally — updating")
            shutil.rmtree(dest)

        # Remove .git directory (we don't need history in bundles/)
        git_dir = repo_dir / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        # Move repo contents into bundles/<bundle_id>/
        shutil.move(str(repo_dir), str(dest))

        # Allocate port if dedicated and not yet allocated
        mcp = manifest.get("mcp_server", {})
        if mcp.get("mode") == "dedicated" and mcp.get("port"):
            _register_port(bundle_id, mcp["server_id"], mcp["port"])

        print(f"  Cloned to: community/shared/bundles/{bundle_id}/")
        return bundle_id

    finally:
        # Clean up temp dir
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def _register_port(bundle_id: str, server_id: str, port: int) -> None:
    """Register a port allocation in port_map.json (idempotent)."""
    if not PORT_MAP_PATH.exists():
        pm = {"ranges": {"community": {"start": 9200, "end": 9999}}, "allocated": {}}
    else:
        with PORT_MAP_PATH.open("r") as f:
            pm = json.load(f)

    port_str = str(port)
    if port_str not in pm.get("allocated", {}):
        pm.setdefault("allocated", {})[port_str] = {
            "server_id": server_id,
            "bundle_id": bundle_id,
        }
        PORT_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PORT_MAP_PATH.open("w") as f:
            json.dump(pm, f, indent=2)


def _load_manifest(bundle_id: str) -> dict:
    manifest_path = BUNDLES_DIR / bundle_id / "bundle_manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: Bundle '{bundle_id}' not found at {manifest_path}")
        sys.exit(1)
    with manifest_path.open("r") as f:
        return json.load(f)


def _yaml_contains_id(yaml_path: Path, server_id: str) -> bool:
    """Check if a YAML file already contains a server ID (simple text search)."""
    if not yaml_path.exists():
        return False
    content = yaml_path.read_text()
    return f"id: {server_id}" in content or f"name: {server_id}" in content


def _append_yaml_entry(yaml_path: Path, entry_path: Path, section_comment: str) -> bool:
    """Append a YAML entry to a file if not already present."""
    if not entry_path.exists():
        return False
    entry_text = entry_path.read_text().strip()
    # Strip leading comments from entry (keep only the YAML data lines)
    lines = []
    for line in entry_text.split("\n"):
        if line.startswith("#"):
            continue
        lines.append(line)
    entry_data = "\n".join(lines).strip()

    if not yaml_path.exists():
        print(f"  WARNING: {yaml_path} not found, skipping")
        return False

    content = yaml_path.read_text()
    content += f"\n\n  # ── {section_comment} ──\n"
    # Indent each line by 2 spaces (matching YAML list item nesting)
    for line in entry_data.split("\n"):
        content += f"  {line}\n"

    yaml_path.write_text(content)
    return True


def install(bundle_id: str, dry_run: bool = False) -> None:
    """Install a shared bundle into HomePilot."""
    manifest = _load_manifest(bundle_id)
    mcp = manifest.get("mcp_server", {})
    mode = mcp.get("mode", "none")
    server_id = mcp.get("server_id", "")

    print(f"Installing bundle: {bundle_id}")
    print(f"  Persona: {manifest['persona']['name']} ({manifest['persona']['role']})")
    print(f"  MCP mode: {mode}")

    if mode == "dedicated":
        print(f"  Server ID: {server_id}")
        print(f"  Port: {mcp.get('port')}")
        print(f"  Tools: {', '.join(mcp.get('tools_provided', []))}")

    if dry_run:
        print("\n  [DRY RUN] No changes made.")
        return

    bundle_dir = BUNDLES_DIR / bundle_id

    # ── Step 1: Copy MCP server code ─────────────────────────────────────
    if mode == "dedicated":
        src_server = bundle_dir / "mcp_server" / "app.py"
        slug = server_id.replace("hp-community-", "")

        # Create entry point: agentic/integrations/mcp/community_<slug>_server.py
        entry_point = MCP_DIR / f"community_{slug}_server.py"
        if not entry_point.exists():
            entry_content = (
                f"# Auto-installed from community/shared/bundles/{bundle_id}\n"
                f"from community.shared.bundles.{bundle_id}.mcp_server.app import app  # noqa: F401\n"
            )
            entry_point.write_text(entry_content)
            print(f"  Created entry point: {entry_point.relative_to(PROJECT_ROOT)}")
        else:
            print(f"  Entry point already exists: {entry_point.relative_to(PROJECT_ROOT)}")

    # ── Step 2: Append server_catalog.yaml ────────────────────────────────
    if mode == "dedicated" and not _yaml_contains_id(CATALOG_PATH, server_id):
        entry_file = bundle_dir / "forge" / "server_catalog_entry.yaml"
        if _append_yaml_entry(CATALOG_PATH, entry_file, f"Community: {bundle_id}"):
            print(f"  Appended to server_catalog.yaml")
    elif mode == "dedicated":
        print(f"  server_catalog.yaml already has {server_id}")

    # ── Step 3: Append gateways.yaml ──────────────────────────────────────
    if mode == "dedicated" and not _yaml_contains_id(GATEWAYS_PATH, server_id):
        entry_file = bundle_dir / "forge" / "gateway_entry.yaml"
        if _append_yaml_entry(GATEWAYS_PATH, entry_file, f"Community: {bundle_id}"):
            print(f"  Appended to gateways.yaml")
    elif mode == "dedicated":
        print(f"  gateways.yaml already has {server_id}")

    # ── Step 4: Append virtual_servers.yaml ───────────────────────────────
    if mode == "dedicated" and not _yaml_contains_id(VIRTUAL_SERVERS_PATH, server_id):
        entry_file = bundle_dir / "forge" / "virtual_server_entry.yaml"
        if _append_yaml_entry(VIRTUAL_SERVERS_PATH, entry_file, f"Community: {bundle_id}"):
            print(f"  Appended to virtual_servers.yaml")
    elif mode == "dedicated":
        print(f"  virtual_servers.yaml already has {server_id}")

    # ── Step 5: Build .hpersona package ───────────────────────────────────
    persona_dir = bundle_dir / "persona"
    hpersona_path = bundle_dir / f"{bundle_id}.hpersona"

    if persona_dir.exists():
        with zipfile.ZipFile(hpersona_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(persona_dir.rglob("*")):
                if file_path.is_file():
                    arcname = str(file_path.relative_to(persona_dir))
                    zf.write(file_path, arcname)
        print(f"  Built {hpersona_path.relative_to(PROJECT_ROOT)}")
        print(f"\n  Ready! Import via: POST /persona/import with {hpersona_path.name}")
    else:
        print(f"  WARNING: No persona/ directory found in bundle")

    # ── Step 6: Post-install instructions ─────────────────────────────────
    if mode == "dedicated":
        print(f"\n  Next steps:")
        print(f"    1. Restart HomePilot (or call server_manager.install('{server_id}'))")
        print(f"    2. Forge will discover tools via POST /rpc tools/list")
        print(f"    3. Import {bundle_id}.hpersona via UI or API")


def uninstall(bundle_id: str) -> None:
    """Remove a bundle's catalog entries (does not delete bundle files)."""
    manifest = _load_manifest(bundle_id)
    mcp = manifest.get("mcp_server", {})
    server_id = mcp.get("server_id", "")
    slug = server_id.replace("hp-community-", "")

    print(f"Uninstalling bundle: {bundle_id}")

    # Remove entry point
    entry_point = MCP_DIR / f"community_{slug}_server.py"
    if entry_point.exists():
        entry_point.unlink()
        print(f"  Removed {entry_point.relative_to(PROJECT_ROOT)}")

    # Remove .hpersona
    hpersona_path = BUNDLES_DIR / bundle_id / f"{bundle_id}.hpersona"
    if hpersona_path.exists():
        hpersona_path.unlink()
        print(f"  Removed {hpersona_path.relative_to(PROJECT_ROOT)}")

    print(f"  NOTE: Manually remove entries from server_catalog.yaml, gateways.yaml, virtual_servers.yaml")
    print(f"  NOTE: Call server_manager.uninstall('{server_id}') to stop the server")


def list_bundles() -> None:
    """List all available bundles."""
    print("Available shared bundles:\n")
    for bundle_dir in sorted(BUNDLES_DIR.iterdir()):
        manifest_path = bundle_dir / "bundle_manifest.json"
        if not manifest_path.exists():
            continue
        with manifest_path.open("r") as f:
            m = json.load(f)
        persona = m.get("persona", {})
        mcp = m.get("mcp_server", {})
        tools = mcp.get("tools_provided", [])
        print(f"  {m['bundle_id']} v{m.get('bundle_version', '?')}")
        print(f"    Persona: {persona.get('name')} — {persona.get('role')}")
        print(f"    MCP: {mcp.get('mode')} ({mcp.get('server_id', 'n/a')}, port {mcp.get('port', '—')})")
        print(f"    Tools: {len(tools)} ({', '.join(tools[:3])}{'...' if len(tools) > 3 else ''})")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Install/manage shared persona bundles")
    parser.add_argument("bundle_id", nargs="?", help="Bundle ID to install (local)")
    parser.add_argument("--from-git", metavar="URL", help="Clone bundle from Git URL and install")
    parser.add_argument("--ref", help="Git branch, tag, or commit (used with --from-git)")
    parser.add_argument("--list", action="store_true", help="List available bundles")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall a bundle")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    if args.list:
        list_bundles()
    elif args.from_git:
        # Clone from Git → install in one step
        bundle_id = fetch_from_git(args.from_git, ref=args.ref)
        install(bundle_id, dry_run=args.dry_run)
    elif args.uninstall and args.bundle_id:
        uninstall(args.bundle_id)
    elif args.bundle_id:
        install(args.bundle_id, dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
