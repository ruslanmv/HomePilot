# backend/app/openai_compat_endpoint.py
"""
OpenAI-compatible /v1/chat/completions endpoint for HomePilot personas.

Exposes HomePilot persona conversations as a standard OpenAI API, enabling
external tools (OllaBridge, 3D-Avatar-Chatbot, any OpenAI SDK) to chat
with a HomePilot persona as if it were a regular LLM model.

Model naming convention:
  - "persona:<project_id>"  → routes to that persona project
  - "personality:<id>"      → routes to a built-in personality agent

The endpoint handles:
  - Standard OpenAI chat/completions request/response format
  - System prompt passthrough (merged with persona context)
  - Conversation history via message array
  - Agent-controlled tool use (MCP tools) when agentic capabilities are enabled
  - Model listing via /v1/models
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field

from .auth import require_api_key
from . import config as _config
from .llm import chat as llm_chat, strip_think_tags
from .personalities import registry as personality_registry, build_system_prompt, ConversationMemory
from .storage import add_message, get_recent

# Lazy imports to avoid circular dependencies
_projects_mod = None
_agent_chat_mod = None


def _get_projects():
    global _projects_mod
    if _projects_mod is None:
        from . import projects as _p
        _projects_mod = _p
    return _projects_mod


def _get_agent_chat():
    global _agent_chat_mod
    if _agent_chat_mod is None:
        from . import agent_chat as _ac
        _agent_chat_mod = _ac
    return _agent_chat_mod


router = APIRouter(tags=["openai-compat"])

# Runtime toggle — set by /settings/ollabridge endpoint.
# True by default so the API works out of the box; the settings toggle can disable it.
_compat_enabled: bool = True

# In-memory conversation memories for OpenAI-compat sessions
_compat_memories: Dict[str, ConversationMemory] = {}


# ---------------------------------------------------------------------------
# Request / Response schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="default", description="Model ID: 'persona:<project_id>' or 'personality:<id>'")
    messages: List[ChatMessage] = Field(..., description="Conversation messages")
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=800, ge=1, le=16384)
    stream: Optional[bool] = Field(default=False)


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Usage = Field(default_factory=Usage)


class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "homepilot"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: List[ModelObject]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_model(model: str) -> tuple[str, str]:
    """Parse model string into (type, id).

    Returns:
        ("persona", "<project_id>") or ("personality", "<personality_id>")
        or ("default", "") for unrecognized models.
    """
    if model.startswith("persona:"):
        return ("persona", model[len("persona:"):])
    if model.startswith("personality:"):
        return ("personality", model[len("personality:"):])
    # Check if it matches a known personality id directly
    if personality_registry.get(model):
        return ("personality", model)
    return ("default", model)


def _build_persona_system_prompt(project_data: Dict[str, Any]) -> str:
    """Build system prompt from persona project data."""
    parts = []

    # Extract persona agent definition from project
    persona_agent = project_data.get("persona_agent") or {}
    system_prompt = persona_agent.get("system_prompt", "")
    if system_prompt:
        parts.append(system_prompt)

    # Add personality context
    label = persona_agent.get("label", "")
    if label:
        parts.append(f"Your name is {label}.")

    # Add agentic context if available
    agentic = project_data.get("agentic") or {}
    goal = agentic.get("goal", "")
    if goal:
        parts.append(f"Your goal: {goal}")

    return "\n\n".join(parts) if parts else "You are a helpful assistant."


async def _chat_with_persona_project(
    project_id: str,
    messages: List[ChatMessage],
    temperature: float,
    max_tokens: int,
) -> str:
    """Route a chat request through a persona project, including MCP tools if enabled."""
    projects = _get_projects()
    project_data = projects.get_project_by_id(project_id)
    if not project_data:
        raise HTTPException(404, f"Persona project '{project_id}' not found")

    if project_data.get("project_type") != "persona":
        raise HTTPException(400, f"Project '{project_id}' is not a persona project")

    # Build system prompt from persona
    system_prompt = _build_persona_system_prompt(project_data)

    # Extract user message and history
    user_message = messages[-1].content if messages else ""
    conversation_id = f"compat-{project_id}-{uuid.uuid4().hex[:8]}"

    # Build LLM messages array
    llm_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        if msg.role != "system":
            llm_messages.append({"role": msg.role, "content": msg.content})

    # Check if agentic capabilities are enabled
    agentic = project_data.get("agentic") or {}
    capabilities = agentic.get("capabilities") or []

    if capabilities:
        # Use agent chat with tool use
        try:
            agent_chat = _get_agent_chat()
            result = await agent_chat.run_agent_loop(
                user_text=user_message,
                conversation_id=conversation_id,
                project_id=project_id,
                system_prompt=system_prompt,
                provider=_config.DEFAULT_PROVIDER,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return result.get("text", "I couldn't generate a response.")
        except Exception as e:
            print(f"[COMPAT] Agent loop failed, falling back to direct LLM: {e}")

    # Direct LLM call (no tools)
    try:
        result = await llm_chat(
            llm_messages,
            provider=_config.DEFAULT_PROVIDER,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        return strip_think_tags(content)
    except Exception as e:
        raise HTTPException(502, f"LLM backend error: {e}")


async def _chat_with_personality(
    personality_id: str,
    messages: List[ChatMessage],
    temperature: float,
    max_tokens: int,
) -> str:
    """Route a chat request through a built-in personality agent."""
    agent = personality_registry.get(personality_id)
    if not agent:
        raise HTTPException(404, f"Personality '{personality_id}' not found")

    # Get or create conversation memory
    session_key = f"compat-{personality_id}"
    if session_key not in _compat_memories:
        _compat_memories[session_key] = ConversationMemory()
    memory = _compat_memories[session_key]

    # Build system prompt
    is_first = len(messages) <= 1
    system_prompt = build_system_prompt(agent, memory, is_first_turn=is_first)

    # Build LLM messages
    llm_messages = [{"role": "system", "content": system_prompt}]

    # Merge any external system messages with persona prompt
    for msg in messages:
        if msg.role == "system":
            llm_messages[0]["content"] += f"\n\n{msg.content}"
        else:
            llm_messages.append({"role": msg.role, "content": msg.content})

    # Call LLM
    try:
        result = await llm_chat(
            llm_messages,
            provider=_config.DEFAULT_PROVIDER,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = strip_think_tags(content)

        # Update memory
        if messages:
            memory.record_turn(len(messages[-1].content))

        return content
    except Exception as e:
        raise HTTPException(502, f"LLM backend error: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
async def openai_chat_completions(req: ChatCompletionRequest) -> ChatCompletionResponse:
    """OpenAI-compatible chat completions endpoint.

    Routes to HomePilot personas via model naming:
      - model="persona:<project_id>"  → persona project with MCP tools
      - model="personality:<id>"      → built-in personality agent
      - model="<personality_id>"      → built-in personality (shorthand)
      - model="default"               → plain LLM passthrough
    """
    if not _compat_enabled:
        raise HTTPException(503, "Persona API is disabled. Enable it in Settings > OllaBridge Gateway.")

    if req.stream:
        raise HTTPException(501, "Streaming is not yet supported for persona endpoints")

    t0 = time.time()
    model_type, model_id = _parse_model(req.model)

    temperature = req.temperature if req.temperature is not None else 0.7
    max_tokens = req.max_tokens if req.max_tokens is not None else 800

    if model_type == "persona":
        content = await _chat_with_persona_project(
            model_id, req.messages, temperature, max_tokens,
        )
    elif model_type == "personality":
        content = await _chat_with_personality(
            model_id, req.messages, temperature, max_tokens,
        )
    else:
        # Default: plain LLM passthrough
        llm_messages = [{"role": m.role, "content": m.content} for m in req.messages]
        try:
            result = await llm_chat(
                llm_messages,
                provider=_config.DEFAULT_PROVIDER,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            content = strip_think_tags(content)
        except Exception as e:
            raise HTTPException(502, f"LLM backend error: {e}")

    latency_ms = int((time.time() - t0) * 1000)
    print(f"[COMPAT] model={req.model} latency={latency_ms}ms content_len={len(content)}")

    return ChatCompletionResponse(
        id=f"homepilot-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=req.model,
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(role="assistant", content=content),
            )
        ],
    )


@router.get("/v1/models", dependencies=[Depends(require_api_key)])
async def openai_list_models() -> ModelListResponse:
    """List available models (personas + built-in personalities).

    Returns them in OpenAI /v1/models format so any OpenAI SDK can discover them.
    """
    if not _compat_enabled:
        raise HTTPException(503, "Persona API is disabled. Enable it in Settings > OllaBridge Gateway.")

    models: List[ModelObject] = []
    now = int(time.time())

    # Built-in personalities
    for agent in personality_registry.all():
        models.append(ModelObject(
            id=f"personality:{agent.id}",
            created=now,
            owned_by="homepilot-personality",
        ))

    # Persona projects
    try:
        projects = _get_projects()
        all_projects = projects.list_projects()
        for proj in all_projects:
            if proj.get("project_type") == "persona":
                pid = proj.get("id", "")
                models.append(ModelObject(
                    id=f"persona:{pid}",
                    created=now,
                    owned_by="homepilot-persona",
                ))
    except Exception as e:
        print(f"[COMPAT] Error listing persona projects: {e}")

    return ModelListResponse(data=models)
