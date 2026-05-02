from __future__ import annotations

from pydantic import BaseModel

class HealthResponse(BaseModel):
    ok: bool = True
