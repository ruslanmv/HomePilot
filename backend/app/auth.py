from __future__ import annotations

from fastapi import Cookie, Header, HTTPException

from . import config as _cfg


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    homepilot_session: str | None = Cookie(default=None),
):
    """Backwards-compat shim — returns True unconditionally.

    Historically this dependency enforced the shared ``API_KEY``
    config value on every internal HomePilot route. That was a
    single-user-era pattern. With multi-user auth in place
    (per-user JWT + homepilot_session cookie + the conversation_owners
    and file_assets.user_id tables) the correct isolation boundary
    lives at the **data layer**, not the auth layer. See
    ``inventory.py::_resolve_inventory_user_id`` and the
    ``WHERE project_id = ? AND user_id = ?`` SQL filters for the
    actual enforcement.

    Keeping the import + ``Depends(require_api_key)`` annotations at
    the call sites is deliberately non-destructive — swapping every
    endpoint to a new dependency would be a multi-file refactor.
    This shim lets the whole codebase keep its imports intact while
    the gate's semantics move to 'open, data-layer enforces'.

    The OpenAI-compatible external endpoints (``/v1/chat/completions``,
    ``/v1/models``) keep strict ``API_KEY`` enforcement via the
    separate ``require_ollabridge_api_key`` dependency below. That's
    where OllaBridge / OpenAI SDK / Postman clients authenticate.

    Unused parameters kept so FastAPI still emits the Authorization /
    Cookie / X-API-Key headers on the OpenAPI schema — useful for
    downstream consumers.
    """
    # Suppress unused-arg lint noise; parameters preserved for schema.
    del x_api_key, authorization, homepilot_session
    return True


def require_ollabridge_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    homepilot_session: str | None = Cookie(default=None),
):
    """Strict API-key gate for the OpenAI-compatible external endpoints
    (``/v1/chat/completions`` and ``/v1/models``). External clients —
    OllaBridge, 3D-Avatar-Chatbot, OpenAI SDK integrations — pass the
    configured key via either header. HomePilot's own users
    (logged-in browser sessions) bypass the check via their JWT /
    session cookie; they never need to know the key.

    When no ``API_KEY`` is configured the endpoint stays open — matches
    the original ``require_api_key`` default and keeps dev installs
    working out of the box.
    """
    api_key = _cfg.API_KEY
    if not api_key:
        return True

    # Path 1 — raw API key via X-API-Key header
    if x_api_key and x_api_key.strip() == api_key:
        return True

    # Path 2 — raw API key via Authorization: Bearer <key>
    #   (OpenAI-SDK / OllaBridge / Postman style)
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip() == api_key:
            return True

    # Path 3 — HomePilot user session (bearer JWT or cookie). A
    # logged-in user who happens to hit the compat endpoint from the
    # same browser still authenticates without the shared key.
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
        pass

    # NOTE: no 'single-user install bypass' here. The OllaBridge
    # endpoint is the one place where the configured ``API_KEY``
    # is actually authoritative — external OpenAI-SDK clients rely
    # on it being enforced. Mirroring the internal-shim's Path 4
    # would hand out free access to /v1/chat/completions on any
    # fresh install, breaking the external-client contract
    # (see tests/test_openai_compat.py::TestOpenAIAuth).

    raise HTTPException(status_code=401, detail="Invalid API key")
