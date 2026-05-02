from __future__ import annotations

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_WORKSPACES: dict[str, dict[str, str]] = {}


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


def _get_ws(workspace_id: str) -> dict[str, str]:
    return _WORKSPACES.setdefault(workspace_id, {})


async def open_archive(args: dict) -> dict:
    workspace_id = str(args.get("workspace_id", "")).strip() or "default"
    files = args.get("files") or {}
    if not isinstance(files, dict):
        return _content("files must be a path->content object", ok=False)
    ws = _get_ws(workspace_id)
    for path, content in files.items():
        ws[str(path)] = str(content)
    return _content(f"Loaded {len(files)} files into {workspace_id}", ok=True, workspace_id=workspace_id, file_count=len(ws))


async def ws_search(args: dict) -> dict:
    workspace_id = str(args.get("workspace_id", "")).strip() or "default"
    query = str(args.get("query", "")).strip().lower()
    top_k = max(1, min(int(args.get("top_k", 20) or 20), 200))
    ws = _get_ws(workspace_id)
    matches = []
    for path, content in ws.items():
        if query in path.lower() or query in content.lower():
            matches.append({"path": path, "preview": content[:180]})
    matches = matches[:top_k]
    return _content(f"Found {len(matches)} matches in {workspace_id}", ok=True, workspace_id=workspace_id, matches=matches)


async def ws_read_range(args: dict) -> dict:
    workspace_id = str(args.get("workspace_id", "")).strip() or "default"
    path = str(args.get("path", "")).strip()
    start = max(1, int(args.get("start_line", 1) or 1))
    end = max(start, int(args.get("end_line", start) or start))
    ws = _get_ws(workspace_id)
    if path not in ws:
        return _content("Path not found", ok=False, workspace_id=workspace_id, path=path)
    lines = ws[path].splitlines()
    chunk = lines[start - 1 : end]
    text = "\n".join(f"{idx}: {line}" for idx, line in enumerate(chunk, start=start))
    return _content(text or "<empty range>", ok=True, workspace_id=workspace_id, path=path, start_line=start, end_line=end)


async def ws_replace_range(args: dict) -> dict:
    workspace_id = str(args.get("workspace_id", "")).strip() or "default"
    path = str(args.get("path", "")).strip()
    start = max(1, int(args.get("start_line", 1) or 1))
    end = max(start, int(args.get("end_line", start) or start))
    replacement = str(args.get("replacement", ""))
    ws = _get_ws(workspace_id)
    if path not in ws:
        return _content("Path not found", ok=False, workspace_id=workspace_id, path=path)

    lines = ws[path].splitlines()
    prefix = lines[: start - 1]
    suffix = lines[end:]
    ws[path] = "\n".join(prefix + replacement.splitlines() + suffix)
    return _content("Range replaced", ok=True, workspace_id=workspace_id, path=path)


async def ws_tree(args: dict) -> dict:
    workspace_id = str(args.get("workspace_id", "")).strip() or "default"
    ws = _get_ws(workspace_id)
    paths = sorted(ws.keys())
    return _content("\n".join(paths) if paths else "<empty workspace>", ok=True, workspace_id=workspace_id, paths=paths)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.ws.open_archive", "Load workspace files", {"type": "object", "properties": {"workspace_id": {"type": "string"}, "files": {"type": "object"}}}, open_archive),
        ToolDef("hp.ws.search", "Search files in workspace", {"type": "object", "properties": {"workspace_id": {"type": "string"}, "query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["query"]}, ws_search),
        ToolDef("hp.ws.read_range", "Read line range from workspace file", {"type": "object", "properties": {"workspace_id": {"type": "string"}, "path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}, ws_read_range),
        ToolDef("hp.ws.replace_range", "Replace line range in workspace file", {"type": "object", "properties": {"workspace_id": {"type": "string"}, "path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}, "replacement": {"type": "string"}}, "required": ["path", "replacement"]}, ws_replace_range),
        ToolDef("hp.ws.tree", "List workspace files", {"type": "object", "properties": {"workspace_id": {"type": "string"}}}, ws_tree),
    ]


app = create_mcp_app(server_name="mcp-archive-workspace", tools=register_tools())
