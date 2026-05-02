"""
Shared helpers for the HTTP routes.

- ``current_user`` dependency — resolves viewer → HomePilot user_id,
  returns 401 if none (anonymous install has a default user, so
  this only trips when the users subsystem is unreachable).
- ``scoped_experience`` dependency — fetches an experience by id
  and enforces user-scoping (probe-safe 404 if mismatched).
- ``http_error_from`` — uniform translator from typed
  InteractiveError → FastAPI HTTPException. Keeps routes free of
  boilerplate try/except chains.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException

from .. import repo
from ..auth import resolve_viewer_user_id
from ..errors import (
    InteractiveError,
    NotAuthenticatedError,
    NotAuthorizedError,
    NotFoundError,
)
from ..models import Experience


def current_user(
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> str:
    """FastAPI dependency: returns the viewer's HomePilot user id.

    Resolves via the same logic as the rest of the app. Raises 401
    if no user can be found — on the single-user install this
    never happens because the default user is auto-created.
    """
    uid = resolve_viewer_user_id(authorization=authorization, homepilot_session=homepilot_session)
    if not uid:
        raise http_error_from(NotAuthenticatedError("no user"))
    return uid


def scoped_experience(
    experience_id: str, user_id: str = Depends(current_user),
) -> Experience:
    """FastAPI dependency: fetch an experience and enforce ownership."""
    exp = repo.get_experience(experience_id, user_id=user_id)
    if not exp:
        raise http_error_from(NotAuthorizedError("not found or not yours"))
    return exp


def http_error_from(err: InteractiveError) -> HTTPException:
    """Map a typed InteractiveError to an HTTPException.

    The response body mirrors ``err.to_dict()`` so the frontend
    can always branch on ``{"code": ..., "error": ..., "data": ...}``.
    """
    return HTTPException(status_code=err.http_status, detail=err.to_dict())
