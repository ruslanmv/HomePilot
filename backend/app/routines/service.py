"""Routine execution service.

This module deliberately reuses HomePilot's native chat/project/persona session
paths. A routine therefore produces the same kind of conversation the user can
open and continue manually; it does not invent a parallel automation chat store.

── A routine is a task HomePilot performs, not a message from the user ─────────────────

The conversation a routine leaves behind is the product: it opens, the answer is there, and
the user can carry on talking from it — an Alexa routine that also happens to be a thread.

What makes that work is that the thread is **true**. It used to open with a fabricated user
turn — ``"Prepare my morning news briefing for today."`` attributed to the person, who was
probably asleep — because the prepared instruction was handed to the chat pipeline as
``payload["message"]`` and both chat paths persist that as ``role="user"``. Three things
went wrong at once:

* the record lied about who said what, and nothing downstream could tell;
* the user's first *real* message landed second, in a thread that already misrepresented
  them, so the model's "history" of them was wrong from the first turn;
* memory and later summaries ingested the fabrication as a genuine request.

Now the instruction travels as ``system_initiated`` and is stored as a ``system`` turn that
reads as what it is — *the routine ran, here is the task*. The model sees the same words,
because history is mapped role-for-role into the provider call. Only the attribution
changes, and the attribution was the whole bug.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .. import projects
from .. import sessions as persona_sessions
from ..config import (
    DEFAULT_PROVIDER,
    LLM_BASE_URL,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)
from ..orchestrator import handle_request
from . import actions, events, store


def _scheduled_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_title(routine: Dict[str, Any], scheduled_for: str) -> str:
    tz_name = str(routine.get("timezone") or "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    try:
        instant = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
    except Exception:
        instant = datetime.now(timezone.utc)
    local = instant.astimezone(tz)
    return f"{routine.get('name') or 'Routine'} · {local.strftime('%b %d')}"


def _local_time_label(routine: Dict[str, Any], scheduled_for: str) -> str:
    """``07:04 on Sep 24``, in the routine's own timezone."""
    tz_name = str(routine.get("timezone") or "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    try:
        instant = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
    except Exception:
        instant = datetime.now(timezone.utc)
    local = instant.astimezone(tz)
    return f"{local.strftime('%H:%M')} on {local.strftime('%b %d')}"


def opening_turn(routine: Dict[str, Any], instruction: str, scheduled_for: str) -> str:
    """The turn a routine's conversation opens with.

    One message doing two honest jobs. To the reader opening the chat it says what ran and
    when, so a thread that appeared by itself explains itself. To the model it is the task,
    arriving as the last turn in history exactly as an instruction should.

    What it is *not* is the user talking. It is stored with ``role="system"``, so nothing —
    the reader, search, memory, a later summary — can mistake it for a request somebody
    made.
    """
    name = str(routine.get("name") or "Routine").strip() or "Routine"
    when = _local_time_label(routine, scheduled_for)
    return f"Scheduled routine “{name}” ran automatically at {when}.\nTask: {instruction}"


def _provider_payload() -> Dict[str, Any]:
    provider = DEFAULT_PROVIDER
    payload: Dict[str, Any] = {"provider": provider}
    if provider == "ollama":
        payload["provider_base_url"] = OLLAMA_BASE_URL
        payload["provider_model"] = OLLAMA_MODEL
        payload["ollama_model"] = OLLAMA_MODEL
    elif provider == "openai_compat":
        payload["provider_base_url"] = LLM_BASE_URL
        payload["provider_model"] = LLM_MODEL
        payload["llm_model"] = LLM_MODEL
    return payload


def _speech_text(text: str) -> str:
    value = text or ""
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = value.replace("**", "").replace("__", "").replace(chr(96), "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _conversation_for_target(
    routine: Dict[str, Any],
    *,
    scheduled_for: str,
) -> tuple[str, Optional[str], str]:
    target = routine.get("target") or {"type": "assistant"}
    target_type = str(target.get("type") or "assistant")
    project_id = target.get("project_id")

    if target_type == "persona":
        if not project_id:
            raise RuntimeError("Persona routine has no project target")
        session = persona_sessions.create_session(
            str(project_id),
            mode="text",
            title=_local_title(routine, scheduled_for),
            force_new=True,
            activate=False,
        )
        return str(session["conversation_id"]), str(project_id), "project"

    if target_type == "project":
        if not project_id or not projects.get_project_by_id(str(project_id)):
            raise RuntimeError("Project routine target is unavailable")
        return str(uuid.uuid4()), str(project_id), "project"

    return str(uuid.uuid4()), None, "chat"


async def execute_routine(
    user_id: str,
    routine: Dict[str, Any],
    *,
    scheduled_for: Optional[str] = None,
    run_key: Optional[str] = None,
) -> Dict[str, Any]:
    scheduled = scheduled_for or _scheduled_now()
    run, created = store.claim_run(
        user_id,
        routine["id"],
        scheduled_for=scheduled,
        run_key=run_key,
    )
    if not created:
        return run

    try:
        material = await actions.prepare_action(routine)
        conversation_id, project_id, mode = _conversation_for_target(
            routine,
            scheduled_for=scheduled,
        )

        instruction = str(
            material.get("instruction") or material.get("message") or ""
        ).strip()
        if not instruction:
            raise RuntimeError("Routine action produced no task to perform")

        payload: Dict[str, Any] = {
            "message": opening_turn(routine, instruction, scheduled),
            "conversation_id": conversation_id,
            "project_id": project_id,
            "extra_system_context": material.get("extra_context") or "",
            "user_id": user_id,
            "memoryEngine": "v2",
            "persist_project_conversation": False,
            # The turn above is HomePilot acting on a schedule, so it is stored as `system`
            # rather than forged into the user's name. See this module's docstring.
            "system_initiated": True,
            **_provider_payload(),
        }
        if mode == "project":
            payload["mode"] = "project"

        generated = await handle_request(mode, payload)
        text = str(generated.get("text") or "").strip()
        if not text:
            raise RuntimeError("Routine generated an empty response")

        actual_conversation_id = str(generated.get("conversation_id") or conversation_id)
        presentation = {
            "speech_text": _speech_text(text),
            "display_markdown": text,
            "sources": material.get("sources") or [],
            "avatar": {
                "emotion": "thinking" if (routine.get("action") or {}).get("type") == "news_digest" else "friendly",
                "intensity": 0.6,
            },
        }
        result = {
            "routine_id": routine["id"],
            "routine_name": routine.get("name") or "Routine",
            "target": routine.get("target") or {"type": "assistant"},
            "provider": material.get("provider"),
            "notification": bool(
                (routine.get("delivery") or {}).get(
                    "notification",
                    (routine.get("delivery") or {}).get("in_app", True),
                )
            ),
            "speak_if_active": bool(
                (routine.get("delivery") or {}).get("speak_if_active", True)
            ),
            "presentation": presentation,
        }
        finished = store.finish_run(
            user_id,
            run["id"],
            status="success",
            project_id=project_id,
            conversation_id=actual_conversation_id,
            result_preview=_speech_text(text)[:240],
            result=result,
        )
        completed = finished or run
        await events.publish(
            user_id,
            {
                "type": "routine.completed",
                "run_id": completed["id"],
                "routine": {
                    "id": routine["id"],
                    "name": routine.get("name") or "Routine",
                },
                "target": routine.get("target") or {"type": "assistant"},
                "scheduled_for": completed.get("scheduled_for"),
                "project_id": project_id,
                "conversation_id": actual_conversation_id,
                "presentation": presentation,
            },
        )
        return completed
    except Exception as exc:
        failed = store.finish_run(
            user_id,
            run["id"],
            status="failed",
            error=str(exc),
            result_preview=str(exc)[:240],
            result={
                "routine_id": routine["id"],
                "routine_name": routine.get("name") or "Routine",
            },
        )
        return failed or run


async def run_now(user_id: str, routine: Dict[str, Any]) -> Dict[str, Any]:
    scheduled = _scheduled_now()
    return await execute_routine(
        user_id,
        routine,
        scheduled_for=scheduled,
        run_key=f"manual:{routine['id']}:{uuid.uuid4()}",
    )
