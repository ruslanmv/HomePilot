from pydantic import BaseModel, Field
from typing import List
from expert.types import ToolResult


class TurnState(BaseModel):
    user_message: str
    tool_results: List[ToolResult] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    done: bool = False
