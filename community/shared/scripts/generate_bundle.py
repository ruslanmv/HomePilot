#!/usr/bin/env python3
"""
generate_bundle.py — Scaffold a new shared persona bundle with MCP server.

Creates a complete bundle directory from templates, ready to customize.
Automatically allocates the next available port from the port map.

Usage:
  python community/shared/scripts/generate_bundle.py \\
    --id weather_forecast \\
    --name "Cirrus" \\
    --role "Weather Forecaster" \\
    --class-id assistant \\
    --author "Your Name" \\
    --tools "forecast,radar,alerts"

  python community/shared/scripts/generate_bundle.py \\
    --id task_manager \\
    --name "Planner" \\
    --role "Task Manager" \\
    --class-id secretary \\
    --shared-server hp-community-greeter   # share existing server

Scalability design:
  - Port range 9200-9999 = 800 dedicated community servers
  - Shared servers allow unlimited personas per server
  - Registry tracks port allocation to avoid conflicts
  - Generator enforces unique bundle_ids and ports
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_DIR = SCRIPT_DIR.parent
BUNDLES_DIR = SHARED_DIR / "bundles"
REGISTRY_DIR = SHARED_DIR / "registry"
TEMPLATES_DIR = SHARED_DIR / "_templates"

PORT_MAP_PATH = REGISTRY_DIR / "port_map.json"
REGISTRY_PATH = REGISTRY_DIR / "shared_registry.json"


def _load_port_map() -> dict:
    if PORT_MAP_PATH.exists():
        with PORT_MAP_PATH.open("r") as f:
            return json.load(f)
    return {
        "ranges": {"community": {"start": 9200, "end": 9999}},
        "allocated": {},
    }


def _save_port_map(pm: dict) -> None:
    PORT_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PORT_MAP_PATH.open("w") as f:
        json.dump(pm, f, indent=2)


def _next_port(pm: dict) -> int:
    """Find the next available port in the community range."""
    allocated_ports = {int(p) for p in pm.get("allocated", {}).keys()}
    start = pm["ranges"]["community"]["start"]
    end = pm["ranges"]["community"]["end"]
    for port in range(start, end + 1):
        if port not in allocated_ports:
            return port
    raise RuntimeError(f"No available ports in community range {start}-{end}")


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        with REGISTRY_PATH.open("r") as f:
            return json.load(f)
    return {
        "schema_version": 1,
        "kind": "homepilot.shared_registry",
        "generated_at": "",
        "port_allocation": {"community_range_start": 9200, "community_range_end": 9999, "next_available": 9200},
        "mcp_servers": [],
        "bundles": [],
    }


def _save_registry(reg: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_PATH.open("w") as f:
        json.dump(reg, f, indent=2)


def generate(
    bundle_id: str,
    name: str,
    role: str,
    class_id: str,
    author: str,
    tools: List[str],
    shared_server: Optional[str] = None,
    tags: Optional[List[str]] = None,
    git_url: str = "",
    git_ref: str = "main",
) -> None:
    """Generate a complete bundle scaffold."""
    tags = tags or [bundle_id.replace("_", "-")]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    slug = bundle_id.replace("_", "-")
    server_slug = bundle_id

    bundle_dir = BUNDLES_DIR / bundle_id
    if bundle_dir.exists():
        print(f"ERROR: Bundle '{bundle_id}' already exists at {bundle_dir}")
        sys.exit(1)

    # Determine MCP mode and port
    if shared_server:
        mode = "shared"
        server_id = shared_server
        port = None
        print(f"Using shared server: {shared_server}")
    else:
        mode = "dedicated"
        pm = _load_port_map()
        port = _next_port(pm)
        server_id = f"hp-community-{slug}"
        # Allocate port
        pm["allocated"][str(port)] = {"server_id": server_id, "bundle_id": bundle_id}
        _save_port_map(pm)
        print(f"Allocated port: {port}")

    # Tool names
    tool_prefix = f"hp.community.{server_slug}"
    tool_fqns = [f"{tool_prefix}.{t}" for t in tools]
    personality_tools = [f"community_{t}" for t in tools]

    # ── Create directories ────────────────────────────────────────────────
    dirs = [
        bundle_dir / "persona" / "blueprint",
        bundle_dir / "persona" / "dependencies",
        bundle_dir / "persona" / "assets",
        bundle_dir / "persona" / "preview",
        bundle_dir / "forge",
    ]
    if mode == "dedicated":
        dirs.append(bundle_dir / "mcp_server")
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # ── bundle_manifest.json ──────────────────────────────────────────────
    manifest = {
        "kind": "homepilot.shared_bundle",
        "schema_version": 1,
        "bundle_id": bundle_id,
        "bundle_version": "1.0.0",
        "author": author,
        "license": "MIT",
        "created_at": now,
        "persona": {
            "id": bundle_id,
            "name": name,
            "role": role,
            "class_id": class_id,
            "content_rating": "sfw",
            "tags": tags,
        },
        "mcp_server": {
            "mode": mode,
            "server_id": server_id,
            **({"port": port, "module": f"agentic.integrations.mcp.community_{slug}_server:app"} if mode == "dedicated" else {}),
            "git": git_url,
            "ref": git_ref,
            "tools_provided": tool_fqns,
            "shared_with": [],
        },
        "compatibility": {
            "min_homepilot_version": "2.1.0",
            "hpersona_schema_version": 2,
            "requires_config": [],
        },
    }
    _write_json(bundle_dir / "bundle_manifest.json", manifest)

    # ── persona/manifest.json ─────────────────────────────────────────────
    _write_json(bundle_dir / "persona" / "manifest.json", {
        "kind": "homepilot.persona",
        "schema_version": 2,
        "package_version": 2,
        "project_type": "persona",
        "source_homepilot_version": "2.1.0",
        "content_rating": "sfw",
        "created_at": now,
        "contents": {
            "has_avatar": False,
            "has_outfits": False,
            "outfit_count": 0,
            "has_tool_dependencies": True,
            "has_mcp_servers": True,
            "has_a2a_agents": False,
            "has_model_requirements": False,
        },
        "capability_summary": {
            "personality_tools": personality_tools,
            "capabilities": [],
            "mcp_servers_count": 1,
            "a2a_agents_count": 0,
        },
    })

    # ── persona/blueprint/ ────────────────────────────────────────────────
    _write_json(bundle_dir / "persona" / "blueprint" / "persona_agent.json", {
        "id": bundle_id,
        "label": name,
        "role": role,
        "category": "sfw",
        "system_prompt": f"You are {name}, a {role}.\nCustomize this system prompt for your persona.",
        "response_style": {"tone": "Professional, helpful"},
        "allowed_tools": personality_tools,
    })

    _write_json(bundle_dir / "persona" / "blueprint" / "persona_appearance.json", {
        "persona_class": class_id,
        "style_tags": ["Casual"],
        "backstory": f"{name} is a {role}. Add your backstory here.",
    })

    _write_json(bundle_dir / "persona" / "blueprint" / "agentic.json", {
        "goal": f"Help users with {role.lower()} tasks",
        "capabilities": [],
        "tool_source": "all",
    })

    # ── persona/dependencies/ ─────────────────────────────────────────────
    _write_json(bundle_dir / "persona" / "dependencies" / "mcp_servers.json", {
        "schema_version": 1,
        "servers": [{
            "name": server_id,
            "description": f"{name} tools",
            "default_port": port or 0,
            "source": {"type": "community_bundle", "bundle_id": bundle_id, "git": git_url, "ref": git_ref},
            "transport": "HTTP",
            "protocol": "MCP",
            "tools_provided": tool_fqns,
            "health_check": {"method": "GET", "path": "/health"},
        }],
    })

    _write_json(bundle_dir / "persona" / "dependencies" / "tools.json", {
        "schema_version": 1,
        "personality_tools": {"description": "PersonalityAgent.allowed_tools", "tools": personality_tools},
        "forge_tools": {"description": "Context Forge tool references", "tools": tool_fqns},
        "tool_schemas": [
            {
                "name": fqn,
                "description": f"TODO: describe {t}",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
            for t, fqn in zip(tools, tool_fqns)
        ],
        "capability_summary": {"required": [], "optional": []},
    })

    _write_json(bundle_dir / "persona" / "dependencies" / "a2a_agents.json", {"schema_version": 1, "agents": []})
    _write_json(bundle_dir / "persona" / "dependencies" / "models.json", {"schema_version": 1, "image_models": [], "video_models": []})
    _write_json(bundle_dir / "persona" / "dependencies" / "suite.json", {"schema_version": 1, "tool_source": "all", "tool_ids": []})

    # ── persona/preview/card.json ─────────────────────────────────────────
    _write_json(bundle_dir / "persona" / "preview" / "card.json", {
        "name": name,
        "role": role,
        "short": f"{role} — customize this description",
        "class_id": class_id,
        "tone": "Professional, helpful",
        "tags": tags,
        "tools": personality_tools,
        "content_rating": "sfw",
        "has_avatar": False,
        "bundle_info": {
            "has_mcp_server": True,
            "mcp_server_mode": mode,
            "mcp_server_id": server_id,
        },
    })

    # ── MCP server scaffold (dedicated only) ──────────────────────────────
    if mode == "dedicated":
        # Read template and substitute
        tmpl_path = TEMPLATES_DIR / "mcp_server" / "app.py.tmpl"
        if tmpl_path.exists():
            tmpl = tmpl_path.read_text()
            tmpl = tmpl.replace("{{SERVER_NAME}}", name)
            tmpl = tmpl.replace("{{SERVER_SLUG}}", server_slug)
            (bundle_dir / "mcp_server" / "app.py").write_text(tmpl)
        else:
            # Minimal fallback
            (bundle_dir / "mcp_server" / "app.py").write_text(
                f"# TODO: implement MCP server for {name}\n"
                f"# Tool namespace: hp.community.{server_slug}.*\n"
            )
        (bundle_dir / "mcp_server" / "__init__.py").write_text("")

        # ── Forge integration files ───────────────────────────────────────
        (bundle_dir / "forge" / "server_catalog_entry.yaml").write_text(
            f"- id: {server_id}\n"
            f"  port: {port}\n"
            f'  module: "agentic.integrations.mcp.community_{slug}_server:app"\n'
            f'  label: "{name}"\n'
            f'  description: "{role} tools"\n'
            f"  category: community\n"
            f"  icon: box\n"
        )

        (bundle_dir / "forge" / "gateway_entry.yaml").write_text(
            f"- name: {server_id}\n"
            f'  url: "http://localhost:{port}/rpc"\n'
            f'  transport: "SSE"\n'
            f'  description: "HomePilot Community {name} MCP server"\n'
        )

        (bundle_dir / "forge" / "virtual_server_entry.yaml").write_text(
            f'- name: "{server_id}"\n'
            f'  description: "{name} tools"\n'
            f"  include_tool_prefixes:\n"
            f'    - "{tool_prefix}."\n'
        )

    # ── Makefile + test_bundle.py ────────────────────────────────────────
    makefile_tmpl = TEMPLATES_DIR / "persona_bundle" / "Makefile.tmpl"
    if makefile_tmpl.exists():
        mf = makefile_tmpl.read_text()
        mf = mf.replace("{{BUNDLE_ID}}", bundle_id)
        mf = mf.replace("{{SERVER_ID}}", server_id)
        mf = mf.replace("{{PORT}}", str(port or 0))
        (bundle_dir / "Makefile").write_text(mf)

    test_tmpl = TEMPLATES_DIR / "persona_bundle" / "test_bundle.py.tmpl"
    if test_tmpl.exists():
        (bundle_dir / "test_bundle.py").write_text(test_tmpl.read_text())

    # ── Update registry ───────────────────────────────────────────────────
    reg = _load_registry()
    reg["generated_at"] = now

    # Add MCP server entry if dedicated and not already listed
    if mode == "dedicated":
        existing_ids = {s["server_id"] for s in reg.get("mcp_servers", [])}
        if server_id not in existing_ids:
            reg.setdefault("mcp_servers", []).append({
                "server_id": server_id,
                "port": port,
                "bundle_id": bundle_id,
                "tool_prefix": f"{tool_prefix}.",
                "shared_by_bundles": [bundle_id],
            })

    # Add bundle entry
    reg.setdefault("bundles", []).append({
        "bundle_id": bundle_id,
        "name": f"{name} — {role}",
        "version": "1.0.0",
        "persona_id": bundle_id,
        "class_id": class_id,
        "tags": tags,
        "content_rating": "sfw",
        "mcp_server_mode": mode,
        "mcp_server_id": server_id,
        "tool_count": len(tools),
        "requires_config": [],
        "status": "draft",
    })

    if port:
        reg["port_allocation"]["next_available"] = port + 1
    _save_registry(reg)

    print(f"\nBundle scaffolded at: {bundle_dir.relative_to(SHARED_DIR.parent)}")
    print(f"  Persona: {name} ({role})")
    print(f"  MCP: {mode} → {server_id}" + (f" port {port}" if port else ""))
    print(f"  Tools: {', '.join(tool_fqns)}")
    print(f"\nNext steps:")
    print(f"  1. Edit mcp_server/app.py — implement your tool handlers")
    print(f"  2. Edit persona/blueprint/persona_agent.json — customize system prompt")
    print(f"  3. Run: python community/shared/scripts/install_bundle.py {bundle_id}")


def _write_json(path: Path, data: dict) -> None:
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a new shared persona bundle")
    parser.add_argument("--id", required=True, help="Bundle ID (snake_case, e.g. weather_forecast)")
    parser.add_argument("--name", required=True, help="Persona display name (e.g. Cirrus)")
    parser.add_argument("--role", required=True, help="Persona role (e.g. Weather Forecaster)")
    parser.add_argument("--class-id", default="assistant", choices=["assistant", "secretary", "companion", "creative", "specialist"])
    parser.add_argument("--author", default="HomePilot Community")
    parser.add_argument("--tools", required=True, help="Comma-separated tool names (e.g. forecast,radar,alerts)")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--shared-server", help="Use existing MCP server ID instead of creating a new one")
    parser.add_argument("--git-url", default="", help="GitHub repo URL where this bundle will be published")
    parser.add_argument("--git-ref", default="main", help="Git branch/tag (default: main)")
    args = parser.parse_args()

    tools = [t.strip() for t in args.tools.split(",")]
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None

    generate(
        bundle_id=args.id,
        name=args.name,
        role=args.role,
        class_id=args.class_id,
        author=args.author,
        tools=tools,
        shared_server=args.shared_server,
        tags=tags,
        git_url=args.git_url,
        git_ref=args.git_ref,
    )


if __name__ == "__main__":
    main()
