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

import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field

from .auth import require_ollabridge_api_key
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
    name: Optional[str] = None


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


def _build_external_id(proj: Dict[str, Any]) -> str:
    """Build a stable external model ID for a published persona.

    Format: persona:<alias>--<short_uuid>  (if alias set)
            persona:<name>--<short_uuid>   (auto-derived from persona name)
            persona:<short_uuid>           (last-resort fallback)
    """
    shared = proj.get("shared_api") or {}
    alias = (shared.get("alias") or "").strip()
    pid = proj.get("id", "")
    short = pid[:8]

    if alias:
        safe = re.sub(r'[^a-z0-9-]', '', alias.lower().replace(' ', '-'))
        return f"persona:{safe}--{short}"

    # Auto-derive from persona label or project name
    label = ""
    pa = proj.get("persona_agent")
    if isinstance(pa, dict):
        label = (pa.get("label") or "").strip()
    if not label:
        label = (proj.get("name") or "").strip()
    if label:
        safe = re.sub(r'[^a-z0-9-]', '', label.lower().replace(' ', '-'))
        if safe:
            return f"persona:{safe}--{short}"

    return f"persona:{short}"


def _resolve_published_persona(raw_id: str) -> Dict[str, Any]:
    """Resolve an external persona model ID to its project data.

    Checks published status and returns structured 404 if not found/unpublished.
    """
    projects = _get_projects()
    all_projects = projects.list_all_projects()

    for proj in all_projects:
        if proj.get("project_type") != "persona":
            continue
        shared = proj.get("shared_api") or {}
        if not shared.get("enabled"):
            continue
        ext_id = _build_external_id(proj)
        # Match full external_id (without prefix) or raw project_id
        if ext_id == f"persona:{raw_id}" or proj["id"] == raw_id:
            return proj

    # Check if it exists but is unpublished (for better error message)
    for proj in all_projects:
        if proj.get("project_type") != "persona":
            continue
        if proj["id"] == raw_id or _build_external_id(proj) == f"persona:{raw_id}":
            label = (proj.get("persona_agent") or {}).get("label", raw_id)
            raise HTTPException(404, detail={
                "error": {
                    "type": "model_not_available",
                    "code": "persona_unpublished",
                    "message": f"Persona '{label}' is not published to the shared API.",
                    "model": f"persona:{raw_id}",
                    "available_models_hint": True,
                }
            })

    raise HTTPException(404, detail={
        "error": {
            "type": "model_not_available",
            "code": "model_not_found",
            "message": f"No persona found for model 'persona:{raw_id}'.",
            "model": f"persona:{raw_id}",
            "available_models_hint": True,
        }
    })


def _resolve_show_tags(content: str, project_id: str) -> tuple[str, list[Dict[str, Any]]]:
    """Resolve [show:Label] tags in assistant text to attachment metadata.

    Returns (clean_text, attachments_list).
    Reuses the existing media_resolver infrastructure.
    """
    _SHOW_RE = re.compile(r"\[show:([^\]]+)\]")
    labels = _SHOW_RE.findall(content)
    if not labels:
        return content, []

    attachments: list[Dict[str, Any]] = []
    try:
        from .media_resolver import _build_label_index, _lookup_label
        idx = _build_label_index(project_id)
        seen: set[str] = set()
        for lbl in labels:
            lbl = lbl.strip()
            url = None
            if lbl.lower() in ("default", "default look"):
                url = idx.get("default")
            else:
                url = _lookup_label(idx, lbl)
                if not url:
                    url = _lookup_label(idx, lbl.replace(" ", "_"))
            if url and url not in seen:
                import mimetypes
                mime = mimetypes.guess_type(url)[0] or "image/png"
                attachments.append({
                    "type": "image",
                    "name": lbl,
                    "url": url,
                    "mime": mime,
                })
                seen.add(url)
    except Exception as e:
        print(f"[COMPAT] Tag resolution failed for {project_id}: {e}")

    # Strip tags from visible text
    clean = _SHOW_RE.sub("", content)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, attachments


def _build_persona_system_prompt(
    project_data: Dict[str, Any],
    client_type: Optional[str] = None,
) -> str:
    """Build system prompt from persona project data.

    Phase 8: When client_type is 'vr-chatbot', applies VR-aware shaping:
    - Omits detailed wardrobe browsing instructions (VR renders images differently)
    - Prefers compact, voice-friendly language
    - Encourages emotion/mood cues
    """
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

    # Phase 8: VR-aware prompt shaping
    is_vr = client_type and "vr" in client_type.lower()
    if is_vr:
        parts.append(
            "CLIENT CONTEXT: The user is interacting via VR headset with voice input/output.\n"
            "- Keep responses concise and conversational (2-3 sentences ideal).\n"
            "- Prefer natural spoken language — avoid lists, tables, or markdown.\n"
            "- You can still use [show:Label] tags for images — the system handles rendering.\n"
            "- Express emotions naturally — the avatar will reflect your mood.\n"
            "- Do not reference 'scrolling', 'clicking', or web-specific interactions."
        )

    return "\n\n".join(parts) if parts else "You are a helpful assistant."


async def _chat_with_persona_project(
    project_id: str,
    messages: List[ChatMessage],
    temperature: float,
    max_tokens: int,
    client_type: Optional[str] = None,
) -> str:
    """Route a chat request through a persona project, including MCP tools if enabled."""
    projects = _get_projects()
    project_data = projects.get_project_by_id(project_id)
    if not project_data:
        raise HTTPException(404, f"Persona project '{project_id}' not found")

    if project_data.get("project_type") != "persona":
        raise HTTPException(400, f"Project '{project_id}' is not a persona project")

    # Build system prompt from persona — use the full persona context
    # (wardrobe catalog, [show:Label] instructions, identity, rules)
    # so the LLM knows how to handle photo requests via external clients.
    projects_mod = _get_projects()
    system_prompt = projects_mod.build_persona_context(project_id)

    if not system_prompt:
        # Fallback to minimal prompt if build_persona_context returns empty
        system_prompt = _build_persona_system_prompt(project_data, client_type=client_type)

    # Phase 8: Append VR-aware shaping when applicable
    if client_type and "vr" in client_type.lower():
        system_prompt += (
            "\n\nCLIENT CONTEXT: The user is interacting via VR headset with voice input/output.\n"
            "- Keep responses concise and conversational (2-3 sentences ideal).\n"
            "- Prefer natural spoken language — avoid lists, tables, or markdown.\n"
            "- You can still use [show:Label] tags for images — the system handles rendering.\n"
            "- Express emotions naturally — the avatar will reflect your mood.\n"
            "- Do not reference 'scrolling', 'clicking', or web-specific interactions."
        )

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
            _ac = _get_agent_chat()
            provider = _config.DEFAULT_PROVIDER
            if provider == "ollama":
                base_url = _config.OLLAMA_BASE_URL
                model = _config.OLLAMA_MODEL or None
            else:
                base_url = _config.LLM_BASE_URL
                model = _config.LLM_MODEL or None
            result = await _ac.agent_chat(
                user_text=user_message,
                conversation_id=conversation_id,
                project_id=project_id,
                llm_provider=provider,
                llm_base_url=base_url,
                llm_model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                vision_provider=provider,
                vision_base_url=base_url,
                vision_model=model,
                nsfw_mode=False,
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

@router.post("/v1/chat/completions", dependencies=[Depends(require_ollabridge_api_key)])
async def openai_chat_completions(
    req: ChatCompletionRequest,
    x_client_type: Optional[str] = Header(default=None, alias="X-Client-Type"),
    include_media: Optional[str] = Header(default=None, alias="X-Include-Media"),
) -> Any:
    """OpenAI-compatible chat completions endpoint.

    Routes to HomePilot personas via model naming:
      - model="persona:<project_id>"  → persona project with MCP tools
      - model="personality:<id>"      → built-in personality agent
      - model="<personality_id>"      → built-in personality (shorthand)
      - model="default"               → plain LLM passthrough

    Phase 3 — Enriched mode:
      When X-Client-Type header is present or X-Include-Media is "true",
      the response includes optional x_attachments and x_directives fields
      alongside the standard OpenAI-compatible response.
    """
    if not _compat_enabled:
        raise HTTPException(503, "Persona API is disabled. Enable it in Settings > OllaBridge Gateway.")

    if req.stream:
        raise HTTPException(501, "Streaming is not yet supported for persona endpoints")

    t0 = time.time()
    model_type, model_id = _parse_model(req.model)

    temperature = req.temperature if req.temperature is not None else 0.7
    max_tokens = req.max_tokens if req.max_tokens is not None else 800

    # Track the resolved project_id for enriched mode
    resolved_project_id: Optional[str] = None

    if model_type == "persona":
        project_data = _resolve_published_persona(model_id)
        resolved_project_id = project_data["id"]
        content = await _chat_with_persona_project(
            project_data["id"], req.messages, temperature, max_tokens,
            client_type=x_client_type,
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

    # --- Phase 3: Enriched response mode ---
    # Resolve [show:Label] tags into structured attachments when a
    # bridge-aware client is calling (X-Client-Type present or include_media).
    enriched = bool(x_client_type) or (include_media or "").lower() in ("true", "1", "yes")
    x_attachments: list[Dict[str, Any]] = []
    x_directives: Dict[str, Any] = {}

    if enriched and resolved_project_id and "[show:" in content:
        content, x_attachments = _resolve_show_tags(content, resolved_project_id)

    # Safety net: LLM talked about showing a photo but forgot the [show:] tag.
    # Detect "here I am", "here's my look", etc. and inject the best-match photo.
    # Phase 3B: angle-aware fallback — check user's request for angle keywords
    # (back, front, left, right, turn around) and inject the correct view.
    if enriched and resolved_project_id and not x_attachments:
        _photo_cue = re.search(
            r"here(?:'s| is| are)|current look|my photo|take a look|have a look|"
            r"let me show|showing you|this is me|check.?this|here i am",
            content, re.IGNORECASE,
        )
        if _photo_cue:
            try:
                from .media_resolver import _build_label_index, _lookup_label
                idx = _build_label_index(resolved_project_id)

                # --- Angle-aware fallback ---
                # Check user's last message for angle/view keywords and try to
                # match a view-pack angle from the label index.
                _user_msgs = [m for m in req.messages if m.role == "user"]
                _user_text = _user_msgs[-1].content.lower() if _user_msgs else ""

                _angle_map = {
                    "back": "Back",
                    "behind": "Back",
                    "rear": "Back",
                    "turn around": "Back",
                    "from behind": "Back",
                    "front": "Front",
                    "facing me": "Front",
                    "left": "Left",
                    "right": "Right",
                    "side": "Left",
                }
                _detected_angle = None
                for _kw, _ang in _angle_map.items():
                    if _kw in _user_text:
                        _detected_angle = _ang
                        break

                _fallback_url = None
                _fallback_name = "Default Look"
                _fallback_reason = "default"

                # Collect base outfit labels (skip angle variants, Default, Portrait)
                _outfit_labels = []
                for key in idx:
                    if key.startswith("label:"):
                        _lbl = key[len("label:"):]
                        if any(_lbl.endswith(f" {a}") for a in ("Front", "Back", "Left", "Right")):
                            continue
                        if _lbl.lower() in ("default look", "portrait"):
                            continue
                        _outfit_labels.append(_lbl)

                # Step 1: Combined outfit + angle (e.g. "show me your lingerie back")
                # Match the specific outfit's angle, not just any angle.
                if _detected_angle:
                    for _lbl in _outfit_labels:
                        if _lbl.lower() in _user_text:
                            _combined = f"{_lbl} {_detected_angle}"
                            _combined_url = _lookup_label(idx, _combined)
                            if _combined_url:
                                _fallback_url = _combined_url
                                _fallback_name = _combined
                                _fallback_reason = "angle"
                                break

                # Step 2: Angle-only match (e.g. "show me your back")
                if not _fallback_url and _detected_angle:
                    _angle_suffix = f" {_detected_angle}"
                    for key, url in idx.items():
                        if key.startswith("label:") and key.endswith(_angle_suffix):
                            _fallback_url = url
                            _fallback_name = key[len("label:"):]
                            _fallback_reason = "angle"
                            break

                # Step 3: Outfit label match (e.g. "show me your lingerie")
                if not _fallback_url:
                    for _lbl in _outfit_labels:
                        if _lbl.lower() in _user_text:
                            url = _lookup_label(idx, _lbl)
                            if url:
                                _fallback_url = url
                                _fallback_name = _lbl
                                _fallback_reason = "outfit"
                                break

                # Step 3: Fall back to default
                if not _fallback_url:
                    _fallback_url = idx.get("default")

                if _fallback_url:
                    import mimetypes
                    mime = mimetypes.guess_type(_fallback_url)[0] or "image/png"
                    x_attachments = [{
                        "type": "image",
                        "name": _fallback_name,
                        "url": _fallback_url,
                        "mime": mime,
                    }]
                    if _fallback_reason == "angle":
                        print(f"[COMPAT] photo-fallback: LLM forgot [show:] tag, injecting angle photo ({_fallback_name})")
                    elif _fallback_reason == "outfit":
                        print(f"[COMPAT] photo-fallback: LLM forgot [show:] tag, injecting outfit photo ({_fallback_name})")
                    else:
                        print(f"[COMPAT] photo-fallback: LLM forgot [show:] tag, injecting default photo")
            except Exception as e:
                print(f"[COMPAT] photo-fallback failed: {e}")

    print(f"[COMPAT] model={req.model} latency={latency_ms}ms content_len={len(content)} enriched={enriched} attachments={len(x_attachments)}")

    response_data: Dict[str, Any] = ChatCompletionResponse(
        id=f"homepilot-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=req.model,
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(role="assistant", content=content),
            )
        ],
    ).model_dump()

    # Append enriched fields only when active and present
    if enriched and x_attachments:
        response_data["x_attachments"] = x_attachments
    if enriched and x_directives:
        response_data["x_directives"] = x_directives

    return response_data


@router.get("/v1/models", dependencies=[Depends(require_ollabridge_api_key)])
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
        display_name = agent.id.replace("_", " ").title()
        models.append(ModelObject(
            id=f"personality:{agent.id}",
            name=display_name,
            created=now,
            owned_by="homepilot-personality",
        ))

    # Persona projects (only those published via shared_api)
    try:
        projects = _get_projects()
        all_projects = projects.list_all_projects()
        for proj in all_projects:
            if proj.get("project_type") != "persona":
                continue
            shared = proj.get("shared_api") or {}
            if not shared.get("enabled"):
                continue
            external_id = _build_external_id(proj)
            pa = proj.get("persona_agent") or {}
            label = pa.get("label") or proj.get("name") or external_id
            models.append(ModelObject(
                id=external_id,
                name=label,
                created=now,
                owned_by="homepilot-persona",
            ))
    except Exception as e:
        print(f"[COMPAT] Error listing persona projects: {e}")

    return ModelListResponse(data=models)
