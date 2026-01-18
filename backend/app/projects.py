"""
Project memory system for HomePilot
Provides scoped context for project-based conversations
"""
from typing import Any, Dict, List, Optional
from .llm import chat as llm_chat
from .storage import add_message, get_recent


async def run_project_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Project mode: Chat with project-scoped context

    TODO: Implement project context injection from database
    For now, behaves like regular chat with project_id tracking

    Returns:
        {
            "type": "project",
            "conversation_id": str,
            "project_id": str,
            "text": str,
            "media": dict | None
        }
    """
    message = payload.get("message", "").strip()
    conversation_id = payload.get("conversation_id", "")
    project_id = payload.get("project_id", "default")
    provider = payload.get("provider", "openai_compat")

    if not message:
        return {
            "type": "project",
            "conversation_id": conversation_id,
            "project_id": project_id,
            "text": "Please provide a message.",
            "media": None
        }

    # Add user message to storage
    add_message(conversation_id, "user", message)

    # Get recent conversation history
    history = get_recent(conversation_id, limit=24)

    # TODO: Inject project context from database
    # For now, use basic system prompt
    system = f"""You are HomePilot, an AI assistant helping with project: {project_id}.

You have access to the project's context and history. Be helpful, concise, and relevant to the project."""

    messages = [{"role": "system", "content": system}]
    for role, content in history:
        messages.append({"role": role, "content": content})

    try:
        response = await llm_chat(
            messages,
            provider=provider,
            temperature=0.7,
            max_tokens=900
        )

        text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        text = text.strip() or "Could not generate response."

        # Add assistant message to storage
        add_message(conversation_id, "assistant", text)

        return {
            "type": "project",
            "conversation_id": conversation_id,
            "project_id": project_id,
            "text": text,
            "media": None
        }

    except Exception as e:
        error_text = f"Error in project chat: {str(e)}"
        add_message(conversation_id, "assistant", error_text)
        return {
            "type": "project",
            "conversation_id": conversation_id,
            "project_id": project_id,
            "text": error_text,
            "media": None
        }
