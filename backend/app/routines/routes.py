"""HTTP API for user routines.

Definition management stays separate from execution. The web tab and optional
companion clients share this contract, while the scheduler/runner can evolve
behind it without changing how routines are authored.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .. import projects
from ..users import (
    count_users,
    ensure_users_tables,
    get_current_user,
    get_or_create_default_user,
)
from . import store


router = APIRouter(prefix="/v1/routines", tags=["routines"])


class RoutineSchedule(BaseModel):
    type: Literal["daily", "weekly", "once"] = "daily"
    time: Optional[str] = Field(default="08:00", max_length=5)
    days: List[int] = Field(default_factory=list)
    at: Optional[str] = None


class RoutineTarget(BaseModel):
    type: Literal["assistant", "persona", "project"] = "assistant"
    project_id: Optional[str] = None


class RoutineAction(BaseModel):
    type: Literal["news_digest", "daily_briefing", "reminder", "assistant_prompt"]
    parameters: Dict[str, Any] = Field(default_factory=dict)


class RoutineDelivery(BaseModel):
    # in_app remains for backwards compatibility with the first Routines UI.
    in_app: bool = True
    notification: bool = True
    create_conversation: bool = True
    speak_if_active: bool = True
    catch_up: bool = True


class RoutineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    enabled: bool = True
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    schedule: RoutineSchedule
    target: RoutineTarget = Field(default_factory=RoutineTarget)
    action: RoutineAction
    delivery: RoutineDelivery = Field(default_factory=RoutineDelivery)


class RoutineUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    enabled: Optional[bool] = None
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=80)
    schedule: Optional[RoutineSchedule] = None
    target: Optional[RoutineTarget] = None
    action: Optional[RoutineAction] = None
    delivery: Optional[RoutineDelivery] = None


def _user(
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """Resolve the owner without weakening multi-user isolation."""
    ensure_users_tables()
    user = get_current_user(
        authorization=authorization,
        homepilot_session=homepilot_session,
    )
    if user:
        return user
    if count_users() <= 1:
        return get_or_create_default_user()
    raise HTTPException(status_code=401, detail="Authentication required")


def _validate_target(target: RoutineTarget) -> Dict[str, Any]:
    if target.type == "assistant":
        return {"type": "assistant"}

    project_id = (target.project_id or "").strip()
    if not project_id:
        raise HTTPException(status_code=422, detail="A project target is required")

    project = projects.get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Target project not found")

    if target.type == "persona" and project.get("project_type") != "persona":
        raise HTTPException(status_code=422, detail="Selected target is not a persona project")

    return {"type": target.type, "project_id": project_id}


@router.get("/capabilities")
def capabilities() -> Dict[str, Any]:
    return {
        "available": True,
        "version": 2,
        "execution": "definition_only",
        "actions": [
            "news_digest",
            "daily_briefing",
            "reminder",
            "assistant_prompt",
        ],
        "schedule_types": ["daily", "weekly", "once"],
        "target_types": ["assistant", "persona", "project"],
        "delivery": [
            "notification",
            "create_conversation",
            "speak_if_active",
            "catch_up",
        ],
        "companion_compatible": True,
    }


@router.get("")
def list_user_routines(user: Dict[str, Any] = Depends(_user)) -> Dict[str, Any]:
    return {"routines": store.list_routines(user["id"])}


@router.post("", status_code=201)
def create_user_routine(
    body: RoutineCreate,
    user: Dict[str, Any] = Depends(_user),
) -> Dict[str, Any]:
    data = body.model_dump()
    data["target"] = _validate_target(body.target)
    return store.create_routine(user["id"], data)


@router.patch("/{routine_id}")
def update_user_routine(
    routine_id: str,
    body: RoutineUpdate,
    user: Dict[str, Any] = Depends(_user),
) -> Dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if body.target is not None:
        changes["target"] = _validate_target(body.target)
    routine = store.update_routine(user["id"], routine_id, changes)
    if not routine:
        raise HTTPException(status_code=404, detail="Routine not found")
    return routine




@router.get("/runs")
def list_user_runs(
    unseen_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user: Dict[str, Any] = Depends(_user),
) -> Dict[str, Any]:
    return {
        "runs": store.list_runs(
            user["id"],
            limit=limit,
            unseen_only=unseen_only,
        )
    }


@router.get("/{routine_id}/runs")
def list_routine_runs(
    routine_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: Dict[str, Any] = Depends(_user),
) -> Dict[str, Any]:
    if not store.get_routine(user["id"], routine_id):
        raise HTTPException(status_code=404, detail="Routine not found")
    return {
        "runs": store.list_runs(
            user["id"],
            routine_id=routine_id,
            limit=limit,
        )
    }


@router.patch("/runs/{run_id}/seen")
def mark_run_seen(
    run_id: str,
    opened: bool = Query(default=False),
    user: Dict[str, Any] = Depends(_user),
) -> Dict[str, Any]:
    run = store.mark_run_seen(user["id"], run_id, opened=opened)
    if not run:
        raise HTTPException(status_code=404, detail="Routine run not found")
    return run


@router.delete("/{routine_id}")
def delete_user_routine(
    routine_id: str,
    user: Dict[str, Any] = Depends(_user),
) -> Dict[str, Any]:
    if not store.archive_routine(user["id"], routine_id):
        raise HTTPException(status_code=404, detail="Routine not found")
    return {"ok": True, "id": routine_id}
