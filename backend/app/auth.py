from __future__ import annotations

from fastapi import Cookie, Header, HTTPException

from . import config as _cfg


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    homepilot_session: str | None = Cookie(default=None),
):
    """Validate API key from ``X-API-Key`` header or ``Authorization:
    Bearer <key>``, OR a valid user session (bearer JWT / session
    cookie). The two auth worlds coexist for backwards compatibility:

    - OpenAI-SDK / OllaBridge clients keep passing the raw API key
      as a Bearer token or via ``X-API-Key``.
    - Logged-in HomePilot users (browser sessions) authenticate via
      their JWT or ``homepilot_session`` cookie — no API key needed
      to browse their own inventory, chat, sessions, etc.

    Reads the key from config at call time (not import time) so that
    ``/settings/ollabridge`` can update the key at runtime.
    """
    api_key = _cfg.API_KEY
    if not api_key:
        return True

    # Path 1 — raw API key via X-API-Key header
    if x_api_key and x_api_key.strip() == api_key:
        return True

    # Path 2 — raw API key via Authorization: Bearer <key>
    #   (used by OpenAI SDKs / OllaBridge / Postman setups)
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip() == api_key:
            return True

    # Path 3 (additive) — valid HomePilot user session. The raw API
    # key is a shared-tenant gate from the single-user era; per-user
    # data endpoints (inventory, chat, persona sessions) should be
    # reachable by any logged-in user without the admin-level key.
    # We treat a verified JWT / session cookie as equivalent proof
    # of authorisation. Missing users subsystem = quietly fall
    # through to the 401 below.
    try:
        from .users import ensure_users_tables, _validate_token
        ensure_users_tables()
        token = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
        if not token and homepilot_session:
            token = homepilot_session.strip()
        if token and _validate_token(token):
            return True
    except Exception:
        pass  # users table not ready / import issue — fall through

    raise HTTPException(status_code=401, detail="Invalid API key")
