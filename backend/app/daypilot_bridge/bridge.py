"""DayPilot bridge protocol — header parsing, propose-mode instruction, and
directive extraction for the OpenAI-compatible persona endpoint (Batch A5).

Contract (frozen, mirrored from DayPilot's runtime contract):
  * DayPilot sends ``X-HomePilot-Tool-Mode: propose`` on every turn.
  * HomePilot reasons with the persona but returns *proposed* operations as
    structured directives in ``x_directives`` — it performs no external writes.
  * DayPilot validates each directive (type ∈ allowed set, capability ∈ allowed
    set, argument bounds, workspace ownership) and gates external actions behind
    its Approval Center.

The persona expresses a proposal by appending a single machine block at the very
end of its reply::

    [[DAYPILOT_DIRECTIVES]]{ "directives": [ ... ] }[[/DAYPILOT_DIRECTIVES]]

HomePilot parses that block, validates it defensively (the model output is
untrusted), strips it from the visible content, and returns the directives.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

BRIDGE_VERSION = 1

# The tool modes DayPilot may request. Only ``propose`` is ever used in
# production; the others exist so the contract is total.
TOOL_MODES: frozenset[str] = frozenset({"propose", "execute", "disabled"})
DEFAULT_TOOL_MODE = "propose"

# Directive types DayPilot accepts. Anything else is dropped while the plain-text
# reply is preserved.
ALLOWED_DIRECTIVES: frozenset[str] = frozenset(
    {
        "task.create",
        "task.update",
        "task.complete",
        "task.block",
        "progress.report",
        "delegate.request",
        "daypilot.action.propose",
        "artifact.attach",
    }
)

# DayPilot capabilities a ``daypilot.action.propose`` directive may target. Every
# one of these still becomes a draft + Approval on the DayPilot side — HomePilot
# never performs the action itself.
CAPABILITIES: frozenset[str] = frozenset(
    {
        "email.send",
        "calendar.create",
        "calendar.update",
        "calendar.cancel",
        "coding.run",
        "github.change",
        "message.send",
        "document.generate",
        "finance.change",
        "hr.change",
        "system.change",
    }
)

VALID_PRIORITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})

# Defensive bounds on untrusted model output (match DayPilot's validation).
MAX_DIRECTIVES_PER_TURN = 12
MAX_TITLE_LEN = 200
MAX_TEXT_LEN = 4000

# Sentinel-delimited machine block. Tolerant of surrounding whitespace and an
# optional markdown code fence the model may wrap it in.
_BLOCK_RE = re.compile(
    r"`{0,3}\s*\[\[DAYPILOT_DIRECTIVES\]\]\s*(?P<body>.*?)\s*\[\[/DAYPILOT_DIRECTIVES\]\]\s*`{0,3}",
    re.DOTALL,
)


@dataclass(frozen=True)
class BridgeContext:
    """Parsed state of a bridge-aware request.

    ``active`` is True when DayPilot (or any bridge-aware client) is calling, so
    the endpoint should attach ``x_directives`` / ``x_homepilot``. ``propose`` is
    True in the only production mode: propose-only. ``session_id`` is DayPilot's
    external session id, echoed back so DayPilot can correlate turns.
    """

    active: bool
    tool_mode: str
    session_id: str | None
    bridge_version: int

    @property
    def propose(self) -> bool:
        return self.tool_mode == "propose"


def parse_bridge_headers(
    *,
    x_client_type: str | None,
    tool_mode: str | None,
    session_id: str | None,
    bridge_version: str | None,
) -> BridgeContext:
    """Derive the bridge context from request headers.

    The bridge is *active* when the caller identifies as DayPilot via
    ``X-Client-Type: daypilot`` OR sends any explicit bridge header. An unknown
    tool mode falls back to the safe default (propose) — HomePilot never executes
    on DayPilot's behalf, so the conservative default is also the correct one.
    """
    client = (x_client_type or "").strip().lower()
    mode_raw = (tool_mode or "").strip().lower()
    active = client == "daypilot" or bool(mode_raw) or bool(bridge_version)
    mode = mode_raw if mode_raw in TOOL_MODES else DEFAULT_TOOL_MODE
    try:
        ver = int(bridge_version) if bridge_version else BRIDGE_VERSION
    except (TypeError, ValueError):
        ver = BRIDGE_VERSION
    sid = (session_id or "").strip() or None
    return BridgeContext(active=active, tool_mode=mode, session_id=sid, bridge_version=ver)


def propose_system_suffix() -> str:
    """The propose-mode instruction, appended as a SEPARATE system message.

    Never modifies the persona's own prompt. It tells the persona that it is
    connected to DayPilot, cannot act on the outside world itself, and how to
    propose an action as a machine block. On an ordinary conversational turn the
    persona simply omits the block.
    """
    return (
        "[DAYPILOT BRIDGE — propose-only mode, appended only for this turn]\n"
        "You are connected to DayPilot, which manages the user's real tasks, "
        "email, calendar, and projects. You CANNOT send email, change files, "
        "schedule events, or complete tasks yourself — DayPilot does that, and "
        "only after the user approves it.\n"
        "Reply to the user normally. THEN, only if you intend a concrete action "
        "or want to track work, append ONE machine block at the very end, exactly:\n"
        "[[DAYPILOT_DIRECTIVES]]{\"directives\":[ ... ]}[[/DAYPILOT_DIRECTIVES]]\n"
        "Each directive is an object with a \"type\". Allowed types: "
        "task.create (title, priority, detail), task.update, task.complete, "
        "task.block, progress.report (summary, percent), delegate.request, "
        "artifact.attach, and daypilot.action.propose (capability + summary + "
        "arguments) for anything that touches the outside world — capability is "
        "one of: email.send, calendar.create, calendar.update, calendar.cancel, "
        "message.send, document.generate, coding.run, github.change.\n"
        "Never invent results or claim an action is done. Propose, don't perform. "
        "If no action is needed, omit the block entirely."
    )


def _clip(value: Any, limit: int) -> str:
    return str(value)[:limit] if value is not None else ""


def _sanitize_directive(raw: Any) -> dict[str, Any] | None:
    """Validate + normalize one untrusted directive. Returns None if invalid."""
    if not isinstance(raw, dict):
        return None
    dtype = str(raw.get("type") or "").strip()
    if dtype not in ALLOWED_DIRECTIVES:
        return None

    out: dict[str, Any] = {"type": dtype}

    if dtype == "daypilot.action.propose":
        capability = str(raw.get("capability") or "").strip()
        if capability not in CAPABILITIES:
            return None  # a real-world action with no valid capability is unusable
        out["capability"] = capability
        out["summary"] = _clip(raw.get("summary") or raw.get("title"), MAX_TITLE_LEN)
        args = raw.get("arguments")
        if isinstance(args, dict):
            out["arguments"] = args

    if "title" in raw:
        out["title"] = _clip(raw.get("title"), MAX_TITLE_LEN)
    if "detail" in raw or "text" in raw:
        out["detail"] = _clip(raw.get("detail") or raw.get("text"), MAX_TEXT_LEN)
    if "summary" in raw and "summary" not in out:
        out["summary"] = _clip(raw.get("summary"), MAX_TITLE_LEN)

    priority = str(raw.get("priority") or "").strip().lower()
    if priority in VALID_PRIORITIES:
        out["priority"] = priority

    if "percent" in raw:
        try:
            out["percent"] = max(0, min(100, int(raw.get("percent"))))
        except (TypeError, ValueError):
            pass

    # Preserve an optional client-supplied ref so DayPilot can de-duplicate.
    if raw.get("ref"):
        out["ref"] = _clip(raw.get("ref"), 120)

    return out


def extract_directives(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Pull the directive block out of a persona reply.

    Returns ``(visible_content, directives)``. The machine block is stripped from
    the visible content. Malformed JSON or unknown directive types are dropped
    silently — the plain-text reply is always preserved. At most
    ``MAX_DIRECTIVES_PER_TURN`` valid directives are returned.
    """
    if not content:
        return content, []
    match = _BLOCK_RE.search(content)
    if not match:
        return content, []

    visible = (content[: match.start()] + content[match.end():]).strip()

    directives: list[dict[str, Any]] = []
    try:
        parsed = json.loads(match.group("body"))
    except (ValueError, TypeError):
        return visible, []

    items = parsed.get("directives") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return visible, []

    for raw in items:
        clean = _sanitize_directive(raw)
        if clean is not None:
            directives.append(clean)
        if len(directives) >= MAX_DIRECTIVES_PER_TURN:
            break

    return visible, directives


def build_x_homepilot(
    ctx: BridgeContext,
    *,
    project_id: str | None,
    model: str,
    directive_count: int,
) -> dict[str, Any]:
    """Bridge metadata returned alongside the OpenAI response so DayPilot can
    correlate the turn and confirm the mode HomePilot honored."""
    return {
        "bridge_version": BRIDGE_VERSION,
        "tool_mode": ctx.tool_mode,
        "session_id": ctx.session_id,
        "project_id": project_id,
        "model": model,
        "directive_count": directive_count,
    }


def capabilities_document() -> dict[str, Any]:
    """Static description of what this HomePilot bridge supports, served at
    ``/v1/integrations/daypilot/capabilities`` so DayPilot can feature-detect a
    bridge-aware HomePilot without a chat round-trip."""
    return {
        "bridge_version": BRIDGE_VERSION,
        "tool_modes": sorted(TOOL_MODES),
        "default_tool_mode": DEFAULT_TOOL_MODE,
        "directives": sorted(ALLOWED_DIRECTIVES),
        "capabilities": sorted(CAPABILITIES),
        "limits": {
            "max_directives_per_turn": MAX_DIRECTIVES_PER_TURN,
            "max_title_len": MAX_TITLE_LEN,
            "max_text_len": MAX_TEXT_LEN,
        },
        "headers": {
            "tool_mode": "X-HomePilot-Tool-Mode",
            "session_id": "X-HomePilot-Session-ID",
            "bridge_version": "X-HomePilot-Bridge-Version",
            "client_type": "X-Client-Type",
        },
        "response_fields": ["x_directives", "x_homepilot"],
        "notes": "Propose-only: HomePilot never performs external writes; DayPilot validates and approves.",
    }
