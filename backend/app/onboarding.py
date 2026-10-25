"""
The first conversation — every account's own assistant, created before it says a word.

Each account gets one plain assistant named "HomePilot", and its first chat is the onboarding:
a greeting, one question with an answer already filled in ("What would you like to call me?"),
a short introduction that claims only what this install can do, and then an ordinary chat.

The lines are written into the conversation here, by the server, not invented by a model, so
a refresh shows the same thread and never plays it again. The user row keeps the assistant's
project id (``default_assistant_id``) and the step reached, so a second tab or a second login
finds the same assistant instead of creating another.

Steps: ``created`` (greeting + the name question) → ``introduced`` (name settled, introduction
written) → ``done`` (onboarding complete; the app opens the assistant from now on).

The assistant is a regular chat project, not a persona: the chat's Fast / Expert / Heavy path
answers in it, with its instructions, and it needs no picture or image service.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import projects
from .storage import add_message, ensure_conversation_owner, get_messages
from .users import ensure_users_tables, get_current_user, _get_db_path

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])

DEFAULT_NAME = "HomePilot"
MAX_NAME = 24

INSTRUCTIONS = (
    "You are {name}, the user's personal assistant in HomePilot. Be warm, natural and brief; "
    "match the length of the request. You remember this chat. Only mention tools and abilities "
    "that are actually connected here, and ask before doing anything outside this chat."
)

# One lock is enough: creating an assistant happens once per account, in one process.
_lock = threading.Lock()


# ── user row ─────────────────────────────────────────────────────────────────

def _row(user_id: str) -> Dict[str, Any]:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT default_assistant_id, onboarding_data, onboarding_complete FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    con.close()
    if not row:
        return {"assistant_id": "", "data": {}, "complete": False}
    try:
        data = json.loads(row["onboarding_data"] or "{}")
    except ValueError:
        data = {}
    return {
        "assistant_id": row["default_assistant_id"] or "",
        "data": data if isinstance(data, dict) else {},
        "complete": bool(row["onboarding_complete"]),
    }


def _save(user_id: str, *, assistant_id: Optional[str] = None, step: Optional[str] = None,
          conversation_id: Optional[str] = None, complete: bool = False) -> None:
    current = _row(user_id)
    data = dict(current["data"])
    if step:
        data["assistant_step"] = step
    if conversation_id:
        data["assistant_conversation_id"] = conversation_id
    con = sqlite3.connect(_get_db_path())
    con.execute(
        "UPDATE users SET default_assistant_id = ?, onboarding_data = ?, "
        "onboarding_complete = CASE WHEN ? THEN 1 ELSE onboarding_complete END WHERE id = ?",
        (assistant_id if assistant_id is not None else current["assistant_id"],
         json.dumps(data), 1 if complete else 0, user_id),
    )
    con.commit()
    con.close()


def _require_user(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    if not user:
        raise HTTPException(status_code=401, detail="Sign in first")
    return user


# ── what the assistant says ──────────────────────────────────────────────────

def _on_space() -> bool:
    return bool(os.getenv("SPACE_ID", "").strip() or os.getenv("SPACE_HOST", "").strip())


def _can_make_images() -> bool:
    from .config import COMFY_BASE_URL
    return bool((COMFY_BASE_URL or "").strip())


def _can_look_things_up() -> bool:
    """Expert's web search is a tool; the Space ships without the tool servers (start.sh)."""
    return os.getenv("EXPERT_TOOLS_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def first_name(user: Dict[str, Any]) -> str:
    """The name to greet with — one the person chose, never a guest id or the stock "Admin"."""
    if (user.get("auth_provider") or "local") == "guest":
        return ""
    name = (user.get("display_name") or user.get("username") or "").strip()
    if not name or name.lower() == "admin":
        return ""
    return name.split()[0][:1].upper() + name.split()[0][1:]


def greeting(user: Dict[str, Any]) -> List[str]:
    who = first_name(user)
    return [
        f"Hi {who}! I'm {DEFAULT_NAME}." if who else f"Hi there! I'm {DEFAULT_NAME}.",
        "What would you like to call me? You can always change this later.",
    ]


def introduction(user: Dict[str, Any], name: str) -> List[str]:
    who = first_name(user)
    place = "on this Space" if _on_space() else "on this computer"
    skills = ["chat", "write", "explain things"]
    if _can_look_things_up():
        skills.append("look things up")
    if _can_make_images():
        skills.append("make images")
    can = ", ".join(skills[:-1]) + " and " + skills[-1]
    return [
        f"{name} it is! Nice to meet you, {who}." if who else f"{name} it is! Nice to meet you.",
        f"A little about me:\n\n- I live {place} and remember our chats.\n- I can {can}.\n"
        "- I only use what's connected, and I ask before doing anything outside this chat.",
        "What would you like to do first? Ask me anything.",
    ]


def starters() -> List[Dict[str, str]]:
    """What to try first — the first seconds decide whether someone stays, so the introduction
    ends with a few one-tap things to do. Only what this install can really do: images when a
    diffusion backend is connected, meetings and voice on a computer, plain chat everywhere.
    ``prompt`` sends ``text`` as the first message; ``mode`` opens that part of the app."""
    out: List[Dict[str, str]] = []
    if _can_make_images():
        out.append({"id": "image", "icon": "🎨", "label": "Make an image", "kind": "prompt",
                    "text": "Make an image of a cozy cabin in snowy mountains at golden hour"})
    if not _on_space():
        out.append({"id": "meeting", "icon": "🎙️", "label": "Take meeting notes", "kind": "mode", "mode": "meetings"})
        out.append({"id": "voice", "icon": "🗣️", "label": "Talk with me", "kind": "mode", "mode": "voice"})
    out += [
        {"id": "plan", "icon": "🗓️", "label": "Plan my week", "kind": "prompt",
         "text": "Help me plan a balanced week: work, exercise and some time for myself."},
        {"id": "write", "icon": "✍️", "label": "Write a message", "kind": "prompt",
         "text": "Write a short, friendly message inviting friends to dinner on Saturday."},
        {"id": "explain", "icon": "💡", "label": "Explain something", "kind": "prompt",
         "text": "Explain how black holes work, like I'm twelve."},
        {"id": "dinner", "icon": "🍝", "label": "Dinner idea", "kind": "prompt",
         "text": "Give me an easy dinner idea using things most people have at home."},
    ]
    return out[:4]


def clean_name(text: str) -> Optional[str]:
    """A name the person typed, or None when it reads like a message ("what's the weather?").
    A short phrase — up to 3 words and 24 characters, not a question — is a name."""
    name = re.sub(r"\s+", " ", (text or "").strip()).strip(" .!\"'")
    if not name or len(name) > MAX_NAME or "?" in name or len(name.split(" ")) > 3:
        return None
    return name


# ── the assistant and its thread ─────────────────────────────────────────────

def _messages(conversation_id: str, user_id: str) -> List[Dict[str, Any]]:
    return [
        {"role": m["role"], "content": m["content"], "onboarding": (m.get("media") or {}).get("onboarding")}
        for m in get_messages(conversation_id, user_id=user_id)
    ]


def _say(conversation_id: str, project_id: str, user_id: str, lines: List[str], step: str) -> None:
    for line in lines:
        add_message(conversation_id, "assistant", line, media={"onboarding": step},
                    project_id=project_id, user_id=user_id)


def _state(user: Dict[str, Any], *, created: bool = False) -> Dict[str, Any]:
    row = _row(user["id"])
    project = projects.get_project_by_id(row["assistant_id"]) if row["assistant_id"] else None
    if not project:
        return {"ok": True, "assistant": None, "step": None, "complete": row["complete"]}
    conversation_id = row["data"].get("assistant_conversation_id") or project.get("last_conversation_id") or ""
    return {
        "ok": True,
        "created": created,
        "assistant": {
            "id": project["id"],
            "name": project.get("name") or DEFAULT_NAME,
            "project_type": project.get("project_type") or "chat",
            "instructions": project.get("instructions") or "",
            "description": project.get("description") or "",
        },
        "conversation_id": conversation_id,
        "step": row["data"].get("assistant_step") or "done",
        "complete": row["complete"],
        "messages": _messages(conversation_id, user["id"]) if conversation_id else [],
        "on_space": _on_space(),
        "starters": starters(),
    }


def ensure_assistant(user: Dict[str, Any]) -> Dict[str, Any]:
    """The account's assistant, creating it (and its greeting) once. A second call, a second
    tab or a second login returns the same one; a project lost from disk is made again."""
    ensure_users_tables()
    with _lock:
        row = _row(user["id"])
        if row["assistant_id"] and projects.get_project_by_id(row["assistant_id"]):
            return _state(user)
        project = projects.create_new_project({
            "name": DEFAULT_NAME,
            "description": "Your assistant",
            "instructions": INSTRUCTIONS.format(name=DEFAULT_NAME),
            "project_type": "chat",
            "is_default_assistant": True,
            "owner_user_id": user["id"],
        })
        conversation_id = str(uuid.uuid4())
        ensure_conversation_owner(conversation_id, user["id"])
        # An account that already finished onboarding (the old wizard) still gets its
        # assistant, but no interview: the thread starts where an ordinary chat would.
        step = "done" if row["complete"] else "created"
        _say(conversation_id, project["id"], user["id"],
             greeting(user)[:1] if step == "done" else greeting(user), step)
        projects._save_project_conversation(project["id"], conversation_id)
        _save(user["id"], assistant_id=project["id"], step=step, conversation_id=conversation_id)
        return _state(user, created=True)


# ── routes ───────────────────────────────────────────────────────────────────

class NameIn(BaseModel):
    # Empty keeps the default name (the "HomePilot ✓" choice).
    name: str = Field(default="", max_length=400)


@router.get("/assistant")
def get_assistant(user: Dict[str, Any] = Depends(_require_user)) -> Dict[str, Any]:
    """The account's assistant if it has one (the app opens it on start); never creates one."""
    ensure_users_tables()
    return _state(user)


@router.post("/assistant")
def post_assistant(user: Dict[str, Any] = Depends(_require_user)) -> Dict[str, Any]:
    """Create the assistant and its greeting once, or return the existing one."""
    return ensure_assistant(user)


@router.post("/name")
def post_name(body: NameIn, user: Dict[str, Any] = Depends(_require_user)) -> Dict[str, Any]:
    """Settle the assistant's name and write the introduction.

    ``accepted: false`` means the text read like a message, not a name: the name stays
    HomePilot, nothing is written, and the app sends the text as the first real message."""
    state = ensure_assistant(user)
    if state["step"] != "created":
        return {**state, "accepted": True}
    typed = (body.name or "").strip()
    name = clean_name(typed) if typed else DEFAULT_NAME
    if name is None:
        return {**state, "accepted": False}
    project_id, conversation_id = state["assistant"]["id"], state["conversation_id"]
    with _lock:
        if _row(user["id"])["data"].get("assistant_step") != "created":
            return {**_state(user), "accepted": True}  # a second tap, or another tab, got here first
        if typed:
            add_message(conversation_id, "user", name, media={"onboarding": "named"},
                        project_id=project_id, user_id=user["id"])
        if name != DEFAULT_NAME:
            projects.update_project(project_id, {"name": name, "instructions": INSTRUCTIONS.format(name=name)})
        _say(conversation_id, project_id, user["id"], introduction(user, name), "introduced")
        _save(user["id"], step="introduced")
    return {**_state(user), "accepted": True}


@router.post("/done")
def post_done(user: Dict[str, Any] = Depends(_require_user)) -> Dict[str, Any]:
    """Onboarding is over (Start chatting, Skip, or the first real message)."""
    ensure_assistant(user)
    _save(user["id"], step="done", complete=True)
    return _state(user)
