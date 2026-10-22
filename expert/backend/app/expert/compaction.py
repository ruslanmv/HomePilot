"""Compaction: turns older than the window become a running note instead of vanishing.

What ChatGPT and Claude do when a thread outgrows the context: keep the recent turns
verbatim, and carry the rest as a short memory note — facts, decisions, preferences, open
questions — refreshed incrementally. One small model call per overflow, cached per session.
The note travels like grounding does: a context variable that ``build_messages`` appends to
the system prompt of every pipeline step.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .config import (
    EXPERT_COMPACTION_ENABLED,
    EXPERT_COMPACTION_MAX_INPUT_CHARS,
    EXPERT_COMPACTION_MAX_TOKENS,
)

logger = logging.getLogger("expert.compaction")

_CURRENT: ContextVar[str] = ContextVar("expert_compaction_note", default="")
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_MAX = 500

SUMMARY_SYSTEM = (
    "You maintain a compact memory note of a conversation. Update the note with the new turns: "
    "keep facts, decisions, preferences, names, numbers, open questions and the user's goals; "
    "drop chit-chat. Write in the third person, at most 250 words, no preamble."
)


def apply(system_prompt: str) -> str:
    """``system_prompt`` with this request's note appended (unchanged when there is none)."""
    note = _CURRENT.get()
    if not note:
        return system_prompt
    return f"{system_prompt}\n\nSummary of the earlier conversation (turns not shown):\n{note}"


@contextmanager
def using(note: Optional[str]) -> Iterator[str]:
    token = _CURRENT.set((note or "").strip())
    try:
        yield _CURRENT.get()
    finally:
        _CURRENT.reset(token)


def _digest(turns: List[Dict[str, Any]]) -> str:
    h = hashlib.sha1()
    for t in turns:
        h.update(f"{t.get('role')}\x1f{t.get('content')}\x1e".encode("utf-8", "replace"))
    return h.hexdigest()


def split(history: Optional[List[Dict[str, Any]]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(older, window)``: the window exactly as the pipelines will see it, and the clean turns
    before it."""
    from .router import clean_turns, history_window

    clean = clean_turns(history)
    window = history_window(clean)
    older = clean[: len(clean) - len(window)] if window else clean
    return older, window


def render(turns: List[Dict[str, Any]], max_chars: int) -> str:
    """The turns as a transcript, newest kept when the budget cuts."""
    lines = [f"{'User' if t.get('role') == 'user' else 'Assistant'}: {t.get('content', '')}" for t in turns]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = "…" + text[-max_chars:]
    return text


def _clean(summary: str) -> str:
    summary = re.sub(r"<think>.*?</think>", "", summary or "", flags=re.S)
    return summary.strip()


async def summarize(previous: str, transcript: str, provider: str, model: Optional[str], temperature: float) -> str:
    from .router import dispatch

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {"role": "user", "content": f"Current note:\n{previous or '(none yet)'}\n\nNew turns:\n{transcript}\n\nUpdated note:"},
    ]
    raw = await dispatch(messages, provider, model=model, temperature=temperature, max_tokens=EXPERT_COMPACTION_MAX_TOKENS)
    try:
        return _clean(raw["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        return ""


def _remember(session_id: str, key: str, count: int, note: str) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        oldest = min(_CACHE.items(), key=lambda kv: kv[1]["ts"])[0]
        _CACHE.pop(oldest, None)
    _CACHE[session_id] = {"key": key, "count": count, "note": note, "ts": time.monotonic()}


def cached_note(session_id: Optional[str]) -> Optional[str]:
    entry = _CACHE.get(session_id or "")
    return entry["note"] if entry else None


def needs_summary(history: Optional[List[Dict[str, Any]]], session_id: Optional[str]) -> int:
    """How many older turns :func:`prepare` would summarize with a model call now (0: nothing
    overflowed, or the session's note already covers them). No model call — the stream uses it
    to show "Compacting the conversation…" before the summary starts."""
    if not EXPERT_COMPACTION_ENABLED:
        return 0
    older, _window = split(history)
    if not older:
        return 0
    key = _digest(older)
    cached = _CACHE.get(session_id or "")
    if cached and cached["key"] == key:
        return 0
    if cached and cached["count"] < len(older) and _digest(older[: cached["count"]]) == cached["key"]:
        return len(older) - cached["count"]
    return len(older)


async def prepare(
    history: Optional[List[Dict[str, Any]]],
    *,
    session_id: Optional[str],
    provider: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    """``(window, note, notice)``: the turns to send verbatim, the note for the ones before
    them (None when nothing overflowed), and a user-facing notice when summarizing failed.

    Incremental per session: a thread whose overflow grew by two turns summarizes those two
    on top of the previous note, not the whole history again."""
    older, window = split(history)
    if not EXPERT_COMPACTION_ENABLED or not older:
        return window, None, None
    key = _digest(older)
    cached = _CACHE.get(session_id or "")
    if cached and cached["key"] == key:
        return window, cached["note"], None
    previous, new_turns = "", older
    if cached and cached["count"] < len(older) and _digest(older[: cached["count"]]) == cached["key"]:
        previous, new_turns = cached["note"], older[cached["count"]:]
    transcript = render(new_turns, EXPERT_COMPACTION_MAX_INPUT_CHARS)
    try:
        note = await summarize(previous, transcript, provider, model, temperature)
    except Exception as exc:  # noqa: BLE001
        logger.warning("compaction: summarizing %d older turns failed: %s", len(new_turns), exc)
        notice = (
            f"The earlier part of this conversation could not be summarized ({type(exc).__name__}); "
            f"only the last {len(window)} turns are in context."
        )
        return window, previous or None, notice
    if not note:
        return window, previous or None, None
    if session_id:
        _remember(session_id, key, len(older), note)
    return window, note, None
