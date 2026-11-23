"""Project sharing, capabilities, activity and workspaces.

    GET  /projects/{id}/sharing           my role, visibility, members (owner sees members)
    PUT  /projects/{id}/sharing           visibility / workspace            (owner)
    PUT  /projects/{id}/members/{user}    add or change a member            (owner)
    DELETE /projects/{id}/members/{user}  remove a member                   (owner)
    GET  /projects/{id}/capabilities      tools and connectors, on or off
    PUT  /projects/{id}/capabilities      turn them on or off               (owner)
    GET  /projects/{id}/activity          the audit log                     (editor)
    POST /v1/workspaces                   create a workspace
    PUT  /v1/workspaces/{id}/members/{u}  add or change a member (workspace owner)

``ProjectGuard`` has already refused callers without the needed role before
these handlers run; each handler checks again, so the rule does not depend on
middleware order.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import project_access as access
from . import project_capabilities as caps

router = APIRouter(tags=["projects"])


def _who(request: Request) -> str:
    return access.request_user_id(request)


def _need(project_id: str, user_id: str, role: str) -> None:
    try:
        access.require(project_id, user_id, role)
    except access.ProjectAccessDenied:
        raise HTTPException(status_code=404, detail="Project not found")


class SharingIn(BaseModel):
    visibility: str = Field(..., pattern="^(private|workspace|public)$")
    workspace_id: Optional[str] = Field(None, max_length=64)


class MemberIn(BaseModel):
    role: str = Field(..., pattern="^(viewer|editor)$")


class CapabilitiesIn(BaseModel):
    tools: Dict[str, bool] = Field(default_factory=dict)
    connectors: Dict[str, bool] = Field(default_factory=dict)


class WorkspaceIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class WorkspaceMemberIn(BaseModel):
    role: str = Field(..., pattern="^(viewer|editor|owner)$")


@router.get("/projects/{project_id}/sharing")
def get_sharing(project_id: str, request: Request) -> Dict[str, Any]:
    uid = _who(request)
    _need(project_id, uid, "viewer")
    return {"ok": True, **access.describe(project_id, uid)}


@router.put("/projects/{project_id}/sharing")
def put_sharing(project_id: str, body: SharingIn, request: Request) -> Dict[str, Any]:
    uid = _who(request)
    _need(project_id, uid, "owner")
    try:
        access.set_visibility(project_id, body.visibility, by=uid, workspace_id=body.workspace_id)
    except access.ProjectAccessDenied:
        raise HTTPException(status_code=403, detail="You are not a member of that workspace")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Keep the legacy flag the UI and exports read in step with the ACL.
    from . import projects
    projects.update_project(project_id, {"is_public": body.visibility == "public"})
    return {"ok": True, **access.describe(project_id, uid)}


@router.put("/projects/{project_id}/members/{member_id}")
def put_member(project_id: str, member_id: str, body: MemberIn, request: Request) -> Dict[str, Any]:
    uid = _who(request)
    _need(project_id, uid, "owner")
    from .users import get_user_by_id
    if not get_user_by_id(member_id):
        raise HTTPException(status_code=404, detail="No such user")
    try:
        access.set_member(project_id, member_id, body.role, by=uid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **access.describe(project_id, uid)}


@router.delete("/projects/{project_id}/members/{member_id}")
def delete_member(project_id: str, member_id: str, request: Request) -> Dict[str, Any]:
    uid = _who(request)
    _need(project_id, uid, "owner")
    try:
        access.set_member(project_id, member_id, None, by=uid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **access.describe(project_id, uid)}


@router.get("/projects/{project_id}/capabilities")
def get_capabilities(project_id: str, request: Request) -> Dict[str, Any]:
    uid = _who(request)
    _need(project_id, uid, "viewer")
    return {"ok": True, "can_edit": access.can(project_id, uid, "owner"),
            **caps.describe(project_id, uid)}


@router.put("/projects/{project_id}/capabilities")
def put_capabilities(project_id: str, body: CapabilitiesIn, request: Request) -> Dict[str, Any]:
    uid = _who(request)
    _need(project_id, uid, "owner")
    try:
        out = caps.update(project_id, body.model_dump(), by=uid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "can_edit": True, **out}


@router.get("/projects/{project_id}/activity")
def get_activity(project_id: str, request: Request, limit: int = 100) -> Dict[str, Any]:
    uid = _who(request)
    _need(project_id, uid, "editor")
    return {"ok": True, "activity": access.activity(project_id, limit)}


@router.post("/v1/workspaces")
def post_workspace(body: WorkspaceIn, request: Request) -> Dict[str, Any]:
    uid = _who(request)
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in first")
    return {"ok": True, "workspace": access.create_workspace(body.name, uid)}


@router.put("/v1/workspaces/{workspace_id}/members/{member_id}")
def put_workspace_member(workspace_id: str, member_id: str, body: WorkspaceMemberIn,
                         request: Request) -> Dict[str, Any]:
    uid = _who(request)
    try:
        access.set_workspace_member(workspace_id, member_id, body.role, by=uid)
    except access.ProjectAccessDenied:
        raise HTTPException(status_code=404, detail="Workspace not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}
