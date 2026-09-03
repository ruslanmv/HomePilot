"""Getting back into a meeting (batch MS16, wave W5).

A meeting ends and the useful part starts. B.3 of the design gives three ways back in, and the
whole point of the batch is that **all three reuse conversation machinery that already
exists** — no meetings tab, no second inbox, no new job type.

1. **Reopen the chat it was recorded in.** The conversation is still there; the card hydrates
   from the store as a frozen one. What was missing was the link: nothing on a message says
   which meeting produced it, so `ms_threads` records the pairing when the meeting starts.

2. **New thread from this meeting.** A fresh conversation opened with a compact brief — what
   was decided, what is still open, what was on screen — and the meeting attached, so a persona
   answering in it can reach the whole transcript through MS15's retrieval rather than being
   handed twenty thousand words it would truncate anyway.

3. **Attach to a project.** The transcript, as Markdown, through `vectordb.process_and_add_file`
   — the same function the project upload button calls. That is deliberate and it is the batch
   row's point: **this is the only route by which a meeting reaches project jobs, and it needs
   no new job type.** A meeting is not absorbed into a project by being recorded (D4); it is
   absorbed by somebody deciding it should be.

**There is no `conversations` table**, in this file or anywhere in HomePilot: a conversation is
messages grouped by `conversation_id`, and History labels each with the content of its last
message. So branching is "mint an id and write the first message", and the brief has to lead
with a line worth seeing in a list.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import export, store

log = logging.getLogger(__name__)

#: Marks the opening message of a branched thread, the way ``[Meeting]`` marks a summary.
BRIEF_PREFIX = "[Meeting brief]"

#: Slides listed in a brief. The brief is an opening move, not the record — the card and the
#: export hold the full strip, and forty caption lines above the first question is a wall.
MAX_BRIEF_SLIDES = 6

#: Open actions listed. Same reasoning, and a shorter list because these are what the reader
#: is meant to act on.
MAX_BRIEF_ACTIONS = 10


def brief(
    meeting: Dict[str, Any],
    segments: Any = (),
    keyframes: Any = (),
    notes: Any = None,
) -> str:
    """The opening message of a thread branched from a meeting.

    Deliberately **not** ``finalize.meeting_message``. That one is a record written into the
    conversation the meeting happened in, where the reader has just been in the meeting. This
    one opens a conversation whose reader may be coming back a week later with no context at
    all, so it leads with what is still open rather than with what was said, and ends by
    saying the transcript is searchable — otherwise the reader's first question is "can you
    see the meeting?" rather than a question about the meeting.
    """
    title = (meeting.get("title") or "Meeting").strip() or "Meeting"
    lines = [f"{BRIEF_PREFIX} {title}"]

    started = meeting.get("started_at")
    ended = meeting.get("ended_at")
    facts: List[str] = []
    if started and ended:
        facts.append(export.clock(int((float(ended) - float(started)) * 1000)))
    if meeting.get("source"):
        facts.append(str(meeting["source"]))
    count = len(list(segments))
    facts.append(f"{count} segment{'' if count == 1 else 's'}")
    lines.append(" · ".join(facts))

    body = export.notes_body(notes)
    if body:
        recap = (body.get("recap") or body.get("summary") or "").strip()
        if recap:
            lines += ["", recap]
        lines += _section("Decisions", body.get("decisions"))
        # Open questions and unfinished actions lead, because they are the reason somebody
        # opens a thread from a meeting rather than reading the summary again.
        lines += _section(
            "Still open",
            [q for q in (body.get("questions") or []) if not _done(q)],
        )
        lines += _section(
            "Actions",
            [a for a in (body.get("actions") or []) if not _done(a)],
            limit=MAX_BRIEF_ACTIONS,
        )
    else:
        lines += ["", "No notes were taken for this meeting."]

    frames = [f for f in keyframes if (f.get("caption") or "").strip()]
    if frames:
        lines += ["", "Slides:"]
        for frame in frames[:MAX_BRIEF_SLIDES]:
            lines.append(f"  {export.clock(frame.get('t_ms'))} {frame['caption'].strip()}")
        if len(frames) > MAX_BRIEF_SLIDES:
            lines.append(f"  … and {len(frames) - MAX_BRIEF_SLIDES} more.")

    lines += [
        "",
        # The line that makes the thread usable. Without it the reader's first message is
        # "can you see the meeting?" rather than a question about the meeting.
        "Ask me anything about this meeting — I can search the full transcript and cite the "
        "moment it was said.",
    ]
    return "\n".join(lines)


def _done(item: Any) -> bool:
    return bool(isinstance(item, dict) and (item.get("resolved") or item.get("done")))


def _section(label: str, items: Any, *, limit: Optional[int] = None) -> List[str]:
    """One brief section, or nothing.

    An empty heading claims something: "Decisions:" with nothing under it reads as a meeting
    where nothing was decided, which is a different statement from "no notes were taken".
    """
    if not items:
        return []
    rows = list(items)[: limit or len(list(items))]
    lines = ["", f"{label}:"]
    for item in rows:
        text = (item.get("text") or "").strip() if isinstance(item, dict) else str(item).strip()
        if not text:
            continue
        owner = f" — {item['owner']}" if isinstance(item, dict) and item.get("owner") else ""
        stamp = ""
        if isinstance(item, dict) and isinstance(item.get("t0"), (int, float)):
            stamp = f" [{export.clock(item['t0'])}]"
        lines.append(f"  - {text}{owner}{stamp}")
    return lines if len(lines) > 2 else []


def branch(meeting_id: str, *, conversation_id: Optional[str] = None,
           now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Open a new conversation from a meeting. ``None`` if there is no such meeting.

    Returns the conversation it created (or was given) and the thread row recording the link.
    The brief is written as an **assistant** message, because it is the meeting speaking rather
    than the user, and because History labels a conversation with its last message — so a
    thread with nothing said in it yet still reads as the meeting it came from.
    """
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        return None

    cid = conversation_id or uuid.uuid4().hex
    text = brief(
        meeting,
        store.get_segments(meeting_id),
        store.get_keyframes(meeting_id),
        store.get_notes(meeting_id),
    )
    written = False
    try:
        from ..storage import add_message

        add_message(cid, "assistant", text, project_id=meeting.get("project_id"))
        written = True
    except Exception:  # noqa: BLE001 — the link is still worth recording
        log.exception("meetingsense: could not write the brief for %s", meeting_id)

    thread_id = store.add_thread(meeting_id, cid, kind="branch",
                                 created_at=now if now is not None else time.time())
    return {
        "meeting_id": meeting_id,
        "conversation_id": cid,
        "thread_id": thread_id,
        "brief": text,
        # Reported rather than hidden: a thread whose brief did not land is a thread the client
        # should render from `brief` itself instead of waiting for a message that is not there.
        "message_written": written,
    }


def _slug(text: str) -> str:
    """A filename a person can recognise in a project's file list."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip()).strip("-").lower()
    return (cleaned or "meeting")[:60]


def attach_to_project(meeting_id: str, project_id: str, *,
                      now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Push a meeting's transcript into a project's knowledge base. ``None`` if no meeting.

    Through ``process_and_add_file`` — the function the project upload button calls — rather
    than through a MeetingSense-shaped indexing path. That is the batch row's point: the
    project already knows how to extract, chunk and embed a Markdown file, already records the
    file against the project, and already has whatever jobs run over project knowledge. A
    second pipeline would be a second thing to keep in step for no capability.

    The Markdown written is the export: transcript, slide captions and notes, which is exactly
    what somebody attaching a meeting means by "the meeting".
    """
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        return None

    markdown = export.to_markdown(
        meeting,
        store.get_segments(meeting_id),
        store.get_keyframes(meeting_id),
        store.get_notes(meeting_id),
    )
    title = (meeting.get("title") or "meeting").strip() or "meeting"
    name = f"meeting-{_slug(title)}-{meeting_id[:8]}.md"

    root = _upload_root()
    if root is None:
        return {"meeting_id": meeting_id, "project_id": project_id, "chunks": 0,
                "error": "no upload directory is configured"}
    path = root / name
    try:
        path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        log.exception("meetingsense: could not write %s", path)
        return {"meeting_id": meeting_id, "project_id": project_id, "chunks": 0, "error": str(exc)}

    chunks = 0
    error = None
    try:
        from ..vectordb import process_and_add_file

        chunks = int(process_and_add_file(project_id, path) or 0)
    except Exception as exc:  # noqa: BLE001 — no Chroma is a capability, not a crash
        log.warning("meetingsense: could not index %s into %s (%s)", meeting_id, project_id, exc)
        error = str(exc)

    _record_project_file(project_id, name, path, chunks)
    store.add_artifact(meeting_id, kind="project", target=project_id, ref=str(path),
                       detail=str(chunks), created_at=now if now is not None else time.time())
    result = {"meeting_id": meeting_id, "project_id": project_id, "chunks": chunks,
              "path": str(path), "filename": name}
    if error:
        result["error"] = error
    return result


def _upload_root() -> Optional[Path]:
    try:
        from ..files import _upload_root as root

        return Path(root())
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: no upload root for attach", exc_info=True)
        return None


def _record_project_file(project_id: str, name: str, path: Path, chunks: int) -> None:
    """List the transcript in the project's own files, the way an upload does.

    Best-effort and separate: a meeting indexed into a project but missing from its file list
    is searchable and invisible, which is worse than the reverse — the user has no way to
    remove something they cannot see.
    """
    try:
        from .. import projects

        project = projects.get_project_by_id(project_id)
        if not project:
            return
        files = list(project.get("files") or [])
        files.append({
            "name": name,
            "size": f"{path.stat().st_size / 1024 / 1024:.2f} MB",
            "path": str(path),
            "chunks": chunks,
            "source_type": "document",
        })
        projects.update_project(project_id, {"files": files})
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: could not list the transcript in project %s", project_id, exc_info=True)


def hydrate(conversation_id: str) -> List[Dict[str, Any]]:
    """The meetings a conversation can show a card for, oldest first.

    What "reopen the chat and the card comes back" needs. Each row carries enough to render
    the collapsed card without a second call — the counts and the state — and the client asks
    ``GET /v1/meetingsense/{id}`` for the transcript only when the card is opened.
    """
    rows = store.meetings_for_conversation(conversation_id)
    out: List[Dict[str, Any]] = []
    for meeting in rows:
        counts = {
            "segments": len(store.get_segments(meeting["id"])),
            "slides": len(store.get_keyframes(meeting["id"])),
        }
        out.append({
            "meeting_id": meeting["id"],
            "title": meeting.get("title"),
            "source": meeting.get("source"),
            "status": meeting.get("status"),
            "started_at": meeting.get("started_at"),
            "ended_at": meeting.get("ended_at"),
            "thread_kind": meeting.get("thread_kind"),
            "counts": counts,
        })
    return out
