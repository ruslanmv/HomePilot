from pydantic import BaseModel
from typing import Optional
from expert.types import ToolResult, PlannedStep


class AgentStepOutcome(BaseModel):
    planned_step: PlannedStep
    executed: bool = False
    skipped: bool = False
    tool_result: Optional[ToolResult] = None
    note: str = ""
