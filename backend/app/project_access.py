"""Project ownership, sharing and access control.

Projects used to be one shared JSON file that every signed-in user could read
and change, and most project routes did not check who was asking
(``auth.require_api_key`` is a no-op shim). This module makes a project a
real permission boundary.

Model
-----
* Every project has exactly one **owner** (a HomePilot user id).
* It may belong to a **workspace** (an organisation): members of that
  workspace get the role the workspace grants them.
* It may list individual **members** with a role.
* ``visibility`` is ``private`` (default), ``workspace`` or ``public``.
  Public grants read access only.

Roles, weakest to strongest: ``viewer`` (read, chat) < ``editor`` (change
content, files, instructions) < ``owner`` (delete, sharing, tool and
connector permissions).

Ownership lives in SQLite (``project_acl`` and friends), next to users and
sessions; project content stays in ``projects_metadata.json``. Access is
decided only from these tables, never from fields a client can send.

Inaccessible projects answer 404, the same as missing ones, so project ids
cannot be probed.

Legacy projects
---------------
On first start every project without an ACL row is given one, without
touching its id or content:

* a project that already names its owner (a default assistant) keeps it;
* otherwise the owner is ``HOMEPILOT_LEGACY_PROJECT_OWNER`` (a user id or
  username) when set, else the install's first non-guest account;
* ``is_public: true`` becomes ``visibility = public``.

The JSON file is copied once to ``projects_metadata.pre-acl.json`` first.
Rollback: stop the app and delete the four ``project_*`` tables — the JSON
was not modified, so the previous version runs unchanged.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

ROLES = ("viewer", "editor", "owner")
_RANK = {"viewer": 1, "editor": 2, "owner": 3}
VISIBILITIES = ("private", "workspace", "public")
_migrate_lock = threading.Lock()
_migrated_for: Optional[str] = None


class ProjectAccessDenied(Exception):
    """The caller may not do this to the project (reported as 404)."""


# ── storage ──────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    from .storage import _get_db_path
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def ensure_tables() -> None:
    con = _conn()
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_acl(
                project_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                workspace_id TEXT,
                visibility TEXT NOT NULL DEFAULT 'private',
                created_at REAL NOT NULL,
                migrated INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_project_acl_owner ON project_acl(owner_user_id);
            CREATE TABLE IF NOT EXISTS project_members(
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                added_by TEXT,
                added_at REAL NOT NULL,
                PRIMARY KEY(project_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS workspaces(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workspace_members(
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY(workspace_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS project_activity(
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                user_id TEXT,
                action TEXT NOT NULL,
                detail TEXT,
                ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_project_activity ON project_activity(project_id, ts);
            """
        )
        con.commit()
    finally:
        con.close()


# ── who is asking ────────────────────────────────────────────────────────────

def resolve_user_id(token: str = "") -> str:
    """The signed-in user for a session token; on a single-user install with no
    session, that install's one account (as conversations already do). ``""``
    means anonymous."""
    from .users import _validate_token, count_users, get_or_create_default_user
    if token:
        user = _validate_token(token)
        if user:
            return str(user["id"])
    try:
        if count_users() <= 1:
            return str(get_or_create_default_user()["id"])
    except Exception:
        pass
    return ""


def request_user_id(request) -> str:
    auth = request.headers.get("authorization") or ""
    token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    token = token or (request.cookies.get("homepilot_session") or "").strip()
    return resolve_user_id(token)


# ── legacy migration ─────────────────────────────────────────────────────────

def _legacy_owner() -> str:
    from .users import list_users
    wanted = (os.getenv("HOMEPILOT_LEGACY_PROJECT_OWNER") or "").strip()
    users = [u for u in list_users() if (u.get("auth_provider") or "local") != "guest"]
    if wanted:
        for u in users:
            if wanted in (str(u.get("id")), str(u.get("username"))):
                return str(u["id"])
    if users:
        return str(sorted(users, key=lambda u: str(u.get("created_at") or ""))[0]["id"])
    from .users import get_or_create_default_user
    return str(get_or_create_default_user()["id"])


def migrate_legacy(force: bool = False) -> Dict[str, int]:
    """Give every project without an ACL row an owner. Idempotent."""
    global _migrated_for
    from . import projects
    key = str(projects.PROJECTS_FILE)
    if _migrated_for == key and not force:
        return {"migrated": 0}
    with _migrate_lock:
        ensure_tables()
        db = projects._load_projects_db()
        con = _conn()
        try:
            known = {r["project_id"] for r in con.execute("SELECT project_id FROM project_acl")}
            missing = [pid for pid in db if pid not in known]
            if missing:
                backup = projects.PROJECTS_FILE.with_name("projects_metadata.pre-acl.json")
                if projects.PROJECTS_FILE.exists() and not backup.exists():
                    shutil.copy2(projects.PROJECTS_FILE, backup)
                fallback = _legacy_owner()
                now = time.time()
                for pid in missing:
                    p = db[pid] or {}
                    owner = str(p.get("owner_user_id") or "") or fallback
                    visibility = "public" if p.get("is_public") else "private"
                    con.execute(
                        "INSERT OR IGNORE INTO project_acl(project_id, owner_user_id, visibility, "
                        "created_at, migrated) VALUES(?,?,?,?,1)",
                        (pid, owner, visibility, float(p.get("created_at") or now)))
                    con.execute(
                        "INSERT INTO project_activity(id, project_id, user_id, action, detail, ts) "
                        "VALUES(?,?,?,?,?,?)",
                        (uuid.uuid4().hex, pid, None, "acl.migrated",
                         json.dumps({"owner": owner, "visibility": visibility}), now))
                con.commit()
        finally:
            con.close()
        _migrated_for = key
        return {"migrated": len(missing)}


# ── decisions ────────────────────────────────────────────────────────────────

def _acl(con: sqlite3.Connection, project_id: str) -> Optional[sqlite3.Row]:
    return con.execute("SELECT * FROM project_acl WHERE project_id = ?", (project_id,)).fetchone()


def role_for(project_id: str, user_id: str) -> Optional[str]:
    """The strongest role ``user_id`` has on the project, or ``None``."""
    from . import projects
    if project_id in projects.EXAMPLE_PROJECTS:
        return "viewer"
    migrate_legacy()
    con = _conn()
    try:
        acl = _acl(con, project_id)
        if acl is None:
            return None
        best = 0
        if user_id and acl["owner_user_id"] == user_id:
            return "owner"
        if user_id:
            row = con.execute("SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
                              (project_id, user_id)).fetchone()
            if row:
                best = max(best, _RANK.get(row["role"], 0))
            if acl["workspace_id"] and acl["visibility"] in ("workspace", "public"):
                row = con.execute(
                    "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                    (acl["workspace_id"], user_id)).fetchone()
                if row:
                    # A workspace grants at most editor: ownership is personal.
                    best = max(best, min(_RANK.get(row["role"], 0), _RANK["editor"]))
        if acl["visibility"] == "public":
            best = max(best, _RANK["viewer"])
    finally:
        con.close()
    return next((r for r, n in _RANK.items() if n == best), None) if best else None


def can(project_id: str, user_id: str, need: str = "viewer") -> bool:
    role = role_for(project_id, user_id)
    return bool(role) and _RANK[role] >= _RANK[need]


def require(project_id: str, user_id: str, need: str = "viewer") -> str:
    """The caller's role, or :class:`ProjectAccessDenied`."""
    role = role_for(project_id, user_id)
    if not role or _RANK[role] < _RANK[need]:
        raise ProjectAccessDenied(project_id)
    return role


def visible_project_ids(user_id: str, candidates: Iterable[str]) -> List[str]:
    return [pid for pid in candidates if can(pid, user_id, "viewer")]


def owner_of(project_id: str) -> Optional[str]:
    migrate_legacy()
    con = _conn()
    try:
        acl = _acl(con, project_id)
        return acl["owner_user_id"] if acl else None
    finally:
        con.close()


# ── changes ──────────────────────────────────────────────────────────────────

def record_owner(project_id: str, user_id: str, *, visibility: str = "private",
                 workspace_id: Optional[str] = None) -> None:
    """Called when a project is created."""
    if not user_id:
        raise ValueError("a project needs an owner")
    ensure_tables()
    con = _conn()
    try:
        con.execute(
            "INSERT OR REPLACE INTO project_acl(project_id, owner_user_id, workspace_id, visibility, "
            "created_at, migrated) VALUES(?,?,?,?,?,0)",
            (project_id, user_id, workspace_id,
             visibility if visibility in VISIBILITIES else "private", time.time()))
        con.commit()
    finally:
        con.close()
    log(project_id, user_id, "project.created", {"visibility": visibility})


def forget(project_id: str) -> None:
    con = _conn()
    try:
        for table in ("project_acl", "project_members"):
            con.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        con.commit()
    finally:
        con.close()


def set_visibility(project_id: str, visibility: str, *, by: str,
                   workspace_id: Optional[str] = None) -> None:
    if visibility not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {', '.join(VISIBILITIES)}")
    if visibility == "workspace" and workspace_id and not is_workspace_member(workspace_id, by):
        raise ProjectAccessDenied(project_id)
    con = _conn()
    try:
        if workspace_id is not None:
            con.execute("UPDATE project_acl SET visibility = ?, workspace_id = ? WHERE project_id = ?",
                        (visibility, workspace_id or None, project_id))
        else:
            con.execute("UPDATE project_acl SET visibility = ? WHERE project_id = ?",
                        (visibility, project_id))
        con.commit()
    finally:
        con.close()
    log(project_id, by, "project.visibility", {"visibility": visibility, "workspace_id": workspace_id})


def members(project_id: str) -> List[Dict[str, Any]]:
    con = _conn()
    try:
        return [dict(r) for r in con.execute(
            "SELECT user_id, role, added_by, added_at FROM project_members WHERE project_id = ? "
            "ORDER BY added_at", (project_id,))]
    finally:
        con.close()


def set_member(project_id: str, user_id: str, role: Optional[str], *, by: str) -> None:
    """Add, change or (``role=None``) remove a member. The owner is not a member row."""
    if role is not None and role not in ("viewer", "editor"):
        raise ValueError("a member is a viewer or an editor; ownership is not shared")
    if user_id == owner_of(project_id):
        raise ValueError("the owner already has full access")
    con = _conn()
    try:
        if role is None:
            con.execute("DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
                        (project_id, user_id))
        else:
            con.execute(
                "INSERT INTO project_members(project_id, user_id, role, added_by, added_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role",
                (project_id, user_id, role, by, time.time()))
        con.commit()
    finally:
        con.close()
    log(project_id, by, "project.member", {"user_id": user_id, "role": role})


def create_workspace(name: str, created_by: str) -> Dict[str, Any]:
    ensure_tables()
    wid = "ws_" + uuid.uuid4().hex[:12]
    con = _conn()
    try:
        con.execute("INSERT INTO workspaces(id, name, created_by, created_at) VALUES(?,?,?,?)",
                    (wid, name.strip()[:120] or "Workspace", created_by, time.time()))
        con.execute("INSERT INTO workspace_members(workspace_id, user_id, role) VALUES(?,?,?)",
                    (wid, created_by, "owner"))
        con.commit()
    finally:
        con.close()
    return {"id": wid, "name": name}


def is_workspace_member(workspace_id: str, user_id: str) -> bool:
    con = _conn()
    try:
        return con.execute("SELECT 1 FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                           (workspace_id, user_id)).fetchone() is not None
    finally:
        con.close()


def set_workspace_member(workspace_id: str, user_id: str, role: Optional[str], *, by: str) -> None:
    con = _conn()
    try:
        row = con.execute("SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                          (workspace_id, by)).fetchone()
        if not row or row["role"] != "owner":
            raise ProjectAccessDenied(workspace_id)
        if role is None:
            con.execute("DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
                        (workspace_id, user_id))
        else:
            if role not in ROLES:
                raise ValueError("unknown role")
            con.execute(
                "INSERT INTO workspace_members(workspace_id, user_id, role) VALUES(?,?,?) "
                "ON CONFLICT(workspace_id, user_id) DO UPDATE SET role = excluded.role",
                (workspace_id, user_id, role))
        con.commit()
    finally:
        con.close()


def describe(project_id: str, user_id: str) -> Dict[str, Any]:
    """Sharing facts the caller may see (never other users' credentials)."""
    con = _conn()
    try:
        acl = _acl(con, project_id)
    finally:
        con.close()
    role = role_for(project_id, user_id)
    return {
        "role": role,
        "is_owner": role == "owner",
        "visibility": acl["visibility"] if acl else "public",
        "workspace_id": acl["workspace_id"] if acl else None,
        "members": members(project_id) if role == "owner" else [],
    }


# ── audit ────────────────────────────────────────────────────────────────────

def log(project_id: str, user_id: Optional[str], action: str, detail: Any = None) -> None:
    """Append to the project's activity log. Never raises into a request."""
    try:
        ensure_tables()
        con = _conn()
        try:
            con.execute(
                "INSERT INTO project_activity(id, project_id, user_id, action, detail, ts) "
                "VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, project_id, user_id, action,
                 json.dumps(detail, default=str)[:4000] if detail is not None else None, time.time()))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def activity(project_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    con = _conn()
    try:
        rows = con.execute(
            "SELECT user_id, action, detail, ts FROM project_activity WHERE project_id = ? "
            "ORDER BY ts DESC LIMIT ?", (project_id, max(1, min(limit, 500)))).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        item = dict(r)
        try:
            item["detail"] = json.loads(item["detail"]) if item["detail"] else None
        except ValueError:
            pass
        out.append(item)
    return out


# ── HTTP guard ───────────────────────────────────────────────────────────────

import re as _re

_PROJECT_PATH = _re.compile(r"^/projects/([^/]+)(/.*)?$")
_INVENTORY_PATH = _re.compile(r"^/v1/inventory/([^/]+)(/.*)?$")
_NOT_A_PROJECT = {"examples", "from-example"}
#: Sub-paths that change who can do what: owner only.
_OWNER_ONLY = _re.compile(r"^/(capabilities|members|sharing)(/.*)?$")


def _need_for(method: str, rest: str) -> str:
    if _OWNER_ONLY.match(rest or ""):
        return "viewer" if method in ("GET", "HEAD") else "owner"
    if method in ("GET", "HEAD", "OPTIONS"):
        return "viewer"
    if method == "DELETE" and not rest:
        return "owner"
    if (rest or "").startswith("/persona/export"):
        return "editor"
    return "editor"


#: Routes that change persona state from a JSON body: editor or better.
_BODY_EDIT_PREFIXES = ("/persona/memory", "/v1/viewpack/")
_MAX_GUARDED_BODY = 2 * 1024 * 1024


def _deny_response():
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={
        "ok": False, "error": "Project not found", "code": "not_found"})


def _project_exists(project_id: str) -> bool:
    from . import projects
    return project_id in projects.EXAMPLE_PROJECTS or project_id in projects._load_projects_db()


def _ids_in_body(raw: bytes) -> List[str]:
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return []
    if not isinstance(body, dict):
        return []
    ids = []
    pid = body.get("project_id")
    if isinstance(pid, str) and pid.strip():
        ids.append(pid.strip())
    personality = body.get("personalityId")
    if isinstance(personality, str) and personality.startswith("persona:"):
        ids.append(personality.removeprefix("persona:"))
    return ids


class ProjectGuard:
    """ASGI middleware that enforces project access before any route runs.

    Covered:
      * ``/projects/{id}/…`` and ``/v1/inventory/{id}/…`` — every method,
        including routes added later;
      * ``?project_id=`` on any request;
      * ``project_id`` (or ``personalityId: "persona:<id>"``) in a JSON body —
        chat, agent chat, persona sessions and memory, view packs.

    A project the caller cannot see answers 404, like one that does not exist.
    Pure ASGI (not ``BaseHTTPMiddleware``) so a body it inspects is replayed
    intact to the route on every Starlette version.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)
        from starlette.requests import Request
        request = Request(scope)
        method, path = scope["method"], scope.get("path", "")
        checks: List[tuple] = []

        m = _PROJECT_PATH.match(path) or _INVENTORY_PATH.match(path)
        if m and m.group(1) not in _NOT_A_PROJECT:
            need = _need_for(method, m.group(2) or "")
            if path.startswith("/v1/inventory/") and method not in ("GET", "HEAD"):
                need = "editor"
            checks.append((m.group(1), need))

        qpid = request.query_params.get("project_id")
        if qpid:
            mutating = method not in ("GET", "HEAD") and path.startswith(_BODY_EDIT_PREFIXES)
            checks.append((qpid, "editor" if mutating else "viewer"))

        replay = receive
        ctype = (request.headers.get("content-type") or "").lower()
        if method in ("POST", "PUT", "PATCH", "DELETE") and "application/json" in ctype:
            chunks, size, more = [], 0, True
            while more:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                chunks.append(chunk)
                more = message.get("more_body", False)
            raw = b"".join(chunks)
            if size <= _MAX_GUARDED_BODY:
                need = "editor" if path.startswith(_BODY_EDIT_PREFIXES) else "viewer"
                checks.extend((pid, need) for pid in _ids_in_body(raw))
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": raw, "more_body": False}
                return await receive()

        if checks:
            user_id = request_user_id(request)
            for project_id, need in checks:
                if _project_exists(project_id) and not can(project_id, user_id, need):
                    return await _deny_response()(scope, replay, send)
        return await self.app(scope, replay, send)


def check_body_project(project_id: Optional[str], user_id: str, need: str = "viewer") -> None:
    """For routes that take ``project_id`` in a body (chat, agent chat).
    Raises :class:`ProjectAccessDenied`; an unknown id is left to the route."""
    if not project_id:
        return
    from . import projects
    pid = str(project_id)
    if pid in projects.EXAMPLE_PROJECTS or pid in projects._load_projects_db():
        require(pid, user_id, need)
