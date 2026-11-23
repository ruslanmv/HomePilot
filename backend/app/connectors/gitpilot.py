"""GitPilot connector — coding from inside HomePilot.

GitPilot (https://github.com/ruslanmv/gitpilot) is a multi-agent coding
assistant: it reads a repository, drafts a step-by-step plan, writes the
changes on a branch and opens a pull request. This connector makes that a
native HomePilot capability without moving any of it into HomePilot:

  * the user links GitPilot once in Settings → Connectors (its address and
    their GitHub token; the token is checked by GitPilot and kept server-side);
  * agent chats — the Coder persona or any other — get four ``code.*`` tools;
  * HomePilot keeps the conversation, the plans and the approval record.

Additive: nothing changes for a user who has not linked it.

How it follows the practices coding agents have converged on
------------------------------------------------------------
**Plan, then act.** ``code.plan`` is read-only and always comes first. Nothing
is written from a prompt alone.

**A person approves every change.** ``code.apply`` and ``code.open_pr`` do not
run. They record a pending approval and hand the user a short code. Only the
user can resolve it — by replying ``approve CODE`` / ``deny CODE`` or with the
buttons in Settings → Connectors — and that resolution is handled by
HomePilot's own code, never by the model. A prompt-injected or confused model
can ask for a change; it cannot make one.

**What is approved is what runs.** The approval stores the exact plan GitPilot
returned. Approving executes that stored plan, not a new one the model
describes later.

**Least privilege, per user.** Each user's own GitHub token is used for that
user's requests only. A read-only switch turns writes off entirely.
Changes land on a branch and reach the default branch only through a pull
request the user merges on GitHub.

**One contract, owned by the backend.** HomePilot calls GitPilot's REST API
(``/api/repos``, ``/api/chat/plan``, ``/api/chat/execute``, pull requests).
GitPilot also publishes an MCP-style tool surface (``/mcp-server/mcp``); its
``gitpilot.execute`` tool is documented there as not implemented and points
callers at the REST route, so REST is what this connector uses.

**No loops, no leaks.** Requests carry ``X-Gitpilot-Origin: homepilot`` (GitPilot
refuses its own ``self`` origin). The address is checked by the outbound-URL
guard. Under the ``private_local`` routing mode a GitPilot that is not on the
user's own network is refused.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import store
from .context import current_user_id

ID = "gitpilot"
#: Stored in place of a token when GitPilot signs in to GitHub by itself.
SERVER_IDENTITY = "gitpilot-server-identity"
ORIGIN_HEADER = "X-Gitpilot-Origin"
APPROVAL_TTL_S = 30 * 60
PLAN_TTL_S = 24 * 3600
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I
_CODE_RE = re.compile(r"^\s*(approve|deny|cancel|reject)\s+#?([A-Za-z0-9]{6})\s*[.!]?\s*$", re.I)
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]{1,200}$")

NOT_LINKED = "Connect GitPilot in Settings → Connectors to work on code."

#: Test seam.
default_transport: httpx.BaseTransport | None = None


class GitPilotError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class NotLinked(GitPilotError):
    def __init__(self) -> None:
        super().__init__("not_linked", NOT_LINKED)


# ── address and credentials ──────────────────────────────────────────────────

def default_endpoint() -> str:
    return (os.getenv("GITPILOT_URL") or "").strip().rstrip("/")


def normalize_endpoint(url: str) -> str:
    """A clean base URL, or ``ValueError`` saying what is wrong with it."""
    url = (url or "").strip().rstrip("/") or default_endpoint()
    if not url:
        raise ValueError("Enter the address of your GitPilot, for example http://localhost:8000.")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    from ..compute.netguard import is_safe_outbound_url
    if not is_safe_outbound_url(url):
        raise ValueError("That address is not allowed from this HomePilot.")
    return url


def _link(user_id: Optional[str]) -> Tuple[str, str, Dict[str, Any]]:
    """``(endpoint, github_token, meta)`` for this user, or :class:`NotLinked`."""
    uid = user_id or current_user_id()
    secret = store.secret(uid, ID)
    if not secret:
        raise NotLinked()
    row = next((r for r in store.linked(uid) if r["id"] == ID), None)
    meta = (row or {}).get("meta") or {}
    endpoint = str(meta.get("endpoint") or default_endpoint())
    if not endpoint:
        raise NotLinked()
    _private_check(uid, endpoint)
    return endpoint, ("" if secret == SERVER_IDENTITY else secret), meta


def is_linked(user_id: Optional[str] = None) -> bool:
    try:
        return bool(store.secret(user_id or current_user_id(), ID))
    except Exception:
        return False


def read_only(user_id: Optional[str] = None) -> bool:
    uid = user_id or current_user_id()
    row = next((r for r in store.linked(uid) if r["id"] == ID), None)
    return bool(((row or {}).get("meta") or {}).get("read_only"))


def _private_check(user_id: str, endpoint: str) -> None:
    """``private_local``: code may only go to a GitPilot on the user's own network."""
    try:
        from ..compute import routing
        if routing.effective_prefs(user_id).strategy == "private_local" \
                and not routing._is_own_network(endpoint):
            raise GitPilotError(
                "privacy_restricted",
                "Private mode is on and this GitPilot is not on your own network, "
                "so nothing was sent to it.")
    except GitPilotError:
        raise
    except Exception:
        pass


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _redact(text: str, token: str) -> str:
    return text.replace(token, "(redacted)") if token else text


async def _request(method: str, path: str, *, endpoint: str, token: str = "",
                   json_body: Any = None, params: Optional[Dict[str, Any]] = None,
                   timeout: float = 60.0) -> Any:
    headers = {ORIGIN_HEADER: "homepilot", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(base_url=endpoint, timeout=timeout,
                                     transport=default_transport) as client:
            r = await client.request(method, path, json=json_body, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise GitPilotError("timeout", "GitPilot took too long to answer.") from exc
    except httpx.HTTPError as exc:
        raise GitPilotError("unreachable", f"GitPilot could not be reached at {endpoint}.") from exc
    try:
        data = r.json()
    except ValueError:
        data = None
    if r.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else None
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("error") or json.dumps(detail)
        message = _redact(str(detail or r.text or f"HTTP {r.status_code}")[:400], token)
        code = {401: "auth_failed", 403: "forbidden", 404: "not_found",
                429: "rate_limited"}.get(r.status_code, "gitpilot_error")
        raise GitPilotError(code, message)
    return data


async def verify(endpoint: str, token: str) -> Dict[str, Any]:
    """Check an address and a token before linking. Raises ``ValueError`` with
    words for the person linking it."""
    endpoint = normalize_endpoint(endpoint)
    try:
        health = await _request("GET", "/api/health", endpoint=endpoint, timeout=10.0)
    except GitPilotError as exc:
        raise ValueError(f"No GitPilot answered at {endpoint}. Is it running?") from exc
    version = (health or {}).get("version") if isinstance(health, dict) else None
    token = (token or "").strip()
    if not token:
        try:
            status = await _request("GET", "/api/auth/status", endpoint=endpoint, timeout=10.0)
        except GitPilotError:
            status = {}
        if not (isinstance(status, dict) and status.get("pat_configured")):
            raise ValueError("Paste a GitHub token: this GitPilot has no GitHub sign-in of its own.")
        return {"endpoint": endpoint, "account": "GitPilot's own GitHub sign-in",
                "avatar": "", "version": version, "secret": SERVER_IDENTITY}
    try:
        info = await _request("POST", "/api/auth/validate", endpoint=endpoint,
                              json_body={"access_token": token}, timeout=20.0)
    except GitPilotError as exc:
        raise ValueError(f"GitPilot could not check the token: {exc}") from exc
    if not (isinstance(info, dict) and info.get("authenticated")):
        raise ValueError("GitHub did not accept that token.")
    user = info.get("user") or {}
    return {"endpoint": endpoint, "account": str(user.get("login") or ""),
            "avatar": str(user.get("avatar_url") or ""), "version": version, "secret": token}


# ── storage: plans and approvals ─────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    from ..storage import _get_db_path
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS coding_plans("
        "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, conversation_id TEXT, repo TEXT NOT NULL, "
        "branch TEXT, goal TEXT, plan TEXT NOT NULL, created_at REAL NOT NULL)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS coding_approvals("
        "code TEXT PRIMARY KEY, user_id TEXT NOT NULL, conversation_id TEXT, kind TEXT NOT NULL, "
        "payload TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL, "
        "created_at REAL NOT NULL, resolved_at REAL, result TEXT)")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(coding_approvals)")}
    if "project_id" not in cols:
        con.execute("ALTER TABLE coding_approvals ADD COLUMN project_id TEXT")
    return con


def _split_repo(repo: str) -> Tuple[str, str]:
    repo = (repo or "").strip().removeprefix("https://github.com/").strip("/")
    if not _REPO_RE.match(repo):
        raise GitPilotError("bad_request", "Name the repository as owner/name, for example octocat/hello-world.")
    owner, name = repo.split("/", 1)
    return owner, name


def _branch(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    if not _BRANCH_RE.match(value) or ".." in value:
        raise GitPilotError("bad_request", "That branch name is not valid.")
    return value


def get_plan(user_id: str, plan_id: str) -> Optional[Dict[str, Any]]:
    con = _db()
    try:
        row = con.execute("SELECT * FROM coding_plans WHERE id = ? AND user_id = ?",
                          (plan_id, user_id)).fetchone()
    finally:
        con.close()
    if not row or time.time() - row["created_at"] > PLAN_TTL_S:
        return None
    return {**dict(row), "plan": json.loads(row["plan"])}


def _new_code(con: sqlite3.Connection) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not con.execute("SELECT 1 FROM coding_approvals WHERE code = ?", (code,)).fetchone():
            return code
    raise GitPilotError("gitpilot_error", "Could not create an approval code.")


def request_approval(user_id: str, kind: str, payload: Dict[str, Any], summary: str,
                     conversation_id: str = "", project_id: Optional[str] = None) -> Dict[str, Any]:
    """Record a change that waits for the user. Nothing is executed here."""
    if read_only(user_id):
        raise GitPilotError("read_only", "GitPilot is set to read-only in Settings → Connectors, "
                                         "so it can plan but not change anything.")
    con = _db()
    try:
        code = _new_code(con)
        con.execute(
            "INSERT INTO coding_approvals(code, user_id, conversation_id, kind, payload, summary, "
            "status, created_at, project_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (code, user_id, conversation_id, kind, json.dumps(payload), summary, "pending", time.time(),
             project_id or None))
        con.commit()
    finally:
        con.close()
    return {"code": code, "kind": kind, "summary": summary, "expires_in_s": APPROVAL_TTL_S}


def pending_approvals(user_id: str) -> List[Dict[str, Any]]:
    con = _db()
    try:
        rows = con.execute(
            "SELECT code, kind, summary, conversation_id, created_at FROM coding_approvals "
            "WHERE user_id = ? AND status = 'pending' AND created_at >= ? ORDER BY created_at DESC",
            (user_id, time.time() - APPROVAL_TTL_S)).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def _claim(user_id: str, code: str, new_status: str) -> Optional[Dict[str, Any]]:
    """Atomically move one of *this user's* pending approvals to ``new_status``.

    The single UPDATE is what makes an approval single-use: two clicks, or a
    click and a chat reply, cannot both run the change."""
    code = (code or "").strip().upper()
    con = _db()
    try:
        cur = con.execute(
            "UPDATE coding_approvals SET status = ?, resolved_at = ? "
            "WHERE code = ? AND user_id = ? AND status = 'pending' AND created_at >= ?",
            (new_status, time.time(), code, user_id, time.time() - APPROVAL_TTL_S))
        con.commit()
        if cur.rowcount != 1:
            return None
        row = con.execute("SELECT * FROM coding_approvals WHERE code = ?", (code,)).fetchone()
    finally:
        con.close()
    return {**dict(row), "payload": json.loads(row["payload"])}


def _finish(code: str, status: str, result: Dict[str, Any]) -> None:
    con = _db()
    try:
        con.execute("UPDATE coding_approvals SET status = ?, result = ? WHERE code = ?",
                    (status, json.dumps(result)[:20000], code))
        con.commit()
    finally:
        con.close()


# ── operations ───────────────────────────────────────────────────────────────

async def status(user_id: Optional[str] = None) -> Dict[str, Any]:
    uid = user_id or current_user_id()
    if not is_linked(uid):
        return {"connected": False, "reachable": False, "pending": []}
    try:
        endpoint, _token, meta = _link(uid)
        health = await _request("GET", "/api/health", endpoint=endpoint, timeout=6.0)
        reachable, version = True, (health or {}).get("version") if isinstance(health, dict) else None
        problem = None
    except GitPilotError as exc:
        endpoint, meta = "", {}
        reachable, version, problem = False, None, str(exc)
    return {"connected": True, "reachable": reachable, "version": version, "problem": problem,
            "endpoint": endpoint, "read_only": bool(meta.get("read_only")),
            "pending": pending_approvals(uid)}


async def repos(user_id: Optional[str] = None, query: str = "") -> List[Dict[str, Any]]:
    endpoint, token, _ = _link(user_id)
    params: Dict[str, Any] = {"per_page": 30}
    if query.strip():
        params["query"] = query.strip()[:100]
    data = await _request("GET", "/api/repos", endpoint=endpoint, token=token, params=params)
    rows = (data or {}).get("repositories") or []
    return [{"repo": r.get("full_name") or f"{r.get('owner')}/{r.get('name')}",
             "private": bool(r.get("private")), "default_branch": r.get("default_branch") or "main"}
            for r in rows if isinstance(r, dict)]


async def plan(user_id: Optional[str], repo: str, goal: str, branch: Optional[str] = None,
               conversation_id: str = "") -> Dict[str, Any]:
    """Ask GitPilot for a plan. Read-only: no file is written, no branch made."""
    uid = user_id or current_user_id()
    endpoint, token, _ = _link(uid)
    owner, name = _split_repo(repo)
    goal = (goal or "").strip()
    if not goal:
        raise GitPilotError("bad_request", "Say what should change.")
    body: Dict[str, Any] = {"repo_owner": owner, "repo_name": name, "goal": goal[:8000]}
    if _branch(branch):
        body["branch_name"] = _branch(branch)
    result = await _request("POST", "/api/chat/plan", endpoint=endpoint, token=token,
                            json_body=body, timeout=300.0)
    if not isinstance(result, dict) or not isinstance(result.get("steps"), list):
        raise GitPilotError("gitpilot_error", "GitPilot did not return a plan.")
    plan_id = "plan_" + uuid.uuid4().hex[:10]
    con = _db()
    try:
        con.execute(
            "INSERT INTO coding_plans(id, user_id, conversation_id, repo, branch, goal, plan, created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (plan_id, uid, conversation_id, f"{owner}/{name}", _branch(branch), goal,
             json.dumps(result), time.time()))
        con.commit()
    finally:
        con.close()
    return {"plan_id": plan_id, "repo": f"{owner}/{name}", "branch": _branch(branch), "plan": result}


def render_plan(planned: Dict[str, Any]) -> str:
    p = planned["plan"]
    lines = [f"Plan {planned['plan_id']} for {planned['repo']}"
             + (f" (branch {planned['branch']})" if planned.get("branch") else ""),
             str(p.get("summary") or p.get("goal") or "").strip()]
    for step in p.get("steps") or []:
        files = ", ".join(f"{f.get('action', 'MODIFY')} {f.get('path')}"
                          for f in (step.get("files") or []) if isinstance(f, dict))
        lines.append(f"{step.get('step_number', '?')}. {step.get('title', '')}"
                     + (f" — {files}" if files else ""))
        if step.get("risks"):
            lines.append(f"   Risk: {step['risks']}")
    lines.append("Nothing has been changed. To make these changes the user must approve them.")
    return "\n".join(line for line in lines if line)


def _files_changed(p: Dict[str, Any]) -> int:
    return len({f.get("path") for s in (p.get("steps") or []) for f in (s.get("files") or [])
                if isinstance(f, dict) and f.get("action") in ("CREATE", "MODIFY", "DELETE")})


def ask_to_apply(user_id: Optional[str], plan_id: str, conversation_id: str = "",
                 project_id: Optional[str] = None) -> Dict[str, Any]:
    uid = user_id or current_user_id()
    stored = get_plan(uid, (plan_id or "").strip())
    if not stored:
        raise GitPilotError("not_found", "That plan does not exist or has expired. Make a new plan first.")
    p = stored["plan"]
    summary = (f"Apply plan {stored['id']} to {stored['repo']}: {len(p.get('steps') or [])} steps, "
               f"{_files_changed(p)} files, on a new branch"
               + (f" from {stored['branch']}" if stored.get("branch") else "") + ".")
    return request_approval(uid, "apply", {"plan_id": stored["id"]}, summary, conversation_id, project_id)


def ask_to_open_pr(user_id: Optional[str], repo: str, head: str, title: str, body: str = "",
                   base: str = "", conversation_id: str = "",
                   project_id: Optional[str] = None) -> Dict[str, Any]:
    uid = user_id or current_user_id()
    owner, name = _split_repo(repo)
    head_branch = _branch(head)
    title = (title or "").strip()[:200]
    if not head_branch or not title:
        raise GitPilotError("bad_request", "A pull request needs the branch with the changes and a title.")
    payload = {"owner": owner, "repo": name, "head": head_branch, "title": title,
               "body": (body or "")[:20000], "base": _branch(base) or ""}
    summary = (f"Open a pull request on {owner}/{name} from {head_branch}"
               + (f" into {payload['base']}" if payload["base"] else "") + f': "{title}".')
    return request_approval(uid, "open_pr", payload, summary, conversation_id, project_id)


def approval_prompt(approval: Dict[str, Any]) -> str:
    return (f"{approval['summary']}\n\n"
            f"This needs your approval. Reply **approve {approval['code']}** to go ahead, "
            f"or **deny {approval['code']}**. You can also approve it in Settings → Connectors. "
            f"The request expires in {APPROVAL_TTL_S // 60} minutes.")


async def resolve(user_id: Optional[str], code: str, approve: bool,
                  project_id: Optional[str] = None) -> Dict[str, Any]:
    """The user's decision on a pending change. Runs it when approved."""
    uid = user_id or current_user_id()
    claimed = _claim(uid, code, "running" if approve else "denied")
    if claimed is None:
        raise GitPilotError("not_found", "There is no pending request with that code. "
                                         "It may have expired or already been decided.")
    origin_project = claimed.get("project_id")
    if origin_project:
        from .. import project_access
        project_access.log(origin_project, uid, f"approval.{'approved' if approve else 'denied'}",
                           {"code": claimed["code"], "kind": claimed["kind"], "summary": claimed["summary"]})
    if not approve:
        return {"code": claimed["code"], "status": "denied", "text": "Cancelled. Nothing was changed."}
    try:
        # Disabled means disabled: if the project the request came from has
        # since turned GitPilot off, or the user lost access to it, an earlier
        # approval code no longer runs.
        if origin_project:
            from .. import project_access, project_capabilities
            if not project_access.can(origin_project, uid, "viewer") or \
                    not project_capabilities.is_enabled(origin_project, "connector", ID):
                raise GitPilotError("connector_disabled",
                                    "GitPilot is turned off for the project this request came from, "
                                    "so nothing was changed.")
        if read_only(uid):
            raise GitPilotError("read_only", "GitPilot is set to read-only, so nothing was changed.")
        endpoint, token, _ = _link(uid)
        payload = claimed["payload"]
        if claimed["kind"] == "apply":
            stored = get_plan(uid, payload["plan_id"])
            if not stored:
                raise GitPilotError("not_found", "The plan has expired. Make a new plan.")
            owner, name = _split_repo(stored["repo"])
            body: Dict[str, Any] = {"repo_owner": owner, "repo_name": name, "plan": stored["plan"]}
            if stored.get("branch"):
                body["branch_name"] = stored["branch"]
            result = await _request("POST", "/api/chat/execute", endpoint=endpoint, token=token,
                                    json_body=body, timeout=900.0)
            result = result if isinstance(result, dict) else {}
            branch = result.get("branch")
            text = (str(result.get("message") or "The plan was applied.")
                    + (f"\nBranch: {branch}" if branch else "")
                    + (f"\n{result['branch_url']}" if result.get("branch_url") else "")
                    + "\nNothing was merged. Ask me to open a pull request when you are ready.")
            out = {"code": claimed["code"], "status": "done", "kind": "apply", "text": text,
                   "repo": stored["repo"], "branch": branch, "branch_url": result.get("branch_url")}
        elif claimed["kind"] == "open_pr":
            body = {"title": payload["title"], "head": payload["head"], "body": payload.get("body") or ""}
            if payload.get("base"):
                body["base"] = payload["base"]
            result = await _request(
                "POST", f"/api/repos/{payload['owner']}/{payload['repo']}/pulls",
                endpoint=endpoint, token=token, json_body=body, timeout=60.0)
            result = result if isinstance(result, dict) else {}
            url = result.get("html_url") or result.get("url")
            text = "The pull request is open." + (f"\n{url}" if url else "") \
                + "\nIt is not merged: review and merge it on GitHub."
            out = {"code": claimed["code"], "status": "done", "kind": "open_pr", "text": text, "url": url}
        else:
            raise GitPilotError("gitpilot_error", "Unknown request kind.")
    except GitPilotError as exc:
        _finish(claimed["code"], "failed", {"error": exc.code, "message": str(exc)})
        raise
    _finish(claimed["code"], "done", out)
    return out


def parse_decision(text: str) -> Optional[Tuple[bool, str]]:
    """``"approve K7QW2M"`` → ``(True, "K7QW2M")``. Anything else → ``None``."""
    m = _CODE_RE.match(text or "")
    if not m:
        return None
    return m.group(1).lower() == "approve", m.group(2).upper()


# ── agent tools ──────────────────────────────────────────────────────────────

TOOLS: Dict[str, str] = {
    "code.repos": "code.repos(query): lists the user's GitHub repositories through GitPilot. "
                  "query is optional text to search for.",
    "code.plan": "code.plan(repo, request, branch): asks GitPilot to plan a code change. Read-only — "
                 "nothing is written.\n  repo: owner/name. request: what should change. "
                 "branch: optional starting branch. Always plan before applying.",
    "code.apply": "code.apply(plan_id): asks the user to approve applying a plan from code.plan. "
                  "The change runs only after the user approves; you cannot approve it yourself.",
    "code.open_pr": "code.open_pr(repo, head, title, body, base): asks the user to approve opening a "
                    "pull request from branch head. Runs only after the user approves.",
}
TOOL_LABELS = {"code.repos": "Repositories", "code.plan": "Code Plan",
               "code.apply": "Approval Requested", "code.open_pr": "Approval Requested"}


def tool_catalog(user_id: Optional[str] = None) -> List[str]:
    """Catalog lines for the agent prompt — empty unless this user linked GitPilot."""
    if not is_linked(user_id):
        return []
    names = ("code.repos", "code.plan") if read_only(user_id) else tuple(TOOLS)
    return [TOOLS[n] for n in names]


def has_tool(name: str, user_id: Optional[str] = None) -> bool:
    return name in TOOLS and is_linked(user_id)


async def run_tool(name: str, args: Dict[str, Any], *, user_id: Optional[str],
                   conversation_id: str = "", project_id: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Run one ``code.*`` tool. Returns ``(text, meta)``; ``meta["terminal"]``
    means the text must be shown to the user as is (an approval request)."""
    uid = user_id or current_user_id()
    try:
        if name == "code.repos":
            rows = await repos(uid, str(args.get("query") or ""))
            if not rows:
                return "No repositories were found.", {"count": 0}
            listing = "\n".join(f"- {r['repo']}" + (" (private)" if r["private"] else "")
                                + f", default branch {r['default_branch']}" for r in rows[:30])
            return listing, {"count": len(rows)}
        if name == "code.plan":
            planned = await plan(uid, str(args.get("repo") or ""),
                                 str(args.get("request") or args.get("goal") or args.get("prompt") or ""),
                                 args.get("branch"), conversation_id)
            return render_plan(planned), {"plan_id": planned["plan_id"], "repo": planned["repo"]}
        if name == "code.apply":
            approval = ask_to_apply(uid, str(args.get("plan_id") or ""), conversation_id, project_id)
            return approval_prompt(approval), {"terminal": True, "approval": approval["code"]}
        if name == "code.open_pr":
            approval = ask_to_open_pr(uid, str(args.get("repo") or ""), str(args.get("head") or ""),
                                      str(args.get("title") or ""), str(args.get("body") or ""),
                                      str(args.get("base") or ""), conversation_id, project_id)
            return approval_prompt(approval), {"terminal": True, "approval": approval["code"]}
    except GitPilotError as exc:
        return f"GitPilot: {exc}", {"error_code": exc.code, "terminal": exc.code in ("read_only", "not_linked")}
    return f"Unknown tool {name}.", {"error_code": "unknown_tool"}
