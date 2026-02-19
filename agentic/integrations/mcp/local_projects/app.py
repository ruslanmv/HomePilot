"""MCP server: local-projects — safe access to local project/workspace files.

Tools:
  projects.list(root_path?)
  projects.read_file(path)
  projects.search_text(query, root_path?, file_globs?, limit=50)
  projects.write_file(path, content)   [write-gated]
  projects.diff(path, proposed_content)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
ALLOWED_ROOTS = [r.strip() for r in os.getenv("ALLOWED_ROOTS", "").split(",") if r.strip()]

# Blocked patterns
_BLOCKED = {".ssh", ".gnupg", ".aws", ".env", ".git/config", "credentials.json"}


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _write_gate(action: str) -> Json | None:
    if not WRITE_ENABLED:
        msg = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
        if DRY_RUN:
            msg += " (DRY_RUN mode — no changes made)"
        return _text(msg)
    return None


def _is_allowed(path_str: str) -> bool:
    """Check path is within allowed roots and not blocked."""
    p = Path(path_str).resolve()
    for part in p.parts:
        if part in _BLOCKED:
            return False
    if not ALLOWED_ROOTS:
        return True  # no restriction configured
    return any(str(p).startswith(str(Path(r).resolve())) for r in ALLOWED_ROOTS)


async def projects_list(args: Json) -> Json:
    root_path = str(args.get("root_path", "")).strip()
    if not root_path:
        if ALLOWED_ROOTS:
            return {"roots": ALLOWED_ROOTS, "hint": "Provide root_path to list contents."}
        return _text("No root_path provided and ALLOWED_ROOTS not configured.")

    if not _is_allowed(root_path):
        return _text(f"Access denied: '{root_path}' is outside allowed roots.")

    p = Path(root_path)
    if not p.is_dir():
        return _text(f"'{root_path}' is not a directory.")

    entries = []
    for child in sorted(p.iterdir()):
        if child.name.startswith("."):
            continue
        entries.append({"name": child.name, "type": "dir" if child.is_dir() else "file", "size": child.stat().st_size if child.is_file() else None})
    return {"root": root_path, "entries": entries[:200]}


async def projects_read_file(args: Json) -> Json:
    path = str(args.get("path", "")).strip()
    if not path:
        return _text("Please provide a 'path'.")
    if not _is_allowed(path):
        return _text(f"Access denied: '{path}'.")
    p = Path(path)
    if not p.is_file():
        return _text(f"'{path}' is not a file or does not exist.")
    try:
        content = p.read_text(errors="replace")[:100_000]
    except Exception as e:
        return _text(f"Error reading '{path}': {e}")
    return {"path": path, "content": content, "size": p.stat().st_size}


async def projects_search_text(args: Json) -> Json:
    query = str(args.get("query", "")).strip()
    root_path = str(args.get("root_path", "")).strip()
    limit = max(1, min(int(args.get("limit", 50) or 50), 200))
    if not query:
        return _text("Please provide a non-empty 'query'.")
    if not root_path:
        if ALLOWED_ROOTS:
            root_path = ALLOWED_ROOTS[0]
        else:
            return _text("No root_path provided and ALLOWED_ROOTS not configured.")
    if not _is_allowed(root_path):
        return _text(f"Access denied: '{root_path}'.")
    # Placeholder search — in production, use ripgrep or index
    return _text(f"Search for '{query}' in '{root_path}' (placeholder — {limit} max results).")


async def projects_write_file(args: Json) -> Json:
    gate = _write_gate("projects.write_file")
    if gate:
        return gate
    path = str(args.get("path", "")).strip()
    content = str(args.get("content", ""))
    if not path:
        return _text("Please provide a 'path'.")
    if not _is_allowed(path):
        return _text(f"Access denied: '{path}'.")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content)
    return _text(f"Wrote {len(content)} bytes to '{path}'.")


async def projects_diff(args: Json) -> Json:
    path = str(args.get("path", "")).strip()
    proposed = str(args.get("proposed_content", ""))
    if not path:
        return _text("Please provide a 'path'.")
    if not _is_allowed(path):
        return _text(f"Access denied: '{path}'.")
    p = Path(path)
    if not p.is_file():
        return _text(f"'{path}' does not exist — would create new file ({len(proposed)} bytes).")
    existing = p.read_text(errors="replace")
    if existing == proposed:
        return _text("No changes detected.")
    return _text(f"Diff preview: existing={len(existing)} bytes, proposed={len(proposed)} bytes. (detailed diff not yet implemented)")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.projects.list",
        description="List files and directories in a project root.",
        input_schema={
            "type": "object",
            "properties": {
                "root_path": {"type": "string", "description": "Root directory to list"},
            },
        },
        handler=projects_list,
    ),
    ToolDef(
        name="hp.projects.read_file",
        description="Read the contents of a file.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
            },
            "required": ["path"],
        },
        handler=projects_read_file,
    ),
    ToolDef(
        name="hp.projects.search_text",
        description="Search for text across project files.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "root_path": {"type": "string"},
                "file_globs": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
            "required": ["query"],
        },
        handler=projects_search_text,
    ),
    ToolDef(
        name="hp.projects.write_file",
        description="Write content to a file. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=projects_write_file,
    ),
    ToolDef(
        name="hp.projects.diff",
        description="Preview a diff between existing file and proposed content (safe, read-only).",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "proposed_content": {"type": "string"},
            },
            "required": ["path", "proposed_content"],
        },
        handler=projects_diff,
    ),
]

app = create_mcp_app(server_name="homepilot-local-projects", tools=TOOLS)
