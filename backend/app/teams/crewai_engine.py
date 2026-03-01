# backend/app/teams/crewai_engine.py
"""
CrewAI-based workflow engine for HomePilot Teams.

Replaces the custom stage runner (``crew_engine.py``) with real CrewAI
orchestration primitives while keeping HomePilot's room state model,
Play Mode tick loop, and persona system intact.

Design choices:
  - **One Agent + one Task per tick**: preserves watchable, turn-by-turn
    progression for Play Mode.
  - **Pydantic structured output** via ``output_pydantic`` replaces
    brittle regex section extraction.
  - **asyncio.to_thread** bridges CrewAI's sync ``kickoff()`` with
    FastAPI's async world.
  - **Existing room.state.crew** shape is reused so the UI and legacy
    engine can coexist.
  - **Telemetry disabled** by default (no outbound traffic).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from crewai import Agent, Task, Crew, Process

from .. import projects
from . import rooms
from .crew_profiles import get_profile
from .crewai_llm import make_crewai_llm
from .crewai_outputs import output_model_for_profile, render_output
from .meeting_engine import build_persona_prompt, _recent_conversation_query
from .orchestrator import ensure_defaults
from .participants_resolver import resolve_participants

from ..config import TEAMS_CREWAI_PROCESS, TEAMS_CREWAI_MEMORY

logger = logging.getLogger("homepilot.teams.crewai_engine")


# ── Telemetry guard + logging setup ──────────────────────────────────

def _disable_telemetry() -> None:
    """Disable CrewAI / OpenTelemetry phone-home for production."""
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")


_CREWAI_LOGGING_CONFIGURED = False


def _setup_crewai_logging() -> None:
    """Enable CrewAI's native logging with colored output.

    Sets up Python logging for the ``crewai`` namespace so that
    Agent / Task / Crew lifecycle events are visible in the backend console
    with ANSI color codes for readability.
    """
    global _CREWAI_LOGGING_CONFIGURED
    if _CREWAI_LOGGING_CONFIGURED:
        return
    _CREWAI_LOGGING_CONFIGURED = True

    # ANSI color codes
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    class CrewAIColorFormatter(logging.Formatter):
        LEVEL_COLORS = {
            logging.DEBUG: CYAN,
            logging.INFO: GREEN,
            logging.WARNING: YELLOW,
        }

        def format(self, record: logging.LogRecord) -> str:
            color = self.LEVEL_COLORS.get(record.levelno, RESET)
            prefix = f"{BOLD}{color}[CREWAI]{RESET} {color}"
            msg = super().format(record)
            return f"{prefix}{msg}{RESET}"

    handler = logging.StreamHandler()
    handler.setFormatter(
        CrewAIColorFormatter("%(levelname)s %(name)s: %(message)s")
    )

    for name in ("crewai", "crewai.agent", "crewai.task", "crewai.crew"):
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        log.addHandler(handler)
        log.propagate = False

    logger.info(
        "%s%s[CREWAI] Colored logging enabled for crewai.*%s",
        BOLD, GREEN, RESET,
    )


# ── Speaker selection (same logic as legacy engine) ────────────────────

def _pick_speaker_for_stage(
    participants: List[Dict[str, Any]],
    preferred_tags: List[str],
    last_speaker: Optional[str],
    fallback_index: int = 0,
) -> str:
    """Return the ``persona_id`` of the best speaker for a stage.

    Scores each participant by the number of matching role tags, avoids
    repeating the last speaker on a tie, falls back to round-robin.
    """
    tag_set = {t.lower() for t in (preferred_tags or [])}

    scored: List[tuple] = []
    for p in participants:
        p_tags = {t.lower() for t in p.get("role_tags", [])}
        score = len(p_tags & tag_set) if tag_set else 0
        scored.append((score, p["persona_id"]))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Among top-scored, prefer someone other than last speaker
    top_score = scored[0][0] if scored else 0
    top_pids = [pid for sc, pid in scored if sc == top_score]

    # If no tags matched at all, fall back to round-robin
    if top_score == 0:
        return participants[fallback_index % len(participants)]["persona_id"]

    if len(top_pids) > 1 and last_speaker in top_pids:
        top_pids.remove(last_speaker)

    if top_pids:
        return top_pids[0]

    # Pure round-robin fallback
    return participants[fallback_index % len(participants)]["persona_id"]


# ── Context builder ────────────────────────────────────────────────────

def _build_task_context(
    room: Dict[str, Any],
    crew_state: Dict[str, Any],
    stage_title: str,
) -> str:
    """Compose the context block injected into CrewAI Task description."""
    topic = room.get("topic") or room.get("description") or ""
    agenda = room.get("agenda") or []
    draft = crew_state.get("draft") or {}
    checklist = crew_state.get("checklist") or {}

    parts = [f"TOPIC:\n{topic}"]

    if agenda:
        parts.append("AGENDA:\n" + "\n".join(f"- {a}" for a in agenda))

    parts.append(f"CURRENT STAGE: {stage_title}")

    if checklist:
        cl_lines = "\n".join(f"- {k}: {'done' if v else 'todo'}" for k, v in checklist.items())
        parts.append(f"PROGRESS CHECKLIST:\n{cl_lines}")

    if draft:
        draft_lines = "\n".join(f"[{k}]\n{v[:300]}" for k, v in draft.items())
        parts.append(f"WORK-IN-PROGRESS (prior stage outputs):\n{draft_lines}")

    return "\n\n".join(parts).strip()


# ── Default checklist (mirrors legacy engine) ──────────────────────────

def _default_checklist(profile_id: str) -> Dict[str, bool]:
    """Create an empty checklist from the profile's stages."""
    profile = get_profile(profile_id)
    if not profile:
        return {}
    return {stage.id: False for stage in profile.stages}


# ── Main entry point ───────────────────────────────────────────────────

async def run_crew_turn(
    *,
    room_id: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    max_concurrent: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute exactly ONE workflow stage step using CrewAI.

    Maintains the same return shape as the legacy ``crew_engine.run_crew_turn``
    so routes, Play Mode, and frontend work unchanged.
    """
    _disable_telemetry()
    _setup_crewai_logging()
    t0 = time.time()

    # ── Load room & validate ───────────────────────────────────────────
    room = rooms.get_room(room_id)
    if not room:
        raise ValueError(f"Room not found: {room_id}")

    ensure_defaults(room)
    policy = room.get("policy") or {}
    crew_policy = policy.get("crew") or {}
    profile_id = crew_policy.get("profile_id") or "task_planner_v1"
    profile = get_profile(profile_id)
    if not profile:
        raise ValueError(f"Unknown workflow profile: {profile_id}")

    # ── Resolve participants ───────────────────────────────────────────
    participants = resolve_participants(room.get("participant_ids") or [])
    if not participants:
        raise ValueError("No valid participants for room")

    # ── Initialise / resume crew state ─────────────────────────────────
    state = room.get("state") or {}
    crew_state = state.get("crew") or {}
    if not crew_state.get("run_id"):
        crew_state = {
            "run_id": str(uuid.uuid4()),
            "stage_index": 0,
            "current_stage": profile.stages[0].id,
            "checklist": _default_checklist(profile_id),
            "draft": {},
            "progress": {
                "novelty_scores": [],
                "no_progress_count": 0,
                "last_update_ts": time.time(),
                "last_reason": "",
            },
            "meta": {"fallback_index": 0, "last_speaker": None},
        }

    stage_index = int(crew_state.get("stage_index", 0))

    # Already complete?
    if stage_index >= len(profile.stages):
        return {
            "room": room,
            "new_messages": [],
            "speakers": [],
            "engine_debug": {
                "engine": "crewai",
                "profile_id": profile_id,
                "complete": True,
                "runtime_ms": int((time.time() - t0) * 1000),
            },
        }

    stage = profile.stages[stage_index]

    # ── Pick speaker ───────────────────────────────────────────────────
    meta = crew_state.get("meta") or {}
    speaker_id = _pick_speaker_for_stage(
        participants=participants,
        preferred_tags=stage.preferred_tags,
        last_speaker=meta.get("last_speaker"),
        fallback_index=meta.get("fallback_index", 0),
    )

    proj = projects.get_project_by_id(speaker_id)
    if not proj:
        raise ValueError(f"Speaker project not found: {speaker_id}")

    # ── Build CrewAI primitives ────────────────────────────────────────
    llm = make_crewai_llm(provider=provider, model=model, base_url=base_url)

    # Build persona backstory from meeting engine
    all_projects = [projects.get_project_by_id(p["persona_id"]) for p in participants]
    all_projects = [p for p in all_projects if p]
    others = [p for p in all_projects if p.get("id") != speaker_id]
    knowledge_query = _recent_conversation_query(room)
    backstory = build_persona_prompt(proj, room, others, knowledge_query=knowledge_query)

    agent = Agent(
        role=proj.get("name") or "Team Member",
        goal=f"Contribute to the team deliverable for stage: {stage.title}",
        backstory=backstory,
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    # Context for the task
    task_context = _build_task_context(room, crew_state, stage.title)
    max_w = profile.output_contract.max_words
    description = (
        f"{task_context}\n\n"
        f"STAGE INSTRUCTIONS:\n{stage.instruction}\n\n"
        "This is a team meeting, not a chatbot. "
        "Respond like a real person in a meeting: 1-3 sentences max. "
        "Be concrete and specific — no long explanations or recaps. "
        f"Hard limit: {max_w} words."
    )

    # Structured output model (optional — depends on profile)
    out_model = output_model_for_profile(profile_id)
    task_kwargs: Dict[str, Any] = {
        "description": description,
        "agent": agent,
    }
    if out_model is not None:
        task_kwargs["output_pydantic"] = out_model
        task_kwargs["expected_output"] = (
            f"Return a structured response with fields: "
            f"{', '.join(out_model.model_fields.keys())}."
        )
    else:
        task_kwargs["expected_output"] = (
            "A helpful, specific response about the topic."
        )

    task = Task(**task_kwargs)

    process = (
        Process.hierarchical
        if TEAMS_CREWAI_PROCESS == "hierarchical"
        else Process.sequential
    )

    crew_kwargs: Dict[str, Any] = {
        "agents": [agent],
        "tasks": [task],
        "process": process,
        "verbose": False,
    }
    if TEAMS_CREWAI_MEMORY:
        crew_kwargs["memory"] = True

    crew = Crew(**crew_kwargs)

    # ── Execute (sync kickoff in thread to keep FastAPI responsive) ────
    logger.info(
        "[CREWAI] Kicking off stage=%s speaker=%s profile=%s",
        stage.id, speaker_id, profile_id,
    )
    try:
        result = await asyncio.to_thread(crew.kickoff)
    except Exception as exc:
        logger.error("[CREWAI] kickoff failed: %s", exc)
        # Fall back to raw error message rather than crashing
        result = f"I need a moment to gather my thoughts on this. (Error: {exc})"

    # ── Extract output ─────────────────────────────────────────────────
    raw_text = str(result).strip()
    structured_obj = None

    try:
        task_output = getattr(task, "output", None)
        if task_output is not None:
            pydantic_out = getattr(task_output, "pydantic", None)
            if pydantic_out is not None:
                structured_obj = pydantic_out
            elif hasattr(task_output, "raw") and task_output.raw:
                raw_text = task_output.raw.strip()
    except Exception:
        pass

    final_text = render_output(profile_id, structured_obj or raw_text)
    llm_ms = int((time.time() - t0) * 1000)
    logger.info("[CREWAI] Response (%dms): %.200s...", llm_ms, final_text)

    # ── Update crew state ──────────────────────────────────────────────
    checklist = crew_state.get("checklist") or {}
    draft = crew_state.get("draft") or {}

    # Mark checklist items as done if the structured output has them
    if structured_obj and out_model:
        for field_name in out_model.model_fields:
            val = getattr(structured_obj, field_name, None)
            if val:
                key = field_name.lower()
                if key in checklist:
                    # Non-empty list or non-empty string counts as done
                    if isinstance(val, list):
                        checklist[key] = len(val) > 0
                    elif isinstance(val, str):
                        checklist[key] = bool(val.strip() and val.strip().lower() not in ("n/a", "none", ""))
                    else:
                        checklist[key] = True

    # Store draft by stage id
    draft[stage.id] = final_text
    crew_state["draft"] = draft
    crew_state["checklist"] = checklist

    # Advance to next stage
    next_index = stage_index + 1
    crew_state["stage_index"] = next_index
    crew_state["current_stage"] = (
        profile.stages[next_index].id if next_index < len(profile.stages) else stage.id
    )

    # Update meta
    meta["last_speaker"] = speaker_id
    meta["fallback_index"] = meta.get("fallback_index", 0) + 1
    crew_state["meta"] = meta

    # Progress tracking
    progress = crew_state.get("progress") or {}
    progress["last_update_ts"] = time.time()
    progress["last_reason"] = "crewai_ok"
    crew_state["progress"] = progress

    is_complete = next_index >= len(profile.stages)

    # ── Persist message + state to room ────────────────────────────────
    msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "sender_id": speaker_id,
        "sender_name": proj.get("name", "Team Member"),
        "content": final_text,
        "timestamp": time.time(),
    }
    messages = room.get("messages") or []
    messages.append(msg)

    state["crew"] = crew_state
    rooms.update_room(room_id, {
        "messages": messages,
        "state": state,
    })

    # Reload room after update
    room = rooms.get_room(room_id) or room

    return {
        "room": room,
        "new_messages": [msg],
        "speakers": [speaker_id],
        "engine_debug": {
            "engine": "crewai",
            "profile_id": profile_id,
            "stage": stage.id,
            "stage_index": stage_index,
            "speaker_id": speaker_id,
            "validation": {"ok": True, "reason": "crewai_ok"},
            "complete": is_complete,
            "runtime_ms": llm_ms,
        },
    }
