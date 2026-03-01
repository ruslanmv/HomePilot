# backend/app/teams/play_mode.py
"""
Play Mode — autonomous AI conversation loop for Teams.

When enabled, personas converse among themselves without human input.
The user becomes an observer and can optionally join by sending a message.

Architecture:
  - One asyncio.Task per room (stored in _play_tasks)
  - Each iteration runs one orchestration step via run_reactive_step()
  - Room lock prevents collision with manual /react calls
  - Stops automatically when: max_rounds reached, no speakers for 3 cycles,
    or user explicitly stops

Play Modes (style presets that tune orchestration):
  - discussion : normal thresholds, multi-speaker
  - debate     : enforce alternating speakers, high diversity
  - roundtable : round-robin, everyone speaks once per cycle
  - roleplay   : amplified personality, lower threshold
  - simulation : scenario-driven, max rounds raised
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from . import rooms
from .continuation import (
    generate_smart_trigger,
    needs_continuation,
    inject_continuation_message,
)
from .locks import get_room_lock
from .orchestrator import run_reactive_step, ensure_defaults
from .participants_resolver import resolve_participants

logger = logging.getLogger("homepilot.teams.play_mode")

# ── Active play tasks (one per room) ─────────────────────────────────────

_play_tasks: Dict[str, asyncio.Task] = {}


# ── Style presets ────────────────────────────────────────────────────────

STYLE_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "discussion": {
        "max_speakers_per_event": 2,
        "speak_threshold": 0.35,
        "max_rounds_per_event": 2,
    },
    "debate": {
        "max_speakers_per_event": 1,
        "speak_threshold": 0.30,
        "max_rounds_per_event": 2,
        "redundancy_threshold": 0.5,
        "dominance_penalty": 0.25,
    },
    "roundtable": {
        "max_speakers_per_event": 1,
        "speak_threshold": 0.20,
        "max_rounds_per_event": 1,
        "cooldown_turns": 2,
    },
    "roleplay": {
        "max_speakers_per_event": 2,
        "speak_threshold": 0.25,
        "max_rounds_per_event": 3,
    },
    "simulation": {
        "max_speakers_per_event": 2,
        "speak_threshold": 0.30,
        "max_rounds_per_event": 3,
    },
}


# ── Default play mode state ─────────────────────────────────────────────

def default_play_mode() -> Dict[str, Any]:
    return {
        "enabled": False,
        "style": "discussion",
        "interval_ms": 3000,
        "max_rounds": 50,
        "round_count": 0,
        "paused_by_user": False,
    }


# ── Core loop ────────────────────────────────────────────────────────────

async def _play_loop(
    room_id: str,
    generate_fn: Callable[[str, Dict[str, Any]], Awaitable[str]],
) -> None:
    """Background loop that drives autonomous AI conversation."""
    silence_streak = 0
    MAX_SILENCE = 3  # stop after 3 rounds with no speakers

    while True:
        room = rooms.get_room(room_id)
        if not room:
            logger.warning("Play loop: room %s not found, stopping", room_id)
            break

        pm = room.get("play_mode") or {}
        if not pm.get("enabled"):
            logger.info("Play loop: play_mode disabled for %s, stopping", room_id)
            break
        if pm.get("paused_by_user"):
            # Paused — sleep and check again
            await asyncio.sleep(1.0)
            continue
        max_r = pm.get("max_rounds", 50)
        if max_r > 0 and pm.get("round_count", 0) >= max_r:
            logger.info("Play loop: max rounds reached for %s", room_id)
            _stop_play_mode(room_id, reason="max_rounds")
            break

        interval_s = max(1.0, pm.get("interval_ms", 3000) / 1000.0)

        # Resolve participants
        participant_ids = room.get("participant_ids") or []
        participants = resolve_participants(participant_ids)
        if not participants:
            logger.warning("Play loop: no participants in %s, stopping", room_id)
            _stop_play_mode(room_id, reason="no_participants")
            break

        # Apply style overrides to policy temporarily
        style = pm.get("style", "discussion")
        overrides = STYLE_OVERRIDES.get(style, {})
        ensure_defaults(room)
        original_policy = dict(room.get("policy", {}))
        for k, v in overrides.items():
            room["policy"][k] = v
        # Persist the tweaked policy for this step
        rooms.update_room(room_id, {"policy": room["policy"]})

        # ── Smart Continuation Engine ─────────────────────────────
        # Generate a context-aware trigger based on topic, agenda,
        # conversation history, and participant roles.  Also injects
        # a facilitator message into the transcript so the LLM has
        # fresh "user" input to respond to.
        if needs_continuation(room):
            trigger = generate_smart_trigger(room, participants)
            inject_continuation_message(room_id, room, trigger)
            logger.debug("Play loop: injected smart trigger for %s", room_id)
        else:
            # Fresh human input exists — use it directly
            msgs = room.get("messages") or []
            trigger = msgs[-1].get("content", "") if msgs else ""
            if not trigger:
                trigger = generate_smart_trigger(room, participants)

        # Run one orchestration step
        lock = get_room_lock(room_id)
        try:
            async with lock:
                result = await run_reactive_step(
                    room_id,
                    last_human_message=trigger,
                    participants=participants,
                    generate_fn=generate_fn,
                )
        except Exception as exc:
            logger.error("Play loop step failed for %s: %s", room_id, exc)
            silence_streak += 1
            if silence_streak >= MAX_SILENCE:
                _stop_play_mode(room_id, reason="errors")
                break
            await asyncio.sleep(interval_s)
            continue

        # Update round count
        speakers = result.get("speakers", [])
        room = rooms.get_room(room_id)
        if room:
            pm = room.get("play_mode") or default_play_mode()
            pm["round_count"] = pm.get("round_count", 0) + 1
            rooms.update_room(room_id, {"play_mode": pm})

        # Check for silence
        if not speakers:
            silence_streak += 1
            if silence_streak >= MAX_SILENCE:
                logger.info("Play loop: %d silent rounds, stopping %s", MAX_SILENCE, room_id)
                _stop_play_mode(room_id, reason="silence")
                break
        else:
            silence_streak = 0

        # Wait before next iteration
        await asyncio.sleep(interval_s)


def _stop_play_mode(room_id: str, reason: str = "manual") -> None:
    """Disable play_mode on room and clean up."""
    room = rooms.get_room(room_id)
    if room:
        pm = room.get("play_mode") or default_play_mode()
        pm["enabled"] = False
        rooms.update_room(room_id, {"play_mode": pm})
    logger.info("Play mode stopped for %s (reason: %s)", room_id, reason)


# ── Public API ───────────────────────────────────────────────────────────

def start_play_mode(
    room_id: str,
    generate_fn: Callable[[str, Dict[str, Any]], Awaitable[str]],
    style: str = "discussion",
    interval_ms: int = 3000,
    max_rounds: int = 50,
) -> Dict[str, Any]:
    """Start autonomous play mode for a room. Returns updated play_mode state."""
    # Stop any existing task
    stop_play_mode(room_id)

    room = rooms.get_room(room_id)
    if not room:
        raise ValueError("Room not found")

    pm: Dict[str, Any] = {
        "enabled": True,
        "style": style,
        "interval_ms": max(1000, interval_ms),
        "max_rounds": 0 if max_rounds <= 0 else min(500, max(5, max_rounds)),
        "round_count": 0,
        "paused_by_user": False,
    }
    rooms.update_room(room_id, {"play_mode": pm})

    # If there are no messages yet, inject a seed message
    msgs = room.get("messages") or []
    if not msgs:
        seed = {
            "id": str(uuid.uuid4()),
            "sender_id": "system",
            "sender_name": "System",
            "content": f"[Play Mode started — {style} mode. Personas, begin your conversation.]",
            "role": "user",
            "tools_used": [],
            "timestamp": time.time(),
        }
        msgs.append(seed)
        rooms.update_room(room_id, {"messages": msgs})

    task = asyncio.create_task(_play_loop(room_id, generate_fn))
    _play_tasks[room_id] = task

    # Clean up task reference when done
    def _on_done(t: asyncio.Task):
        _play_tasks.pop(room_id, None)
    task.add_done_callback(_on_done)

    return pm


def stop_play_mode(room_id: str) -> Dict[str, Any]:
    """Stop play mode for a room. Returns updated play_mode state."""
    task = _play_tasks.pop(room_id, None)
    if task and not task.done():
        task.cancel()

    _stop_play_mode(room_id, reason="manual")
    room = rooms.get_room(room_id)
    return (room or {}).get("play_mode") or default_play_mode()


def pause_play_mode(room_id: str) -> Dict[str, Any]:
    """Pause play mode (user wants to intervene)."""
    room = rooms.get_room(room_id)
    if not room:
        raise ValueError("Room not found")
    pm = room.get("play_mode") or default_play_mode()
    pm["paused_by_user"] = True
    rooms.update_room(room_id, {"play_mode": pm})
    return pm


def resume_play_mode(room_id: str) -> Dict[str, Any]:
    """Resume paused play mode."""
    room = rooms.get_room(room_id)
    if not room:
        raise ValueError("Room not found")
    pm = room.get("play_mode") or default_play_mode()
    pm["paused_by_user"] = False
    rooms.update_room(room_id, {"play_mode": pm})
    return pm


def get_play_status(room_id: str) -> Dict[str, Any]:
    """Get current play mode status."""
    room = rooms.get_room(room_id)
    if not room:
        return default_play_mode()
    pm = room.get("play_mode") or default_play_mode()
    pm["task_running"] = room_id in _play_tasks and not _play_tasks[room_id].done()
    return pm


def is_playing(room_id: str) -> bool:
    """Quick check: is play mode active?"""
    room = rooms.get_room(room_id)
    if not room:
        return False
    pm = room.get("play_mode") or {}
    return bool(pm.get("enabled"))
