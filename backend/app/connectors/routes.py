"""Settings → Connectors: list, link and unlink accounts; Models: list a connector's models."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import CATALOG, catalog_entry, daypilot, gitpilot, huggingface, oauth, store
from .context import current_user_id

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


def _user() -> str:
    uid = current_user_id()
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in first")
    return uid


class LinkIn(BaseModel):
    token: str = Field(..., min_length=8, max_length=4096)


@router.get("")
def list_connectors(user_id: str = Depends(_user)) -> Dict[str, Any]:
    """Every available connector, with this user's linked account if any (never its secret)."""
    linked = {c["id"]: c for c in store.linked(user_id)}
    return {"ok": True, "connectors": [_public(c, linked.get(c["id"])) for c in CATALOG]}


def _public(entry: Dict[str, Any], row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A catalog entry plus what this user may see of their link: account, avatar, how it was
    linked, whether it expired. Never the secret."""
    meta = (row or {}).get("meta") or {}
    out = {
        **entry,
        "oauth": entry["id"] == huggingface.ID and oauth.enabled(),
        "manage_url": oauth.MANAGE_URL if entry["id"] == huggingface.ID else "",
        "connected": bool(row) and not row.get("expired"),
        "expired": bool(row and row.get("expired")),
        "account": (row or {}).get("account", ""),
        "avatar": meta.get("avatar", ""),
        "via": meta.get("via", "token") if row else "",
        "connected_at": (row or {}).get("connected_at"),
    }
    if entry["id"] == daypilot.ID:
        out["endpoint_value"] = meta.get("endpoint", "") if row else daypilot.default_endpoint()
        out["workspace"] = meta.get("workspace") if row else None
        out["scopes"] = meta.get("scopes", []) if row else []
    if entry["id"] == gitpilot.ID:
        out["endpoint_value"] = meta.get("endpoint", "") if row else gitpilot.default_endpoint()
        out["read_only"] = bool(meta.get("read_only")) if row else False
        out["version"] = meta.get("version", "") if row else ""
    return out


# ── DayPilot (workday) ───────────────────────────────────────────────────────
# The browser talks only to these routes; HomePilot's server talks to DayPilot.

class DayPilotPairIn(BaseModel):
    endpoint: str = Field("", max_length=512)


def _daypilot_http(exc: "daypilot.DayPilotError") -> HTTPException:
    status = {"not_linked": 409, "not_found": 404, "bad_request": 400, "forbidden": 403,
              "insufficient_scope": 403, "privacy_restricted": 403, "not_authorized": 401,
              "invalid_token": 401, "membership_revoked": 403, "offline": 503,
              "loop_detected": 508}.get(exc.code, 502)
    return HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)})


@router.post("/daypilot/pairing")
async def daypilot_pair_start(body: DayPilotPairIn, user_id: str = Depends(_user)) -> Dict[str, Any]:
    """Start connecting: returns the code the user confirms in DayPilot."""
    try:
        return {"ok": True, **(await daypilot.start_pairing(user_id, body.endpoint))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/daypilot/pairing")
async def daypilot_pair_poll(user_id: str = Depends(_user)) -> Dict[str, Any]:
    """Polled by the connect sheet until the user approves in DayPilot."""
    try:
        return {"ok": True, **(await daypilot.poll_pairing(user_id))}
    except daypilot.DayPilotError as exc:
        raise _daypilot_http(exc) from exc


@router.get("/daypilot/status")
async def daypilot_status(user_id: str = Depends(_user)) -> Dict[str, Any]:
    return {"ok": True, **(await daypilot.status(user_id))}


@router.get("/daypilot/context")
async def daypilot_context(project_id: str = Query("", max_length=64),
                           user_id: str = Depends(_user)) -> Dict[str, Any]:
    """The workday card. Inside a project, only the sections that project allows
    are fetched; each other section reports ``not_enabled``. Uses the *caller's*
    own DayPilot connection, never the project owner's."""
    from .. import project_access, project_capabilities as caps
    if project_id:
        if not project_access.can(project_id, user_id, "viewer"):
            raise HTTPException(status_code=404, detail="Project not found")
        if not caps.is_enabled(project_id, "connector", daypilot.ID):
            return {"ok": True, "state": "not_enabled", "sections": {}}
    want = {"plan": "plan", "tasks": "tasks", "projects": "tasks", "calendar": "calendar",
            "approvals": "proposals"}
    allowed = [s for s, f in want.items()
               if not project_id or caps.feature_enabled(project_id, f"daypilot.{f}")]
    if not daypilot.is_linked(user_id):
        return {"ok": True, "state": "not_connected", "sections": {}}
    try:
        data = await daypilot.context(user_id, allowed)
    except daypilot.DayPilotError as exc:
        state = {"offline": "offline", "invalid_token": "not_authorized", "not_authorized": "not_authorized",
                 "membership_revoked": "not_authorized"}.get(exc.code, "needs_attention")
        return {"ok": True, "state": state, "problem": str(exc), "sections": {}}
    sections = dict(data.get("sections") or {})
    for name in want:
        if name not in allowed:
            sections[name] = {"status": "not_enabled"}
    views = {}
    try:
        endpoint = daypilot._link(user_id)[0]
        views = {k: endpoint + v for k, v in ((await daypilot.manifest(user_id)).get("views") or {}).items()}
    except Exception:
        pass
    return {"ok": True, "state": data.get("state", "connected"), "generated_at": data.get("generatedAt"),
            "age_s": data.get("age_s"), "sections": sections, "views": views}


@router.get("/daypilot/proposals/{proposal_id}")
async def daypilot_proposal(proposal_id: str, user_id: str = Depends(_user)) -> Dict[str, Any]:
    try:
        return {"ok": True, **(await daypilot.proposal_status(user_id, proposal_id))}
    except daypilot.DayPilotError as exc:
        raise _daypilot_http(exc) from exc


# ── GitPilot (coding) ────────────────────────────────────────────────────────
# Declared before the generic ``/{connector_id}`` routes so they match first.

class GitPilotLinkIn(BaseModel):
    endpoint: str = Field("", max_length=512)
    token: str = Field("", max_length=4096)


class GitPilotSettingsIn(BaseModel):
    read_only: bool


class GitPilotPlanIn(BaseModel):
    repo: str = Field(..., max_length=220)
    request: str = Field(..., min_length=1, max_length=8000)
    branch: Optional[str] = Field(None, max_length=200)


def _gitpilot_http(exc: "gitpilot.GitPilotError") -> HTTPException:
    status = {"not_linked": 409, "not_found": 404, "bad_request": 400, "read_only": 403,
              "privacy_restricted": 403, "auth_failed": 401, "forbidden": 403,
              "rate_limited": 429, "timeout": 504, "unreachable": 502}.get(exc.code, 502)
    return HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)})


@router.post("/gitpilot")
async def gitpilot_link(body: GitPilotLinkIn, user_id: str = Depends(_user)) -> Dict[str, Any]:
    try:
        info = await gitpilot.verify(body.endpoint, body.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.save(user_id, gitpilot.ID, info["secret"], account=info["account"],
               meta={"endpoint": info["endpoint"], "avatar": info["avatar"],
                     "version": info.get("version") or "", "read_only": False})
    return {"ok": True, "id": gitpilot.ID, "connected": True, "account": info["account"]}


@router.get("/gitpilot/status")
async def gitpilot_status(user_id: str = Depends(_user)) -> Dict[str, Any]:
    return {"ok": True, **(await gitpilot.status(user_id))}


@router.put("/gitpilot/settings")
def gitpilot_settings(body: GitPilotSettingsIn, user_id: str = Depends(_user)) -> Dict[str, Any]:
    row = next((r for r in store.linked(user_id) if r["id"] == gitpilot.ID), None)
    secret = store.secret(user_id, gitpilot.ID)
    if not row or not secret:
        raise HTTPException(status_code=409, detail="GitPilot is not connected")
    store.save(user_id, gitpilot.ID, secret, account=row["account"],
               meta={**row["meta"], "read_only": bool(body.read_only)})
    return {"ok": True, "read_only": bool(body.read_only)}


@router.get("/gitpilot/repos")
async def gitpilot_repos(q: str = Query("", max_length=100), user_id: str = Depends(_user)) -> Dict[str, Any]:
    try:
        return {"ok": True, "repos": await gitpilot.repos(user_id, q)}
    except gitpilot.GitPilotError as exc:
        raise _gitpilot_http(exc) from exc


@router.post("/gitpilot/plan")
async def gitpilot_plan(body: GitPilotPlanIn, user_id: str = Depends(_user)) -> Dict[str, Any]:
    """Read-only: returns a plan and its id. Nothing is written."""
    try:
        return {"ok": True, **(await gitpilot.plan(user_id, body.repo, body.request, body.branch))}
    except gitpilot.GitPilotError as exc:
        raise _gitpilot_http(exc) from exc


@router.post("/gitpilot/plans/{plan_id}/apply")
def gitpilot_ask_apply(plan_id: str, user_id: str = Depends(_user)) -> Dict[str, Any]:
    """Create the approval request for a plan. It still has to be approved."""
    try:
        return {"ok": True, "approval": gitpilot.ask_to_apply(user_id, plan_id)}
    except gitpilot.GitPilotError as exc:
        raise _gitpilot_http(exc) from exc


@router.get("/gitpilot/approvals")
def gitpilot_approvals(user_id: str = Depends(_user)) -> Dict[str, Any]:
    return {"ok": True, "pending": gitpilot.pending_approvals(user_id)}


@router.post("/gitpilot/approvals/{code}/{decision}")
async def gitpilot_decide(code: str, decision: str, user_id: str = Depends(_user)) -> Dict[str, Any]:
    """The signed-in user's own decision on one of their pending changes."""
    if decision not in ("approve", "deny"):
        raise HTTPException(status_code=404, detail="Unknown decision")
    try:
        return {"ok": True, **(await gitpilot.resolve(user_id, code, decision == "approve"))}
    except gitpilot.GitPilotError as exc:
        raise _gitpilot_http(exc) from exc


@router.post("/{connector_id}")
async def link(connector_id: str, body: LinkIn, user_id: str = Depends(_user)) -> Dict[str, Any]:
    if connector_id != huggingface.ID or not catalog_entry(connector_id):
        raise HTTPException(status_code=404, detail="Unknown connector")
    secret = body.token.strip()
    try:
        info = await huggingface.whoami(secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    account = str(info.get("name") or info.get("fullname") or "")
    store.save(user_id, connector_id, secret, account=account, meta={"type": info.get("type") or "user"})
    return {"ok": True, "id": connector_id, "connected": True, "account": account}


@router.post("/huggingface/oauth/start")
def hf_oauth_start(request: Request, user_id: str = Depends(_user)) -> Dict[str, Any]:
    """A one-use "Sign in with Hugging Face" URL for this user, to open in a new window."""
    if not oauth.enabled():
        raise HTTPException(status_code=404, detail="Sign in with Hugging Face is not set up on this server.")
    origin = (request.headers.get("origin") or "").strip()
    return {"ok": True, "url": oauth.start(user_id, str(request.base_url), origin=origin)}


@router.get("/huggingface/oauth/callback", response_class=HTMLResponse)
async def hf_oauth_callback(code: str = "", state: str = "", error: str = "",
                            error_description: str = "") -> HTMLResponse:
    """Where Hugging Face sends the sign-in window back. Links the account, then closes."""
    pending = oauth.take(state)
    origin = (pending or {}).get("origin", "")
    if error:
        reason = "You cancelled the sign-in." if error == "access_denied" else (error_description or error)
        return HTMLResponse(oauth.finish_page(False, error=reason, origin=origin))
    if not pending:
        return HTMLResponse(oauth.finish_page(False, error="This sign-in link expired. Please try again."), status_code=400)
    try:
        got = await oauth.exchange(code, pending)
    except ValueError as exc:
        return HTMLResponse(oauth.finish_page(False, error=str(exc), origin=origin), status_code=400)
    except Exception as exc:  # noqa: BLE001 — Hugging Face unreachable
        return HTMLResponse(oauth.finish_page(False, error=f"Could not reach Hugging Face ({type(exc).__name__}).",
                                              origin=origin), status_code=502)
    store.save(pending["user_id"], huggingface.ID, got["token"], account=got["account"], meta=got["meta"])
    return HTMLResponse(oauth.finish_page(True, account=got["account"], origin=origin))


@router.delete("/{connector_id}")
async def unlink(connector_id: str, user_id: str = Depends(_user)) -> Dict[str, Any]:
    if connector_id == daypilot.ID:
        # Revoke the grant on DayPilot too, not just forget it here.
        out = await daypilot.disconnect(user_id)
        return {"ok": True, "id": connector_id, **out}
    store.remove(user_id, connector_id)
    return {"ok": True, "id": connector_id, "connected": False}


@router.get("/huggingface/models")
async def hf_models(
    model_type: str = Query("chat", alias="type", description="chat | multimodal | image | video"),
    sort: str = Query("popular", description="popular | likes | trending | newest | rising"),
    user_id: Optional[str] = Depends(_user),
) -> Dict[str, Any]:
    """Models Inference Providers serve live for a type, ranked (FitLab's inference lane):
    ``popular`` weighs likes, downloads, trend and freshness; ``likes`` is ranked by the people."""
    try:
        listed, source = await huggingface.ranked(model_type, sort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — the Hub unreachable
        raise HTTPException(status_code=502, detail=f"Could not list Hugging Face models ({type(exc).__name__}).") from exc
    return {"ok": True, "type": model_type, "sort": sort, "orders": list(huggingface.ORDERS),
            "source": source, "connected": bool(huggingface.token(user_id)), "models": listed,
            "note": "Ranked by popularity on Hugging Face. Popular is not always best for your task."}
