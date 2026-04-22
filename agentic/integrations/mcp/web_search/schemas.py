from __future__ import annotations

from pydantic import BaseModel, Field


class ToolInvocation(BaseModel):
    method: str
    payload: dict = Field(default_factory=dict)


class ToolResponse(BaseModel):
    ok: bool = True
    result: dict = Field(default_factory=dict)
