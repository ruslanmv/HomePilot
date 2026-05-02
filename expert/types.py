from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_name: str
    ok: bool = True
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class PlannedStep(BaseModel):
    id: str
    kind: Literal["tool", "answer", "confirm", "finalize"]
    reasoning: str
    tool_call: Optional[ToolCall] = None
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class SessionState(BaseModel):
    session_id: str
    messages: List[Message] = Field(default_factory=list)
    summary: str = ""
    workspace_id: Optional[str] = None
    pending_confirmation: Optional[Dict[str, Any]] = None


class AgentEvent(BaseModel):
    type: Literal[
        "status",
        "plan",
        "tool_start",
        "tool_result",
        "tool_error",
        "confirmation_required",
        "final_answer",
        "done"
    ]
    data: Dict[str, Any] = Field(default_factory=dict)
