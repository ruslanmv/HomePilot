# backend/app/teams/crew_engine.py
"""
Crew workflow engine for Teams — "Task Collaboration Mode".

When room.policy.engine == "crew", this module drives structured,
stage-based workflow execution instead of free-form conversation.

Design principles:
  - Additive / non-destructive: native engines untouched unless enabled
  - Step-based and watchable: one workflow stage step per call
  - Stable: output contract + validators + stop rules prevent echo loops
  - No external dependency: works without the crewai package, using
    HomePilot's existing LLM adapter and meeting engine infrastructure

One "turn" = one workflow step that advances a deliverable.
Outputs render as normal chat messages from personas, but orchestration
is task-based with validation and progress tracking.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .. import projects
from . import rooms
from .crew_profiles import WorkflowProfile, get_profile
from .meeting_engine import (
    build_chat_messages,
    build_persona_prompt,
    _recent_conversation_query,
)
from .orchestrator import ensure_defaults
from .participants_resolver import resolve_participants
from .llm_adapter import llm_text

logger = logging.getLogger("homepilot.teams.crew_engine")


# ── Token similarity / novelty ────────────────────────────────────────────

_STOP = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "have", "been",
    "were", "will", "your", "youre", "you", "our", "their", "they", "them",
    "what", "when", "where", "which", "about", "would", "could", "should",
    "just", "like", "more", "also", "than", "then", "very", "some", "into",
    "over", "only", "even", "most", "each", "really", "make", "love",
})


def _tok(text: str) -> set:
    words = set(re.findall(r"[a-zA-Z]{3,}", (text or "").lower()))
    return {w for w in words if w not in _STOP}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tok(a), _tok(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


# ── Output contract parsing / validation ──────────────────────────────────

_SECTION_RE = re.compile(r"^\s*([A-Z][A-Z0-9 _-]{2,})\s*:\s*$", re.MULTILINE)


def _extract_sections(text: str) -> Dict[str, str]:
    """Parse structured sections from LLM output.

    Example input::

        PLAN:
        1) Cook dinner at home
        2) Watch a movie

        BUDGET:
        - Groceries: €15
        - Total: €15

    Returns ``{"PLAN": "1) Cook dinner...", "BUDGET": "- Groceries..."}``
    """
    text = (text or "").strip()
    if not text:
        return {}
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return {}
    out: Dict[str, str] = {}
    for i, m in enumerate(matches):
        name = m.group(1).strip().upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[name] = text[start:end].strip()
    return out


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _validate_output(
    *,
    profile: WorkflowProfile,
    text: str,
    budget_limit: Optional[float],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate LLM output: word count and budget only.

    Returns ``(ok, reason, meta)`` where meta includes parsed sections.
    Section headers are NOT required — natural conversation is preferred.
    """
    wc = _word_count(text)
    max_w = int(profile.output_contract.max_words)

    if wc < 10:
        return False, "too_short", {"word_count": wc}

    if wc > max_w:
        return False, f"too_long({wc}>{max_w})", {"word_count": wc}

    # Budget limit check — scan the full text for "Total: €X"
    if budget_limit is not None:
        m = re.search(
            r"total\s*:\s*[€$£]?\s*([0-9]+(?:\.[0-9]+)?)",
            text,
            re.IGNORECASE,
        )
        if m:
            try:
                total = float(m.group(1))
                if total > float(budget_limit) + 1e-6:
                    return (
                        False,
                        "budget_over_limit",
                        {"total": total, "limit": budget_limit},
                    )
            except ValueError:
                pass

    sections = _extract_sections(text)
    return True, "ok", {"word_count": wc, "sections": sections}


# ── Speaker selection for a stage ─────────────────────────────────────────


def _pick_speaker_for_stage(
    *,
    participants: List[Dict[str, Any]],
    preferred_tags: List[str],
    visible_agents: Optional[List[str]],
    last_speaker: Optional[str],
    fallback_index: int,
) -> str:
    """Deterministic speaker selection for a workflow stage.

    Prefers participants whose ``role_tags`` intersect ``preferred_tags``.
    Avoids repeating the last speaker if possible.
    Falls back to round-robin on the participant list.
    """
    pool = participants
    if visible_agents:
        vis = set(visible_agents)
        pool = [p for p in participants if p["persona_id"] in vis] or participants

    pref = {t.lower() for t in preferred_tags}
    ranked = []
    for p in pool:
        tags = {t.lower() for t in (p.get("role_tags") or [])}
        score = len(tags & pref)
        ranked.append({"p": p, "score": score})
    ranked.sort(key=lambda x: x["score"], reverse=True)

    # Strong preference match — use it (avoid last speaker if tie)
    if ranked and ranked[0]["score"] > 0:
        candidates = [x["p"] for x in ranked if x["score"] == ranked[0]["score"]]
        for c in candidates:
            if c["persona_id"] != last_speaker:
                return c["persona_id"]
        return candidates[0]["persona_id"]

    # Deterministic round robin
    if not pool:
        return participants[0]["persona_id"]
    idx = fallback_index % len(pool)
    if pool[idx]["persona_id"] == last_speaker and len(pool) > 1:
        idx = (idx + 1) % len(pool)
    return pool[idx]["persona_id"]


# ── Checklist heuristics ─────────────────────────────────────────────────


def _update_checklist(
    checklist: Dict[str, bool],
    stage_id: str,
) -> Dict[str, bool]:
    """Mark the current stage as complete in the checklist."""
    if stage_id in checklist:
        checklist[stage_id] = True
    return checklist


def _is_checklist_complete(checklist: Dict[str, bool]) -> bool:
    """True if all checklist items are True (or checklist is empty)."""
    if not checklist:
        return False
    return all(checklist.values())


# ── Default checklist per profile ─────────────────────────────────────────


def _default_checklist(profile_id: str) -> Dict[str, bool]:
    """Create default checklist based on the profile's stages.

    One checklist item per stage — marked complete after each stage runs.
    """
    profile = get_profile(profile_id)
    if profile:
        return {stage.id: False for stage in profile.stages}
    return {}


# ── Safe fallback output ──────────────────────────────────────────────────


def _safe_fallback(profile_id: str, topic: str = "") -> str:
    """Generate a natural fallback when LLM output is too short.

    Produces brief, conversational text — no section headers.
    """
    if topic:
        return (
            f"That's a great topic! I'd love to share my thoughts on {topic}. "
            "Let me think about the best approach and we can work through it together."
        )
    return "I need a moment to gather my thoughts on this. Let me think about it and share some ideas."


# ── Main engine: one workflow step per call ──────────────────────────────


async def run_crew_turn(
    *,
    room_id: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    max_concurrent: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute one workflow stage step and append message(s) to transcript.

    Returns::

        {
            "room": updated_room,
            "new_messages": [msg],
            "speakers": [persona_id],
            "engine_debug": {...},
        }
    """
    logger.info("═══ CREW TURN START ═══ room=%s", room_id)

    room = rooms.get_room(room_id)
    if not room:
        raise ValueError("Room not found")

    ensure_defaults(room)
    policy = room.get("policy") or {}
    crew_policy = policy.get("crew") or {}

    profile_id = (crew_policy.get("profile_id") or "task_planner_v1").strip()
    profile = get_profile(profile_id)
    if not profile:
        raise ValueError(f"Unknown workflow profile: {profile_id}")

    logger.info(
        "[CREW] Profile: %s (%s) | Topic: %s",
        profile_id, profile.title,
        (room.get("topic") or room.get("description") or "(none)")[:80],
    )

    participant_ids = room.get("participant_ids") or []
    participants = resolve_participants(participant_ids)
    if not participants:
        raise ValueError("No valid participants")
    logger.info("[CREW] Participants: %s", [p.get("name") or p["persona_id"] for p in participants])

    # ── Runtime state ─────────────────────────────────────────────────
    state = room.get("state") or {}
    crew_state = state.get("crew") or {}

    if not crew_state.get("run_id"):
        crew_state = {
            "run_id": str(uuid.uuid4()),
            "current_stage": profile.stages[0].id,
            "stage_index": 0,
            "checklist": _default_checklist(profile_id),
            "draft": {},
            "progress": {
                "last_update_ts": time.time(),
                "novelty_scores": [],
                "no_progress_count": 0,
                "last_reason": "init",
            },
            "meta": {"fallback_index": 0, "last_speaker": None},
        }

    stage_index = max(0, min(int(crew_state.get("stage_index") or 0), len(profile.stages) - 1))
    stage = profile.stages[stage_index]
    logger.info(
        "[CREW] Stage %d/%d: %s (%s) | run_id=%s",
        stage_index + 1, len(profile.stages), stage.title, stage.id,
        crew_state.get("run_id", "new"),
    )

    # ── Settings ─────────────────────────────────────────────────────
    visible_agents = crew_policy.get("visible_agents") or None
    controller_visibility = (crew_policy.get("controller_visibility") or "hidden").lower()
    stop_rules = profile.stop_rules

    # Budget limit: from policy or extracted from topic text
    budget_limit = crew_policy.get("budget_limit_eur")
    if budget_limit is None:
        m = re.search(r"[€$£]\s*([0-9]+(?:\.[0-9]+)?)", room.get("topic") or "")
        if m:
            try:
                budget_limit = float(m.group(1))
            except ValueError:
                budget_limit = None

    # ── Speaker selection ─────────────────────────────────────────────
    last_speaker = (crew_state.get("meta") or {}).get("last_speaker")
    fallback_index = int((crew_state.get("meta") or {}).get("fallback_index") or 0)

    speaker_id = _pick_speaker_for_stage(
        participants=participants,
        preferred_tags=list(stage.preferred_tags),
        visible_agents=visible_agents,
        last_speaker=last_speaker,
        fallback_index=fallback_index,
    )

    proj = projects.get_project_by_id(speaker_id)
    if not proj:
        raise ValueError("Selected persona project not found")
    logger.info(
        "[CREW] Speaker: %s (%s) | preferred_tags=%s | last_speaker=%s",
        proj.get("name") or speaker_id, speaker_id,
        stage.preferred_tags, last_speaker,
    )

    # ── Build task anchor + stage instruction ─────────────────────────
    topic = (room.get("topic") or room.get("description") or "").strip()
    agenda = room.get("agenda") or []
    checklist = crew_state.get("checklist") or _default_checklist(profile_id)
    draft = crew_state.get("draft") or {}

    # Build a readable summary of prior draft content
    draft_summary = (
        draft.get("steps") or draft.get("plan") or draft.get("outline")
        or draft.get("ideas") or "(nothing yet — you are the first to contribute)"
    )

    task_anchor = (
        f"TOPIC: {topic}\n"
        + (f"AGENDA: {', '.join(agenda)}\n" if agenda else "")
        + f"WORKFLOW STAGE: {stage.title} (stage {stage_index + 1}/{len(profile.stages)})\n"
        + f"PROGRESS: {sum(checklist.values())}/{len(checklist)} items complete\n"
        + "WHAT WE HAVE SO FAR:\n"
        + draft_summary
    ).strip()

    contract = profile.output_contract

    stage_instruction = (
        f"{task_anchor}\n\n"
        f"YOUR TASK: {stage.instruction}\n\n"
        "Respond naturally and concisely as yourself. "
        "Be specific — use real names, quantities, and details. "
        f"Keep it under {contract.max_words} words."
    )

    # ── Build persona prompt using existing meeting engine ────────────
    all_projects = [projects.get_project_by_id(p["persona_id"]) for p in participants]
    all_projects = [p for p in all_projects if p]
    others = [p for p in all_projects if p.get("id") != speaker_id]
    knowledge_query = _recent_conversation_query(room)
    system_prompt = build_persona_prompt(proj, room, others, knowledge_query=knowledge_query)
    chat_messages = build_chat_messages(room, system_prompt, current_persona_id=speaker_id)

    # Inject the task anchor as a user message (not in transcript)
    chat_messages = list(chat_messages) + [{"role": "user", "content": stage_instruction}]

    # ── Generate ─────────────────────────────────────────────────────
    logger.info("[CREW] Calling LLM (provider=%s, model=%s) ...", provider, model)
    t0 = time.time()
    text = (await llm_text(
        chat_messages,
        provider=provider,
        model=model,
        base_url=base_url,
        max_concurrent=max_concurrent,
    )).strip()
    llm_ms = int((time.time() - t0) * 1000)
    logger.info("[CREW] LLM response (%dms, %d words): %.200s...", llm_ms, _word_count(text), text)

    ok, reason, meta = _validate_output(
        profile=profile, text=text, budget_limit=budget_limit,
    )
    logger.info("[CREW] Validation: ok=%s reason=%s", ok, reason)

    # ── Novelty check ─────────────────────────────────────────────────
    recent = []
    for m_msg in reversed(room.get("messages") or []):
        if m_msg.get("role") == "assistant":
            recent.append(m_msg.get("content") or "")
        if len(recent) >= 6:
            break
    novelty = 1.0
    if recent:
        novelty = 1.0 - max(_jaccard(text, r) for r in recent)

    progress = crew_state.get("progress") or {}
    novs = list(progress.get("novelty_scores") or [])
    novs.append(float(novelty))
    progress["novelty_scores"] = novs[-50:]

    no_progress = int(progress.get("no_progress_count") or 0)
    if novelty < stop_rules.low_novelty_threshold:
        no_progress += 1
    else:
        no_progress = 0
    progress["no_progress_count"] = no_progress
    progress["last_update_ts"] = time.time()
    progress["last_reason"] = reason

    logger.info(
        "[CREW] Novelty=%.3f | no_progress_count=%d | checklist=%s",
        novelty, no_progress, checklist,
    )

    # Handle validation failures simply — no retry loops
    if not ok:
        if reason == "too_short":
            logger.warning("[CREW] Output too short, using fallback")
            text = _safe_fallback(profile_id, topic=topic)
            no_progress += 1
            progress["no_progress_count"] = no_progress
        else:
            # too_long or budget_over — keep the text, just flag it
            logger.info("[CREW] Accepting output despite: %s", reason)

    # ── Update checklist + draft ─────────────────────────────────────
    checklist = _update_checklist(checklist, stage.id)
    # Store parsed sections (if any) into draft for reference
    sections = meta.get("sections") if isinstance(meta, dict) else None
    if isinstance(sections, dict):
        for key, val in sections.items():
            if val and val.strip():
                draft[key.lower()] = val.strip()

    crew_state["checklist"] = checklist
    crew_state["draft"] = draft
    crew_state["progress"] = progress

    # ── Stage advancement / termination ──────────────────────────────
    complete = _is_checklist_complete(checklist)
    should_stop = False
    stop_reason = None

    if stop_rules.stop_when_complete and complete and stage.id == profile.stages[-1].id:
        should_stop = True
        stop_reason = "complete"

    if stop_rules.stop_on_low_novelty:
        window = stop_rules.low_novelty_window
        if len(progress["novelty_scores"]) >= window:
            last_window = progress["novelty_scores"][-window:]
            if all(x < stop_rules.low_novelty_threshold for x in last_window):
                should_stop = True
                stop_reason = "low_novelty"

    if no_progress >= stop_rules.max_no_progress_steps:
        should_stop = True
        stop_reason = "no_progress"

    # Advance stage if not stopping
    if not should_stop:
        next_index = min(stage_index + 1, len(profile.stages) - 1)
        crew_state["stage_index"] = next_index
        crew_state["current_stage"] = profile.stages[next_index].id
        if next_index != stage_index:
            logger.info(
                "[CREW] Advancing stage: %s → %s",
                stage.id, profile.stages[next_index].id,
            )
    else:
        crew_state["current_stage"] = profile.stages[stage_index].id
        logger.info("[CREW] STOPPING: reason=%s complete=%s", stop_reason, complete)

    # Update meta
    crew_meta = crew_state.get("meta") or {}
    crew_meta["last_speaker"] = speaker_id
    crew_meta["fallback_index"] = fallback_index + 1
    crew_state["meta"] = crew_meta

    # ── Persist message ──────────────────────────────────────────────
    msg = {
        "id": str(uuid.uuid4()),
        "sender_id": speaker_id,
        "sender_name": proj.get("name") or proj.get("title") or "Persona",
        "content": text,
        "role": "assistant",
        "tools_used": [],
        "timestamp": time.time(),
    }
    room.setdefault("messages", []).append(msg)

    state["crew"] = crew_state
    room["state"] = state
    rooms.update_room(room_id, {
        "messages": room["messages"],
        "state": room["state"],
        "policy": room.get("policy", {}),
    })

    dt_ms = int((time.time() - t0) * 1000)
    engine_debug = {
        "engine": "crew",
        "profile_id": profile_id,
        "stage": stage.id,
        "stage_index": stage_index,
        "speaker_id": speaker_id,
        "validation": {"ok": ok, "reason": reason},
        "novelty": round(novelty, 3),
        "complete": complete,
        "stop": {"should_stop": should_stop, "reason": stop_reason},
        "runtime_ms": dt_ms,
        "controller_visibility": controller_visibility,
    }

    logger.info(
        "═══ CREW TURN END ═══ room=%s | stage=%s | speaker=%s | novelty=%.3f | ok=%s | %dms",
        room_id, stage.id, proj.get("name") or speaker_id,
        novelty, ok, dt_ms,
    )

    updated = rooms.get_room(room_id)
    return {
        "room": updated,
        "new_messages": [msg],
        "speakers": [speaker_id],
        "engine_debug": engine_debug,
    }
