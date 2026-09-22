"""HTTP API for user routines.

This is intentionally a CRUD contract, not a scheduler. Keeping definition
management separate from execution lets HomePilot add a durable runner later
without changing the API used by the web tab or optional 3D Avatar clients.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, Field

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


class RoutineAction(BaseModel):
    type: Literal["news_digest", "daily_briefing", "reminder", "assistant_prompt"]
    parameters: Dict[str, Any] = Field(default_factory=dict)


class RoutineDelivery(BaseModel):
    in_app: bool = True
    speak_if_active: bool = True
    catch_up: bool = True


class RoutineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    enabled: bool = True
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    schedule: RoutineSchedule
    action: RoutineAction
    delivery: RoutineDelivery = Field(default_factory=RoutineDelivery)


class RoutineUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    enabled: Optional[bool] = None
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=80)
    schedule: Optional[RoutineSchedule] = None
    action: Optional[RoutineAction] = None
    delivery: Optional[RoutineDelivery] = None


def _user(
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """Resolve the owner without weakening multi-user isolation.

    Logged-in installs use their normal bearer/cookie identity. Legacy
    single-user installs fall back to the default user. Once multiple users
    exist, anonymous access is rejected rather than guessing an owner.
    """
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


@router.get("/capabilities")
def capabilities() -> Dict[str, Any]:
    return {
        "available": True,
        "version": 1,
        "execution": "definition_only",
        "actions": [
            "news_digest",
            "daily_briefing",
            "reminder",
            "assistant_prompt",
        ],
        "schedule_types": ["daily", "weekly", "once"],
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
    return store.create_routine(user["id"], body.model_dump())


@router.patch("/{routine_id}")
def update_user_routine(
    routine_id: str,
    body: RoutineUpdate,
    user: Dict[str, Any] = Depends(_user),
) -> Dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    routine = store.update_routine(user["id"], routine_id, changes)
    if not routine:
        raise HTTPException(status_code=404, detail="Routine not found")
    return routine


@router.delete("/{routine_id}")
def delete_user_routine(
    routine_id: str,
    user: Dict[str, Any] = Depends(_user),
) -> Dict[str, Any]:
    if not store.archive_routine(user["id"], routine_id):
        raise HTTPException(status_code=404, detail="Routine not found")
    return {"ok": True, "id": routine_id}
