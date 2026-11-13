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
``connector``  An external service acting on the user's behalf (``gitpilot``,
               ``daypilot`` …). **Off until the project's owner turns it on.**
``feature``    A finer switch inside a connector (``daypilot.calendar`` …).
               **Off until turned on**, and only effective while its connector
               is on. A feature marked ``coming_soon`` cannot be turned on.

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

KINDS = ("tool", "connector", "feature")

#: Which connector each external tool family needs.
TOOL_CONNECTOR = {"code.": "gitpilot", "workday.": "daypilot"}

#: Per-connector feature switches: feature -> label, description, and the tools it gates.
CONNECTOR_FEATURES: Dict[str, List[Dict[str, Any]]] = {
    "daypilot": [
        {"ref": "plan", "name": "Today's plan", "description": "Focus block, next block, standup draft.",
         "tools": ["workday.today"]},
        {"ref": "tasks", "name": "Tasks and project updates", "description": "Open tasks and operational projects.",
         "tools": ["workday.tasks"]},
        {"ref": "calendar", "name": "Calendar", "description": "Today's and upcoming events, and conflicts.",
         "tools": ["workday.calendar"]},
        {"ref": "proposals", "name": "Propose actions for approval",
         "description": "Ask DayPilot to prepare changes. You approve each one in DayPilot.",
         "tools": ["workday.propose"]},
        {"ref": "wellness", "name": "Personal wellness sharing",
         "description": "Not available yet: DayPilot keeps wellness data in your browser only.",
         "tools": [], "coming_soon": True},
    ],
}


def feature_for_tool(tool: str) -> Optional[str]:
    """``workday.calendar`` → ``daypilot.calendar``; ``None`` for un-gated tools."""
    for connector, features in CONNECTOR_FEATURES.items():
        for f in features:
            if tool in f["tools"]:
                return f"{connector}.{f['ref']}"
    return None


def feature_enabled(project_id: Optional[str], feature: str) -> bool:
    """A connector feature is on only when its switch *and* its connector are on."""
    if not project_id:
        return True
    connector = feature.split(".", 1)[0]
    return is_enabled(project_id, "connector", connector) and is_enabled(project_id, "feature", feature)


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
    return kind == "tool"          # built-ins on by default; connectors and features off


def tool_allowed(project_id: Optional[str], tool: str) -> bool:
    """May ``tool`` run in this project right now?"""
    if not project_id:
        return True
    feature = feature_for_tool(tool)
    if feature:
        return feature_enabled(project_id, feature)
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
                   "linked": c["id"] in linked,
                   "features": [{"kind": "feature", "ref": f"{c['id']}.{f['ref']}", "name": f["name"],
                                 "description": f["description"],
                                 "enabled": (not f.get("coming_soon"))
                                 and saved.get(("feature", f"{c['id']}.{f['ref']}"), False),
                                 "coming_soon": bool(f.get("coming_soon"))}
                                for f in CONNECTOR_FEATURES.get(c["id"], [])]}
                  for c in _connectors()]
    return {"project_id": project_id, "tools": tools, "connectors": connectors}


def update(project_id: str, changes: Dict[str, Dict[str, bool]], *, by: str) -> Dict[str, Any]:
    """``{"tools": {"web.search": False}, "connectors": {"gitpilot": True}}``.
    Unknown names are rejected rather than stored."""
    from . import project_access
    known = {"tool": set(_builtin_tools()), "connector": {c["id"] for c in _connectors()},
             "feature": {f"{cid}.{f['ref']}" for cid, fs in CONNECTOR_FEATURES.items() for f in fs}}
    soon = {f"{cid}.{f['ref']}" for cid, fs in CONNECTOR_FEATURES.items() for f in fs if f.get("coming_soon")}
    rows = []
    for section, kind in (("tools", "tool"), ("connectors", "connector"), ("features", "feature")):
        for ref, enabled in (changes.get(section) or {}).items():
            if ref not in known[kind]:
                raise ValueError(f"unknown {kind} '{ref}'")
            if kind == "feature" and ref in soon and enabled:
                raise ValueError(f"'{ref}' is not available yet")
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
