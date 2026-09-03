"""Taking a meeting out of HomePilot (batch MS6).

Three formats, and the choice is not arbitrary: **Markdown** to paste into a document,
**SRT** to lay over a recording, **JSON** for anything else. Each is a pure function from
stored rows to a string, so the hard part — what a transcript looks like when the data is
imperfect — is testable without a socket, a database or a browser.

The imperfect case is not hypothetical. ``t1`` is ``None`` whenever the speech provider did
not measure the end of a span, which is *every* segment when transcription goes through a
remote OpenAI-compatible endpoint (MS1-a is still unbuilt). An export that raised, or wrote
``00:00:00,000`` for those, would fail on exactly the installs least able to diagnose it. So
every function here treats a missing end as a fact to work around rather than an error.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

#: How long a segment is assumed to last when nothing measured it and no later segment bounds
#: it — the last line of a remotely-transcribed meeting. Two seconds is an ordinary utterance;
#: the alternative is a zero-length cue, which subtitle players skip entirely.
FALLBACK_CUE_MS = 2000

#: Least time a cue may occupy. Players drop shorter ones, so a rounding accident becomes an
#: invisible subtitle rather than a short one.
MIN_CUE_MS = 100

FORMATS = ("md", "srt", "json")


def clock(ms: Optional[int], *, srt: bool = False) -> str:
    """``hh:mm:ss``, or ``hh:mm:ss,mmm`` for SRT. ``None`` reads as the start of the meeting."""
    total = max(0, int(ms or 0))
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    if srt:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def speaker_label(speaker: Optional[str]) -> str:
    """``me`` / ``them`` are wire values, not words a reader should meet in a document."""
    return {"me": "You", "them": "Them"}.get((speaker or "").strip(), "Speaker")


def cue_bounds(segments: Sequence[Dict[str, Any]], index: int) -> tuple:
    """Start and end of one cue, in milliseconds.

    The end comes from three places in order of trust: the measured ``t1``; failing that, the
    start of the next segment, which is a real bound rather than a guess; and failing both, a
    fixed span. Ordering matters — using the next segment's start *before* a measured end
    would stretch a two-second sentence across a thirty-second silence.
    """
    segment = segments[index]
    start = max(0, int(segment.get("t0_ms") or 0))
    end = segment.get("t1_ms")
    if end is None:
        following = segments[index + 1] if index + 1 < len(segments) else None
        end = int(following["t0_ms"]) if following and following.get("t0_ms") is not None else None
    if end is None:
        end = start + FALLBACK_CUE_MS
    return start, max(int(end), start + MIN_CUE_MS)


def to_srt(segments: Sequence[Dict[str, Any]]) -> str:
    """SRT cues, numbered from 1.

    Blank segments are skipped rather than written as empty cues — a numbered cue with no text
    is a hole in the file that some players render as a flash of nothing.
    """
    blocks: List[str] = []
    usable = [s for s in segments if (s.get("text") or "").strip()]
    for index, segment in enumerate(usable):
        start, end = cue_bounds(usable, index)
        label = speaker_label(segment.get("speaker"))
        blocks.append(
            f"{index + 1}\n"
            f"{clock(start, srt=True)} --> {clock(end, srt=True)}\n"
            f"{label}: {(segment.get('text') or '').strip()}\n"
        )
    return "\n".join(blocks)


def _meeting_heading(meeting: Dict[str, Any]) -> str:
    title = (meeting.get("title") or "").strip() or "Meeting"
    started = meeting.get("started_at")
    when = (
        datetime.fromtimestamp(float(started), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if started
        else "unknown time"
    )
    parts = [when]
    if meeting.get("source"):
        parts.append(str(meeting["source"]))
    if meeting.get("audio_mode"):
        parts.append(str(meeting["audio_mode"]))
    if meeting.get("started_at") and meeting.get("ended_at"):
        length = int((float(meeting["ended_at"]) - float(meeting["started_at"])) * 1000)
        parts.append(f"{clock(length)} long")
    return f"# 🎙 {title}\n\n*{' · '.join(parts)}*\n"


def to_markdown(
    meeting: Dict[str, Any],
    segments: Sequence[Dict[str, Any]],
    keyframes: Sequence[Dict[str, Any]] = (),
    notes: Optional[Dict[str, Any]] = None,
) -> str:
    """Summary, then slides, then transcript — the order somebody reads them in.

    Notes and slides are omitted entirely when there are none, rather than left as empty
    headings. A document with a "Decisions" heading and nothing under it reads as a meeting
    where nothing was decided, which is a different claim from "this install has no notes
    engine yet".
    """
    out: List[str] = [_meeting_heading(meeting)]

    body = (notes or {}).get("json") if isinstance(notes, dict) else None
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            body = None
    if isinstance(body, dict):
        for heading, key in (("Summary", "summary"), ("Decisions", "decisions"),
                             ("Actions", "actions"), ("Open questions", "questions")):
            value = body.get(key)
            if not value:
                continue
            out.append(f"\n## {heading}\n")
            if isinstance(value, str):
                out.append(f"\n{value}\n")
            else:
                out.extend(f"\n- {item}" for item in value)
                out.append("\n")

    if keyframes:
        out.append("\n## Slides\n")
        for frame in keyframes:
            caption = (frame.get("caption") or "").strip() or "(not captioned)"
            out.append(f"\n- `{clock(frame.get('t_ms'))}` {caption}")
        out.append("\n")

    out.append("\n## Transcript\n")
    if not segments:
        # Said plainly. An empty transcript section invites the reader to assume the export
        # broke, when the honest answer is usually that nothing was transcribed.
        out.append("\n*No transcript was recorded.*\n")
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        out.append(f"\n`{clock(segment.get('t0_ms'))}` **{speaker_label(segment.get('speaker'))}** {text}")
    out.append("\n")
    return "".join(out)


def to_json(
    meeting: Dict[str, Any],
    segments: Sequence[Dict[str, Any]],
    keyframes: Sequence[Dict[str, Any]] = (),
    notes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Everything, in the shape it is stored in.

    ``t1_ms`` stays ``None`` here rather than being filled in the way the SRT fills it. The
    other two formats have to put *something* on screen; a data export does not, and inventing
    an end time would hand the next tool a measurement nobody made.
    """
    return {
        "meeting": meeting,
        "segments": list(segments),
        "keyframes": list(keyframes),
        "notes": notes,
    }


#: What each format is called on disk and on the wire.
MEDIA_TYPES = {
    "md": ("text/markdown; charset=utf-8", "md"),
    "srt": ("application/x-subrip; charset=utf-8", "srt"),
    "json": ("application/json", "json"),
}


def filename(meeting: Dict[str, Any], fmt: str) -> str:
    """A filename a person can find again: the title, the date, the format."""
    title = (meeting.get("title") or "meeting").strip() or "meeting"
    safe = "".join(c if c.isalnum() or c in "-_ " else "-" for c in title).strip().replace(" ", "-")
    started = meeting.get("started_at")
    day = (
        datetime.fromtimestamp(float(started), tz=timezone.utc).strftime("%Y-%m-%d")
        if started
        else "undated"
    )
    return f"{safe or 'meeting'}-{day}.{MEDIA_TYPES[fmt][1]}"
