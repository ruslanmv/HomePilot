"""What one Expert request is grounded in: today's date, and — when the chat searched the web —
the numbered sources HomePilot found (``backend/app/web_search.py``).

Expert's three pipelines build their own prompts (fast: ``router.build_messages``; think:
``thinking._msg``; heavy: ``heavy._msg``), and think and heavy never see the history. So the
grounding rides on the system prompt itself, through every step, the way ``target.py`` carries
the chosen model: a context variable set for the request, applied with :func:`apply`.

Without the date a model answers "which day is today?" from its training data; without sources
it recites old news as current. Both happened in Fast mode before this.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Iterator, Optional

_CURRENT: ContextVar[str] = ContextVar("expert_grounding", default="")

#: The most a request may add to the prompt (a web-results block is ~5-8 kB).
MAX_CONTEXT_CHARS = 24_000


def date_line(timezone: Optional[str] = None, now: Optional[datetime] = None) -> str:
    """Today's date and time, in the user's zone when the browser sent one."""
    moment = (now or datetime.now()).astimezone()
    zone = ""
    if timezone:
        try:
            from zoneinfo import ZoneInfo

            moment = moment.astimezone(ZoneInfo(timezone))
            zone = timezone
        except Exception:  # noqa: BLE001 — an unknown name falls back to the server's zone
            zone = ""
    zone = zone or (moment.tzname() or "")
    stamp = moment.strftime("%A, %B %d, %Y, %H:%M").replace(" 0", " ")
    return (
        f"Current date and time: {stamp}{f' ({zone})' if zone else ''}. Use it for anything that "
        "depends on today's date. Your own knowledge stops at your training cutoff: for news, prices, "
        "scores or anything else that may have changed since, say you cannot check live information "
        "unless web results are provided, and never invent recent events."
    )


@contextmanager
def using(timezone: Optional[str] = None, context: Optional[str] = None) -> Iterator[str]:
    """Ground every prompt built inside the block in today's date and ``context``."""
    parts = [date_line(timezone)]
    extra = (context or "").strip()
    if extra:
        parts.append(extra[:MAX_CONTEXT_CHARS])
    token = _CURRENT.set("\n\n".join(parts))
    try:
        yield _CURRENT.get()
    finally:
        _CURRENT.reset(token)


def apply(system_prompt: str) -> str:
    """``system_prompt`` with this request's grounding appended (unchanged outside a request)."""
    extra = _CURRENT.get()
    return f"{system_prompt}\n\n{extra}" if extra else system_prompt
