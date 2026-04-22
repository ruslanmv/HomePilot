# expert/schemas.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ExpertMessage(BaseModel):
    """Single turn in conversation history."""
    role: Literal["user", "assistant", "system"]
    content: str


class ExpertChatRequest(BaseModel):
    """Request body for POST /v1/expert/chat (non-streaming)."""
    query: str = Field(..., min_length=1, description="User's message / question")
    provider: Literal["auto", "local", "groq", "grok", "gemini", "claude", "openai"] = Field(
        default="auto",
        description="Provider to use. 'auto' applies complexity-based routing.",
    )
    thinking_mode: Literal["auto", "fast", "think", "heavy"] = Field(
        default="auto",
        description=(
            "Pipeline mode. "
            "'auto' = complexity-based selection; "
            "'fast' = single LLM call, local model; "
            "'think' = analyze→plan→solve chain (3 LLM calls); "
            "'heavy' = 4-agent research→reason→synthesize→validate pipeline."
        ),
    )
    with_critique: bool = Field(
        default=False,
        description="In 'think' mode, add a self-critique/correction step.",
    )
    history: List[ExpertMessage] = Field(
        default_factory=list,
        description="Previous conversation turns (newest last).",
    )
    model: Optional[str] = Field(
        default=None,
        description="Override the default model for the selected provider.",
    )
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192)
    system_prompt: Optional[str] = Field(
        default=None,
        description="Override the default Expert system prompt.",
    )


class ExpertStreamRequest(ExpertChatRequest):
    """Same as ExpertChatRequest — exists for clarity in the route signature."""
    pass


class ExpertChatResponse(BaseModel):
    """Response from POST /v1/expert/chat."""
    model_config = {"protected_namespaces": ()}

    content: str = Field(..., description="The assistant's reply.")
    provider_used: str = Field(..., description="Which provider actually answered.")
    model_used: Optional[str] = Field(default=None)
    complexity_score: int = Field(
        ..., ge=0, le=10,
        description="Complexity score that drove provider selection (0=simple, 10=complex).",
    )
    thinking_mode_used: str = Field(
        default="fast",
        description="Which pipeline actually ran: fast / think / heavy.",
    )
    steps: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Intermediate step outputs from think/heavy pipelines.",
    )
    provider_raw: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw provider response for debugging (omitted in production).",
    )


class ExpertInfoResponse(BaseModel):
    """Response from GET /v1/expert/info — lists available providers and routing config."""
    available_providers: List[str]
    default_provider: str
    local_threshold: int
    groq_threshold: int
    local_model: str
    local_fast_model: str
    groq_model: str
    grok_model: str
    gemini_model: str
