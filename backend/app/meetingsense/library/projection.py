"""The Meetings Library — one list over every kind of meeting HomePilot has.

Projected, not copied: a meeting recorded live, an imported recording, a synced Insta360
folder and a scheduled meeting are all rows in ``ms_meetings`` (with the library's companion
row beside the later three), and a Teams room is read from the Teams store as it is. Each
appears once, under a stable ``library_id``, and opens in the place it belongs to.

Teams rooms are persona conversations, not recordings: they are listed as such (no audio,
transcript-only), only once a room has had a real exchange, and they open in Teams.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from . import db

PAGE_MAX = 60
#: A Teams room becomes a library item once it has had at least this many messages — a
#: room that was created and never used is not a meeting.
TEAMS_MIN_MESSAGES = 4

TABS = ("all", "project", "recorded", "imported", "unsorted", "processing")
SORTS = ("newest", "oldest", "title", "duration")
_PROCESSING = {"queued", "transcribing", "needs_setup", "failed"}

_SOURCE_LABELS = {
    "insta360": "Insta360 Import",
    "upload": "Upload",
    "folder": "Folder Sync",
    "transcript": "Transcript Only",
    "teams_room": "Teams room",
    "scheduled": "Scheduled",
}
_LIVE_SOURCE_LABELS = {
    "zoom": "Zoom", "meet": "Google Meet", "teams": "Microsoft Teams", "webex": "Webex",
    "slack": "Slack", "discord": "Discord", "local": "This computer",
}


def _projects_by_id() -> Dict[str, Dict[str, Any]]:
    try:
        from ... import projects as projects_mod  # noqa: PLC0415

        out = {p.get("id"): p for p in projects_mod.list_all_projects() if p.get("id")}
        for p in projects_mod.get_example_projects():
            out.setdefault(p["id"], p)
        return out
    except Exception:  # noqa: BLE001
        return {}


def _latest_notes(meeting_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not meeting_ids:
        return out
    con = db._connect()
    try:
        for i in range(0, len(meeting_ids), 500):
            part = list(meeting_ids[i:i + 500])
            rows = con.execute(
                "SELECT n.meeting_id, n.json FROM ms_notes n JOIN (SELECT meeting_id, MAX(version) v FROM ms_notes"
                f" WHERE meeting_id IN ({','.join('?' * len(part))}) GROUP BY meeting_id) x"
                " ON x.meeting_id = n.meeting_id AND x.v = n.version",
                part,
            ).fetchall()
            for r in rows:
                try:
                    out[r["meeting_id"]] = json.loads(r["json"]) or {}
                except (TypeError, ValueError):
                    pass
    finally:
        con.close()
    return out


def _segment_counts() -> Dict[str, int]:
    con = db._connect()
    try:
        return {r["meeting_id"]: r["c"] for r in con.execute(
            "SELECT meeting_id, COUNT(*) c FROM ms_segments GROUP BY meeting_id").fetchall()}
    finally:
        con.close()


def _live_ids() -> set:
    try:
        from .. import session as session_mod  # noqa: PLC0415

        return {mid for mid, s in session_mod._SESSIONS.items()
                if getattr(s, "state", None) == session_mod.MeetingState.LIVE}
    except Exception:  # noqa: BLE001
        return set()


#: A row younger than this may be a meeting whose session is a moment from being registered.
_ORPHAN_MIN_AGE_S = 60.0


def _close_orphans() -> None:
    """End rows still "in progress" that no session of this process holds.

    The startup sweep (``store.close_orphaned_meetings``) only ran once, so a meeting whose
    session went away while the server kept running — a part split off by a reconnect, a stop
    stuck behind a slow model — said "Recording" on its card until the next restart. The
    library is where that lie is seen, so the library is where it is corrected.
    """
    try:
        import time  # noqa: PLC0415

        from .. import session as session_mod  # noqa: PLC0415
        from .. import store  # noqa: PLC0415

        held = [mid for mid, s in session_mod._SESSIONS.items()
                if getattr(s, "state", None) in (session_mod.MeetingState.LIVE,
                                                 session_mod.MeetingState.SUSPENDED)]
        store.close_orphaned_meetings(held, started_before=time.time() - _ORPHAN_MIN_AGE_S)
    except Exception:  # noqa: BLE001 — a stale chip is better than a library that will not load
        pass


def _summary_state(row: Dict[str, Any], entry: Dict[str, Any], notes: Dict[str, Any]) -> str:
    """``pending`` while the end-of-meeting document is being written for a recorded meeting.

    A meeting that has just ended has its summary written by the session (``minutes.
    autogenerate``), not by a library job, so the library said "none" until it landed — and
    the recap, which shows this page the moment a meeting ends, had no reason to look again.
    """
    try:
        from .. import minutes  # noqa: PLC0415

        if minutes.is_writing(row["id"]):
            return "pending"
    except Exception:  # noqa: BLE001
        pass
    return entry.get("summary_state") or ("ready" if notes else "none")


def _summary_line(notes: Dict[str, Any], entry: Dict[str, Any]) -> str:
    text = (entry or {}).get("description") or ""
    if not text:
        body = notes.get("notes") if isinstance(notes.get("notes"), dict) else notes
        text = str((body or {}).get("summary") or "")
    text = " ".join(text.split())
    return text[:220]


def meeting_items(viewer: str = "") -> List[Dict[str, Any]]:
    """Every MeetingSense / library meeting the viewer may see, as library items."""
    _close_orphans()
    con = db._connect()
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM ms_meetings").fetchall()]
    finally:
        con.close()
    ids = [r["id"] for r in rows]
    entries = db.entries_by_id(ids)
    links = db.project_links(ids)
    projects = _projects_by_id()
    notes = _latest_notes(ids)
    counts = _segment_counts()
    live = _live_ids()
    items: List[Dict[str, Any]] = []
    for row in rows:
        entry = entries.get(row["id"]) or {}
        if entry.get("hidden_at"):
            continue
        owner = entry.get("owner_user_id") or ""
        if viewer and owner and owner != viewer:
            continue
        items.append(_item(row, entry, links.get(row["id"], []), projects, notes.get(row["id"], {}),
                           counts.get(row["id"], 0), row["id"] in live))
    return items


def _item(row: Dict[str, Any], entry: Dict[str, Any], links: List[Dict[str, Any]],
          projects: Dict[str, Dict[str, Any]], notes: Dict[str, Any], segments: int, live: bool) -> Dict[str, Any]:
    origin = entry.get("origin_type") or "meetingsense"
    status = row.get("status") or ""
    if origin == "meetingsense":
        # A suspended meeting lost its socket and is waiting out the grace window for the
        # browser to come back. That is not "Recording" — nothing is being heard — and the
        # card says so ("Reconnecting") until it resumes or ends.
        # After the meeting: its own recording, still arriving from the browser ("saving") or
        # kept ("present") — `library/recording.py`.
        if status == "live":
            recording = "recording"
        elif status == "suspended":
            recording = "paused"
        elif entry.get("recording_state") == "uploading":
            recording = "saving"
        else:
            recording = "present" if entry.get("media_present") else "none"
        transcript = "live" if status == "live" else ("ready" if segments else "none")
        source_kind = "meetingsense"
        source_label = _LIVE_SOURCE_LABELS.get((row.get("source") or "").lower(), "HomePilot")
    else:
        recording = entry.get("recording_state") or "none"
        transcript = entry.get("transcript_state") or "none"
        source_kind = row.get("source") or ("scheduled" if origin == "scheduled" else "upload")
        source_label = _SOURCE_LABELS.get(source_kind, source_kind.title())
    project_list = []
    for link in links:
        p = projects.get(link["project_id"]) or {}
        project_list.append({"id": link["project_id"], "name": p.get("name") or "Missing project",
                             "kind": link.get("kind"), "missing": not p})
    category = entry.get("category")
    if not category:
        category = "Project Meeting" if project_list else ("Recorded" if origin == "meetingsense" else "Meeting")
    started = row.get("started_at")
    ended = row.get("ended_at")
    duration_ms = entry.get("duration_ms")
    if duration_ms is None and started and ended and ended > started:
        duration_ms = int((ended - started) * 1000)
    return {
        "library_id": row["id"],
        "meeting_id": row["id"],
        "origin_type": origin,
        "origin_id": row["id"],
        "title": (row.get("title") or "").strip() or "Untitled meeting",
        "description": _summary_line(notes, entry),
        "category": category,
        "started_at": started,
        "ended_at": ended,
        "scheduled_for": entry.get("scheduled_for"),
        "duration_ms": duration_ms,
        "projects": project_list,
        "source": {"kind": source_kind, "label": source_label},
        "media_present": bool(entry.get("media_present")),
        "recording_state": recording,
        "transcript_state": transcript,
        "summary_state": _summary_state(row, entry, notes),
        "segments": segments,
        "conversation_id": row.get("conversation_id"),
        "status": status,
        "live": live,
        "warnings": entry.get("warnings") or [],
    }


def teams_items() -> List[Dict[str, Any]]:
    """Teams rooms that held a real conversation — read-only, opened in Teams."""
    try:
        from ...teams import rooms as rooms_mod  # noqa: PLC0415

        rooms = rooms_mod.list_rooms()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for room in rooms:
        msgs = room.get("messages") or []
        if len(msgs) < TEAMS_MIN_MESSAGES:
            continue
        first = msgs[0].get("timestamp") or room.get("created_at")
        last = msgs[-1].get("timestamp") or room.get("updated_at")
        out.append({
            "library_id": f"teams_room:{room['id']}",
            "meeting_id": None,
            "origin_type": "teams_room",
            "origin_id": room["id"],
            "title": room.get("name") or "Team meeting",
            "description": " ".join(str(room.get("topic") or room.get("description") or "").split())[:220],
            "category": "Team Meeting",
            "started_at": first,
            "ended_at": last,
            "scheduled_for": None,
            "duration_ms": None,
            "projects": [],
            "source": {"kind": "teams_room", "label": "Teams room"},
            "media_present": False,
            "recording_state": "none",
            "transcript_state": "transcript_only",
            "summary_state": "none",
            "segments": len(msgs),
            "conversation_id": None,
            "status": room.get("status") or "",
            "live": False,
            "warnings": [],
        })
    return out


def _matches_query(item: Dict[str, Any], q: str, transcript_hits: set) -> bool:
    if not q:
        return True
    hay = " ".join([
        item.get("title") or "", item.get("description") or "", item.get("category") or "",
        (item.get("source") or {}).get("label") or "", " ".join(p["name"] for p in item.get("projects") or []),
    ]).lower()
    return all(word in hay for word in q.lower().split()) or (item.get("meeting_id") in transcript_hits)


def _transcript_hits(q: str) -> set:
    q = " ".join(q.split())
    if len(q) < 3:
        return set()
    con = db._connect()
    try:
        return {r["meeting_id"] for r in con.execute(
            "SELECT DISTINCT meeting_id FROM ms_segments WHERE text LIKE ? LIMIT 500", (f"%{q}%",)).fetchall()}
    finally:
        con.close()


def _in_tab(item: Dict[str, Any], tab: str) -> bool:
    if tab == "project":
        return bool(item["projects"])
    if tab == "recorded":
        return item["origin_type"] in ("meetingsense",) or (item["origin_type"] == "scheduled" and item["media_present"])
    if tab == "imported":
        return item["origin_type"] in ("import", "sync")
    if tab == "unsorted":
        return not item["projects"] and item["origin_type"] != "teams_room"
    if tab == "processing":
        return item["transcript_state"] in _PROCESSING or item["summary_state"] == "pending"
    return True


def list_library(*, viewer: str = "", tab: str = "all", q: str = "", source: str = "", project_id: str = "",
                 state: str = "", date_from: Optional[float] = None, date_to: Optional[float] = None,
                 sort: str = "newest", cursor: str = "", limit: int = 24) -> Dict[str, Any]:
    items = meeting_items(viewer) + teams_items()
    counts = {t: sum(1 for i in items if _in_tab(i, t)) for t in TABS}
    hits = _transcript_hits(q) if q else set()
    shown = [
        i for i in items
        if _in_tab(i, tab if tab in TABS else "all")
        and _matches_query(i, q, hits)
        and (not source or i["source"]["kind"] == source)
        and (not project_id or any(p["id"] == project_id for p in i["projects"]))
        and (not state or i["transcript_state"] == state)
        and (date_from is None or (i.get("started_at") or 0) >= date_from)
        and (date_to is None or (i.get("started_at") or 0) <= date_to)
    ]
    key = {
        "oldest": lambda i: (i.get("started_at") or 0),
        "title": lambda i: (i.get("title") or "").lower(),
        "duration": lambda i: -(i.get("duration_ms") or 0),
    }.get(sort)
    if key is None:
        shown.sort(key=lambda i: (i.get("started_at") or 0), reverse=True)
    else:
        shown.sort(key=key)
    try:
        offset = max(0, int(cursor or 0))
    except ValueError:
        offset = 0
    limit = max(1, min(int(limit or 24), PAGE_MAX))
    page = shown[offset:offset + limit]
    nxt = str(offset + limit) if offset + limit < len(shown) else None
    sources = sorted({(i["source"]["kind"], i["source"]["label"]) for i in items})
    return {
        "items": page,
        "next_cursor": nxt,
        "total": len(shown),
        "counts": counts,
        "facets": {"sources": [{"kind": k, "label": label} for k, label in sources],
                   "projects": [{"id": pid, "name": name} for pid, name in sorted(
                       {(p["id"], p["name"]) for i in items for p in i["projects"]}, key=lambda x: x[1].lower())]},
    }


def find_item(library_id: str, viewer: str = "") -> Optional[Dict[str, Any]]:
    if library_id.startswith("teams_room:"):
        return next((i for i in teams_items() if i["library_id"] == library_id), None)
    for item in meeting_items(viewer):
        if item["library_id"] == library_id:
            return item
    return None
