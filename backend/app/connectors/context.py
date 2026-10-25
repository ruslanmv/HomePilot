"""Whose connectors a request may use.

The chat, vision, image and video code paths do not carry the user, so the request's own
credentials are kept here for the length of the request (``bind_request``, a middleware) and
turned into a user only when a connector is actually needed. ``bind_user`` lets code that
already knows the user (the orchestrator) say so directly.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_request_token: ContextVar[str] = ContextVar("hp_connector_request_token", default="")
_user_id: ContextVar[str] = ContextVar("hp_connector_user_id", default="")


async def bind_request(request, call_next):
    """Middleware: remember the request's session token (Bearer, else the session cookie)."""
    auth = request.headers.get("authorization") or ""
    token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    token = token or (request.cookies.get("homepilot_session") or "").strip()
    reset = _request_token.set(token)
    try:
        return await call_next(request)
    finally:
        _request_token.reset(reset)


def bind_user(user_id: Optional[str]) -> None:
    if user_id:
        _user_id.set(user_id)


def current_user_id() -> str:
    """The user this request acts for: bound by the caller, else from the session token,
    else the single user of a local install. Empty when nobody can be named — a connector is
    then not used, rather than borrowing someone else's."""
    uid = _user_id.get()
    if uid:
        return uid
    from ..users import _validate_token, count_users, get_or_create_default_user, guest_accounts_enabled

    token = _request_token.get()
    if token:
        user = _validate_token(token)
        if user:
            return user["id"]
    if not guest_accounts_enabled() and count_users() <= 1:
        return get_or_create_default_user()["id"]
    return ""
