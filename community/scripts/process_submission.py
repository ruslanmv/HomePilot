#!/usr/bin/env python3
"""
process_submission.py — Validate a .hpersona package and extract metadata
for the GitHub Actions persona-publish pipeline.

Usage:
    python process_submission.py validate <path-to-.hpersona>
    python process_submission.py extract  <path-to-.hpersona> <output-dir>
    python process_submission.py registry <registry.json> <entry.json> [--remove <persona_id>]

Exit codes:
    0 = success
    1 = validation failure (printed to stderr)
    2 = bad arguments
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SCHEMA_VERSION = 2
MAX_PACKAGE_SIZE = 50 * 1024 * 1024  # 50 MB
REQUIRED_FILES = ["manifest.json", "blueprint/persona_agent.json", "blueprint/persona_appearance.json"]
VALID_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def validate_package(path: Path) -> Dict[str, Any]:
    """
    Validate a .hpersona ZIP package.

    Returns a dict with keys:
        valid (bool), errors (list[str]), warnings (list[str]),
        manifest (dict | None), card (dict | None)
    """
    errors: List[str] = []
    warnings: List[str] = []
    manifest: Optional[Dict[str, Any]] = None
    card: Optional[Dict[str, Any]] = None

    # --- Size check ---
    size = path.stat().st_size
    if size > MAX_PACKAGE_SIZE:
        errors.append(f"Package too large: {size / 1024 / 1024:.1f} MB (max {MAX_PACKAGE_SIZE // 1024 // 1024} MB)")
        return {"valid": False, "errors": errors, "warnings": warnings, "manifest": None, "card": None}

    # --- ZIP validity ---
    if not zipfile.is_zipfile(path):
        errors.append("File is not a valid ZIP archive")
        return {"valid": False, "errors": errors, "warnings": warnings, "manifest": None, "card": None}

    with zipfile.ZipFile(path, "r") as z:
        names = set(z.namelist())

        # --- Required files ---
        for req in REQUIRED_FILES:
            if req not in names:
                errors.append(f"Missing required file: {req}")

        if errors:
            return {"valid": False, "errors": errors, "warnings": warnings, "manifest": None, "card": None}

        # --- Manifest ---
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"manifest.json is not valid JSON: {exc}")
            return {"valid": False, "errors": errors, "warnings": warnings, "manifest": None, "card": None}

        if manifest.get("kind") != "homepilot.persona":
            errors.append(f"Invalid kind: {manifest.get('kind')} (expected homepilot.persona)")

        schema_ver = int(manifest.get("schema_version", 0))
        if schema_ver < 1:
            errors.append("schema_version must be >= 1")
        elif schema_ver > MAX_SCHEMA_VERSION:
            errors.append(f"schema_version {schema_ver} is not supported (max {MAX_SCHEMA_VERSION})")

        # --- Blueprint validity ---
        try:
            agent = json.loads(z.read("blueprint/persona_agent.json").decode("utf-8"))
            if not agent.get("label"):
                warnings.append("persona_agent.label is empty — name may display as 'Persona'")
        except (json.JSONDecodeError, UnicodeDecodeError):
            errors.append("blueprint/persona_agent.json is not valid JSON")

        try:
            json.loads(z.read("blueprint/persona_appearance.json").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            errors.append("blueprint/persona_appearance.json is not valid JSON")

        # --- Optional card ---
        if "preview/card.json" in names:
            try:
                card = json.loads(z.read("preview/card.json").decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                warnings.append("preview/card.json is not valid JSON — will generate from blueprint")

        # --- Asset sanity ---
        asset_files = [n for n in names if n.startswith("assets/") and not n.endswith("/")]
        for af in asset_files:
            ext = os.path.splitext(af)[1].lower()
            if ext not in VALID_ASSET_EXTENSIONS:
                warnings.append(f"Unexpected asset type: {af}")

        # --- Path traversal check ---
        for name in names:
            if ".." in name or name.startswith("/"):
                errors.append(f"Suspicious path in archive: {name}")

        # --- Dependencies (v2) ---
        if schema_ver >= 2:
            for dep in ("tools", "mcp_servers", "a2a_agents", "models"):
                dep_path = f"dependencies/{dep}.json"
                if dep_path in names:
                    try:
                        json.loads(z.read(dep_path).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        warnings.append(f"{dep_path} is not valid JSON")
                else:
                    warnings.append(f"Missing optional dependency file: {dep_path}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "manifest": manifest,
        "card": card,
        "size_bytes": size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Extract metadata + preview assets
# ---------------------------------------------------------------------------


def extract_metadata(path: Path, out_dir: Path) -> Dict[str, Any]:
    """
    Extract gallery-ready metadata and preview assets from a .hpersona package.

    Creates in out_dir:
        card.json     — gallery card metadata
        preview.webp  — preview image (if avatar exists in package)
        entry.json    — registry entry ready to merge into registry.json
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    size = path.stat().st_size

    with zipfile.ZipFile(path, "r") as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        agent = json.loads(z.read("blueprint/persona_agent.json").decode("utf-8"))
        appearance = json.loads(z.read("blueprint/persona_appearance.json").decode("utf-8"))

        # Try reading existing card, or build one
        card: Dict[str, Any] = {}
        try:
            card = json.loads(z.read("preview/card.json").decode("utf-8"))
        except (KeyError, json.JSONDecodeError):
            pass

        if not card.get("name"):
            card["name"] = agent.get("label") or "Persona"
        if not card.get("role"):
            card["role"] = agent.get("role") or ""
        card["content_rating"] = manifest.get("content_rating", "sfw")
        card["tools_count"] = len(agent.get("allowed_tools") or [])

        # Agentic data
        agentic: Dict[str, Any] = {}
        try:
            agentic = json.loads(z.read("blueprint/agentic.json").decode("utf-8"))
        except (KeyError, json.JSONDecodeError):
            pass
        card["capabilities_count"] = len(agentic.get("capabilities") or [])

        # Dependencies summary
        deps_summary: Dict[str, Any] = {}
        for dep_name in ("tools", "mcp_servers", "a2a_agents", "models"):
            try:
                deps_summary[dep_name] = json.loads(
                    z.read(f"dependencies/{dep_name}.json").decode("utf-8")
                )
            except (KeyError, json.JSONDecodeError):
                pass
        card["dependencies"] = deps_summary

        # Write card
        (out_dir / "card.json").write_text(json.dumps(card, indent=2))

        # Extract preview image (avatar from assets/)
        preview_extracted = False
        names = z.namelist()
        # Prefer thumbnail, then full avatar
        avatar_candidates = sorted(
            [n for n in names if n.startswith("assets/") and not n.endswith("/")],
            key=lambda x: (0 if "thumb" in x else 1, x),
        )
        for candidate in avatar_candidates:
            ext = os.path.splitext(candidate)[1].lower()
            if ext in VALID_ASSET_EXTENSIONS:
                out_name = f"preview{ext}"
                with z.open(candidate) as src:
                    (out_dir / out_name).write_bytes(src.read())
                preview_extracted = True
                card["preview_filename"] = out_name
                break

    return {
        "card": card,
        "manifest": manifest,
        "sha256": sha,
        "size_bytes": size,
        "preview_extracted": preview_extracted,
    }


# ---------------------------------------------------------------------------
# Registry management
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Convert a persona name to a URL-safe slug."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s or "persona"


def update_registry(
    registry_path: Path,
    entry: Dict[str, Any],
    *,
    remove_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add or update a persona entry in registry.json.
    If remove_id is set, removes that persona instead.
    """
    if registry_path.exists():
        registry = json.loads(registry_path.read_text())
    else:
        registry = {"schema_version": 1, "generated_at": "", "source": "github-pages", "items": []}

    items: List[Dict[str, Any]] = registry.get("items", [])

    if remove_id:
        items = [i for i in items if i.get("id") != remove_id]
    elif entry:
        # Upsert by ID
        persona_id = entry.get("id", "")
        items = [i for i in items if i.get("id") != persona_id]
        items.append(entry)
        # Sort by name for stable ordering
        items.sort(key=lambda x: x.get("name", "").lower())

    from datetime import datetime, timezone
    registry["items"] = items
    registry["generated_at"] = datetime.now(timezone.utc).isoformat()
    registry["total"] = len(items)

    registry_path.write_text(json.dumps(registry, indent=2) + "\n")
    return registry


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} validate|extract|registry ...", file=sys.stderr)
        return 2

    cmd = sys.argv[1]

    if cmd == "validate":
        if len(sys.argv) < 3:
            print("Usage: validate <path>", file=sys.stderr)
            return 2
        result = validate_package(Path(sys.argv[2]))
        print(json.dumps(result, indent=2))
        return 0 if result["valid"] else 1

    elif cmd == "extract":
        if len(sys.argv) < 4:
            print("Usage: extract <path> <output-dir>", file=sys.stderr)
            return 2
        result = extract_metadata(Path(sys.argv[2]), Path(sys.argv[3]))
        print(json.dumps(result, indent=2))
        return 0

    elif cmd == "registry":
        if len(sys.argv) < 4:
            print("Usage: registry <registry.json> <entry.json> [--remove <id>]", file=sys.stderr)
            return 2
        registry_path = Path(sys.argv[2])
        entry_path = Path(sys.argv[3])
        remove_id = None
        if "--remove" in sys.argv:
            idx = sys.argv.index("--remove")
            if idx + 1 < len(sys.argv):
                remove_id = sys.argv[idx + 1]

        entry = json.loads(entry_path.read_text()) if entry_path.exists() and not remove_id else {}
        result = update_registry(registry_path, entry, remove_id=remove_id)
        print(json.dumps({"ok": True, "total": result.get("total", 0)}))
        return 0

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
