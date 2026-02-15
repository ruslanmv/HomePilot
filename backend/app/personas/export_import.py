# backend/app/personas/export_import.py
"""
Persona project export/import (.hpersona packaging) — v2.

Package structure (v2):
  manifest.json                    — version info + contents summary
  blueprint/
    persona_agent.json             — full PersonalityAgent definition
    persona_appearance.json        — appearance config + generation seeds
    agentic.json                   — goal, capabilities, execution profile
  dependencies/
    tools.json                     — tool manifest + schemas + capability mapping
    mcp_servers.json               — MCP server requirements + sources
    a2a_agents.json                — A2A agent requirements
    models.json                    — image/video model requirements
    suite.json                     — recommended suite/virtual-server config
  assets/
    avatar_<stem>.<ext>            — committed avatar (full res)
    thumb_avatar_<stem>.webp       — thumbnail (256x256)
  preview/
    card.json                      — pre-rendered card data for galleries

Backward compatibility:
  - v2 import accepts v1 packages (no dependencies/ folder)
  - v1 HomePilot rejects v2 via schema_version check (clean error)

Schema versioning ensures forward compatibility:
  - Older HomePilot can reject newer schema versions gracefully
  - Newer HomePilot can import older packages without issues
"""
from __future__ import annotations

import io
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import projects

PACKAGE_VERSION = 2
SCHEMA_VERSION = 2

# We still accept v1 packages on import
_MAX_IMPORT_SCHEMA = SCHEMA_VERSION


@dataclass(frozen=True)
class ExportResult:
    """Result of exporting a persona project."""
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class PreviewResult:
    """Preview of a .hpersona package without creating a project."""
    manifest: Dict[str, Any]
    persona_agent: Dict[str, Any]
    persona_appearance: Dict[str, Any]
    agentic: Dict[str, Any]
    dependencies: Dict[str, Any]
    has_avatar: bool
    asset_names: List[str]


def _safe_basename(name: str) -> str:
    base = os.path.basename(name)
    if base in ("", ".", ".."):
        raise ValueError("Invalid filename")
    return base


# ---------------------------------------------------------------------------
# Tool / MCP / Agent dependency builders
# ---------------------------------------------------------------------------

def _build_tools_manifest(project: Dict[str, Any]) -> Dict[str, Any]:
    """Build tools.json from project's persona_agent + agentic data."""
    persona_agent = project.get("persona_agent") or {}
    agentic = project.get("agentic") or {}

    personality_tools = persona_agent.get("allowed_tools") or []

    # Build tool schemas from the personality tools catalog
    tool_schemas = []
    try:
        from ..personalities.tools import TOOL_CATALOG
        for tool_name in personality_tools:
            if tool_name in TOOL_CATALOG:
                tool_def = TOOL_CATALOG[tool_name]
                tool_schemas.append({
                    "name": tool_name,
                    "description": tool_def.get("description", ""),
                    "input_schema": tool_def.get("parameters", {}),
                    "source": "personality_builtin",
                    "required": False,
                })
    except ImportError:
        pass

    # Forge tool IDs from agentic config
    forge_tool_ids = []
    tool_details = agentic.get("tool_details") or {}
    for tid, detail in tool_details.items():
        forge_tool_ids.append({
            "id": tid,
            "name": detail.get("name") or tid,
            "description": detail.get("description") or "",
            "source": "forge",
        })

    # Capability summary
    capabilities = agentic.get("capabilities") or []

    return {
        "schema_version": 1,
        "personality_tools": {
            "description": "Simple tool IDs from PersonalityAgent.allowed_tools",
            "tools": personality_tools,
        },
        "forge_tools": {
            "description": "Tool references from Context Forge / MCP",
            "tools": forge_tool_ids,
        },
        "tool_schemas": tool_schemas,
        "capability_summary": {
            "required": [c for c in capabilities if c in ("generate_images",)],
            "optional": [c for c in capabilities if c not in ("generate_images",)],
        },
    }


def _build_mcp_servers_manifest(project: Dict[str, Any]) -> Dict[str, Any]:
    """Build mcp_servers.json from project's agentic configuration."""
    agentic = project.get("agentic") or {}
    tool_details = agentic.get("tool_details") or {}

    # Detect MCP servers from tool prefixes
    server_prefixes = set()
    for tid, detail in tool_details.items():
        name = detail.get("name") or tid
        # HomePilot MCP tools follow hp.<server>.<tool> naming
        parts = name.split(".")
        if len(parts) >= 2 and parts[0] == "hp":
            server_prefixes.add(f"hp.{parts[1]}")

    # Map known prefixes to built-in servers
    _KNOWN_SERVERS = {
        "hp.personal": {
            "name": "hp-personal-assistant",
            "description": "Personal notes search and day planning",
            "default_port": 9101,
            "source": {"type": "builtin", "builtin_id": "hp-personal-assistant"},
        },
        "hp.knowledge": {
            "name": "hp-knowledge",
            "description": "Knowledge base and document retrieval",
            "default_port": 9102,
            "source": {"type": "builtin", "builtin_id": "hp-knowledge"},
        },
        "hp.decision": {
            "name": "hp-decision-copilot",
            "description": "Decision support and analysis",
            "default_port": 9103,
            "source": {"type": "builtin", "builtin_id": "hp-decision-copilot"},
        },
        "hp.brief": {
            "name": "hp-executive-briefing",
            "description": "Executive briefing generation",
            "default_port": 9104,
            "source": {"type": "builtin", "builtin_id": "hp-executive-briefing"},
        },
        "hp.web": {
            "name": "hp-web-search",
            "description": "Web search via SearXNG or Tavily",
            "default_port": 9105,
            "source": {"type": "builtin", "builtin_id": "hp-web-search"},
        },
    }

    servers = []
    for prefix in sorted(server_prefixes):
        if prefix in _KNOWN_SERVERS:
            info = _KNOWN_SERVERS[prefix]
            # Collect tools that belong to this server
            tool_names = [
                (detail.get("name") or tid)
                for tid, detail in tool_details.items()
                if (detail.get("name") or tid).startswith(prefix + ".")
            ]
            servers.append({
                **info,
                "transport": "HTTP",
                "protocol": "MCP",
                "tools_provided": tool_names,
                "health_check": {
                    "method": "POST",
                    "path": "/rpc",
                    "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1},
                },
            })

    return {"schema_version": 1, "servers": servers}


def _build_a2a_agents_manifest(project: Dict[str, Any]) -> Dict[str, Any]:
    """Build a2a_agents.json from project's agentic configuration."""
    agentic = project.get("agentic") or {}
    agent_details = agentic.get("agent_details") or {}
    agent_ids = agentic.get("a2a_agent_ids") or []

    _KNOWN_AGENTS = {
        "everyday-assistant": {
            "name": "everyday-assistant",
            "description": "Friendly helper for summarization and planning",
            "default_port": 9201,
            "source": {"type": "builtin", "builtin_id": "everyday-assistant"},
            "required": False,
        },
        "chief-of-staff": {
            "name": "chief-of-staff",
            "description": "Orchestrates fact-gathering, option-structuring, and briefing",
            "default_port": 9202,
            "source": {"type": "builtin", "builtin_id": "chief-of-staff"},
            "required": False,
        },
    }

    agents = []
    seen = set()
    for aid in agent_ids:
        detail = agent_details.get(aid) or {}
        name = detail.get("name") or aid
        if name in seen:
            continue
        seen.add(name)

        if name in _KNOWN_AGENTS:
            agents.append(_KNOWN_AGENTS[name])
        else:
            agents.append({
                "name": name,
                "description": detail.get("description") or "",
                "default_port": None,
                "source": {"type": "external"},
                "required": False,
            })

    return {"schema_version": 1, "agents": agents}


def _build_models_manifest(project: Dict[str, Any]) -> Dict[str, Any]:
    """Build models.json from persona appearance settings."""
    appearance = project.get("persona_appearance") or {}
    avatar_settings = appearance.get("avatar_settings") or {}
    img_model = avatar_settings.get("img_model") or appearance.get("img_model") or ""

    models = []
    if img_model:
        # Try to resolve architecture
        arch = "unknown"
        try:
            from ..model_config import detect_architecture_from_filename
            arch = detect_architecture_from_filename(img_model) or "unknown"
        except (ImportError, Exception):
            pass

        models.append({
            "filename": img_model,
            "architecture": arch,
            "role": "primary_avatar",
            "required": True,
        })

    return {
        "schema_version": 1,
        "image_models": models,
        "llm_hint": {
            "min_capability": "7b",
            "recommended": "llama3:8b",
            "note": "Any 7B+ instruction-tuned model works",
        },
    }


def _build_suite_manifest(project: Dict[str, Any]) -> Dict[str, Any]:
    """Build suite.json from project's agentic configuration."""
    agentic = project.get("agentic") or {}
    tool_source = agentic.get("tool_source") or "all"

    return {
        "schema_version": 1,
        "recommended_suite": "default_home",
        "tool_source": tool_source,
        "forge_sync_required": bool(agentic.get("tool_ids") or agentic.get("a2a_agent_ids")),
    }


def _build_preview_card(project: Dict[str, Any]) -> Dict[str, Any]:
    """Build card.json for gallery display."""
    persona_agent = project.get("persona_agent") or {}
    persona_appearance = project.get("persona_appearance") or {}
    agentic = project.get("agentic") or {}

    return {
        "name": persona_agent.get("label") or project.get("name") or "Persona",
        "role": persona_agent.get("role") or "",
        "category": persona_agent.get("category") or "general",
        "tone": (persona_agent.get("response_style") or {}).get("tone", "warm"),
        "style_preset": persona_appearance.get("style_preset") or "",
        "capabilities_count": len(agentic.get("capabilities") or []),
        "tools_count": len(persona_agent.get("allowed_tools") or []),
        "has_avatar": bool(persona_appearance.get("selected_filename")),
        "content_rating": "nsfw" if persona_appearance.get("nsfwMode") else "sfw",
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _manifest(project: Dict[str, Any]) -> Dict[str, Any]:
    persona_agent = project.get("persona_agent") or {}
    persona_appearance = project.get("persona_appearance") or {}
    agentic = project.get("agentic") or {}

    return {
        "package_version": PACKAGE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "kind": "homepilot.persona",
        "project_type": "persona",
        "source_project_id": project.get("id"),
        "source_homepilot_version": "2.1.0",
        "created_at": project.get("updated_at") or project.get("created_at"),
        "content_rating": "nsfw" if persona_appearance.get("nsfwMode") else "sfw",
        "contents": {
            "has_avatar": bool(persona_appearance.get("selected_filename")),
            "has_outfits": bool(persona_appearance.get("outfits")),
            "outfit_count": len(persona_appearance.get("outfits") or []),
            "has_tool_dependencies": bool(persona_agent.get("allowed_tools")),
            "has_mcp_servers": bool(agentic.get("tool_details")),
            "has_a2a_agents": bool(agentic.get("a2a_agent_ids")),
            "has_model_requirements": bool(
                (persona_appearance.get("avatar_settings") or {}).get("img_model")
                or persona_appearance.get("img_model")
            ),
        },
        "capability_summary": {
            "personality_tools": persona_agent.get("allowed_tools") or [],
            "capabilities": agentic.get("capabilities") or [],
            "mcp_servers_count": 0,  # filled during export
            "a2a_agents_count": len(agentic.get("a2a_agent_ids") or []),
        },
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_persona_project(
    upload_root: Path,
    project: Dict[str, Any],
    mode: str = "blueprint",
) -> ExportResult:
    """
    Export a persona project into a v2 .hpersona (zip) package.

    v2 adds: dependencies/ (tools, MCP, agents, models, suite) + preview/
    """
    if project.get("project_type") != "persona":
        raise ValueError("Not a persona project")

    persona_agent = project.get("persona_agent") or {}
    persona_appearance = project.get("persona_appearance") or {}
    agentic = project.get("agentic") or {}

    selected = persona_appearance.get("selected_filename")
    thumb = persona_appearance.get("selected_thumb_filename")

    # If selected_filename is absent but a ComfyUI image was selected via the
    # wizard (persona_appearance.selected + sets), resolve the actual filename
    # so it can be exported.  The image URL is like "/files/<filename>".
    if not selected:
        sel_ref = persona_appearance.get("selected")
        if isinstance(sel_ref, dict) and sel_ref.get("image_id"):
            target_id = sel_ref["image_id"]
            target_set = sel_ref.get("set_id")
            for s in (persona_appearance.get("sets") or []):
                for img in (s.get("images") or []):
                    if img.get("id") == target_id and (not target_set or img.get("set_id") == target_set):
                        url = img.get("url") or ""
                        # Extract filename from URL:
                        #   /files/ComfyUI_00042_.png → ComfyUI_00042_.png
                        #   http://…/view?filename=X.png → X.png
                        if "/files/" in url:
                            selected = url.rsplit("/files/", 1)[-1].split("?")[0]
                        elif "filename=" in url:
                            selected = url.split("filename=")[-1].split("&")[0]
                        break
                if selected:
                    break

    # Build dependency manifests
    tools_manifest = _build_tools_manifest(project)
    mcp_manifest = _build_mcp_servers_manifest(project)
    a2a_manifest = _build_a2a_agents_manifest(project)
    models_manifest = _build_models_manifest(project)
    suite_manifest = _build_suite_manifest(project)
    preview_card = _build_preview_card(project)

    # Build manifest with accurate counts
    manifest = _manifest(project)
    manifest["capability_summary"]["mcp_servers_count"] = len(mcp_manifest.get("servers", []))

    pkg = io.BytesIO()
    with zipfile.ZipFile(pkg, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # Core
        z.writestr("manifest.json", json.dumps(manifest, indent=2))

        # Blueprint
        z.writestr("blueprint/persona_agent.json", json.dumps(persona_agent, indent=2))
        z.writestr("blueprint/persona_appearance.json", json.dumps(persona_appearance, indent=2))
        z.writestr("blueprint/agentic.json", json.dumps(agentic, indent=2))

        # Dependencies
        z.writestr("dependencies/tools.json", json.dumps(tools_manifest, indent=2))
        z.writestr("dependencies/mcp_servers.json", json.dumps(mcp_manifest, indent=2))
        z.writestr("dependencies/a2a_agents.json", json.dumps(a2a_manifest, indent=2))
        z.writestr("dependencies/models.json", json.dumps(models_manifest, indent=2))
        z.writestr("dependencies/suite.json", json.dumps(suite_manifest, indent=2))

        # Preview
        z.writestr("preview/card.json", json.dumps(preview_card, indent=2))

        # Assets — collect from the project's appearance directory on disk.
        # We try two strategies:
        #   1) Resolve selected_filename / selected_thumb_filename paths
        #   2) Scan the project's appearance directory for all image files
        # This ensures avatars and outfit images are always included when
        # they exist on disk, even if the DB paths are stale or incomplete.

        _added_assets: set = set()  # track arcnames to avoid duplicates

        def _add_file(abs_path: Path, arcname: str) -> None:
            """Add a single file to the ZIP under assets/ if it exists."""
            if arcname in _added_assets:
                return
            if abs_path.exists() and abs_path.is_file():
                z.write(abs_path, arcname=arcname)
                _added_assets.add(arcname)

        def add_asset_by_relpath(rel_path: Optional[str]) -> None:
            """Resolve a DB-stored relative path and add to ZIP."""
            if not rel_path:
                return
            rel_path = rel_path.replace("\\", "/")
            if rel_path.startswith("projects/"):
                abs_path = upload_root / rel_path
            else:
                # Try appearance dir first, then upload_root (for uncommitted
                # ComfyUI outputs that were selected but never committed).
                basename = _safe_basename(rel_path)
                abs_path = appearance_dir / basename
                if not abs_path.exists():
                    abs_path = upload_root / basename
            arcname = f"assets/{_safe_basename(abs_path.name)}"
            _add_file(abs_path, arcname)

        # Locate the project's appearance directory
        project_id = project.get("id") or ""
        appearance_dir = upload_root / "projects" / project_id / "persona" / "appearance"

        # Strategy 1: explicit DB paths
        add_asset_by_relpath(selected)
        add_asset_by_relpath(thumb)

        # Strategy 2: scan appearance directory for all image/asset files
        _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
        if appearance_dir.is_dir():
            for f in sorted(appearance_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in _IMAGE_EXTS:
                    arcname = f"assets/{_safe_basename(f.name)}"
                    _add_file(f, arcname)

        # Strategy 3: outfit images (may be stored outside appearance dir)
        for outfit in (persona_appearance.get("outfits") or []):
            add_asset_by_relpath(outfit.get("filename"))
            add_asset_by_relpath(outfit.get("thumb_filename"))

    name = project.get("name") or persona_agent.get("label") or "persona"
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip() or "persona"
    out_name = f"{safe_name}.hpersona"
    return ExportResult(filename=out_name, content_type="application/zip", data=pkg.getvalue())


# ---------------------------------------------------------------------------
# Preview (parse without importing)
# ---------------------------------------------------------------------------

def preview_persona_package(package_bytes: bytes) -> PreviewResult:
    """
    Parse a .hpersona package and return its contents for preview.
    Does NOT create a project — just reads and validates.
    """
    with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        if manifest.get("kind") != "homepilot.persona":
            raise ValueError("Invalid package kind — expected homepilot.persona")
        if int(manifest.get("schema_version", 0)) > _MAX_IMPORT_SCHEMA:
            raise ValueError(
                f"Package schema_version {manifest.get('schema_version')} "
                f"is newer than this HomePilot (max {_MAX_IMPORT_SCHEMA})"
            )

        persona_agent = json.loads(z.read("blueprint/persona_agent.json").decode("utf-8"))
        persona_appearance = json.loads(z.read("blueprint/persona_appearance.json").decode("utf-8"))

        # v2 optional files
        agentic = {}
        dependencies = {}
        try:
            agentic = json.loads(z.read("blueprint/agentic.json").decode("utf-8"))
        except KeyError:
            pass

        for dep_name in ("tools", "mcp_servers", "a2a_agents", "models", "suite"):
            try:
                dependencies[dep_name] = json.loads(
                    z.read(f"dependencies/{dep_name}.json").decode("utf-8")
                )
            except KeyError:
                pass

        # Check for assets
        asset_names = [
            info.filename.split("/", 1)[1]
            for info in z.infolist()
            if info.filename.startswith("assets/") and not info.is_dir()
            and len(info.filename.split("/", 1)) == 2
            and info.filename.split("/", 1)[1]
        ]

        has_avatar = bool(
            persona_appearance.get("selected_filename")
            or any(n.startswith("avatar_") for n in asset_names)
        )

        return PreviewResult(
            manifest=manifest,
            persona_agent=persona_agent,
            persona_appearance=persona_appearance,
            agentic=agentic,
            dependencies=dependencies,
            has_avatar=has_avatar,
            asset_names=asset_names,
        )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_persona_package(
    upload_root: Path,
    package_bytes: bytes,
    *,
    make_public: bool = False,
) -> Dict[str, Any]:
    """
    Import a .hpersona package (v1 or v2) and create a new persona project.

    Handles backward compatibility:
    - v1: only blueprint/ + assets/ (no dependencies/)
    - v2: full package with dependencies/ + preview/
    """
    with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as z:
        # Validate manifest
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        if manifest.get("kind") != "homepilot.persona":
            raise ValueError("Invalid package kind — expected homepilot.persona")
        if int(manifest.get("schema_version", 0)) > _MAX_IMPORT_SCHEMA:
            raise ValueError(
                f"Package schema_version {manifest.get('schema_version')} "
                f"is newer than this HomePilot (max {_MAX_IMPORT_SCHEMA})"
            )

        persona_agent = json.loads(z.read("blueprint/persona_agent.json").decode("utf-8"))
        persona_appearance = json.loads(z.read("blueprint/persona_appearance.json").decode("utf-8"))

        # v2: read agentic data
        agentic = {}
        try:
            agentic = json.loads(z.read("blueprint/agentic.json").decode("utf-8"))
        except KeyError:
            pass

        # Create new project
        create_data: Dict[str, Any] = {
            "name": persona_agent.get("label") or "Imported Persona",
            "description": f"Imported persona package (v{manifest.get('package_version', 1)})",
            "project_type": "persona",
            "is_public": bool(make_public),
            "persona_agent": persona_agent,
            "persona_appearance": persona_appearance,
        }
        if agentic:
            create_data["agentic"] = agentic

        created = projects.create_new_project(create_data)

        project_id = created["id"]
        project_dir = upload_root / "projects" / project_id
        appearance_dir = project_dir / "persona" / "appearance"
        appearance_dir.mkdir(parents=True, exist_ok=True)

        # Copy assets
        for info in z.infolist():
            if not info.filename.startswith("assets/") or info.is_dir():
                continue
            parts = info.filename.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            asset_name = _safe_basename(parts[1])
            dst = appearance_dir / asset_name
            with z.open(info, "r") as r, open(dst, "wb") as w:
                shutil.copyfileobj(r, w)

        # Remap avatar paths to new project.
        # Strategy: try explicit DB paths first, then auto-detect from
        # extracted assets if the DB paths are empty or stale.
        updated: Dict[str, Any] = {}
        sel = persona_appearance.get("selected_filename")
        th = persona_appearance.get("selected_thumb_filename")

        def _remap(field: str, val: Optional[str]) -> None:
            if not isinstance(val, str):
                return
            bn = _safe_basename(val)
            candidate = appearance_dir / bn
            if candidate.exists():
                updated.setdefault("persona_appearance", dict(persona_appearance))
                updated["persona_appearance"][field] = str(
                    candidate.relative_to(upload_root)
                )

        _remap("selected_filename", sel)
        _remap("selected_thumb_filename", th)

        # Auto-detect: if no selected_filename was remapped but avatar files
        # exist on disk (extracted from assets/), pick the first match.
        if "persona_appearance" not in updated or \
                not updated["persona_appearance"].get("selected_filename"):
            extracted = sorted(appearance_dir.iterdir()) if appearance_dir.is_dir() else []
            for f in extracted:
                if f.is_file() and f.name.startswith("avatar_") and not f.name.startswith("thumb_"):
                    updated.setdefault("persona_appearance", dict(persona_appearance))
                    updated["persona_appearance"]["selected_filename"] = str(
                        f.relative_to(upload_root)
                    )
                    break
            for f in extracted:
                if f.is_file() and f.name.startswith("thumb_avatar_"):
                    updated.setdefault("persona_appearance", dict(persona_appearance))
                    updated["persona_appearance"]["selected_thumb_filename"] = str(
                        f.relative_to(upload_root)
                    )
                    break

        if updated:
            created = projects.update_project(project_id, updated)

        return created
