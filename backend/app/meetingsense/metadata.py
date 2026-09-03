"""Naming a meeting without asking (batch MS17, wave W5).

Nobody types a title before they hit record. They are already in the call, somebody is
talking, and the dialog asking what to call this is the reason the recording did not start.
So a meeting is titled *after the fact*, from two sources that cost the user nothing.

**The shared window title**, which the browser hands over for free —
``"Q3 planning | Microsoft Teams"``, ``"Zoom Meeting"``, ``"Meet – Q3 planning"``. That single
string carries both the meeting's name and which platform it ran on, and pulling them apart is
string work with no network call, no permission and no dependency. It is also the half that can
be tested, which is why it is a pure function with a table of real titles behind it.

**A calendar event**, when `google_calendar` or `microsoft_graph` is connected through MCP —
which adds the attendees and the join link, and a title somebody actually chose.

Two rules keep this from being worse than nothing:

**A title the user gave always wins.** Auto-metadata fills a blank; it never corrects a person.
Somebody who typed "1:1 with Ana" and got "Microsoft Teams" back would stop typing titles.

**An empty answer is not an answer.** Every field here is written only if it says something,
so a calendar that matched nothing, a window title that was just the app name, or an MCP call
that timed out leaves the meeting exactly as it was rather than blanking what is there.

The window-title half is unit-tested against real titles. The calendar half is tested against
an injected invoker and is otherwise the batch row's *"manual: calendar match"* — a live MCP
connection is not something CI has.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

log = logging.getLogger(__name__)

#: How far from a meeting's start a calendar event may be and still be that meeting. Fifteen
#: minutes because people join early and start recording late, and because the next event in a
#: back-to-back day is thirty away — a wider window picks the wrong one on exactly the days
#: when getting it right matters.
CALENDAR_WINDOW_S = 15 * 60

#: The platforms worth naming. Each entry is (source, markers), and the markers are matched on
#: **word boundaries**, which is not fussiness: a plain substring test reads "Cisco Webex
#: Meetings" as Meet, because "Meetings" contains "meet". Ordered with the ambiguous short
#: markers last for the same reason.
#:
#: Domains are markers too, because the same function reads a *join link* off a calendar
#: event: a Teams invitation says "teams.microsoft.com" and never "Microsoft Teams", so a
#: window-title-only list would leave every calendar-matched meeting with no platform.
PLATFORMS: Sequence = (
    ("teams", ("microsoft teams", "msteams", "teams meeting", "teams.microsoft.com")),
    ("zoom", ("zoom meeting", "zoom workplace", "zoom.us", "zoom")),
    ("webex", ("cisco webex", "webex.com", "webex")),
    ("slack", ("slack huddle", "slack call")),
    ("discord", ("discord.gg", "discord")),
    ("meet", ("google meet", "meet.google.com", "meet")),
)

#: Window-title furniture that is never part of a meeting's name. A browser's own name is the
#: obvious one; "Meeting Compact View" and friends are Teams' window states.
_NOISE = (
    "google chrome", "chrome", "chromium", "microsoft edge", "edge", "firefox", "safari",
    "brave", "arc", "opera", "screen", "entire screen", "window", "tab",
    "meeting compact view", "meeting window", "shared screen", "presenting",
)

#: Separators a window title uses between the name and the app.
_SPLIT = re.compile(r"\s+[|–—·-]\s+")


_MARKERS: Dict[str, Any] = {}


def _marker(marker: str):
    """A word-boundary matcher for one platform marker, compiled once.

    ``\b`` rather than ``in``: "Cisco Webex Meetings" contains "meet", and a substring test
    tags every Webex call as a Meet call. The marker's own dots are escaped so
    "meet.google.com" is a literal rather than a pattern matching "meetxgoogleycom".
    """
    pattern = _MARKERS.get(marker)
    if pattern is None:
        pattern = _MARKERS[marker] = re.compile(rf"\b{re.escape(marker)}\b")
    return pattern


def _clean(part: str) -> str:
    return " ".join((part or "").replace("​", " ").split()).strip(" -|·")


def detect_source(window_title: str) -> str:
    """Which platform a shared window belongs to, or ``""``.

    Matched on the whole title rather than on a split part, because the marker is not always
    in the same place: Teams puts it last, Meet puts it first, and Zoom is sometimes the whole
    title. Longest marker first, so ``"Google Meet"`` is not read as ``"Meet"`` and
    ``"Google Chrome"`` is not read as anything.
    """
    # Underscores are word characters to a regex and separators to a person, so
    # "Webex_Meetings" would not match `\bwebex\b` without this. Normalised for *matching*
    # only — the title itself keeps its underscores, which may be somebody's filename.
    lowered = (window_title or "").lower().replace("_", " ")
    if not lowered:
        return ""
    for source, markers in PLATFORMS:
        for marker in markers:
            if _marker(marker).search(lowered):
                return source
    return ""


def title_from_window(window_title: str) -> str:
    """The meeting's name out of a window title, or ``""`` when there isn't one.

    ``"Q3 planning | Microsoft Teams"`` → ``"Q3 planning"``. ``"Zoom Meeting"`` → ``""``,
    because "Zoom Meeting" is not a name — it is the absence of one, and writing it into the
    title makes every Zoom call in History look identical.

    Returns the *longest* surviving part rather than the first: ``"Meet – Q3 planning"`` puts
    the app first and ``"Q3 planning | Teams"`` puts it last, and the name is reliably the
    part with something in it.
    """
    text = _clean(window_title)
    if not text:
        return ""
    parts = [_clean(p) for p in _SPLIT.split(text)] or [text]
    keep: List[str] = []
    for part in parts:
        lowered = part.lower()
        if not part or lowered in _NOISE:
            continue
        # A part that is *only* a platform marker is furniture too — "Zoom Meeting" and
        # "Microsoft Teams" name the app, not the call.
        if any(lowered == marker or lowered == f"{marker} meeting" or lowered == f"{marker} meetings"
               for _, markers in PLATFORMS for marker in markers):
            continue
        if lowered in ("meeting", "call", "video call", "untitled"):
            continue
        keep.append(part)
    if not keep:
        return ""
    best = max(keep, key=len)
    # A single word that is just a platform name slipped through as the longest part.
    return "" if detect_source(best) and len(best.split()) < 2 else best


def from_window_title(window_title: str) -> Dict[str, Any]:
    """Both halves at once — what the client can supply with no permission and no network."""
    return {
        "title": title_from_window(window_title),
        "source": detect_source(window_title),
    }


# ── the calendar half ───────────────────────────────────────────────────────

#: The capability asked of the tool router. Resolved to whichever of `google_calendar` or
#: `microsoft_graph` is actually connected, which is the router's job rather than this one's.
CALENDAR_CAPABILITY = "calendar.events.list"


def _event_seconds(value: Any) -> Optional[float]:
    """A start/end out of whatever shape a calendar returned. ``None`` if unreadable.

    Calendars disagree about this more than they agree: Google nests
    ``{"start": {"dateTime": ...}}``, Graph uses ``{"start": {"dateTime": ..., "timeZone": ...}}``,
    and a normalising MCP server may hand back an epoch. Anything unparseable is skipped
    rather than guessed at — a wrongly-parsed timestamp picks the wrong meeting, which is
    worse than picking none.
    """
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date") or value.get("start")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def pick_event(events: Sequence[Dict[str, Any]], started_at: float,
               *, window_s: float = CALENDAR_WINDOW_S) -> Optional[Dict[str, Any]]:
    """The event a recording that started at ``started_at`` belongs to, or ``None``.

    An event **containing** the start wins outright, however long it is: somebody who starts
    recording twenty minutes into an hour-long call is in that call, not near the next one.
    Only when nothing contains it does proximity decide, and then only inside ``window_s``.

    Ties break on the nearer start, and then on the shorter event: on a day of overlapping
    invitations the specific one is more likely to be the call than the all-day block it sits
    inside.
    """
    containing: List = []
    nearby: List = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        start = _event_seconds(event.get("start"))
        if start is None:
            continue
        end = _event_seconds(event.get("end"))
        length = (end - start) if (end is not None and end > start) else 0.0
        if end is not None and start <= started_at <= end:
            containing.append((abs(started_at - start), length, event))
        elif abs(started_at - start) <= window_s:
            nearby.append((abs(started_at - start), length, event))
    pool = containing or nearby
    if not pool:
        return None
    pool.sort(key=lambda row: (row[0], row[1]))
    return pool[0][2]


def _attendees(event: Dict[str, Any]) -> List[str]:
    """Display names or addresses, deduplicated, order kept.

    Names where a calendar gives them and addresses where it does not: "Ana Costa" is who was
    in the meeting and "a.costa@example.com" is only how to reach her, but half an attendee
    list is worse than a plain one.
    """
    out: List[str] = []
    for person in event.get("attendees") or []:
        if isinstance(person, str):
            name = person.strip()
        elif isinstance(person, dict):
            email = person.get("email")
            if isinstance(email, dict):  # Graph: {"emailAddress": {...}} normalises to this
                email = email.get("address")
            inner = person.get("emailAddress") if isinstance(person.get("emailAddress"), dict) else {}
            name = str(
                person.get("displayName") or inner.get("name") or person.get("name")
                or email or inner.get("address") or ""
            ).strip()
        else:
            continue
        if name and name not in out:
            out.append(name)
    return out


def _link(event: Dict[str, Any]) -> str:
    for key in ("hangoutLink", "onlineMeetingUrl", "joinUrl", "location", "htmlLink", "url"):
        value = event.get(key)
        if isinstance(value, dict):
            value = value.get("joinUrl") or value.get("url")
        if isinstance(value, str) and value.strip().startswith("http"):
            return value.strip()
    online = event.get("onlineMeeting")
    if isinstance(online, dict) and isinstance(online.get("joinUrl"), str):
        return online["joinUrl"].strip()
    return ""


def from_event(event: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """One calendar event → the fields a meeting can take from it."""
    if not isinstance(event, dict):
        return {}
    title = str(event.get("summary") or event.get("subject") or event.get("title") or "").strip()
    out: Dict[str, Any] = {}
    if title:
        out["title"] = title
    attendees = _attendees(event)
    if attendees:
        out["attendees"] = attendees
    link = _link(event)
    if link:
        out["link"] = link
        source = detect_source(link)
        if source:
            out["source"] = source
    return out


async def match_calendar(
    started_at: float,
    *,
    invoke: Optional[Callable[..., Awaitable[Any]]] = None,
    window_s: float = CALENDAR_WINDOW_S,
) -> Dict[str, Any]:
    """Ask the connected calendar what this meeting is. ``{}`` for every kind of nothing.

    ``invoke`` is injected — ``async (capability, args) -> events`` — so this is testable
    without an MCP server, and so the batch's untestable half is one function rather than
    scattered through the module. Never raises: a calendar that is slow, disconnected or
    answering in a shape nobody expected leaves the meeting titled from its window.
    """
    if invoke is None:
        return {}
    try:
        window = (started_at - window_s, started_at + window_s)
        raw = await invoke(CALENDAR_CAPABILITY, {"time_min": window[0], "time_max": window[1]})
    except Exception:  # noqa: BLE001 — an unnamed meeting is a complete meeting
        log.debug("meetingsense: calendar lookup failed", exc_info=True)
        return {}

    events = raw
    if isinstance(raw, dict):
        events = raw.get("items") or raw.get("events") or raw.get("value") or []
    if not isinstance(events, (list, tuple)):
        return {}
    return from_event(pick_event(events, started_at, window_s=window_s))


def merge(existing: Dict[str, Any], *sources: Dict[str, Any]) -> Dict[str, Any]:
    """What to write, given what is already there and what was found.

    **A value already on the meeting wins.** The title someone typed at `start` is the one
    thing here that a person chose, and auto-metadata that corrects a person is auto-metadata
    people turn off. Later sources fill blanks left by earlier ones, in the order given, so
    the caller decides that the calendar outranks the window title by passing it first.
    """
    out: Dict[str, Any] = {}
    for source in sources:
        for key, value in (source or {}).items():
            if value in (None, "", []):
                continue
            if existing.get(key) not in (None, "", []):
                continue
            out.setdefault(key, value)
    return out


async def enrich(
    meeting_id: str,
    *,
    window_title: str = "",
    started_at: Optional[float] = None,
    invoke: Optional[Callable[..., Awaitable[Any]]] = None,
) -> Dict[str, Any]:
    """Name a meeting from whatever is available. Returns what was written.

    The calendar is passed first because it carries a title somebody chose, attendees and a
    link; the window title fills whatever is left, which on an install with no calendar is all
    of it. Neither can overwrite what the user typed.
    """
    from . import store

    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        return {}
    start = started_at if started_at is not None else float(meeting.get("started_at") or 0.0)

    calendar = await match_calendar(start, invoke=invoke) if invoke is not None else {}
    window = from_window_title(window_title)
    writes = merge(meeting, calendar, window)
    if not writes:
        return {}
    try:
        store.update_meeting(meeting_id, writes)
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: could not write metadata for %s", meeting_id)
        return {}
    return writes
