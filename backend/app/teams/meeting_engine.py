# backend/app/teams/meeting_engine.py
"""
Meeting engine — orchestrates persona responses in a meeting room.

Given a meeting room and a human message, the engine:
  1. Adds the human message to the shared transcript
  2. For each persona participant (in turn order):
     a. Builds a prompt with persona's full identity + shared context
     b. Optionally injects relevant knowledge-base context
     c. Calls the LLM
     d. Adds the persona's response to the shared transcript
  3. Returns all new messages

Each persona carries their full project experience into the meeting:
  - Identity: name, role, tone, persona_class, description
  - Training: system_prompt / instructions
  - Knowledge base: RAG-retrieved context relevant to the conversation
  - Meeting awareness: other participants, agenda, conversation history
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("homepilot.teams.meeting_engine")

# Default maximum messages to include in the shared context window.
# Can be overridden per-room via room.policy.memory_depth.
MAX_CONTEXT_MESSAGES = 50
# Maximum knowledge-base chunks to inject per persona per turn
MAX_KNOWLEDGE_CHUNKS = 3


# ── Knowledge base integration (optional, graceful fallback) ──────────────


def _query_persona_knowledge(
    project_id: str,
    query: str,
    n_results: int = MAX_KNOWLEDGE_CHUNKS,
) -> str:
    """
    Query a persona's knowledge base for context relevant to the conversation.

    Returns a formatted string of relevant chunks, or empty string if
    knowledge base is unavailable or empty.
    """
    try:
        from ..projects import RAG_ENABLED
        if not RAG_ENABLED:
            return ""

        from ..vectordb import query_project_knowledge, get_project_document_count

        # Skip if persona has no indexed documents
        if get_project_document_count(project_id) == 0:
            return ""

        results = query_project_knowledge(project_id, query, n_results=n_results)
        if not results:
            return ""

        chunks: List[str] = []
        for r in results:
            content = r.get("content", "").strip()
            source = (r.get("metadata") or {}).get("source", "")
            if content:
                label = f"[{source}] " if source else ""
                chunks.append(f"  {label}{content}")

        if not chunks:
            return ""

        return (
            "\n\nRELEVANT KNOWLEDGE FROM YOUR TRAINING:\n"
            + "\n---\n".join(chunks)
        )
    except Exception as exc:
        logger.debug("Knowledge base query skipped for %s: %s", project_id, exc)
        return ""


# ── Persona prompt builder ────────────────────────────────────────────────


def build_persona_prompt(
    persona_project: Dict[str, Any],
    room: Dict[str, Any],
    other_participants: List[Dict[str, Any]],
    *,
    knowledge_query: str = "",
) -> str:
    """
    Build the full system prompt for a persona in a meeting context.

    Carries the persona's complete project experience:
      - Identity: name, role, tone, persona_class, description
      - Training: system_prompt / instructions
      - Knowledge base: RAG context relevant to the conversation topic
      - Meeting context: room name, agenda, other participants (with roles)
    """
    persona_agent = persona_project.get("persona_agent") or {}
    project_id = persona_project.get("id") or ""

    # ── Persona identity ─────────────────────────────────────────────
    name = persona_project.get("name") or "Persona"
    label = persona_agent.get("label") or name
    role = persona_agent.get("role") or ""
    persona_class = persona_agent.get("persona_class") or ""
    description = persona_project.get("description") or ""
    tone = (persona_agent.get("response_style") or {}).get("tone", "")

    # ── Training / personality ───────────────────────────────────────
    instructions = persona_project.get("instructions") or ""
    system_prompt = persona_agent.get("system_prompt") or instructions

    # ── Meeting context ──────────────────────────────────────────────
    meeting_name = room.get("name") or "Meeting"
    meeting_desc = room.get("description") or ""
    agenda = room.get("agenda") or []

    # Build rich "other participants" list with roles
    others_lines: List[str] = []
    for p in other_participants:
        p_name = p.get("name", "???")
        p_agent = p.get("persona_agent") or {}
        p_role = p_agent.get("role") or p_agent.get("persona_class") or ""
        if p_role:
            others_lines.append(f"  - {p_name} ({p_role})")
        else:
            others_lines.append(f"  - {p_name}")

    # ── Build prompt ─────────────────────────────────────────────────
    lines: List[str] = []

    # Identity block
    lines.append(f'You are "{label}", participating in a team meeting called "{meeting_name}".')
    if role:
        lines.append(f"Your role: {role}")
    if persona_class and persona_class != role:
        lines.append(f"Persona type: {persona_class}")
    if description:
        lines.append(f"About you: {description}")
    if tone:
        lines.append(f"Communication tone: {tone}")
    lines.append("")

    # Other participants
    lines.append("Other participants in this meeting:")
    if others_lines:
        lines.extend(others_lines)
    lines.append("  - A human user (the host)")
    lines.append("")

    # Meeting context
    if meeting_desc:
        lines.append(f"Meeting purpose: {meeting_desc}")
    if agenda:
        lines.append("Agenda:")
        for i, item in enumerate(agenda, 1):
            lines.append(f"  {i}. {item}")
        lines.append("")

    # Training / personality
    if system_prompt:
        lines.append("YOUR PERSONALITY AND EXPERTISE:")
        lines.append(system_prompt)
        lines.append("")

    # Knowledge base context (RAG)
    if knowledge_query and project_id:
        kb_context = _query_persona_knowledge(project_id, knowledge_query)
        if kb_context:
            lines.append(kb_context)
            lines.append("")

    # Meeting behavior rules
    lines.append(
        "MEETING BEHAVIOR:\n"
        "- Respond naturally as yourself — stay in character with your personality and expertise.\n"
        "- Keep responses concise and relevant to the current topic.\n"
        "- Address other participants by name when appropriate.\n"
        "- Draw on your specific knowledge and experience when contributing.\n"
        "- You can agree, disagree, add information, ask questions, or build on others' ideas.\n"
        "- If a topic is outside your expertise, acknowledge it and defer to the right participant.\n"
        "\n"
        "INTER-PARTICIPANT COMMUNICATION:\n"
        "- When the host asks you to speak to, tell, teach, or address another participant, "
        "speak DIRECTLY TO that participant — use their name and address them in second person.\n"
        "- When another participant says something, you may respond to them directly — "
        "you are all in the same room and can hear each other.\n"
        "- React to what other participants actually said — quote or reference their words.\n"
        "- Do NOT address everything to the host. This is a group conversation.\n"
        "- You may ask other participants questions, respond to their ideas, or build on them."
    )

    return "\n".join(lines)


def build_chat_messages(
    room: Dict[str, Any],
    persona_system_prompt: str,
    *,
    current_persona_id: str = "",
) -> List[Dict[str, str]]:
    """Build the messages array for an LLM call from the meeting transcript.

    Key design: only this persona's own past messages get ``role: assistant``.
    Messages from the human AND from other personas both get ``role: user``
    so the LLM treats them as input from other speakers — not its own words.
    This is what allows personas to genuinely respond to each other.
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": persona_system_prompt},
    ]

    # Add recent transcript as conversation history.
    # Context depth is configurable via room.policy.memory_depth.
    ctx_depth = int((room.get("policy") or {}).get("memory_depth", MAX_CONTEXT_MESSAGES))
    ctx_depth = max(5, min(200, ctx_depth))  # clamp to sensible range
    recent = (room.get("messages") or [])[-ctx_depth:]
    for msg in recent:
        sender = msg.get("sender_name") or "Unknown"
        sender_id = msg.get("sender_id") or ""
        content = msg.get("content") or ""

        # Only THIS persona's own past messages are "assistant"; everything
        # else (human + other personas) is "user" so the LLM engages with it.
        if sender_id == current_persona_id and current_persona_id:
            messages.append({"role": "assistant", "content": content})
        else:
            messages.append({"role": "user", "content": f"[{sender}]: {content}"})

    return messages


def _recent_conversation_query(room: Dict[str, Any], k: int = 3) -> str:
    """Extract a knowledge-base query from the most recent messages."""
    msgs = room.get("messages") or []
    recent = msgs[-k:]
    parts = [m.get("content", "") for m in recent if m.get("content")]
    return " ".join(parts)[-500:]  # cap at 500 chars for embedding


async def run_persona_turn(
    persona_project: Dict[str, Any],
    room: Dict[str, Any],
    all_participants: List[Dict[str, Any]],
    llm_fn,
) -> Dict[str, Any]:
    """Run a single persona's turn: build prompt, call LLM, return message.

    The persona carries their full project experience:
      - System prompt / personality / instructions
      - Role, tone, persona_class, description
      - Knowledge base (RAG retrieval from their project documents)

    Args:
        persona_project: The persona's full project data
        room: The meeting room (with messages)
        all_participants: All persona projects in the meeting
        llm_fn: Async callable(messages) -> str  (LLM inference function)

    Returns:
        A message dict ready to be appended to the room.
    """
    persona_id = persona_project.get("id") or "unknown"
    persona_name = persona_project.get("name") or "Persona"

    other = [p for p in all_participants if p.get("id") != persona_id]

    # Build knowledge query from recent conversation for RAG retrieval
    knowledge_query = _recent_conversation_query(room)

    system_prompt = build_persona_prompt(
        persona_project, room, other, knowledge_query=knowledge_query,
    )
    chat_messages = build_chat_messages(
        room, system_prompt, current_persona_id=persona_id,
    )

    try:
        response_text = await llm_fn(chat_messages)
    except Exception as exc:
        logger.error("LLM call failed for persona %s: %s", persona_name, exc)
        response_text = f"*{persona_name} is thinking...*"

    return {
        "id": str(uuid.uuid4()),
        "sender_id": persona_id,
        "sender_name": persona_name,
        "content": response_text,
        "role": "assistant",
        "tools_used": [],
        "timestamp": time.time(),
    }


async def run_meeting_turn(
    room: Dict[str, Any],
    human_message: str,
    human_name: str,
    participant_projects: List[Dict[str, Any]],
    llm_fn,
) -> List[Dict[str, Any]]:
    """Run a complete meeting turn: human message + all persona responses.

    Args:
        room: The meeting room data
        human_message: What the human said
        human_name: Display name for the human
        participant_projects: All persona projects participating
        llm_fn: Async callable(messages) -> str

    Returns:
        List of all new messages (human + each persona response).
    """
    new_messages: List[Dict[str, Any]] = []

    # 1. Add human message
    human_msg = {
        "id": str(uuid.uuid4()),
        "sender_id": "human",
        "sender_name": human_name,
        "content": human_message,
        "role": "user",
        "tools_used": [],
        "timestamp": time.time(),
    }
    room.setdefault("messages", []).append(human_msg)
    new_messages.append(human_msg)

    # 2. Each persona responds in order
    turn_mode = room.get("turn_mode", "round-robin")

    if turn_mode == "round-robin":
        for project in participant_projects:
            msg = await run_persona_turn(project, room, participant_projects, llm_fn)
            room["messages"].append(msg)
            new_messages.append(msg)

    return new_messages


# ── Additive: run *only* persona responses (human message already in room) ──


async def run_persona_responses(
    room: Dict[str, Any],
    participant_projects: List[Dict[str, Any]],
    llm_fn,
) -> List[Dict[str, Any]]:
    """Run only persona responses — the human message is already in the transcript.

    Use this from the ``/run-turn`` endpoint where ``/message`` was called first.

    Args:
        room: The meeting room (messages list already contains the human msg)
        participant_projects: All persona projects participating
        llm_fn: Async callable(messages) -> str

    Returns:
        List of new persona messages (no human message included).
    """
    new_messages: List[Dict[str, Any]] = []
    turn_mode = room.get("turn_mode", "round-robin")

    if turn_mode == "round-robin":
        for project in participant_projects:
            msg = await run_persona_turn(project, room, participant_projects, llm_fn)
            room.setdefault("messages", []).append(msg)
            new_messages.append(msg)

    # free-form / moderated — same as round-robin for now; extended later
    elif turn_mode in ("free-form", "moderated"):
        for project in participant_projects:
            msg = await run_persona_turn(project, room, participant_projects, llm_fn)
            room.setdefault("messages", []).append(msg)
            new_messages.append(msg)

    return new_messages
