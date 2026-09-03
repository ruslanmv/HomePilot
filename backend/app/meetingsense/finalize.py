"""What a finished meeting leaves behind in the chat (batch MS6).

Decision D5: a meeting *is* a conversation. There is no meetings tab, no second navigation, no
new place to look — the meeting lands in History as an assistant message beginning
``[Meeting]``, and the conversation gets a title that says what it was.

That choice is why this file is small, and it is worth being explicit about the alternative:
a separate catalog would need its own list view, its own search, its own permissions and its
own empty state, and would still leave the user asking which of the two places a given meeting
was in. MS28 exists to add one *only if* History gets crowded.

**There is no conversation title to set, and none is needed.** HomePilot has no
``conversations`` table: a conversation is `messages` grouped by `conversation_id`, and
History labels each one with the *content of its last message* (``storage.list_conversations``).
The meeting message is the last message written when a meeting stops, so putting the D5 title
on its first line is what makes History read ``🎙 Q3 planning · teams · 2026-09-03`` — with no
new table, and nothing to keep in step. Adding a title column instead would have written a
value the existing History view never reads.

**Nothing in here may break a stop.** A meeting that recorded fine but could not write its
summary message must still end, and end cleanly. Every failure is logged and swallowed —
the transcript is already in the store, which is the part that cannot be reconstructed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from . import export

log = logging.getLogger(__name__)

#: Marks the message the card renders instead of plain text. A prefix rather than a media
#: field so that a client which has never heard of MeetingSense still shows something
#: readable — the fallback is the message body itself.
MESSAGE_PREFIX = "[Meeting]"

#: Lines of transcript in the placeholder message. MS12 replaces the body with real notes;
#: until then the message has to be worth reading on its own, and the opening exchange is the
#: part that says what the meeting was about.
PREVIEW_SEGMENTS = 6


def conversation_title(meeting: Dict[str, Any]) -> str:
    """``🎙 <title> · <source> · <date>`` (D5)."""
    parts = [(meeting.get("title") or "Meeting").strip() or "Meeting"]
    if meeting.get("source"):
        parts.append(str(meeting["source"]))
    started = meeting.get("started_at")
    if started:
        parts.append(datetime.fromtimestamp(float(started), tz=timezone.utc).strftime("%Y-%m-%d"))
    return "🎙 " + " · ".join(parts)


def meeting_message(
    meeting: Dict[str, Any],
    segments: Sequence[Dict[str, Any]],
    keyframes: Sequence[Dict[str, Any]] = (),
) -> str:
    """The message body.

    Deliberately readable as plain text. The card parses it, but a client that does not — an
    export, a mobile fallback, another persona reading the conversation later — sees a short
    account of the meeting rather than a marker and a blank.
    """
    # The title leads, because this line is what History shows for the whole conversation.
    header = f"{MESSAGE_PREFIX} {conversation_title(meeting)}"
    counts = [f"{len(segments)} segment{'' if len(segments) == 1 else 's'}"]
    if keyframes:
        counts.append(f"{len(keyframes)} slide{'' if len(keyframes) == 1 else 's'}")
    if meeting.get("started_at") and meeting.get("ended_at"):
        length = int((float(meeting["ended_at"]) - float(meeting["started_at"])) * 1000)
        counts.insert(0, export.clock(length))

    lines = [header, " · ".join(counts)]
    preview = [s for s in segments if (s.get("text") or "").strip()][:PREVIEW_SEGMENTS]
    if preview:
        lines.append("")
        for segment in preview:
            label = export.speaker_label(segment.get("speaker"))
            lines.append(f"{export.clock(segment.get('t0_ms'))} {label}: {segment['text'].strip()}")
        if len(segments) > len(preview):
            lines.append(f"… and {len(segments) - len(preview)} more.")
    else:
        lines.append("")
        lines.append("Nothing was transcribed.")
    return "\n".join(lines)


def finalize_meeting(meeting_id: str) -> Optional[str]:
    """Write the meeting into its conversation. Returns the title set, or ``None``.

    Called from the stop path, and therefore never allowed to raise: a meeting that recorded
    fine but could not write its message must still end. The transcript is already stored,
    which is the part that cannot be recovered.
    """
    try:
        from . import store
        from ..storage import add_message

        meeting = store.get_meeting(meeting_id)
        if not meeting or not meeting.get("conversation_id"):
            return None

        segments = store.get_segments(meeting_id)
        keyframes = store.get_keyframes(meeting_id)
        add_message(
            meeting["conversation_id"],
            "assistant",
            meeting_message(meeting, segments, keyframes),
            project_id=meeting.get("project_id"),
        )
        return conversation_title(meeting)
    except Exception:  # noqa: BLE001 — a failure here must not fail the meeting
        log.exception("meetingsense: could not finalize meeting %s", meeting_id)
        return None
