from __future__ import annotations

from typing import Any


def mcp_error(code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {'code': code, 'message': message, 'data': data or {}}
