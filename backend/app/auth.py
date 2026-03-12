from __future__ import annotations

from fastapi import Header, HTTPException

from . import config as _cfg


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
):
    """Validate API key from X-API-Key header or Authorization: Bearer <key>.

    Reads the key from config at call time (not import time) so that
    /settings/ollabridge can update the key at runtime.
    """
    api_key = _cfg.API_KEY
    if not api_key:
        return True

    # Try X-API-Key header first
    if x_api_key and x_api_key.strip() == api_key:
        return True

    # Try Authorization: Bearer <key> (used by OpenAI SDKs / OllaBridge)
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip() == api_key:
            return True

    raise HTTPException(status_code=401, detail="Invalid API key")
