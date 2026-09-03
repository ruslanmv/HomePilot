"""MCP server: meetingsense — a meeting, reachable as tools (batch MS21, wave W7).

Ten tools over what the previous six waves built. Nothing here computes anything: every tool
is a thin call into `backend/app/meetingsense/`, which is the point of putting this batch last
rather than first. A capability layer that reimplemented retrieval, or the live context, or the
notes shape would be a second answer to every question the product already answers, and the two
would drift the first time a batch changed one of them.

## Reads are free; writes are gated

`update_action`, `suggest`, `set_mode` and `export` change something or leave something behind.
They are behind ``WRITE_ENABLED`` exactly as `local-notes` is, and refuse with an explanation
rather than failing — an agent told "write disabled" can say so; one handed a stack trace
cannot. Reads need no gate: a meeting is the user's own recording, on the user's own machine,
and this server is not reachable from outside it.

## It talks HTTP, like its neighbours

The MCP image contains `agentic/` and nothing else — no `backend/` — so importing
`app.meetingsense` here would work from the Makefile and fail in the container, which is the
worst of the two. So every tool is one call to the backend, the way `inventory` does it, and
MS21 added the four routes that did not exist yet (`meetings`, `search`, the live block, and
the notes amendment). One transport, one place the data lives.

## It is honest about not being there

MeetingSense is off by default and most installs never turn it on, and the backend may not be
running at all. Every tool answers "this install has no meetings" rather than raising, so a
persona that asks about a meeting on a machine with none gets a sentence it can pass on
instead of a tool error it cannot.

## Port 9107, and why that matters

D3 assigns it. 9101–9105 are the core servers, 9110–9120 the local ones, and 9106 belongs to
`hp-teams` — registered and unbuilt (MS22). A test asserts 9107 is not a port the Makefile
already starts, because two servers on one port is a failure that looks like a broken tool
rather than a broken port.

Usage:
    uvicorn agentic.integrations.mcp.meetingsense.app:app --port 9107
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

log = logging.getLogger("mcp.meetingsense")

#: The port D3 assigns. Named here so the compose file, the Makefile and the test that checks
#: for a collision all read one number.
PORT = 9107

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

#: Most meetings a list returns. A persona that asks for "my meetings" wants the recent ones;
#: an install with four hundred of them should not put four hundred into a prompt.
MAX_LIST = 25

#: Most transcript segments one call returns. Beyond this the answer is `ms.search`, which is
#: what retrieval is for — a tool that can return an entire two-hour transcript is a tool that
#: will, into a context window that cannot hold it.
MAX_SEGMENTS = 200


def _text(text: str, **meta: Any) -> Json:
    out: Json = {"content": [{"type": "text", "text": text}]}
    if meta:
        out["meta"] = meta
    return out


def _write_gate(action: str) -> Optional[Json]:
    """The refusal, or None. Same shape and wording as `local-notes`, deliberately."""
    if WRITE_ENABLED:
        return None
    message = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
    if DRY_RUN:
        message += " (DRY_RUN mode — no changes made)"
    return _text(message, ok=False, write_enabled=False)


BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")

#: A backend that has not answered in this long is not answering. Short, because every one of
#: these is inside a persona's turn and a model waiting thirty seconds has already lost.
TIMEOUT_S = float(os.getenv("MEETINGSENSE_MCP_TIMEOUT_S", "8"))


class Unreachable(Exception):
    """The backend did not answer, or answered with a failure. Never escapes a tool."""


async def _request(method: str, path: str, **kwargs) -> Any:
    """One call to the backend. Raises :class:`Unreachable`; tools turn that into a sentence."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.request(method, f"{BACKEND_BASE_URL}{path}", **kwargs)
    except Exception as error:  # noqa: BLE001 — no backend is a capability, not a crash
        raise Unreachable(str(error)) from None
    if response.status_code == 404:
        raise Unreachable("not found")
    if response.status_code >= 400:
        raise Unreachable(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        return response.text


async def _get(path: str, **params) -> Any:
    return await _request("GET", path, params={k: v for k, v in params.items() if v not in (None, "")})


async def _post(path: str, body: Json) -> Any:
    return await _request("POST", path, json=body)


def _unavailable(error: Any = None, meeting_id: str = "") -> Json:
    """The one answer for every kind of "there is nothing here".

    A missing meeting, a disabled feature and a backend that is not running are three
    different causes and one useful sentence: a persona can pass this on, and cannot pass on
    a tool error. The cause is in the metadata for whoever is debugging.
    """
    if str(error) == "not found" and meeting_id:
        return _text(f"No meeting '{meeting_id}'.", ok=False, available=True)
    return _text(
        "MeetingSense is not available on this install. Set MEETINGSENSE_ENABLED=true and "
        "restart to record meetings.",
        ok=False,
        available=False,
        reason=str(error) if error is not None else None,
    )


def _summary(meeting: Dict[str, Any]) -> Json:
    """One meeting, as much as a list row should carry and no more."""
    return {
        "meeting_id": meeting.get("id") or meeting.get("meeting_id"),
        "title": meeting.get("title") or "Meeting",
        "source": meeting.get("source"),
        "status": meeting.get("status"),
        "started_at": meeting.get("started_at"),
        "ended_at": meeting.get("ended_at"),
    }


def clock(ms: Any) -> str:
    """``hh:mm:ss``. Four lines rather than an import: the backend owns the transcript, and
    this server owns nothing — pulling in its formatter would make that untrue."""
    total = max(0, int(ms or 0)) // 1000
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


# ── reads ───────────────────────────────────────────────────────────────────


async def list_meetings(args: Json) -> Json:
    limit = max(1, min(int(args.get("limit", 10) or 10), MAX_LIST))
    conversation_id = str(args.get("conversation_id", "") or "").strip()
    try:
        body = await _get("/v1/meetingsense/meetings", limit=limit,
                          conversation_id=conversation_id)
    except Unreachable as error:
        return _unavailable(error)
    rows = [_summary(m) for m in (body or {}).get("meetings") or []]
    if not rows:
        return _text("No meetings have been recorded on this install.", ok=True, meetings=[])
    lines = [f"{len(rows)} meeting{'' if len(rows) == 1 else 's'}:"]
    lines += [f"- {m['title']} ({m['meeting_id']}) · {m['status']}" for m in rows]
    return _text("\n".join(lines), ok=True, meetings=rows)


async def _meeting_bundle(meeting_id: str) -> Json:
    return await _get(f"/v1/meetingsense/{meeting_id}")


async def get_meeting(args: Json) -> Json:
    meeting_id = str(args.get("meeting_id", "") or "").strip()
    if not meeting_id:
        return _text("Please provide a 'meeting_id'.", ok=False)
    try:
        bundle = await _meeting_bundle(meeting_id)
    except Unreachable as error:
        return _unavailable(error, meeting_id)
    notes = ((bundle.get("notes") or {}).get("notes")) or bundle.get("notes") or {}
    if not isinstance(notes, dict):
        notes = {}
    segments = bundle.get("segments") or []
    keyframes = bundle.get("keyframes") or []
    meeting = bundle.get("meeting") or {}
    recap = (notes.get("recap") or notes.get("summary") or "").strip()
    return _text(
        recap or f"{meeting.get('title') or 'Meeting'} — {len(segments)} segments, no notes taken.",
        ok=True,
        meeting=_summary(meeting),
        # The counts, not the rows: a "get" that returned the transcript would make
        # `get_transcript` and its cap pointless.
        counts={"segments": len(segments), "slides": len(keyframes)},
        notes=notes,
        live=bool(bundle.get("live")),
    )


async def get_transcript(args: Json) -> Json:
    meeting_id = str(args.get("meeting_id", "") or "").strip()
    if not meeting_id:
        return _text("Please provide a 'meeting_id'.", ok=False)
    try:
        bundle = await _meeting_bundle(meeting_id)
    except Unreachable as error:
        return _unavailable(error, meeting_id)

    segments = bundle.get("segments") or []
    total = len(segments)
    offset = max(0, int(args.get("offset", 0) or 0))
    limit = max(1, min(int(args.get("limit", 50) or 50), MAX_SEGMENTS))
    window = segments[offset : offset + limit]
    rows = [{"t0_ms": s.get("t0_ms"), "speaker": s.get("speaker"), "text": s.get("text"),
             "stamp": clock(s.get("t0_ms"))} for s in window]
    body = "\n".join(f"[{r['stamp']}] {r['speaker'] or '?'}: {r['text']}" for r in rows)
    more = offset + len(window) < total
    if more:
        # Said in the text, not only in the metadata: a model reading the content is the one
        # that has to decide whether to page or to search, and `ms.search` is usually right.
        body += (f"\n\n… {total - offset - len(window)} more segments. Page with 'offset', or "
                 "use ms.search to find the part you want.")
    return _text(body or "Nothing was transcribed.", ok=True, segments=rows, total=total,
                 offset=offset, has_more=more)


async def search(args: Json) -> Json:
    query = str(args.get("query", "") or "").strip()
    if not query:
        return _text("Please provide a 'query'.", ok=False)
    k = max(1, min(int(args.get("k", 8) or 8), 25))
    try:
        body = await _get("/v1/meetingsense/search", q=query,
                          meeting_id=str(args.get("meeting_id", "") or "").strip(), k=k)
    except Unreachable as error:
        return _unavailable(error)
    rows = (body or {}).get("results") or []
    if not rows:
        return _text(
            "Nothing matched. Meetings are indexed when they stop, so a meeting still running "
            "is not searchable yet — ask about it with ms.get_live_context.",
            ok=True, results=[],
        )
    lines = [f"{len(rows)} match{'' if len(rows) == 1 else 'es'}:"]
    lines += [f"- [{r.get('cite')}] {r.get('text')}" for r in rows]
    return _text("\n".join(lines), ok=True, results=rows)


async def get_live_context(args: Json) -> Json:
    conversation_id = str(args.get("conversation_id", "") or "").strip()
    if not conversation_id:
        return _text("Please provide a 'conversation_id'.", ok=False)
    try:
        body = await _get(f"/v1/meetingsense/conversations/{conversation_id}/live")
    except Unreachable as error:
        return _unavailable(error)
    block = (body or {}).get("block") or ""
    if not block:
        return _text("No meeting is being recorded in that conversation.", ok=True, live=False)
    # The same bounded block MS18 puts in a system prompt, not a bigger one: a tool that
    # returned more than the prompt does would be a way around D9's budget.
    return _text(block, ok=True, live=True)


async def get_slide(args: Json) -> Json:
    meeting_id = str(args.get("meeting_id", "") or "").strip()
    if not meeting_id:
        return _text("Please provide a 'meeting_id'.", ok=False)
    try:
        bundle = await _meeting_bundle(meeting_id)
    except Unreachable as error:
        return _unavailable(error, meeting_id)
    frames = bundle.get("keyframes") or []
    if not frames:
        return _text("That meeting has no slides.", ok=True, slides=[])
    at = args.get("at_ms")
    if at is not None:
        # The slide that was up at that moment: the last one taken at or before it, not the
        # nearest — on a deck clicked through quickly the nearest is often the one that came
        # next, which is a slide the speaker had not reached.
        target = int(at)
        earlier = [f for f in frames if int(f.get("t_ms") or 0) <= target]
        frames = [earlier[-1]] if earlier else [frames[0]]
    rows = [{"t_ms": f.get("t_ms"), "stamp": clock(f.get("t_ms")),
             "caption": f.get("caption"), "url": f.get("url")} for f in frames]
    lines = [f"[{r['stamp']}] {r['caption'] or '(not captioned)'}" for r in rows]
    return _text("\n".join(lines), ok=True, slides=rows)


# ── writes ──────────────────────────────────────────────────────────────────


async def update_action(args: Json) -> Json:
    refused = _write_gate("ms.update_action")
    if refused:
        return refused
    meeting_id = str(args.get("meeting_id", "") or "").strip()
    text = str(args.get("text", "") or "").strip()
    if not meeting_id or not text:
        return _text("Please provide 'meeting_id' and 'text'.", ok=False)
    payload: Json = {"op": "action", "text": text, "done": bool(args.get("done", True))}
    owner = str(args.get("owner", "") or "").strip()
    if owner:
        payload["owner"] = owner
    try:
        body = await _post(f"/v1/meetingsense/{meeting_id}/notes", payload)
    except Unreachable as error:
        return _unavailable(error, meeting_id)
    return _text(f"Action {'closed' if payload['done'] else 'reopened'}: {text}", ok=True,
                 version=(body or {}).get("version"), actions=(body or {}).get("actions"))


async def suggest(args: Json) -> Json:
    refused = _write_gate("ms.suggest")
    if refused:
        return refused
    meeting_id = str(args.get("meeting_id", "") or "").strip()
    text = str(args.get("text", "") or "").strip()
    if not meeting_id or not text:
        return _text("Please provide 'meeting_id' and 'text'.", ok=False)
    try:
        # Recorded beside the notes rather than merged into them: a suggestion is something an
        # agent thinks, and the notes are what the meeting said. Mixing them would make the
        # transcript's own record unciteable.
        body = await _post(f"/v1/meetingsense/{meeting_id}/notes",
                           {"op": "suggestion", "text": text,
                            "kind": str(args.get("kind", "note") or "note")})
    except Unreachable as error:
        return _unavailable(error, meeting_id)
    return _text(f"Noted: {text}", ok=True, artifact_id=(body or {}).get("artifact_id"))


async def set_mode(args: Json) -> Json:
    refused = _write_gate("ms.set_mode")
    if refused:
        return refused
    meeting_id = str(args.get("meeting_id", "") or "").strip()
    mode = str(args.get("mode", "") or "").strip().lower()
    if not meeting_id or not mode:
        return _text("Please provide 'meeting_id' and 'mode'.", ok=False)
    if mode not in MODES:
        # Refused here as well as at the backend, so an agent gets the list of modes without
        # spending a round trip on a typo.
        return _text(f"Unknown mode '{mode}'. Expected one of: {', '.join(MODES)}.", ok=False)
    try:
        body = await _post(f"/v1/meetingsense/{meeting_id}/notes", {"op": "mode", "mode": mode})
    except Unreachable as error:
        return _unavailable(error, meeting_id)
    return _text(f"Mode set to {mode}.", ok=True, mode=mode,
                 artifact_id=(body or {}).get("artifact_id"))


#: The helper modes W9 will implement. Listed because `set_mode` has to refuse an unknown one
#: now — a mode nobody implements yet is still a mode, and a typo is not.
MODES = ("note-taker", "participant", "presenter", "coach", "practice")

#: What `ms.export` can produce, matching `export.FORMATS`.
EXPORT_FORMATS = ("md", "srt", "json")


async def export_meeting(args: Json) -> Json:
    refused = _write_gate("ms.export")
    if refused:
        return refused
    meeting_id = str(args.get("meeting_id", "") or "").strip()
    fmt = str(args.get("format", "md") or "md").strip().lower()
    if not meeting_id:
        return _text("Please provide a 'meeting_id'.", ok=False)
    if fmt not in EXPORT_FORMATS:
        return _text(f"Unknown format '{fmt}'. Expected one of: "
                     f"{', '.join(EXPORT_FORMATS)}.", ok=False)
    try:
        body = await _get(f"/v1/meetingsense/{meeting_id}/export", fmt=fmt)
    except Unreachable as error:
        return _unavailable(error, meeting_id)
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=2)
    return _text(text, ok=True, format=fmt, bytes=len(text.encode("utf-8")))


# ── registration ────────────────────────────────────────────────────────────

_MEETING_ID = {"meeting_id": {"type": "string", "description": "The meeting's id"}}


def register_tools() -> List[ToolDef]:
    """The ten tools, six read and four gated.

    Named `ms.*` rather than `hp.meetingsense.*`: the design's tool table (part 2, §D.1) calls
    them `ms.search` and so on, and a persona prompt that names one has to name the same thing
    the catalog does.
    """
    return [
        ToolDef("ms.list_meetings", "Recent meetings, or the meetings in one conversation",
                {"type": "object", "properties": {
                    "limit": {"type": "integer"}, "conversation_id": {"type": "string"}}},
                list_meetings),
        ToolDef("ms.get_meeting", "One meeting: its recap, notes and counts",
                {"type": "object", "properties": dict(_MEETING_ID), "required": ["meeting_id"]},
                get_meeting),
        ToolDef("ms.get_transcript", "A page of one meeting's transcript",
                {"type": "object", "properties": {
                    **_MEETING_ID, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
                 "required": ["meeting_id"]},
                get_transcript),
        ToolDef("ms.search", "Search across meetings, or inside one; answers cite meeting and time",
                {"type": "object", "properties": {
                    "query": {"type": "string"}, **_MEETING_ID, "k": {"type": "integer"}},
                 "required": ["query"]},
                search),
        ToolDef("ms.get_live_context", "What is happening in the meeting running in a conversation",
                {"type": "object", "properties": {"conversation_id": {"type": "string"}},
                 "required": ["conversation_id"]},
                get_live_context),
        ToolDef("ms.get_slide", "A meeting's slides, or the one on screen at a moment",
                {"type": "object", "properties": {**_MEETING_ID, "at_ms": {"type": "integer"}},
                 "required": ["meeting_id"]},
                get_slide),
        ToolDef("ms.update_action", "Close or reopen an action item [write-gated]",
                {"type": "object", "properties": {
                    **_MEETING_ID, "text": {"type": "string"}, "done": {"type": "boolean"},
                    "owner": {"type": "string"}},
                 "required": ["meeting_id", "text"]},
                update_action),
        ToolDef("ms.suggest", "Leave a suggestion against a meeting [write-gated]",
                {"type": "object", "properties": {
                    **_MEETING_ID, "text": {"type": "string"}, "kind": {"type": "string"}},
                 "required": ["meeting_id", "text"]},
                suggest),
        ToolDef("ms.set_mode", "Set a meeting's helper mode [write-gated]",
                {"type": "object", "properties": {
                    **_MEETING_ID, "mode": {"type": "string", "enum": list(MODES)}},
                 "required": ["meeting_id", "mode"]},
                set_mode),
        ToolDef("ms.export", "A meeting as Markdown, SRT or JSON [write-gated]",
                {"type": "object", "properties": {
                    **_MEETING_ID, "format": {"type": "string", "enum": ["md", "srt", "json"]}},
                 "required": ["meeting_id"]},
                export_meeting),
    ]


app = create_mcp_app(server_name="mcp-meetingsense", tools=register_tools())
