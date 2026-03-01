# backend/app/teams/routes.py
"""
FastAPI router for /v1/teams/* endpoints.

CRUD for meeting rooms + send-message (triggers persona turns).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..auth import require_api_key
from .. import projects
from . import rooms
from .meeting_engine import (
    run_persona_responses,
    build_persona_prompt,
    build_chat_messages,
    _recent_conversation_query,
)
from .llm_adapter import llm_text, LLMConnectionError
from .locks import get_room_lock
from .orchestrator import run_reactive_step, run_initiative_step, preview_next_turn
from .participants_resolver import resolve_participants
from .continuation import generate_smart_trigger
from .crew_engine import run_crew_turn
from .crew_profiles import list_profiles as list_workflow_profiles
from .play_mode import (
    start_play_mode,
    stop_play_mode,
    pause_play_mode,
    resume_play_mode,
    toggle_facilitator,
    get_play_status,
)

logger = logging.getLogger("homepilot.teams.routes")

router = APIRouter(prefix="/v1/teams", tags=["teams"])


# ── Request / Response models ─────────────────────────────────────────────


class CreateRoomIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=1000)
    participant_ids: List[str] = Field(default_factory=list)
    turn_mode: str = Field("reactive")
    agenda: List[str] = Field(default_factory=list)
    topic: Optional[str] = Field(None, description="Initial topic (defaults to description if omitted)")


class UpdateRoomIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    turn_mode: Optional[str] = None
    topic: Optional[str] = None
    agenda: Optional[List[str]] = None
    policy: Optional[Dict[str, Any]] = None


class ParticipantIn(BaseModel):
    persona_id: str


class SendMessageIn(BaseModel):
    content: str = Field(..., min_length=1)
    sender_name: str = Field("You")


class RunTurnIn(BaseModel):
    """Body for POST /rooms/{id}/run-turn."""
    human_name: str = Field("You")
    # LLM settings (passed from frontend Enterprise Settings)
    provider: Optional[str] = Field(None, description="LLM provider override (e.g. 'ollama')")
    model: Optional[str] = Field(None, description="Model override (e.g. 'llama3:8b')")
    base_url: Optional[str] = Field(None, description="Provider base URL override")
    max_concurrent: Optional[int] = Field(None, description="Max concurrent LLM calls (1-3)")


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/rooms")
async def create_room(body: CreateRoomIn, _key: str = Depends(require_api_key)):
    """Create a new meeting room."""
    room = rooms.create_room(
        name=body.name,
        description=body.description,
        participant_ids=body.participant_ids,
        turn_mode=body.turn_mode,
        agenda=body.agenda,
        topic=body.topic,
    )
    return room


@router.get("/rooms")
async def list_rooms_endpoint(_key: str = Depends(require_api_key)):
    """List all meeting rooms."""
    return rooms.list_rooms()


@router.get("/rooms/{room_id}")
async def get_room(room_id: str, _key: str = Depends(require_api_key)):
    """Get a single room by ID (includes full transcript)."""
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.put("/rooms/{room_id}")
async def update_room(room_id: str, body: UpdateRoomIn, _key: str = Depends(require_api_key)):
    """Update room metadata (name, description, turn mode, topic, agenda)."""
    updates: Dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.turn_mode is not None:
        updates["turn_mode"] = body.turn_mode
    if body.topic is not None:
        updates["topic"] = body.topic
    if body.agenda is not None:
        updates["agenda"] = body.agenda
    if body.policy is not None:
        updates["policy"] = body.policy

    room = rooms.update_room(room_id, updates)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.delete("/rooms/{room_id}")
async def delete_room(room_id: str, _key: str = Depends(require_api_key)):
    """Delete a meeting room."""
    if not rooms.delete_room(room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    return {"ok": True}


@router.post("/rooms/{room_id}/participants")
async def add_participant(room_id: str, body: ParticipantIn, _key: str = Depends(require_api_key)):
    """Add a persona to a meeting room."""
    room = rooms.add_participant(room_id, body.persona_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.delete("/rooms/{room_id}/participants/{persona_id}")
async def remove_participant(room_id: str, persona_id: str, _key: str = Depends(require_api_key)):
    """Remove a persona from a meeting room."""
    room = rooms.remove_participant(room_id, persona_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.post("/rooms/{room_id}/message")
async def send_message(room_id: str, body: SendMessageIn, _key: str = Depends(require_api_key)):
    """Send a human message to a room.

    Adds the message to the transcript. In a future phase, this will
    also trigger persona turns via the meeting engine.

    Returns the updated room with new messages.
    """
    room = rooms.add_message(
        room_id=room_id,
        sender_id="human",
        sender_name=body.sender_name,
        content=body.content,
        role="user",
    )
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    return room


@router.post("/rooms/{room_id}/run-turn")
async def run_turn(room_id: str, body: RunTurnIn, _key: str = Depends(require_api_key)):
    """Trigger persona turns for the room.

    Call this after ``POST /rooms/{id}/message`` to get persona responses.
    Uses the meeting engine with the configured LLM provider.
    Returns the updated room + the new persona messages.
    """
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Resolve persona projects for every participant
    participant_ids = room.get("participant_ids") or []
    participant_projects: List[Dict[str, Any]] = []
    missing: List[str] = []
    for pid in participant_ids:
        p = projects.get_project_by_id(pid)
        if not p:
            missing.append(pid)
            continue
        participant_projects.append(p)

    if not participant_projects:
        raise HTTPException(
            status_code=400,
            detail="No valid participants in this room"
            + (f" (missing: {', '.join(missing)})" if missing else ""),
        )

    # Build llm_fn with user's provider settings baked in
    _provider = body.provider
    _model = body.model
    _base_url = body.base_url
    _max_concurrent = body.max_concurrent

    async def _llm_fn(messages):
        return await llm_text(
            messages,
            provider=_provider,
            model=_model,
            base_url=_base_url,
            max_concurrent=_max_concurrent,
        )

    # ── Crew workflow engine dispatch (additive) ─────────────────────
    engine = (room.get("policy") or {}).get("engine", "native")
    if engine == "crew":
        lock = get_room_lock(room_id)
        try:
            async with lock:
                result = await run_crew_turn(
                    room_id=room_id,
                    provider=body.provider,
                    model=body.model,
                    base_url=body.base_url,
                    max_concurrent=body.max_concurrent,
                )
            return result
        except LLMConnectionError as exc:
            logger.error("LLM connection failed in run-turn (crew): %s", exc)
            raise HTTPException(status_code=503, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # Branch by turn_mode: initiative uses deterministic queue,
    # legacy/reactive uses run_persona_responses.
    turn_mode = room.get("turn_mode", "reactive")

    if turn_mode == "round-robin":
        # Initiative mode: use orchestrator's deterministic queue
        participants = resolve_participants(participant_ids)
        if not participants:
            raise HTTPException(status_code=400, detail="No valid participants")

        async def generate_fn(pid: str, room_state: Dict[str, Any]) -> str:
            proj = projects.get_project_by_id(pid)
            if not proj:
                return ""
            all_projects = [projects.get_project_by_id(p["persona_id"]) for p in participants]
            all_projects = [p for p in all_projects if p]
            others = [p for p in all_projects if p.get("id") != pid]
            knowledge_query = _recent_conversation_query(room_state)
            system_prompt = build_persona_prompt(proj, room_state, others, knowledge_query=knowledge_query)
            chat_messages = build_chat_messages(room_state, system_prompt, current_persona_id=pid)
            return await llm_text(
                chat_messages, provider=_provider, model=_model,
                base_url=_base_url, max_concurrent=_max_concurrent,
            )

        lock = get_room_lock(room_id)
        try:
            async with lock:
                result = await run_initiative_step(
                    room_id, participants=participants, generate_fn=generate_fn,
                )
        except LLMConnectionError as exc:
            logger.error("LLM connection failed in run-turn (initiative): %s", exc)
            raise HTTPException(status_code=503, detail=str(exc))

        return result
    else:
        # Legacy / reactive fallback: run_persona_responses
        lock = get_room_lock(room_id)
        try:
            async with lock:
                room = rooms.get_room(room_id)
                if not room:
                    raise HTTPException(status_code=404, detail="Room not found")
                new_messages = await run_persona_responses(
                    room=room,
                    participant_projects=participant_projects,
                    llm_fn=_llm_fn,
                )
                rooms.update_room(room_id, {"messages": room.get("messages", [])})
        except LLMConnectionError as exc:
            logger.error("LLM connection failed in run-turn: %s", exc)
            raise HTTPException(status_code=503, detail=str(exc))

        updated = rooms.get_room(room_id)
        return {"room": updated, "new_messages": new_messages}


# ── Orchestrated meeting endpoints (additive) ─────────────────────────────


class ReactIn(BaseModel):
    """Body for POST /rooms/{id}/react."""
    human_name: str = Field("You")
    # LLM settings (passed from frontend Enterprise Settings)
    provider: Optional[str] = Field(None, description="LLM provider override (e.g. 'ollama')")
    model: Optional[str] = Field(None, description="Model override (e.g. 'llama3:8b')")
    base_url: Optional[str] = Field(None, description="Provider base URL override")
    max_concurrent: Optional[int] = Field(None, description="Max concurrent LLM calls (1-3)")


class CallOnIn(BaseModel):
    persona_id: str


@router.post("/rooms/{room_id}/react")
async def react(room_id: str, body: ReactIn, _key: str = Depends(require_api_key)):
    """Run multi-round orchestrated meeting step (intent → hands → selection → generation).

    Call this after ``POST /rooms/{id}/message``.  Only the most relevant
    persona(s) will respond — not everyone.

    Runs up to ``max_rounds_per_event`` rounds (default: 3).  Each round:
      1. Compute intents for all participants
      2. Auto hand-raise for high-confidence personas
      3. Select speakers (redundancy + diversity gates)
      4. Generate responses for selected speakers
    Stops early if no speakers are selected in a round.
    """
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    participant_ids = room.get("participant_ids") or []
    participants = resolve_participants(participant_ids)
    if not participants:
        raise HTTPException(status_code=400, detail="No valid participants")

    # ── Crew workflow engine dispatch (additive) ─────────────────────
    engine = (room.get("policy") or {}).get("engine", "native")
    if engine == "crew":
        lock = get_room_lock(room_id)
        try:
            async with lock:
                result = await run_crew_turn(
                    room_id=room_id,
                    provider=body.provider,
                    model=body.model,
                    base_url=body.base_url,
                    max_concurrent=body.max_concurrent,
                )
            return result
        except LLMConnectionError as exc:
            logger.error("LLM connection failed in react (crew): %s", exc)
            raise HTTPException(status_code=503, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # Find trigger: last human message, or fallback to last message content.
    # This allows "Run Turn" / "Continue" without new human input.
    human_message = ""
    for msg in reversed(room.get("messages", [])):
        if msg.get("sender_id") == "human" and msg.get("role") == "user":
            human_message = (msg.get("content") or "").strip()
            break
    if not human_message:
        # Use last message from anyone (enables continue-without-typing)
        all_msgs = room.get("messages") or []
        if all_msgs:
            human_message = (all_msgs[-1].get("content") or "").strip()
        if not human_message:
            human_message = generate_smart_trigger(room, participants)

    # Capture LLM settings from request body
    _provider = body.provider
    _model = body.model
    _base_url = body.base_url
    _max_concurrent = body.max_concurrent

    # Build a generate function that carries full persona experience + LLM settings
    async def generate_fn(pid: str, room_state: Dict[str, Any]) -> str:
        proj = projects.get_project_by_id(pid)
        if not proj:
            return ""
        all_projects = [
            projects.get_project_by_id(p["persona_id"])
            for p in participants
        ]
        all_projects = [p for p in all_projects if p]
        others = [p for p in all_projects if p.get("id") != pid]

        knowledge_query = _recent_conversation_query(room_state)

        system_prompt = build_persona_prompt(
            proj, room_state, others, knowledge_query=knowledge_query,
        )
        chat_messages = build_chat_messages(
            room_state, system_prompt, current_persona_id=pid,
        )
        return await llm_text(
            chat_messages,
            provider=_provider,
            model=_model,
            base_url=_base_url,
            max_concurrent=_max_concurrent,
        )

    # Multi-round orchestration loop
    # Round 1 uses the human message for intent scoring.
    # Rounds 2+ use the most recent persona message so that other personas
    # can *react* to what was just said (BG3-style companion reactions).
    max_rounds = int((room.get("policy") or {}).get("max_rounds_per_event", 3))
    all_new_messages: list = []
    all_speakers: list = []
    already_spoke: set = set()  # Prevent same persona from responding twice
    final_result: Dict[str, Any] = {}
    trigger_message = human_message

    lock = get_room_lock(room_id)
    try:
        async with lock:
            for _round in range(max_rounds):
                result = await run_reactive_step(
                    room_id,
                    last_human_message=trigger_message,
                    participants=participants,
                    generate_fn=generate_fn,
                    exclude_speakers=already_spoke if already_spoke else None,
                )
                round_msgs = result.get("new_messages", [])
                round_speakers = result.get("speakers", [])

                # Filter out speakers who already spoke in a previous round
                new_speakers = [s for s in round_speakers if s not in already_spoke]
                new_msgs = [m for m in round_msgs if m.get("sender_id") not in already_spoke]

                all_new_messages.extend(new_msgs)
                all_speakers.extend(new_speakers)
                already_spoke.update(round_speakers)
                final_result = result

                # Stop if no NEW speakers were selected this round
                if not new_speakers:
                    break

                # For subsequent rounds, score intent based on what was
                # just said — this lets personas react to each other.
                if new_msgs:
                    trigger_message = new_msgs[-1].get("content", human_message)
    except LLMConnectionError as exc:
        logger.error("LLM connection failed in react: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )

    # Return aggregated result
    final_result["new_messages"] = all_new_messages
    final_result["speakers"] = all_speakers
    return final_result


@router.get("/rooms/{room_id}/intents")
async def get_intents(room_id: str, _key: str = Depends(require_api_key)):
    """Return current intent states + moderation data for UI rendering."""
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return {
        "intents": room.get("intents", {}),
        "hand_raises": room.get("hand_raises", []),
        "muted": room.get("muted", []),
        "called_on": room.get("called_on"),
    }


@router.get("/rooms/{room_id}/preview-turn")
async def preview_turn(room_id: str, _key: str = Depends(require_api_key)):
    """Preview who would speak next (dry-run, no side effects).

    Returns BG3-style initiative order with per-candidate scores and reasons.
    Use this for the "Preview Next Turn" UI before actually running a turn.
    """
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    participant_ids = room.get("participant_ids") or []
    participants = resolve_participants(participant_ids)
    if not participants:
        raise HTTPException(status_code=400, detail="No valid participants")

    # Find trigger message (same logic as /react, with smart continuation)
    trigger = ""
    for msg in reversed(room.get("messages", [])):
        if msg.get("sender_id") == "human" and msg.get("role") == "user":
            trigger = (msg.get("content") or "").strip()
            break
    if not trigger:
        # Use smart trigger for preview too (no injection — preview is read-only)
        trigger = generate_smart_trigger(room, participants)

    try:
        return preview_next_turn(
            room_id,
            trigger_message=trigger,
            participants=participants,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/rooms/{room_id}/moderation/call-on")
async def call_on(room_id: str, body: CallOnIn, _key: str = Depends(require_api_key)):
    """Moderator calls on a specific persona to speak next."""
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    rooms.update_room(room_id, {"called_on": body.persona_id})
    return {"ok": True, "called_on": body.persona_id}


@router.post("/rooms/{room_id}/hand-raise/{persona_id}")
async def toggle_hand_raise(
    room_id: str, persona_id: str, _key: str = Depends(require_api_key),
):
    """Toggle hand-raise for a persona."""
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    hrs = list(room.get("hand_raises") or [])
    if persona_id in hrs:
        hrs = [x for x in hrs if x != persona_id]
    else:
        hrs.append(persona_id)
    rooms.update_room(room_id, {"hand_raises": hrs})
    return {"hand_raises": hrs}


@router.post("/rooms/{room_id}/mute/{persona_id}")
async def toggle_mute(
    room_id: str, persona_id: str, _key: str = Depends(require_api_key),
):
    """Toggle mute for a persona (muted personas are skipped by orchestrator)."""
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    muted = list(room.get("muted") or [])
    if persona_id in muted:
        muted = [x for x in muted if x != persona_id]
    else:
        muted.append(persona_id)
    rooms.update_room(room_id, {"muted": muted})
    return {"muted": muted}


# ── Play Mode (Autonomous AI conversation) ─────────────────────────────────


class PlayModeStartIn(BaseModel):
    """Body for POST /rooms/{id}/play-mode/start."""
    style: str = Field("discussion", description="Conversation style: discussion|debate|roundtable|roleplay|simulation")
    interval_ms: int = Field(3000, ge=1000, le=15000, description="Pause between auto-steps (ms)")
    max_rounds: int = Field(50, ge=0, le=500, description="Max autonomous rounds (0=infinite)")
    show_facilitator: bool = Field(False, description="Show debug facilitator messages")
    # LLM settings
    provider: Optional[str] = Field(None)
    model: Optional[str] = Field(None)
    base_url: Optional[str] = Field(None)
    max_concurrent: Optional[int] = Field(None)


@router.post("/rooms/{room_id}/play-mode/start")
async def start_play(room_id: str, body: PlayModeStartIn, _key: str = Depends(require_api_key)):
    """Start autonomous Play Mode — personas converse without human input."""
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    participant_ids = room.get("participant_ids") or []
    if len(participant_ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 participants for Play Mode")

    # Build generate_fn (same pattern as /react)
    _provider = body.provider
    _model = body.model
    _base_url = body.base_url
    _max_concurrent = max(1, body.max_concurrent or 1)  # enforce max 1 for play mode

    from .meeting_engine import build_persona_prompt, build_chat_messages, _recent_conversation_query

    async def generate_fn(pid: str, room_state: Dict[str, Any]) -> str:
        proj = projects.get_project_by_id(pid)
        if not proj:
            return ""
        all_ids = room_state.get("participant_ids") or []
        all_projects = [projects.get_project_by_id(p) for p in all_ids]
        all_projects = [p for p in all_projects if p]
        others = [p for p in all_projects if p.get("id") != pid]

        knowledge_query = _recent_conversation_query(room_state)
        system_prompt = build_persona_prompt(
            proj, room_state, others, knowledge_query=knowledge_query,
        )
        chat_messages = build_chat_messages(
            room_state, system_prompt, current_persona_id=pid,
        )
        return await llm_text(
            chat_messages,
            provider=_provider,
            model=_model,
            base_url=_base_url,
            max_concurrent=_max_concurrent,
        )

    try:
        pm = start_play_mode(
            room_id,
            generate_fn=generate_fn,
            style=body.style,
            interval_ms=body.interval_ms,
            max_rounds=body.max_rounds,
            show_facilitator=body.show_facilitator,
        )
        return {"ok": True, "play_mode": pm}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rooms/{room_id}/play-mode/stop")
async def stop_play(room_id: str, _key: str = Depends(require_api_key)):
    """Stop Play Mode."""
    pm = stop_play_mode(room_id)
    return {"ok": True, "play_mode": pm}


@router.post("/rooms/{room_id}/play-mode/pause")
async def pause_play(room_id: str, _key: str = Depends(require_api_key)):
    """Pause Play Mode (user wants to intervene)."""
    try:
        pm = pause_play_mode(room_id)
        return {"ok": True, "play_mode": pm}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/rooms/{room_id}/play-mode/resume")
async def resume_play(room_id: str, _key: str = Depends(require_api_key)):
    """Resume paused Play Mode."""
    try:
        pm = resume_play_mode(room_id)
        return {"ok": True, "play_mode": pm}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/rooms/{room_id}/play-mode/toggle-facilitator")
async def toggle_facilitator_endpoint(room_id: str, _key: str = Depends(require_api_key)):
    """Toggle debug facilitator messages visibility."""
    try:
        pm = toggle_facilitator(room_id)
        return {"ok": True, "play_mode": pm}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/rooms/{room_id}/play-mode/status")
async def play_status(room_id: str, _key: str = Depends(require_api_key)):
    """Get current Play Mode status."""
    return get_play_status(room_id)


# ── Shared Documents (Additive) ───────────────────────────────────────────


class AddUrlDocIn(BaseModel):
    url: str = Field(..., min_length=1, max_length=4000)
    title: str = Field("", max_length=400)


@router.get("/rooms/{room_id}/documents")
async def list_documents(room_id: str, _key: str = Depends(require_api_key)):
    """List shared documents for a room."""
    docs = rooms.list_documents(room_id)
    if docs is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return docs


@router.post("/rooms/{room_id}/documents/upload")
async def upload_document(
    room_id: str,
    file: UploadFile = File(...),
    uploaded_by: str = Form("You"),
    _key: str = Depends(require_api_key),
):
    """Upload a shared document to the room (txt/md/pdf/any file)."""
    try:
        content = await file.read()
        out = rooms.add_document_upload(
            room_id,
            filename=file.filename or "document",
            content_bytes=content,
            uploaded_by=uploaded_by,
        )
        if out is None:
            raise HTTPException(status_code=404, detail="Room not found")
        room, doc = out
        return {"room": room, "document": doc}
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))


@router.post("/rooms/{room_id}/documents/url")
async def add_url_document(
    room_id: str, body: AddUrlDocIn, _key: str = Depends(require_api_key),
):
    """Add a URL reference as a shared document."""
    out = rooms.add_document_url(room_id, url=body.url, title=body.title)
    if out is None:
        raise HTTPException(status_code=404, detail="Room not found")
    room, doc = out
    return {"room": room, "document": doc}


@router.get("/rooms/{room_id}/documents/{doc_id}")
async def get_document(
    room_id: str, doc_id: str, _key: str = Depends(require_api_key),
):
    d = rooms.get_document(room_id, doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    return d


@router.get("/rooms/{room_id}/documents/{doc_id}/preview")
async def get_document_preview(
    room_id: str, doc_id: str, _key: str = Depends(require_api_key),
):
    preview = rooms.get_document_preview(room_id, doc_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"doc_id": doc_id, "preview": preview}


@router.get("/rooms/{room_id}/documents/{doc_id}/download")
async def download_document(
    room_id: str, doc_id: str, _key: str = Depends(require_api_key),
):
    p = rooms.get_document_file_path(room_id, doc_id)
    if not p:
        raise HTTPException(status_code=404, detail="File not found")
    d = rooms.get_document(room_id, doc_id) or {}
    return FileResponse(path=str(p), filename=d.get("name") or p.name)


@router.delete("/rooms/{room_id}/documents/{doc_id}")
async def delete_document(
    room_id: str, doc_id: str, _key: str = Depends(require_api_key),
):
    room = rooms.delete_document(room_id, doc_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


# ── Workflow Profiles (CrewAI-style) ─────────────────────────────────────


@router.get("/workflow/profiles")
async def get_workflow_profiles(_key: str = Depends(require_api_key)):
    """List available workflow profiles for Crew engine mode."""
    return list_workflow_profiles()


@router.get("/rooms/{room_id}/crew-status")
async def get_crew_status(room_id: str, _key: str = Depends(require_api_key)):
    """Get current Crew workflow status (stage, checklist, progress)."""
    room = rooms.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    state = room.get("state") or {}
    crew_state = state.get("crew") or {}
    engine = (room.get("policy") or {}).get("engine", "native")
    return {
        "engine": engine,
        "active": engine == "crew" and bool(crew_state.get("run_id")),
        "run_id": crew_state.get("run_id"),
        "current_stage": crew_state.get("current_stage"),
        "stage_index": crew_state.get("stage_index"),
        "checklist": crew_state.get("checklist", {}),
        "progress": crew_state.get("progress", {}),
    }
