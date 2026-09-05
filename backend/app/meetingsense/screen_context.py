"""What a persona knows about the screen being shared right now (batch MS29, wave W11).

The bug this exists for: the user presses **👁 Share screen**, the vision model captions the
frame perfectly, and then the chat says *"No, I can't see your screen."* Nothing was broken —
the caption went into ScreenSense's own panel and the chat model was never told any of it, so
from where it sat that answer was true. It was also the worst kind of wrong: a flat **capability
claim** that teaches the user not to bother asking again.

**Presence, then content.** Two different things with two different risks:

- *Presence* — "a screen is being shared" — leaks nothing about what is on it, and on its own
  fixes the reported bug. A persona that knows sharing is live never denies it, and can offer
  to look.
- *Content* — the last caption — is genuinely useful and is genuinely screen content going into
  a prompt. So it is capped, it carries its age, and it **expires**: a caption from four minutes
  ago describes a screen that is gone, and confidently describing it is worse than saying
  nothing.

**Why this one defaults on when the rest of MeetingSense defaults off.** Every other flag in
this feature gates a capability that would otherwise run in the background. This one only
produces a block *while the user is actively sharing their screen* — a deliberate action, with
an operating-system indicator on it, that they took in order to be seen. It appears when they
share and it is gone the moment they stop. `MEETINGSENSE_SCREEN=false` turns it off entirely,
and the Settings toggle writes that.

**Off is byte-identical**, the rule MS18 set for the same seam: no share, or the flag down, and
this returns ``""`` so the prompt is character-for-character what it was before.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

#: What the block is called in the prompt. Named, like MS18's, so a persona can be told about
#: it once and a reader debugging a transcript can find it.
BLOCK_HEADER = "[LIVE SCREEN]"

#: How long a caption is worth repeating, in seconds. Past this the screen has almost certainly
#: moved on, and the *presence* line still stands on its own.
CAPTION_TTL_S = 90.0

#: How long a share is believed without being renewed. A browser tab that closed mid-share
#: sends no "stopped", so presence has to expire by itself or a persona claims to see a screen
#: that was put away an hour ago.
PRESENCE_TTL_S = 300.0

#: Characters of caption carried into the prompt. A vision model asked an open question will
#: happily write a paragraph; the prompt is not the place to find that out.
MAX_CAPTION_CHARS = 400

_lock = threading.Lock()
#: conversation_id → {"mode", "started_at", "seen_at", "caption", "caption_at"}
_shares: Dict[str, Dict[str, Any]] = {}


def enabled() -> bool:
    """On unless an operator turned it off. See the module docstring for why this one differs."""
    raw = os.getenv("MEETINGSENSE_SCREEN", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _now() -> float:
    return time.time()


def begin(conversation_id: str, *, mode: str = "browser", now: Optional[float] = None) -> bool:
    """The user started sharing. ``True`` if it was recorded."""
    cid = (conversation_id or "").strip()
    if not cid:
        return False
    stamp = now if now is not None else _now()
    with _lock:
        existing = _shares.get(cid)
        if existing:
            # A renewal, not a new share: keep the original start so "sharing for 12 minutes"
            # stays true across the pings that keep it alive.
            existing["seen_at"] = stamp
            existing["mode"] = mode or existing.get("mode") or "browser"
            return True
        _shares[cid] = {"mode": mode or "browser", "started_at": stamp, "seen_at": stamp,
                        "caption": "", "caption_at": 0.0}
    return True


def end(conversation_id: str) -> bool:
    """The user stopped sharing. Everything about it goes, including the last caption.

    A hard delete, like MS27's prep material and for the same reason: this is the user's screen,
    and "stop sharing" that leaves the last thing seen in a prompt has not stopped anything.
    """
    with _lock:
        return _shares.pop((conversation_id or "").strip(), None) is not None


def observe(conversation_id: str, caption: str, *, now: Optional[float] = None) -> bool:
    """Record the newest thing the vision model read off the screen.

    Ignored when nothing is being shared. A caption arriving for a conversation with no live
    share is a late answer to a question about a screen that is already put away.
    """
    cid = (conversation_id or "").strip()
    body = (caption or "").strip()
    if not cid or not body:
        return False
    stamp = now if now is not None else _now()
    with _lock:
        share = _shares.get(cid)
        if share is None:
            return False
        share["caption"] = body[:MAX_CAPTION_CHARS]
        share["caption_at"] = stamp
        share["seen_at"] = stamp
    return True


def active(conversation_id: str, *, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The live share for this conversation, or ``None``. Expiring one on the way out."""
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    stamp = now if now is not None else _now()
    with _lock:
        share = _shares.get(cid)
        if share is None:
            return None
        if stamp - float(share.get("seen_at") or 0) > PRESENCE_TTL_S:
            # A tab that closed mid-share never said so. Believing it forever is how a persona
            # ends up insisting it can see a screen that was put away an hour ago.
            _shares.pop(cid, None)
            return None
        return dict(share)


def _minutes(seconds: float) -> str:
    """How long, in words a sentence can use."""
    if seconds < 90:
        return "just now"
    return f"{int(round(seconds / 60))} minutes ago"


def build(conversation_id: str, *, now: Optional[float] = None) -> str:
    """The block, or ``""``. Never raises.

    Deliberately three short lines. This sits in front of every message of a conversation while
    a share is live, and a block that grows is a block that starts costing the user answers.
    """
    share = active(conversation_id, now=now)
    if share is None:
        return ""
    stamp = now if now is not None else _now()

    lines: List[str] = [BLOCK_HEADER]
    since = _minutes(stamp - float(share.get("started_at") or stamp))
    where = "their desktop" if share.get("mode") == "desktop" else "a window or tab they picked"
    lines.append(f"The user is sharing their screen with you right now — {where}, started {since}.")

    caption = (share.get("caption") or "").strip()
    caption_age = stamp - float(share.get("caption_at") or 0)
    if caption and caption_age <= CAPTION_TTL_S:
        lines.append(f"The last look at it, {_minutes(caption_age)}: {caption}")
    elif caption:
        # Held back rather than shown stale. The presence line above still stands, and asking
        # for a fresh look is cheap; describing a screen that has moved on is not.
        lines.append("You have not looked recently, so ask for a fresh look before describing it.")

    lines.append(
        "Never tell them you cannot see their screen. If they ask about it, take a look."
    )
    return "\n".join(lines)


def for_conversation(conversation_id: str) -> str:
    """The entry point `prompt_builder` calls. ``""`` on anything unexpected.

    Never raises: a chat that failed because somebody was sharing their screen would be a far
    worse bug than no screen context at all — which is MS18's rule on this seam, kept.
    """
    try:
        if not enabled():
            return ""
        return build(conversation_id)
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: screen context failed")
        return ""


def _reset_for_tests() -> None:
    with _lock:
        _shares.clear()
