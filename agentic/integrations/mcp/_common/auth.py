from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class AuthContext:
    token: str
    subject: str
    roles: tuple[str, ...]


def require_service_token(authorization: Optional[str] = Header(default=None)) -> AuthContext:
    """Minimal bearer-token validation hook for MCP services.

    Replace with your IAM/OIDC validator in production.
    """
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail='Missing bearer token')
    token = authorization.split(' ', 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail='Invalid bearer token')
    return AuthContext(token=token, subject='service', roles=('mcp:invoke',))
