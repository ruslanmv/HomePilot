# backend/app/agent_routes.py
"""
Topology 3: Agent-Controlled tool use — API routes.

Additive router. Mounts at /v1/agent.
Does NOT alter /chat or any existing endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from .auth import require_api_key
from .agent_chat import agent_chat

router = APIRouter(prefix="/v1/agent", tags=["agent"])


class AgentChatIn(BaseModel):
    # conversation/project
    conversation_id: Optional[str] = Field(None, description="Conversation ID (optional)")
    project_id: Optional[str] = Field(None, description="Project ID context (optional)")
    message: str = Field(..., description="User message")

    # main LLM settings
    provider: str = Field("openai_compat", description="Main LLM provider")
    provider_base_url: Optional[str] = Field(None, description="Main LLM base URL")
    provider_model: Optional[str] = Field(None, description="Main LLM model name")
    temperature: float = Field(0.7, description="Main LLM temperature")
    max_tokens: int = Field(900, description="Main LLM max tokens")

    # vision tool settings (multimodal)
    vision_provider: str = Field("ollama", description="Vision provider")
    vision_base_url: Optional[str] = Field(None, description="Vision base URL (Ollama)")
    vision_model: Optional[str] = Field(None, description="Vision model name")

    nsfw_mode: bool = Field(False, description="Allow unrestricted analysis")

    # agent controls
    max_tool_calls: int = Field(2, description="Maximum tool calls per request")
    history_limit: int = Field(24, description="History messages to include")


@router.post("/chat", dependencies=[Depends(require_api_key)])
async def agent_chat_endpoint(inp: AgentChatIn) -> JSONResponse:
    """
    Topology 3: Agent-controlled tool use.
    Additive endpoint. Does not alter /chat or existing multimodal flow.
    """
    out = await agent_chat(
        user_text=inp.message,
        conversation_id=inp.conversation_id,
        project_id=inp.project_id,
        llm_provider=inp.provider,
        llm_base_url=inp.provider_base_url,
        llm_model=inp.provider_model,
        temperature=inp.temperature,
        max_tokens=inp.max_tokens,
        vision_provider=inp.vision_provider,
        vision_base_url=inp.vision_base_url,
        vision_model=inp.vision_model,
        nsfw_mode=inp.nsfw_mode,
        max_tool_calls=inp.max_tool_calls,
        history_limit=inp.history_limit,
    )
    return JSONResponse(status_code=200, content=out)
