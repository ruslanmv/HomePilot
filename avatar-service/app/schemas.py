"""
Request / response models for the avatar microservice.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    count: int = Field(default=4, ge=1, le=8)
    seeds: Optional[List[int]] = None
    truncation: float = Field(default=0.7, ge=0.1, le=1.0)


class Result(BaseModel):
    url: str
    seed: Optional[int] = None
    metadata: Dict[str, Any] = {}


class GenerateResponse(BaseModel):
    results: List[Result]
    warnings: List[str] = []
