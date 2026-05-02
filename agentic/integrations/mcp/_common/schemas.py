from __future__ import annotations

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    source_id: str
    uri: str
    title: str | None = None


class StandardToolResult(BaseModel):
    ok: bool = True
    message: str = Field(default='ok')
    data: dict = Field(default_factory=dict)
