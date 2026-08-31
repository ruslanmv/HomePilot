"""display — structured data on the virtual screen (addendum v1.2 §14.3, batch B20).

The panel channel. A `display` message carries a *kind* and some data; the client draws it
onto a canvas and puts that canvas on the screen it already has. Nothing here knows how it
looks — this side owns what may be sent, and the size limit.

## Rejected, never truncated

`assistant.panelMaxKb` is 64 KB, and a payload over it comes back as an error naming the
size. It is not trimmed to fit, and that is the whole point: a truncated agenda is an agenda
with the afternoon missing, rendered as confidently as a complete one, and the user has no
way to tell. A refusal is legible; a silent trim is a lie the screen tells.

The check is on the **serialised message**, not on the data structure, because what the cap
protects is the wire and the client's canvas — and a small object with one enormous string
in it costs exactly what a large object costs.

## Five kinds, and a closed set

`agenda`, `cards`, `tool_result`, `stats`, `share`. Closed on purpose: the renderer draws
each one differently, so a kind it does not know is a blank screen. An unknown kind is
refused here rather than sent and ignored there — the sender is the one who can fix it.

The renderer is the reusable half of this batch (B21's assistant is one consumer, the coach
and the share cards are others), which is why the two are separate batches.

Pure module: no FastAPI, no I/O.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .protocol import PROTOCOL_VERSION

log = logging.getLogger("avatar_director.panels")

#: What a panel may be. Closed — see the module header.
KINDS = ("agenda", "cards", "tool_result", "stats", "share")

#: Matches `assistant.panelMaxKb` in the client's config. Both sides know the number; the
#: server is the one that enforces it, because it is the one that can refuse.
DEFAULT_MAX_KB = 64

#: Per-kind row limits. A panel is a screen, not a document: an agenda with two hundred
#: entries is unreadable at any resolution, and rendering it would be a worse answer than
#: refusing it.
MAX_ROWS = {"agenda": 24, "cards": 12, "tool_result": 40, "stats": 16, "share": 8}


class PanelError(Exception):
    """A refusal with a code the protocol can carry."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _rows(kind: str, data: Dict[str, Any]) -> List[Any]:
    """The list a kind renders as rows, whatever that kind calls it."""
    for key in ("items", "cards", "rows", "stats", "lines"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def validate(kind: str, data: Any) -> List[str]:
    """Every problem with this panel, or an empty list. Fail-soft: never raises."""
    problems: List[str] = []
    if kind not in KINDS:
        problems.append(f"unknown kind {kind!r}; expected one of {', '.join(KINDS)}")
    if not isinstance(data, dict):
        return problems + ["data must be an object"]

    title = data.get("title")
    if title is not None and not isinstance(title, str):
        problems.append("title must be a string")

    rows = _rows(kind, data)
    limit = MAX_ROWS.get(kind, 24)
    if len(rows) > limit:
        problems.append(f"{len(rows)} rows exceeds the {limit} a {kind} panel can show")

    for index, row in enumerate(rows):
        if not isinstance(row, (dict, str)):
            problems.append(f"row {index} is neither an object nor a string")

    return problems


def measure(message: Dict[str, Any]) -> int:
    """The serialised size in bytes — what actually crosses the wire."""
    return len(json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def build(kind: str, data: Dict[str, Any], *, max_kb: int = DEFAULT_MAX_KB) -> Dict[str, Any]:
    """One `display` message, or a :class:`PanelError`.

    The order matters: shape first, then size. A malformed panel that is also too large
    should be reported as malformed, because that is the fault the sender can act on.
    """
    problems = validate(kind, data)
    if problems:
        raise PanelError("panel_invalid", "; ".join(problems))

    message = {"v": PROTOCOL_VERSION, "type": "display", "kind": kind, "data": data}
    size = measure(message)
    limit = max(1, int(max_kb)) * 1024
    if size > limit:
        # Named in both units, because "68210 bytes" and "over 64 KB" answer different
        # questions and a sender needs both to decide what to cut.
        raise PanelError("panel_too_large", f"{size} bytes exceeds the {max_kb} KB panel limit")
    return message


def truncatable(kind: str, data: Dict[str, Any], *, max_kb: int = DEFAULT_MAX_KB) -> Tuple[bool, Optional[str]]:
    """Would this fit, and if not, what would the sender have to drop?

    Advice, not action. Nothing here trims anything — this exists so a caller that *wants*
    to send a shorter panel can be told how much shorter, rather than discovering it by
    having one silently mangled.
    """
    try:
        build(kind, data, max_kb=max_kb)
    except PanelError as error:
        if error.code != "panel_too_large":
            return False, error.detail
        rows = _rows(kind, data)
        if not rows:
            return False, "the payload is too large and has no rows to drop"
        size = measure({"v": PROTOCOL_VERSION, "type": "display", "kind": kind, "data": data})
        per_row = max(1, size // max(1, len(rows)))
        keep = max(0, (max_kb * 1024) // per_row - 1)
        return False, f"about {len(rows) - keep} of {len(rows)} rows would have to go"
    return True, None
