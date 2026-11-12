"""Per-project tool and connector permissions.

Each project decides which capabilities may operate inside it. The decision is
enforced on the server, at the moment a tool would run — the tool catalog the
model sees is filtered too, but that is a convenience: a model that emits a
call to a disabled tool is refused in ``agent_chat`` no matter what it wrote.

Kinds
-----
``tool``       A built-in HomePilot agent tool (``vision.analyze``, ``web.search`` …).
               **Enabled unless the project turns it off**, so existing projects
               keep working exactly as before.
``connector``  An external service acting on the user's behalf (``gitpilot`` …).
               **Off until the project's owner turns it on.** A connector can
               change things outside HomePilot, so it is opt-in per project.

Outside any project (a plain agent chat), connector tools follow the user's
own connector link, as before.

Only the project owner may change these settings; every change is written to
the project's activity log.

Credentials are never part of a project. When someone other than the owner
uses a shared or public project, connector tools run with *that person's own*
linked account, or not at all — a project never lends its owner's
credentials.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional

KINDS = ("tool", "connector")

#: Which connector each external tool family needs.
TOOL_CONNECTOR = {"code.": "gitpilot"}


def _conn() -> sqlite3.Connection:
    from .storage import _get_db_path
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS project_capabilities("
        "project_id TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, enabled INTEGER NOT NULL, "
        "updated_by TEXT, updated_at REAL NOT NULL, PRIMARY KEY(project_id, kind, ref))")
    return con


def _saved(project_id: str) -> Dict[tuple, bool]:
    con = _conn()
    try:
        rows = con.execute("SELECT kind, ref, enabled FROM project_capabilities WHERE project_id = ?",
                           (project_id,)).fetchall()
    finally:
        con.close()
    return {(r["kind"], r["ref"]): bool(r["enabled"]) for r in rows}


def _builtin_tools() -> List[str]:
    from .agent_chat import TOOL_REGISTRY
    return list(TOOL_REGISTRY.keys())


def _connectors() -> List[Dict[str, Any]]:
    from .connectors import CATALOG
    return [c for c in CATALOG if c["id"] in TOOL_CONNECTOR.values()]


def connector_for_tool(tool: str) -> Optional[str]:
    return next((cid for prefix, cid in TOOL_CONNECTOR.items() if tool.startswith(prefix)), None)


def is_enabled(project_id: Optional[str], kind: str, ref: str) -> bool:
    """The project's decision. No project ⇒ ``True`` (the caller decides)."""
    if not project_id:
        return True
    saved = _saved(project_id).get((kind, ref))
    if saved is not None:
        return saved
    return kind == "tool"          # built-ins on by default, connectors off


def tool_allowed(project_id: Optional[str], tool: str) -> bool:
    """May ``tool`` run in this project right now?"""
    if not project_id:
        return True
    connector = connector_for_tool(tool)
    if connector:
        return is_enabled(project_id, "connector", connector)
    return is_enabled(project_id, "tool", tool)


def allowed_tools(project_id: Optional[str], tools: Iterable[str]) -> List[str]:
    return [t for t in tools if tool_allowed(project_id, t)]


def describe(project_id: str, user_id: str) -> Dict[str, Any]:
    """What the settings screen shows: every capability and its state.
    ``linked`` says whether *this viewer* has an account linked for a connector."""
    from .connectors import store
    saved = _saved(project_id)
    linked = {r["id"] for r in store.linked(user_id) if not r.get("expired")} if user_id else set()
    tools = [{"kind": "tool", "ref": t, "enabled": saved.get(("tool", t), True)}
             for t in _builtin_tools()]
    connectors = [{"kind": "connector", "ref": c["id"], "name": c["name"],
                   "description": c["description"], "enabled": saved.get(("connector", c["id"]), False),
                   "linked": c["id"] in linked}
                  for c in _connectors()]
    return {"project_id": project_id, "tools": tools, "connectors": connectors}


def update(project_id: str, changes: Dict[str, Dict[str, bool]], *, by: str) -> Dict[str, Any]:
    """``{"tools": {"web.search": False}, "connectors": {"gitpilot": True}}``.
    Unknown names are rejected rather than stored."""
    from . import project_access
    known = {"tool": set(_builtin_tools()), "connector": {c["id"] for c in _connectors()}}
    rows = []
    for section, kind in (("tools", "tool"), ("connectors", "connector")):
        for ref, enabled in (changes.get(section) or {}).items():
            if ref not in known[kind]:
                raise ValueError(f"unknown {kind} '{ref}'")
            rows.append((kind, ref, bool(enabled)))
    con = _conn()
    try:
        for kind, ref, enabled in rows:
            con.execute(
                "INSERT INTO project_capabilities(project_id, kind, ref, enabled, updated_by, updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(project_id, kind, ref) DO UPDATE SET "
                "enabled = excluded.enabled, updated_by = excluded.updated_by, updated_at = excluded.updated_at",
                (project_id, kind, ref, 1 if enabled else 0, by, time.time()))
        con.commit()
    finally:
        con.close()
    if rows:
        project_access.log(project_id, by, "capabilities.changed",
                           [{"kind": k, "ref": r, "enabled": e} for k, r, e in rows])
    return describe(project_id, by)


def forget(project_id: str) -> None:
    con = _conn()
    try:
        con.execute("DELETE FROM project_capabilities WHERE project_id = ?", (project_id,))
        con.commit()
    finally:
        con.close()
