# backend/app/teams/play_mode.py
"""
Play Mode — autonomous AI conversation loop for Teams.

When enabled, personas converse among themselves without human input.
The user becomes an observer and can optionally join by sending a message.

Key design decision: the smart trigger is used ONLY for intent scoring
(deciding who speaks next). It is NEVER injected into the transcript.
The LLM already sees other personas' messages as user-role input via
build_chat_messages, so it naturally responds to what was actually said.

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
from .continuation import generate_smart_trigger
from .crew_runner import run_crew_turn
from .locks import get_room_lock
from .orchestrator import run_reactive_step, run_initiative_step, ensure_defaults
from .participants_resolver import resolve_participants

logger = logging.getLogger("homepilot.teams.play_mode")

# ── Active play tasks (one per room) ─────────────────────────────────────

_play_tasks: Dict[str, asyncio.Task] = {}


# ── Style presets ────────────────────────────────────────────────────────

STYLE_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "discussion": {
        "max_speakers_per_event": 1,
        "speak_threshold": 0.35,
        "cooldown_turns": 2,
    },
    "debate": {
        "max_speakers_per_event": 1,
        "speak_threshold": 0.30,
        "cooldown_turns": 2,
        "redundancy_threshold": 0.5,
        "dominance_penalty": 0.25,
    },
    "roundtable": {
        "max_speakers_per_event": 1,
        "speak_threshold": 0.20,
        "cooldown_turns": 2,
    },
    "roleplay": {
        "max_speakers_per_event": 1,
        "speak_threshold": 0.25,
        "cooldown_turns": 2,
    },
    "simulation": {
        "max_speakers_per_event": 1,
        "speak_threshold": 0.30,
        "cooldown_turns": 2,
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
        "show_facilitator": False,
    }


# ── Novelty detection ─────────────────────────────────────────────────────

import re as _re

_NOVELTY_STOP_WORDS = frozenset({
    "that", "this", "with", "from", "have", "been", "were", "will",
    "what", "when", "where", "which", "about", "their", "there",
    "would", "could", "should", "other", "just", "like", "more",
    "they", "them", "your", "also", "than", "then", "very", "some",
    "into", "over", "only", "even", "most", "such", "each", "love",
    "really", "make", "youre", "thats",
})


def _tokenize_for_novelty(text: str) -> set:
    """Extract meaningful word tokens for novelty comparison."""
    words = set(_re.findall(r"[a-zA-Z]{3,}", text.lower()))
    return words - _NOVELTY_STOP_WORDS


def _is_low_novelty(
    room_id: str,
    new_messages: list,
    lookback: int = 6,
    threshold: float = 0.55,
) -> bool:
    """Check if new messages are too similar to recent history.

    Uses **pairwise** Jaccard similarity: compares each new message against
    each individual history message and returns True if any pair exceeds
    the threshold.  This avoids false positives from same-topic conversations
    (where combined history tokens inflate overlap) and only catches actual
    near-identical repetition.
    """
    room = rooms.get_room(room_id)
    if not room:
        return False

    # Collect recent assistant messages (excluding new ones)
    new_ids = {m.get("id") for m in new_messages}
    all_msgs = room.get("messages") or []
    recent_asst = [
        m for m in all_msgs
        if m.get("role") == "assistant" and m.get("id") not in new_ids
    ][-lookback:]

    if len(recent_asst) < 2:
        return False  # Not enough history to compare

    # Pairwise comparison: each new msg vs each history msg individually
    max_similarity = 0.0
    for new_msg in new_messages:
        new_tokens = _tokenize_for_novelty(new_msg.get("content", ""))
        if not new_tokens:
            continue
        for hist_msg in recent_asst:
            hist_tokens = _tokenize_for_novelty(hist_msg.get("content", ""))
            if not hist_tokens:
                continue
            jaccard = len(new_tokens & hist_tokens) / max(1, len(new_tokens | hist_tokens))
            max_similarity = max(max_similarity, jaccard)

    if max_similarity >= threshold:
        logger.debug(
            "Low novelty detected for %s: max pairwise Jaccard=%.2f (threshold=%.2f)",
            room_id, max_similarity, threshold,
        )
        return True
    return False


# ── Core loop ────────────────────────────────────────────────────────────

_CONVERGENCE_SIGNALS = frozenset({
    "recap", "finalize", "wrap up", "here's the plan", "here's our plan",
    "here is the plan", "let's get baking", "let's get started",
    "voilà", "voila", "that's it!", "ready to go",
    "final summary", "final plan", "in summary",
})


def _looks_like_convergence(text: str) -> bool:
    """Detect recap / finalization signals that indicate the task is done."""
    lower = text.lower()
    return sum(1 for s in _CONVERGENCE_SIGNALS if s in lower) >= 2


async def _play_loop(
    room_id: str,
    generate_fn: Callable[[str, Dict[str, Any]], Awaitable[str]],
) -> None:
    """Background loop that drives autonomous AI conversation.

    Cancellation-safe: handles asyncio.CancelledError gracefully.
    Style overrides are applied per-iteration and restored on stop
    to prevent permanent policy mutation.

    Anti-monologue: tracks who spoke last tick and excludes them from
    the next tick so personas must alternate (Fix A+B).
    Convergence: auto-stops when personas start recap/finalize loops (Fix D).
    """
    silence_streak = 0
    low_novelty_streak = 0
    convergence_streak = 0
    MAX_SILENCE = 3       # stop after 3 rounds with no speakers
    MAX_LOW_NOVELTY = 3   # stop after 3 rounds with low novelty
    MAX_CONVERGENCE = 2   # stop after 2 rounds of recap/finalize signals
    _base_policy_snapshot: Optional[Dict[str, Any]] = None

    # Cross-tick anti-monologue: track who spoke last tick so we
    # can exclude them from the next tick, forcing alternation.
    last_tick_speakers: set = set()

    try:
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

            # Apply style overrides to a working copy of the policy —
            # snapshot the original so we can restore it on stop.
            ensure_defaults(room)
            if _base_policy_snapshot is None:
                _base_policy_snapshot = dict(room["policy"])

            style = pm.get("style", "discussion")
            overrides = STYLE_OVERRIDES.get(style, {})
            effective_policy = dict(_base_policy_snapshot)
            effective_policy.update(overrides)
            # Enable observer mode during play — human is watching
            effective_policy["observer_mode"] = True
            room["policy"] = effective_policy
            rooms.update_room(room_id, {"policy": effective_policy})

            # Smart trigger for intent scoring only — NOT injected into transcript.
            # The LLM sees other personas' messages via build_chat_messages.
            trigger = generate_smart_trigger(room, participants)

            # Optionally log the trigger for debug (visible via show_facilitator toggle)
            if pm.get("show_facilitator"):
                debug_msg = {
                    "id": str(uuid.uuid4()),
                    "sender_id": "facilitator",
                    "sender_name": "Facilitator",
                    "content": f"[DEBUG] Trigger for intent scoring: {trigger}",
                    "role": "system",
                    "tools_used": [],
                    "timestamp": time.time(),
                }
                msgs = room.get("messages") or []
                msgs.append(debug_msg)
                rooms.update_room(room_id, {"messages": msgs})

            # Run one orchestration step — branch by engine then turn_mode
            engine = (room.get("policy") or {}).get("engine", "native")
            turn_mode = room.get("turn_mode", "reactive")
            lock = get_room_lock(room_id)
            try:
                async with lock:
                    if engine == "crew":
                        result = await run_crew_turn(room_id=room_id)
                    elif turn_mode == "round-robin":
                        result = await run_initiative_step(
                            room_id,
                            participants=participants,
                            generate_fn=generate_fn,
                        )
                    else:
                        result = await run_reactive_step(
                            room_id,
                            last_human_message=trigger,
                            participants=participants,
                            generate_fn=generate_fn,
                            exclude_speakers=last_tick_speakers or None,
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

            # Check for silence — use new_messages (actual output), not
            # speakers (selected).  Ollama may return empty content causing
            # all selected speakers to be skipped.
            new_messages = result.get("new_messages", [])
            if not new_messages:
                silence_streak += 1
                # If silence was caused by exclusion, reset exclusion
                # so the excluded persona gets another chance next tick.
                last_tick_speakers = set()
                if silence_streak >= MAX_SILENCE:
                    logger.info("Play loop: %d silent rounds, stopping %s", MAX_SILENCE, room_id)
                    _stop_play_mode(room_id, reason="silence")
                    break
            else:
                silence_streak = 0
                # Update cross-tick anti-monologue tracker
                last_tick_speakers = {m.get("sender_id") for m in new_messages}

            # Check for convergence (recap/finalize loops → task complete)
            if new_messages:
                last_content = new_messages[-1].get("content", "")
                if _looks_like_convergence(last_content):
                    convergence_streak += 1
                    logger.debug(
                        "Play loop: convergence signal #%d in %s",
                        convergence_streak, room_id,
                    )
                    if convergence_streak >= MAX_CONVERGENCE:
                        logger.info(
                            "Play loop: task appears complete, stopping %s",
                            room_id,
                        )
                        _stop_play_mode(room_id, reason="completed")
                        break
                else:
                    convergence_streak = 0

            # Check for novelty collapse (repetitive content)
            if new_messages and _is_low_novelty(room_id, new_messages):
                low_novelty_streak += 1
                if low_novelty_streak >= MAX_LOW_NOVELTY:
                    logger.info(
                        "Play loop: %d low-novelty rounds, stopping %s",
                        MAX_LOW_NOVELTY, room_id,
                    )
                    _stop_play_mode(room_id, reason="repetitive")
                    break
            else:
                low_novelty_streak = 0

            # Wait before next iteration
            await asyncio.sleep(interval_s)

    except asyncio.CancelledError:
        logger.info("Play loop cancelled for %s", room_id)
    finally:
        # Restore original policy (remove style overrides + observer_mode)
        if _base_policy_snapshot is not None:
            try:
                rooms.update_room(room_id, {"policy": _base_policy_snapshot})
            except Exception:
                pass


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
    show_facilitator: bool = False,
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
        "show_facilitator": show_facilitator,
    }
    rooms.update_room(room_id, {"play_mode": pm})

    # Always inject a "Play Mode started" indicator message so the
    # user can see when autonomous conversation began in the transcript.
    msgs = room.get("messages") or []
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
    """Stop play mode for a room. Returns updated play_mode state.

    Cancels the background task and waits briefly for cleanup.
    """
    task = _play_tasks.pop(room_id, None)
    if task and not task.done():
        task.cancel()
        # The task's finally block will restore the base policy.

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


def toggle_facilitator(room_id: str) -> Dict[str, Any]:
    """Toggle show_facilitator debug flag."""
    room = rooms.get_room(room_id)
    if not room:
        raise ValueError("Room not found")
    pm = room.get("play_mode") or default_play_mode()
    pm["show_facilitator"] = not pm.get("show_facilitator", False)
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
