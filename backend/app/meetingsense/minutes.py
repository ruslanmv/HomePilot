"""The minutes of a very long meeting (batch MS34).

The rolling notes engine (MS12) writes a recap *while* a meeting runs, one window at a time,
and holds it to 120 words for the whole length of the meeting. That is the right shape for a
card somebody glances at mid-call and the wrong shape for the thing they need afterwards: a
three-hour workshop and a nine-minute stand-up both come out as the same four sentences, and
the two hours fifty-one minutes in between are represented by nothing at all.

This module is the *other* summary — written once, when the meeting has ended and the whole
transcript exists, and sized to the meeting rather than to a card.

── Why a map-reduce, and not one big prompt ────────────────────────────────────────────────

A two-hour meeting is roughly 20,000 words. Handed to a local model with an 8k window it is
truncated somewhere arbitrary, and what comes back is a confident summary of the first third
with nothing to say so. D9 refuses that for the *ask* path; the same refusal applies here.

So the transcript is cut into chunks of :data:`CHUNK_WORDS`, each chunk is summarised on its
own — that is the **map** — and the digests are summarised together into the final document,
which is the **reduce**. Every prompt is then bounded no matter how long the meeting was, and
the bound does not depend on anybody guessing the model's context window.

For a meeting long enough that even the digests do not fit — a full day, a conference track —
the digests are **folded** in groups of :data:`MAX_FANOUT` before the reduce, and folded again
if they still do not fit. That is the only part of this file that exists for "very long"
rather than "long", and it is three lines, because the map-reduce was the right shape to
begin with.

── Additive and non-destructive, stated as a property ──────────────────────────────────────

Nothing here writes to ``ms_notes``. The rolling recap, the decisions and the actions a
reader has already seen on the card are left exactly as the meeting left them; a summary
produced here is a **new artifact beside them**, and generating a second one in a different
style does not disturb the first. That matters more than it sounds: a user who asks for "the
same thing but as an email" must not lose the version they had already copied half of, and a
summariser that rewrote the meeting's notes would make every regeneration a small gamble.

A test asserts the notes row is byte-identical before and after.

── The style is the product ────────────────────────────────────────────────────────────────

"Summarise the meeting" is not one job. Minutes for the record, a recap email somebody sends
to people who were not there, personal notes, an executive brief, and a bare list of who owes
what are five different documents from the same transcript, and a single "summary" that tries
to be all five is a worse version of each. So the style is a first-class option, chosen at
session setup or at the moment of generating, and it selects the reduce prompt.

── It works with no model at all ───────────────────────────────────────────────────────────

An install whose Ollama is not running still ends its meeting, and still deserves something
better than a blank page. Every model call here degrades to an **extractive** digest — real
sentences, quoted with their timestamps, chosen by how much of the chunk's own vocabulary
they carry. It is not a summary and it does not claim to be one: the document says it was
assembled from the transcript. What it is not is empty.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from . import export, store

log = logging.getLogger(__name__)

#: Artifact kind a generated document is stored under. Never ``notes``.
SUMMARY_KIND = "summary"

#: Artifact kind the per-meeting preferences live under. One row, replaced on write.
PREFS_KIND = "summary_prefs"

#: Words of transcript one map call may carry. Sized so the whole prompt — system, framing
#: and chunk — stays well inside a small local model's window, because the install most
#: likely to record a three-hour meeting is the one running an 8k model on its own hardware.
CHUNK_WORDS = 700

#: Words repeated from the end of the previous chunk into the next. A chunk boundary that
#: lands mid-decision otherwise produces two digests that each saw half of it.
CHUNK_OVERLAP_WORDS = 40

#: Ceiling on one chunk's digest. The reduce prompt is ``fan-out × this``, so this number is
#: what actually bounds the second stage.
DIGEST_MAX_WORDS = 90

#: Digests one reduce (or fold) call may take. Beyond this they are folded first.
MAX_FANOUT = 20

#: Hard ceiling on chunks, and therefore on model calls. ~280,000 words of speech, about
#: thirty hours. A meeting longer than that is a recording nobody is going to read a summary
#: of either, and an unbounded loop of model calls is a worse answer than a truncated one.
MAX_CHUNKS = 400

#: Sentences an extractive digest may quote when no model is reachable.
EXTRACT_SENTENCES = 3

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: Words that carry no topic. Short on purpose — see the same list in :mod:`ask`.
_STOP = frozenset(
    """a an and are as at be been but by for from had has have he her his i in is it its
    me my of on or she that the their them they this to was we were what when which who will
    with you your""".split()
)


# ── what kind of document ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Style:
    """One kind of document this module can produce.

    ``system`` is the whole of what makes an email an email rather than minutes. Kept as data
    rather than as branches in the reduce function so that adding a sixth style is a dict
    entry, and so that the five can be read side by side and argued about.
    """

    id: str
    label: str
    note: str
    system: str


#: ``120 words`` and so on: the ceiling handed to the reduce prompt *and* enforced after it,
#: for the same reason `notes_engine.cap_words` enforces the recap's — a model told "350
#: words maximum" will eventually send 800, and a limit that is only a request is not a
#: limit.
LENGTHS: Dict[str, int] = {"short": 150, "standard": 400, "detailed": 900}

DEFAULT_LENGTH = "standard"


_SHARED_RULES = """\
- You are given digests of consecutive parts of the meeting, each with the time range it \
covers. You are NOT given the full transcript and must not ask for it.
- Cite a time as [hh:mm:ss], copying it from a digest you were given. Never invent one.
- Say only what the digests support. If something was not covered, leave it out rather than \
rounding it up into a claim.
- No preamble, no sign-off about being an AI, no meta-commentary about the summary itself."""


STYLES: Dict[str, Style] = {
    "minutes": Style(
        id="minutes",
        label="Minutes",
        note="Formal minutes for the record: what was discussed, settled and assigned.",
        system=(
            "You write the minutes of a meeting, for the record.\n\n"
            "Structure the document with these headings, omitting any with nothing under it:\n"
            "  ## Summary       two or three sentences on what the meeting was for\n"
            "  ## Discussion    the substance, in the order it happened, one paragraph per theme\n"
            "  ## Decisions     what was settled, one per line\n"
            "  ## Actions       who owes what, one per line, owner first\n"
            "  ## Open questions  what was raised and left unanswered\n\n"
            "Rules:\n" + _SHARED_RULES
        ),
    ),
    "notes": Style(
        id="notes",
        label="Notes",
        note="Personal notes: the shape of the conversation, in your own reading order.",
        system=(
            "You write somebody's private notes on a meeting they attended.\n\n"
            "Short headings for each theme, bullets underneath. Plain, direct, no ceremony — "
            "these are notes, not a report. Put anything the reader personally owes at the end "
            "under '## Mine to do'.\n\n"
            "Rules:\n" + _SHARED_RULES
        ),
    ),
    "email": Style(
        id="email",
        label="Recap email",
        note="A sendable recap for people who were not in the room.",
        system=(
            "You write a recap email about a meeting, to be sent to people who were not there.\n\n"
            "Begin with a single line 'Subject: ...' and then the body. The body opens with one "
            "sentence saying what the meeting was and when, then the substance in short "
            "paragraphs or bullets, then a clear 'Next steps' list naming who does what. Close "
            "with one short line inviting corrections.\n\n"
            "Write it so it can be sent as-is: no placeholders, no square-bracket blanks to "
            "fill in, and no names you were not given.\n\n"
            "Rules:\n" + _SHARED_RULES
        ),
    ),
    "brief": Style(
        id="brief",
        label="Executive brief",
        note="What somebody with two minutes needs: outcome first, detail under it.",
        system=(
            "You write an executive brief on a meeting, for a reader with two minutes.\n\n"
            "Open with '## Bottom line' — at most three sentences, the outcome first. Then "
            "'## Why' with the reasoning that got there, then '## What happens next'. Anything "
            "that does not change a decision is detail, and detail is what you leave out.\n\n"
            "Rules:\n" + _SHARED_RULES
        ),
    ),
    "actions": Style(
        id="actions",
        label="Action list",
        note="Only what is owed: owner, task, and when it was agreed.",
        system=(
            "You extract the commitments from a meeting and nothing else.\n\n"
            "One line per action: the owner, then the task, then the timestamp it was agreed "
            "at. Group under '## Actions'; put anything owed by nobody in particular under "
            "'## Unassigned'. If the meeting produced no commitments, say exactly that in one "
            "line — an invented action item is worse than an empty list.\n\n"
            "Rules:\n" + _SHARED_RULES
        ),
    ),
}

DEFAULT_STYLE = "minutes"


def style_catalog() -> List[Dict[str, str]]:
    """The styles, for a picker. Ids and prose, never the prompts."""
    return [{"id": s.id, "label": s.label, "note": s.note} for s in STYLES.values()]


@dataclass(frozen=True)
class Options:
    """What the user asked for. Normalised on the way in, so callers cannot smuggle a prompt.

    ``instructions`` is the escape hatch — "keep it in Spanish", "mention the budget numbers",
    "address it to the board" — and it is deliberately capped and quoted as *the user's*
    request in the prompt rather than concatenated into the system message, so a pasted
    paragraph cannot quietly replace the style's rules about citations.
    """

    style: str = DEFAULT_STYLE
    length: str = DEFAULT_LENGTH
    audience: str = ""
    language: str = ""
    instructions: str = ""

    #: Whether the document ends with the chronological digest of the whole meeting. This is
    #: the "summary transcript": one paragraph per chunk, in order, with its time range — the
    #: thing that makes a three-hour meeting navigable without reading three hours of lines.
    include_outline: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "style": self.style,
            "length": self.length,
            "audience": self.audience,
            "language": self.language,
            "instructions": self.instructions,
            "include_outline": self.include_outline,
        }

    @property
    def word_budget(self) -> int:
        return LENGTHS.get(self.length, LENGTHS[DEFAULT_LENGTH])

    @property
    def style_spec(self) -> Style:
        return STYLES.get(self.style, STYLES[DEFAULT_STYLE])


#: Most characters of free-form instruction one meeting may carry into a prompt.
MAX_INSTRUCTIONS = 600


def options_from(raw: Any) -> Options:
    """Build :class:`Options` from whatever a client sent. Never raises.

    An unknown style is the default rather than a 400: the picker is the client's, the
    document is the point, and refusing to summarise a finished meeting because a dropdown
    sent ``"Minutes"`` instead of ``"minutes"`` is a bad trade.
    """
    body = raw if isinstance(raw, dict) else {}

    def text(key: str, limit: int) -> str:
        return str(body.get(key) or "").strip()[:limit]

    style = str(body.get("style") or "").strip().lower()
    length = str(body.get("length") or "").strip().lower()
    outline = body.get("include_outline")
    return Options(
        style=style if style in STYLES else DEFAULT_STYLE,
        length=length if length in LENGTHS else DEFAULT_LENGTH,
        audience=text("audience", 120),
        language=text("language", 40),
        instructions=text("instructions", MAX_INSTRUCTIONS),
        include_outline=True if outline is None else bool(outline),
    )


# ── the per-meeting preference (set at session setup) ───────────────────────


def set_prefs(meeting_id: str, options: Options) -> Options:
    """Remember how this meeting wants to be summarised. Replaces, never appends.

    Written at ``start`` so the document that appears when the meeting ends is the one the
    user asked for in the setup dialog, rather than the default plus a regeneration.
    """
    try:
        store.delete_artifacts(meeting_id, kind=PREFS_KIND)
        store.add_artifact(meeting_id, kind=PREFS_KIND, target=options.style,
                           detail=json.dumps(options.as_dict()))
    except Exception:  # noqa: BLE001 — a preference is never worth a meeting
        log.exception("meetingsense: could not store summary preferences for %s", meeting_id)
    return options


def prefs(meeting_id: str) -> Options:
    """What this meeting asked for, or the defaults."""
    try:
        rows = store.artifacts_for_meeting(meeting_id, kind=PREFS_KIND)
    except Exception:  # noqa: BLE001
        return Options()
    for row in reversed(rows):
        try:
            return options_from(json.loads(row.get("detail") or ""))
        except ValueError:
            continue
    return Options()


# ── chunking ────────────────────────────────────────────────────────────────


def chunk(
    segments: Sequence[Dict[str, Any]],
    *,
    max_words: int = CHUNK_WORDS,
    overlap_words: int = CHUNK_OVERLAP_WORDS,
    max_chunks: int = MAX_CHUNKS,
) -> List[Dict[str, Any]]:
    """Cut the transcript into consecutive pieces small enough to summarise one at a time.

    Cut on **segment boundaries**, never mid-utterance: a chunk that ends halfway through a
    sentence produces a digest about half a thought, and the model has no way to know that is
    what happened.

    The overlap is carried as whole trailing segments rather than as words, for the same
    reason. It costs a little duplication and buys a decision that straddles a boundary being
    visible to at least one digest in full.
    """
    usable = [s for s in segments if (s.get("text") or "").strip()]
    if not usable:
        return []

    budget = max(50, int(max_words))
    chunks: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    words = 0

    def flush() -> None:
        nonlocal current, words
        if not current:
            return
        chunks.append({
            "index": len(chunks),
            "t0_ms": int(current[0].get("t0_ms") or 0),
            "t1_ms": int(current[-1].get("t1_ms") or current[-1].get("t0_ms") or 0),
            "segments": list(current),
            "words": words,
        })
        # The overlap: whole segments from the tail, up to the word allowance.
        carry: List[Dict[str, Any]] = []
        carried = 0
        for segment in reversed(current):
            length = len((segment.get("text") or "").split())
            if carried + length > max(0, int(overlap_words)):
                break
            carry.insert(0, segment)
            carried += length
        current = carry
        words = carried

    for segment in usable:
        length = len((segment.get("text") or "").split())
        if current and words + length > budget:
            flush()
            if len(chunks) >= max_chunks:
                break
        current.append(segment)
        words += length
    if len(chunks) < max_chunks:
        flush()
    return chunks


def render_chunk(rows: Sequence[Dict[str, Any]]) -> str:
    """One chunk as the model sees it — the same line shape the ask prompt uses."""
    lines = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{export.clock(row.get('t0_ms'))}] {export.speaker_label(row.get('speaker'))}: {text}")
    return "\n".join(lines)


def _range_label(piece: Dict[str, Any]) -> str:
    return f"{export.clock(piece.get('t0_ms'))}–{export.clock(piece.get('t1_ms'))}"


# ── the extractive floor (no model reachable) ───────────────────────────────


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


def extractive_digest(rows: Sequence[Dict[str, Any]], *, limit: int = EXTRACT_SENTENCES) -> str:
    """The most representative sentences of a chunk, quoted with their timestamps.

    Scored by how much of the chunk's own vocabulary a sentence carries, length-normalised
    the same way :func:`ask.score` is and for the same reason: without it the longest
    rambling sentence wins every time.

    This is extraction, not summarisation, and the document says so where it is used. The
    honest floor for an install with no language model is the meeting's own words.
    """
    counts: Dict[str, int] = {}
    pool: List[Dict[str, Any]] = []
    for row in rows:
        for sentence in _sentences((row.get("text") or "").strip()):
            terms = [w for w in (m.group(0).lower() for m in _WORD.finditer(sentence)) if w not in _STOP]
            if not terms:
                continue
            for term in set(terms):
                counts[term] = counts.get(term, 0) + 1
            pool.append({"t0_ms": int(row.get("t0_ms") or 0), "text": sentence, "terms": terms})
    if not pool:
        return ""

    for item in pool:
        weight = sum(counts.get(term, 0) for term in set(item["terms"]))
        item["_score"] = weight / math.log(len(item["terms"]) + 2)
    best = sorted(pool, key=lambda i: (-i["_score"], i["t0_ms"]))[:max(1, limit)]
    best.sort(key=lambda i: i["t0_ms"])
    return " ".join(f"[{export.clock(i['t0_ms'])}] {i['text']}" for i in best)


def cap_words(text: str, limit: int) -> str:
    """Hold a model's answer to the budget it was given. See `notes_engine.cap_words`."""
    words = (text or "").split()
    if len(words) <= limit:
        return (text or "").strip()
    return " ".join(words[:limit]).rstrip(",;:") + "…"


# ── map, fold, reduce ───────────────────────────────────────────────────────


MAP_SYSTEM = f"""\
You are digesting one part of a longer meeting so that it can be summarised as a whole.

You are given a consecutive slice of the transcript. Write what a reader would need to know \
about *this slice* to understand the meeting: the topics, what was settled, what was \
promised, what was asked and left open.

Rules:
- {DIGEST_MAX_WORDS} words maximum. Prose, not headings.
- Keep names, numbers, dates and commitments exactly as they were said. They are the part \
that cannot be recovered later.
- Cite a time as [hh:mm:ss] for anything settled or promised, copying it from the transcript \
you were given. Never invent one.
- This is one slice of a longer meeting. Do not open with "the meeting began" unless it did, \
and do not conclude — you cannot see the end.
- If the slice is small talk, say so in one line. Most slices are not."""


FOLD_SYSTEM = f"""\
You are merging several consecutive digests of one meeting into a single digest.

Rules:
- {DIGEST_MAX_WORDS * 2} words maximum.
- Keep every decision, commitment, name, number and date. Drop repetition and chatter.
- Keep the [hh:mm:ss] citations attached to what they belong to. Never invent one.
- Prose, in the order things happened. Do not conclude."""


class _Outage:
    """One report per summarisation, not one per chunk.

    A three-hour meeting is forty model calls. Against a stopped Ollama that is forty
    identical connection tracebacks in the log for one fact — nothing is listening — and
    they bury whatever real failure happens next. The same reasoning, and the same
    classifier, as `notes_engine._record_model_failure`: an unreachable model is an ordinary
    state of a self-hosted install and gets one line; a model that *answered* with something
    unusable is a bug and gets a traceback.
    """

    def __init__(self, meeting_id: str) -> None:
        self.meeting_id = meeting_id
        self.reported = False
        self.failures = 0

    def record(self, exc: BaseException, what: str) -> None:
        from .notes_engine import classify_model_failure

        self.failures += 1
        if classify_model_failure(exc) is None:
            log.exception("meetingsense: %s failed for %s", what, self.meeting_id)
            return
        if self.reported:
            return
        self.reported = True
        log.warning(
            "meetingsense: no language model reachable while summarising %s (%s: %s) — the "
            "summary falls back to the meeting's own words",
            self.meeting_id, type(exc).__name__, exc,
        )


async def _call_or_none(
    call: Optional[Callable[..., Awaitable[str]]],
    messages: List[Dict[str, str]],
    *,
    temperature: float,
    what: str,
    outage: Optional[_Outage] = None,
) -> Optional[str]:
    """One model call that can fail. ``None`` means "nothing answered", which is a fact the
    caller acts on — it is the difference between a degraded document and a bug."""
    if call is None:
        return None
    try:
        raw = await call(messages, temperature=temperature)
    except Exception as exc:  # noqa: BLE001 — never an exception on the stop path
        if outage is not None:
            outage.record(exc, what)
        else:
            log.warning("meetingsense: %s failed; falling back to the transcript", what)
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


async def map_chunks(
    chunks: Sequence[Dict[str, Any]],
    *,
    call: Optional[Callable[..., Awaitable[str]]],
    outage: Optional[_Outage] = None,
) -> List[Dict[str, Any]]:
    """One digest per chunk. Never raises, and never returns fewer than it was given.

    A chunk whose model call failed keeps its place in the chronology with an extractive
    digest, rather than leaving a hole: the reduce stage reads these in order, and a missing
    twenty minutes in the middle of a meeting is invisible in the output.
    """
    digests: List[Dict[str, Any]] = []
    for piece in chunks:
        body = render_chunk(piece["segments"])
        text = await _call_or_none(
            call,
            [
                {"role": "system", "content": MAP_SYSTEM},
                {"role": "user", "content": (
                    f"Part {piece['index'] + 1} of {len(chunks)}, covering "
                    f"{_range_label(piece)}:\n\n{body}"
                )},
            ],
            temperature=0.2,
            what=f"digest of part {piece['index'] + 1}",
            outage=outage,
        )
        degraded = text is None
        if degraded:
            text = extractive_digest(piece["segments"])
        digests.append({
            "index": piece["index"],
            "t0_ms": piece["t0_ms"],
            "t1_ms": piece["t1_ms"],
            "text": cap_words(text or "", DIGEST_MAX_WORDS * 2),
            "extractive": degraded,
        })
    return digests


async def fold(
    digests: Sequence[Dict[str, Any]],
    *,
    call: Optional[Callable[..., Awaitable[str]]],
    fan_out: int = MAX_FANOUT,
    outage: Optional[_Outage] = None,
) -> List[Dict[str, Any]]:
    """Merge digests in groups until ``fan_out`` of them are left. The "very long" case.

    A day-long recording produces sixty digests, and sixty digests is a reduce prompt as
    unbounded as the transcript was. Folding them in groups keeps every stage the same size
    whatever the length of the meeting — which is the whole reason the map-reduce exists, and
    it would be an odd thing to abandon at the last step.

    With no model reachable the groups are concatenated instead. That grows the document
    rather than shrinking it, which is the honest outcome: nothing here can compress text
    without a model, and silently dropping the middle of the meeting would be worse.
    """
    rows = list(digests)
    while len(rows) > max(2, fan_out):
        groups = [rows[i:i + fan_out] for i in range(0, len(rows), fan_out)]
        merged: List[Dict[str, Any]] = []
        for group in groups:
            if len(group) == 1:
                merged.append(group[0])
                continue
            body = "\n\n".join(f"{_range_label(d)}\n{d['text']}" for d in group)
            text = await _call_or_none(
                call,
                [{"role": "system", "content": FOLD_SYSTEM}, {"role": "user", "content": body}],
                temperature=0.2,
                what="folding digests",
                outage=outage,
            )
            extractive = text is None
            merged.append({
                "index": group[0]["index"],
                "t0_ms": group[0]["t0_ms"],
                "t1_ms": group[-1]["t1_ms"],
                "text": text or body,
                "extractive": extractive or any(d.get("extractive") for d in group),
            })
        if len(merged) >= len(rows):
            # Cannot get smaller — every group was a single digest. Stop rather than spin.
            break
        rows = merged
    return rows


def reduce_prompt(
    digests: Sequence[Dict[str, Any]],
    *,
    options: Options,
    meeting: Optional[Dict[str, Any]] = None,
    notes: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """The one prompt that produces the document. Bounded by construction.

    The meeting's own notes go in when they exist — decisions and actions the rolling engine
    already captured with citations the reader has seen. They are evidence, not competition:
    the document is written from the digests, and the notes stop a decision that happened in
    a quiet window from being rounded away.
    """
    spec = options.style_spec
    parts: List[str] = []

    if meeting:
        title = (meeting.get("title") or "").strip()
        header = [f"Meeting: {title}"] if title else []
        if meeting.get("started_at") and meeting.get("ended_at"):
            length = int((float(meeting["ended_at"]) - float(meeting["started_at"])) * 1000)
            header.append(f"Length: {export.clock(length)}")
        if header:
            parts.append(" · ".join(header))

    body = "\n\n".join(f"[{_range_label(d)}]\n{d['text']}" for d in digests if (d.get("text") or "").strip())
    parts.append(f"Digests of the meeting, in order:\n\n{body}")

    if isinstance(notes, dict):
        lines: List[str] = []
        for key, label in (("decisions", "Decisions"), ("actions", "Actions"), ("questions", "Open questions")):
            items = [i for i in (notes.get(key) or []) if isinstance(i, dict) and (i.get("text") or "").strip()]
            if not items:
                continue
            lines.append(f"{label}:")
            for item in items:
                owner = f" — {item['owner']}" if item.get("owner") else ""
                stamp = f" [{export.clock(item['t0'])}]" if isinstance(item.get("t0"), (int, float)) else ""
                lines.append(f"  - {item['text'].strip()}{owner}{stamp}")
        if lines:
            parts.append("Notes taken during the meeting:\n" + "\n".join(lines))

    wants: List[str] = [f"At most {options.word_budget} words."]
    if options.audience:
        wants.append(f"Written for: {options.audience}.")
    if options.language:
        wants.append(f"Write it in {options.language}.")
    parts.append("Requirements:\n" + "\n".join(f"- {w}" for w in wants))

    if options.instructions:
        # Quoted as the user's request rather than merged into the system message: a pasted
        # paragraph must not be able to replace the rules about citations above it.
        parts.append(
            "The reader also asked for the following. Follow it where it does not conflict "
            f"with the rules above:\n\"{options.instructions}\""
        )

    return [{"role": "system", "content": spec.system}, {"role": "user", "content": "\n\n".join(parts)}]


# ── the document ────────────────────────────────────────────────────────────


def outline(digests: Sequence[Dict[str, Any]]) -> str:
    """The summary transcript: the whole meeting in order, one paragraph per part.

    This is the part that makes a long recording *navigable*. A reader who disagrees with a
    line in the summary can find the twenty minutes it came from without scrolling through
    three hours of transcript, because every paragraph here carries the range it covers.
    """
    lines: List[str] = []
    for digest in digests:
        text = (digest.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"**{_range_label(digest)}** — {text}")
    return "\n\n".join(lines)


def extractive_document(digests: Sequence[Dict[str, Any]]) -> str:
    """The document when nothing could generate one. Says what it is, in its first line."""
    body = outline(digests)
    if not body:
        return ""
    return (
        "*No language model was reachable, so this is assembled from the meeting's own "
        "words rather than written.*\n\n## The meeting in order\n\n" + body
    )


async def summarise(
    meeting_id: str,
    *,
    call: Optional[Callable[..., Awaitable[str]]] = None,
    options: Optional[Options] = None,
    segments: Optional[Sequence[Dict[str, Any]]] = None,
    meeting: Optional[Dict[str, Any]] = None,
    notes: Optional[Dict[str, Any]] = None,
    now: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    """Summarise one meeting, however long it is. Never raises.

    Returns the document. ``text`` is empty only when the meeting has no transcript at all,
    and in that case ``reason`` says so — a caller should not have to guess the difference
    between "nothing was said" and "the summariser fell over".
    """
    opts = options or Options()
    rows = list(segments) if segments is not None else _segments(meeting_id)
    record = meeting if meeting is not None else _meeting(meeting_id)
    body = notes if notes is not None else _notes(meeting_id)

    pieces = chunk(rows)
    if not pieces:
        return {
            "meeting_id": meeting_id,
            "style": opts.style,
            "length": opts.length,
            "options": opts.as_dict(),
            "text": "",
            "outline": "",
            "sections": [],
            "chunks": 0,
            "words": 0,
            "degraded": None,
            "reason": "no_transcript",
            "created_at": now(),
        }

    outage = _Outage(meeting_id)
    digests = await map_chunks(pieces, call=call, outage=outage)
    folded = await fold(digests, call=call, outage=outage)

    text = await _call_or_none(
        call,
        reduce_prompt(folded, options=opts, meeting=record, notes=body),
        temperature=0.3,
        what="the meeting summary",
        outage=outage,
    )
    degraded = text is None
    if degraded:
        text = extractive_document(digests)
    else:
        text = cap_words(text, opts.word_budget * 2)

    chronology = outline(digests)
    if opts.include_outline and chronology and not degraded:
        text = f"{text}\n\n## The meeting in order\n\n{chronology}"

    return {
        "meeting_id": meeting_id,
        "style": opts.style,
        "length": opts.length,
        "label": opts.style_spec.label,
        "options": opts.as_dict(),
        "text": text,
        "outline": chronology,
        "sections": [
            {"t0_ms": d["t0_ms"], "t1_ms": d["t1_ms"], "text": d["text"], "extractive": d["extractive"]}
            for d in digests
        ],
        "chunks": len(pieces),
        "words": sum(p["words"] for p in pieces),
        "degraded": "extractive" if degraded or any(d["extractive"] for d in digests) else None,
        "reason": None,
        "created_at": now(),
    }


# ── storage: beside the notes, never over them ──────────────────────────────


def store_summary(meeting_id: str, document: Dict[str, Any]) -> Optional[str]:
    """Keep a generated document. Returns its id, or ``None`` if it could not be stored.

    An **append**. A meeting accumulates the documents it was asked for, and asking for an
    email after taking minutes leaves the minutes exactly where they were — which is the
    whole of what "non-destructive" means here, and the reason this is an artifact row rather
    than a column on the meeting.
    """
    if not (document.get("text") or "").strip():
        return None
    try:
        return store.add_artifact(
            meeting_id,
            kind=SUMMARY_KIND,
            target=str(document.get("style") or DEFAULT_STYLE),
            detail=json.dumps(document),
            created_at=document.get("created_at"),
        )
    except Exception:  # noqa: BLE001 — an unstored summary is still a summary to return
        log.exception("meetingsense: could not store the summary for %s", meeting_id)
        return None


def summaries(meeting_id: str) -> List[Dict[str, Any]]:
    """Every document generated for this meeting, oldest first."""
    try:
        rows = store.artifacts_for_meeting(meeting_id, kind=SUMMARY_KIND)
    except Exception:  # noqa: BLE001
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            document = json.loads(row.get("detail") or "")
        except ValueError:
            continue
        if isinstance(document, dict) and (document.get("text") or "").strip():
            out.append({**document, "id": row.get("id")})
    return out


def latest(meeting_id: str, *, style: str = "") -> Optional[Dict[str, Any]]:
    """The most recent document, optionally of one style."""
    rows = summaries(meeting_id)
    if style:
        rows = [r for r in rows if r.get("style") == style]
    return rows[-1] if rows else None


async def autogenerate(
    meeting_id: str,
    *,
    call: Optional[Callable[..., Awaitable[str]]] = None,
    options: Optional[Options] = None,
) -> Optional[Dict[str, Any]]:
    """Write the meeting's document when it ends. Never raises, never blocks a stop.

    Called from the stop path, which is why the whole body is inside one try: a meeting that
    recorded a perfectly good transcript must end cleanly even if the summariser cannot run,
    and the transcript is the part that cannot be rebuilt.
    """
    try:
        opts = options or prefs(meeting_id)
        document = await summarise(meeting_id, call=call, options=opts)
        if not (document.get("text") or "").strip():
            return None
        stored = store_summary(meeting_id, document)
        return {**document, "id": stored}
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: could not summarise %s", meeting_id)
        return None


# ── store access, kept dull and failure-tolerant ────────────────────────────


def _segments(meeting_id: str) -> List[Dict[str, Any]]:
    try:
        return list(store.get_segments(meeting_id))
    except Exception:  # noqa: BLE001
        return []


def _meeting(meeting_id: str) -> Optional[Dict[str, Any]]:
    try:
        return store.get_meeting(meeting_id)
    except Exception:  # noqa: BLE001
        return None


def _notes(meeting_id: str) -> Optional[Dict[str, Any]]:
    try:
        return export.notes_body(store.get_notes(meeting_id))
    except Exception:  # noqa: BLE001
        return None
