"""
Auth helper for the interactive service.

Thin wrapper over HomePilot's existing user-resolution logic. Lives
here (instead of reusing ``main._scoped_user_or_none``) so that:

- this subpackage has no import-time dependency on ``main``
- tests can monkeypatch a single entry point
- future interactive-only auth rules (e.g. per-experience share
  links, viewer JWTs) slot in without touching the rest of the app

Resolution order matches the rest of HomePilot:

1. ``Authorization: Bearer <JWT>`` → validate as user token
2. ``homepilot_session`` cookie     → validate as user token
3. Single-user install fallback     → default user

Never raises on a failed lookup; returns ``None`` when no user
could be resolved. Callers decide whether to 401 / fall back.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def resolve_viewer_user_id(
    authorization: str = "",
    homepilot_session: Optional[str] = None,
) -> Optional[str]:
    """Resolve the current viewer to a HomePilot ``users.id``.

    Returns the id as a string, or ``None`` if no user could be
    identified (legitimate on a zero-user install; router decides
    what to do next).
    """
    try:
        from ..users import (
            ensure_users_tables,
            _validate_token,
            get_or_create_default_user,
            count_users,
        )
        ensure_users_tables()
        token = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
        if not token and homepilot_session:
            token = homepilot_session.strip()
        user = _validate_token(token) if token else None
        if user and user.get("id"):
            return str(user["id"])
        # Single-user fallback — mirrors ``_scoped_user_or_none``.
        if count_users() <= 1:
            default_user = get_or_create_default_user()
            uid = default_user.get("id") if default_user else None
            return str(uid) if uid else None
    except Exception:
        # Users subsystem unreachable → treat as anonymous.
        return None
    return None


def resolve_viewer(
    authorization: str = "",
    homepilot_session: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Like ``resolve_viewer_user_id`` but returns the full user row.

    Used where the router needs the username / display_name (e.g.
    personalization rule evaluation).
    """
    uid = resolve_viewer_user_id(authorization, homepilot_session)
    if not uid:
        return None
    try:
        from ..users import list_users
        for u in list_users():
            if u.get("id") == uid:
                return dict(u)
    except Exception:
        pass
    return None
