"""The prompts the notes engine sends (batch MS12).

Kept apart from the engine because a prompt is a thing people edit — read aloud, argued about,
tuned after a bad meeting — and a file of strings is easier to argue with than a file of
strings embedded in control flow.

Two rules shape everything here, and both come from D9.

**The recap is regenerated from the previous recap plus the new window, never from the
transcript.** That is what keeps the prompt a fixed size for a two-hour meeting as much as for
a ten-minute one. A recap built from the whole transcript would grow without bound and would
be the exact failure D9 exists to prevent — and a test asserts the transcript body never
reaches the recap prompt.

**Deltas, not rewrites.** The model is asked what to *add* and what to *resolve*, never for the
whole notes object. Asking for the whole thing means every pass can silently drop a decision
the last pass got right, and the card would rewrite itself under the reader — which §2a
forbids for the same reason it forbids editing a segment already on screen.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

#: Ceiling on the recap, in words. D9 says 3–5 sentences; this is the enforcement, because a
#: model asked for "3–5 sentences" will eventually send eight.
RECAP_MAX_WORDS = 120

#: What the notes engine may return. Anything else in the object is ignored rather than an
#: error, so a model that invents a key costs nothing and a later wave can add one without a
#: version negotiation.
DELTA_KEYS = ("add_decisions", "add_actions", "add_questions", "resolve_questions", "summary")


NOTES_SYSTEM = """\
You take notes in a live meeting. You are given the notes so far and the newest part of the \
transcript. Reply with a JSON object describing only what CHANGED.

Keys, all optional:
  add_decisions     [{"text": str, "t0": int}]   something the group settled
  add_actions       [{"text": str, "owner": str|null, "t0": int}]  something someone will do
  add_questions     [{"text": str, "t0": int}]   something raised and not yet answered
  resolve_questions [{"text": str, "t0": int}]   an earlier question now answered
  summary           str                          one or two sentences, only if it changed

Rules:
- `t0` is the millisecond timestamp of the line the item came from. Copy it from the
  transcript you were given. Never invent one, and omit the item if you cannot cite it.
- Only include a key when it has something in it. An empty object is the right answer for a
  window with nothing in it, and most windows have nothing in them.
- Do not repeat an item that is already in the notes.
- Small talk, greetings, scheduling chatter and thinking aloud are not decisions.
- Reply with the JSON object and nothing else."""


RECAP_SYSTEM = f"""\
You keep a running recap of a meeting, for someone who joined late.

You are given the recap so far and the newest part of the transcript. Write the new recap: \
what someone needs to know to follow the conversation from here.

Rules:
- {RECAP_MAX_WORDS} words maximum. Three to five sentences.
- Rewrite the whole recap, folding the new part in. Do not append.
- Keep what still matters, drop what has been superseded.
- Plain prose. No headings, no bullets, no preamble.
- You are never given the full transcript and must not ask for it."""


def transcript_window(segments: Sequence[Dict[str, Any]]) -> str:
    """Render segments for a prompt, with the timestamps the model must cite.

    The `t0` is in the text rather than in a parallel structure because the model has to copy
    it into its answer, and a model asked to correlate two lists gets it wrong often enough to
    matter. Speaker labels are the wire values — `me`/`them` — since the model's job is to tell
    who said what, not to write prose about them.
    """
    lines = []
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        speaker = segment.get("speaker") or "?"
        lines.append(f"[{int(segment.get('t0_ms') or 0)}] {speaker}: {text}")
    return "\n".join(lines)


def render_notes(notes: Dict[str, Any]) -> str:
    """The notes so far, as the model sees them.

    Deliberately compact: this goes into every window's prompt, so a verbose rendering is a
    cost paid once a minute for the length of the meeting.
    """
    if not notes:
        return "(nothing yet)"
    parts: List[str] = []
    if notes.get("summary"):
        parts.append(f"Summary: {notes['summary']}")
    for key, label in (("decisions", "Decisions"), ("actions", "Actions"), ("questions", "Open questions")):
        items = notes.get(key) or []
        if not items:
            continue
        parts.append(label + ":")
        for item in items:
            mark = "~~" if item.get("resolved") else ""
            owner = f" ({item['owner']})" if item.get("owner") else ""
            parts.append(f"  - {mark}{item.get('text', '')}{mark}{owner}")
    return "\n".join(parts) if parts else "(nothing yet)"


def notes_messages(notes: Dict[str, Any], segments: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The delta prompt: the notes so far, plus the newest window."""
    return [
        {"role": "system", "content": NOTES_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Notes so far:\n{render_notes(notes)}\n\n"
                f"New transcript:\n{transcript_window(segments)}"
            ),
        },
    ]


def recap_messages(previous_recap: str, segments: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The recap prompt: **the previous recap and the new window only**.

    This function is the whole of D9 tier 2, and the reason it takes a string rather than a
    meeting id is so that it *cannot* reach for the transcript. A test asserts that an older
    segment's text never appears in what this produces.
    """
    return [
        {"role": "system", "content": RECAP_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Recap so far:\n{previous_recap.strip() or '(the meeting has just started)'}\n\n"
                f"New transcript:\n{transcript_window(segments)}"
            ),
        },
    ]
