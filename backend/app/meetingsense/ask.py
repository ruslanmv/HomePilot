"""Asking about a meeting (batch MS13, decision D9 tier 3).

The question this module answers is "what did they decide about legal?", and the constraint it
answers it under is that **the full transcript never goes into the prompt**. A two-hour meeting
is perhaps 20,000 words; a prompt built from it is slow, expensive, and — on a local model with
an 8k window — simply truncated somewhere arbitrary, which produces an answer that is confidently
wrong about the part that got cut.

So the prompt is assembled from three tiers, and the budget is enforced rather than hoped for:

1. **verbatim** — the last 90 seconds, because a question asked during a meeting is usually
   about the thing just said;
2. **compressed** — the rolling recap from MS12, which is already a bounded summary of
   everything older;
3. **retrieval** — at most ``MAX_RETRIEVED`` segments that actually match the question, each
   carrying its timestamp so the answer can cite it.

Retrieval here is keyword scoring over this meeting's own rows. MS15 replaces the *scoring*
with a vector search and leaves everything else alone — which is why :func:`retrieve` is a
separate function with a boring signature rather than three lines inside the prompt builder.

**A citation is only offered if it exists.** Every timestamp in the prompt comes from a real
segment, and the system prompt tells the model to cite only what it was given. A model that
invents "at 00:42:15" about a meeting that ran twelve minutes is worse than one that says it
does not know, because the first is checkable only by someone who already has the answer.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from . import export, store

log = logging.getLogger(__name__)

#: The verbatim tier: what a question asked mid-meeting is usually about.
VERBATIM_MS = 90_000

#: Segments the verbatim tier falls back to when the time window is empty.
#:
#: The window is measured against the **session clock**, which is right — a question asked
#: during a silence is still about now — and has one consequence that is not: after ninety
#: seconds of nobody speaking, a window anchored to the clock contains no transcript at all.
#: A broad question then has no evidence behind it, and "what are they talking about?" comes
#: back as *that question could not be answered from this meeting*, about a meeting whose
#: transcript is on screen beside the answer.
#:
#: So the window has a floor: whatever the clock says, the last few things that were actually
#: said are always in the prompt. The tail is small on purpose — it is the difference between
#: no context and some, not a second retrieval tier.
MIN_VERBATIM_ROWS = 6

#: The retrieval tier's ceiling. Twelve segments is roughly two minutes of speech spread across
#: the meeting — enough to answer with, small enough that the budget below is reachable.
MAX_RETRIEVED = 12

#: D9's budget for the whole meeting block. Enforced by trimming the retrieval tier first and
#: the verbatim tier second; the recap is never trimmed, because it is the only tier that
#: represents the parts of the meeting nothing else can reach.
TOKEN_BUDGET = 900

#: The attachments tier's own budget, deliberately outside :data:`TOKEN_BUDGET`.
#:
#: Material the user attached to the session — a brief, an agenda, last week's minutes — is
#: not part of the meeting, so it is not part of the meeting block D9 sizes. Giving it its
#: own small allowance keeps both promises at once: the transcript block is still bounded at
#: exactly what D9 says, and a question the attachment answers is not refused because the
#: transcript filled the prompt.
ATTACHMENT_BUDGET = 220

#: Rough tokens-per-character. An estimate, and named as one: the alternative is importing a
#: tokeniser to decide how much of a transcript to include, which costs more than the slack
#: this ratio leaves.
CHARS_PER_TOKEN = 4

_WORD = re.compile(r"[^\W_]+", re.UNICODE)

#: Words that match everything and therefore rank nothing. Kept short deliberately — an
#: aggressive stop list drops "who", "when" and "why", which are exactly the words that make a
#: meeting question specific.
_STOP = frozenset(
    """a an and are as at be been by for from had has have i in is it its of on or that the
    to was were what will with you your we they he she""".split()
)


def estimate_tokens(text: str) -> int:
    """A cheap upper-ish estimate. See :data:`CHARS_PER_TOKEN`."""
    return max(0, len(text or "")) // CHARS_PER_TOKEN


def keywords(question: str) -> List[str]:
    """The words worth matching on. Empty when the question is only stop words."""
    return [w for w in (m.group(0).lower() for m in _WORD.finditer(question or "")) if w not in _STOP]


def score(text: str, terms: Sequence[str]) -> float:
    """How well one segment answers a question, by keyword overlap.

    Distinct terms matched rather than total occurrences: a segment repeating "legal" six times
    is not six times as relevant as one that mentions legal *and* October, and rewarding
    repetition surfaces the rambling parts of a meeting over the decisive ones.

    Length-normalised gently — ``/ log`` rather than ``/ len`` — so a long segment that genuinely
    covers the question is not beaten by a three-word one that happens to contain the term.

    The denominator is the segment's **total** word count, not its distinct one. Normalising by
    distinct words looks equivalent and is not: a segment saying "legal legal legal legal legal"
    has a vocabulary of one, so it comes out with the *highest* score in the meeting — exactly
    the rambling passage this function is meant to rank below the decisive one. Repetition
    should cost length, and only total length charges it.
    """
    if not terms:
        return 0.0
    words = [m.group(0).lower() for m in _WORD.finditer(text or "")]
    if not words:
        return 0.0
    hits = sum(1 for term in set(terms) if term in set(words))
    if not hits:
        return 0.0
    return hits / math.log(len(words) + 2)


def retrieve(
    segments: Sequence[Dict[str, Any]],
    keyframes: Sequence[Dict[str, Any]],
    question: str,
    *,
    limit: int = MAX_RETRIEVED,
    exclude_after_ms: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """The top-``limit`` rows that match the question, in time order.

    ``exclude_after_ms`` drops what the verbatim tier already carries, so the same sentence is
    not paid for twice — which on a short meeting is most of the budget.

    Returned in **time order** rather than score order: a model reading an answer out of
    fragments does better when they are in the order they were said, and a reader checking a
    citation does too. Score decides *which* twelve; time decides how they are laid out.

    MS15 replaces the scoring here with a vector search over the meeting namespace. The
    signature is deliberately dull so that when it does, nothing above this line changes.
    """
    terms = keywords(question)
    if not terms:
        return []

    candidates: List[Dict[str, Any]] = []
    for segment in segments:
        t0 = int(segment.get("t0_ms") or 0)
        if exclude_after_ms is not None and t0 >= exclude_after_ms:
            continue
        value = score(segment.get("text") or "", terms)
        if value > 0:
            candidates.append({"t0_ms": t0, "text": segment.get("text") or "",
                               "speaker": segment.get("speaker"), "kind": "segment", "_score": value})

    for frame in keyframes:
        caption = (frame.get("caption") or "").strip()
        if not caption:
            continue
        value = score(caption, terms)
        if value > 0:
            candidates.append({"t0_ms": int(frame.get("t_ms") or 0), "text": caption,
                               "speaker": None, "kind": "slide", "_score": value})

    candidates.sort(key=lambda c: (-c["_score"], c["t0_ms"]))
    top = candidates[:limit]
    top.sort(key=lambda c: c["t0_ms"])
    for item in top:
        item.pop("_score", None)
    return top


def fuse(
    vector_rows: Sequence[Dict[str, Any]],
    keyword_rows: Sequence[Dict[str, Any]],
    *,
    limit: int = MAX_RETRIEVED,
) -> List[Dict[str, Any]]:
    """Combine the two retrievers (MS15), interleaved by rank, then in time order.

    **Neither scorer is trusted alone**, which is the whole reason this is not a choice between
    them. Embeddings find the passage that answers a question in words the question did not
    use — "what did we decide about pricing?" against a paragraph that says "we will hold at
    forty a seat" — and are unreliable on the exact tokens people actually ask about: a part
    number, a name, "the four-one-two figure". Keyword scoring is the reverse. A meeting where
    only one of them fires is the normal case.

    Interleaved by *rank* rather than merged by score, because the two scores are not
    comparable: a cosine distance and a length-normalised term count share no scale, and
    sorting one list by both is arithmetic that means nothing. Taking each retriever's best,
    then its second, and so on, asks only that each ranks its own hits correctly.

    De-duplicated on the start time, which is the identity of a passage across both: the same
    moment found twice would otherwise spend the budget twice on one answer.
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()
    vector = list(vector_rows)
    keyword = list(keyword_rows)
    for index in range(max(len(vector), len(keyword))):
        for source in (vector, keyword):
            if index >= len(source) or len(out) >= limit:
                continue
            row = source[index]
            key = (row.get("meeting_id"), int(row.get("t0_ms") or 0))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        if len(out) >= limit:
            break
    out.sort(key=lambda r: int(r.get("t0_ms") or 0))
    return out


def verbatim(
    segments: Sequence[Dict[str, Any]],
    *,
    now_ms: int,
    window_ms: int = VERBATIM_MS,
    min_rows: int = MIN_VERBATIM_ROWS,
) -> List[Dict[str, Any]]:
    """The last ``window_ms`` of transcript — D9 tier 1 — but never nothing.

    See :data:`MIN_VERBATIM_ROWS`. When the clock has run past the last thing anybody said,
    the window is empty and the tail is what stands in for it: a question asked after a
    silence is still a question about this meeting, and answering it from no transcript at
    all is the one outcome that is never useful.
    """
    floor = max(0, now_ms - window_ms)
    inside = [s for s in segments if int(s.get("t0_ms") or 0) >= floor]
    if inside or min_rows <= 0:
        return inside
    return [s for s in segments if (s.get("text") or "").strip()][-min_rows:]


def _render(rows: Sequence[Dict[str, Any]]) -> str:
    lines = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        stamp = export.clock(row.get("t0_ms"))
        label = "slide" if row.get("kind") == "slide" else (row.get("speaker") or "?")
        lines.append(f"[{stamp}] {label}: {text}")
    return "\n".join(lines)


def _extractive_fallback(
    *,
    recap: str,
    verbatim_rows: Sequence[Dict[str, Any]],
    retrieved_rows: Sequence[Dict[str, Any]],
    attachments: Sequence[Dict[str, Any]] = (),
) -> str:
    """Return a useful grounded answer when generation is unavailable.

    Meeting Q&A should degrade to evidence, not to a dead-end error. Prefer rows selected by
    retrieval for specific questions; otherwise use the newest transcript lines, which makes
    broad live questions such as "what are they talking about?" useful even before a recap
    exists. This is deliberately extractive: without a language model we can quote the record,
    but we must not pretend to have inferred more than it says.
    """
    preferred = list(retrieved_rows) or list(verbatim_rows)
    if preferred:
        rows = preferred[-3:]
        rendered = _render(rows)
        if rendered:
            return f"From the meeting transcript:\n{rendered}"
    if recap.strip():
        return f"From the meeting recap: {recap.strip()}"
    attached = _render_attachments(attachments, budget=ATTACHMENT_BUDGET // 2)
    if attached:
        return f"Nothing in the transcript covers this. From the material attached to this session:\n{attached}"
    return ""


#: What is said when a meeting genuinely has nothing to answer from.
#:
#: A sentence rather than an empty string, because empty is what every client turns into
#: *"that question could not be answered from this meeting"* — a message that is indistinct
#: from a bug, and that a user reads as the feature being broken while the transcript sits on
#: screen beside it. These two say which of the two situations it actually is.
NOTHING_TRANSCRIBED = (
    "Nothing has been transcribed in this meeting yet, so there is nothing to answer from. "
    "Check that an audio source is being received, and ask again once somebody has spoken."
)
NOTHING_MATCHED = (
    "I could not find anything about that in what has been captured of this meeting so far."
)


def _attachments(meeting_id: str) -> List[Dict[str, Any]]:
    """Material the user attached to this session, for grounding the answer.

    The same rows Coach draws on, read through the same function, so "what did I attach" has
    one answer rather than two. Failure is empty rather than an exception: an install with no
    artifacts table has no attachments, and that is not a reason to lose an answer the
    transcript could have given on its own.
    """
    try:
        from .agent import coaching as coaching_mod

        return list(coaching_mod.prep(meeting_id))
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: no session attachments for %s", meeting_id, exc_info=True)
        return []


ASK_SYSTEM = """\
You answer questions about a meeting, using only what you are given.

You are given a recap of the meeting, the most recent part of the transcript, the parts of \
the transcript that best match the question, and anything attached to this session. You are \
NOT given the full transcript, and you must not ask for it.

The meeting may still be running. What you have is what has been said so far, and that is an \
answer to "what are they talking about", not a reason to refuse one.

Rules:
- Answer in two or three sentences. No preamble.
- Cite the timestamp of anything you quote or rely on, in the form [hh:mm:ss], copying it \
exactly from what you were given.
- Never invent a timestamp. If nothing you were given supports an answer, say that the \
meeting does not appear to cover it — that is a useful answer, and a confident wrong one is not.
- Say when something came from the attached material rather than from the meeting.
- If the question is about a part you cannot see, say so."""


def _render_attachments(rows: Sequence[Dict[str, Any]], *, budget: int = ATTACHMENT_BUDGET) -> str:
    """Session material, trimmed to :data:`ATTACHMENT_BUDGET`.

    Truncated rather than dropped, whole documents first, for the reason `coaching._trim`
    gives: the first thing a user attaches is usually the brief, and half a brief is more use
    than none of it.
    """
    out: List[str] = []
    left = max(0, int(budget)) * CHARS_PER_TOKEN
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text or left <= 0:
            continue
        title = (row.get("title") or "Attachment").strip() or "Attachment"
        if len(text) > left:
            text = text[:left].rstrip() + "…"
        left -= len(text)
        out.append(f"— {title}\n{text}")
    return "\n\n".join(out)


def build_prompt(
    question: str,
    *,
    recap: str = "",
    verbatim_rows: Sequence[Dict[str, Any]] = (),
    retrieved_rows: Sequence[Dict[str, Any]] = (),
    attachments: Sequence[Dict[str, Any]] = (),
    budget: int = TOKEN_BUDGET,
    mode: str = "",
) -> List[Dict[str, str]]:
    """Assemble the tiers, trimming to the budget.

    The trim order is the whole of D9's priority, made executable: **retrieval first, verbatim
    second, the recap never.** The recap is the only tier that represents the parts of the
    meeting nothing else can reach, so dropping it to make room for a transcript fragment
    trades the summary of two hours for thirty seconds of detail.

    ``attachments`` sit outside that budget and are bounded by their own — see
    :data:`ATTACHMENT_BUDGET`. They are not the meeting, so they do not compete with it.
    """
    retrieved = list(retrieved_rows)
    verbatim_list = list(verbatim_rows)

    def render(retr, verb) -> str:
        parts = []
        if recap.strip():
            parts.append(f"Recap of the meeting so far:\n{recap.strip()}")
        if retr:
            parts.append(f"Relevant parts of the transcript:\n{_render(retr)}")
        if verb:
            parts.append(f"The last minute or two:\n{_render(verb)}")
        parts.append(f"Question: {question.strip()}")
        return "\n\n".join(parts)

    body = render(retrieved, verbatim_list)
    while estimate_tokens(body) > budget and retrieved:
        # Oldest retrieved row goes first: the newest is likeliest to be what the question is
        # about, and dropping from the end would strip the context nearest the asking.
        retrieved.pop(0)
        body = render(retrieved, verbatim_list)
    while estimate_tokens(body) > budget and verbatim_list:
        verbatim_list.pop(0)
        body = render(retrieved, verbatim_list)

    # Prepended after the trim, so what the attachments cost is never taken out of the
    # meeting — and so a prompt with no attachments is byte-identical to what MS13 shipped.
    attached = _render_attachments(attachments)
    if attached:
        body = f"Material attached to this session:\n{attached}\n\n{body}"

    # MS26. A mode's framing is layered *above* `ASK_SYSTEM`, never in place of it: the base
    # carries "cite the timestamp" and "never invent one", and those are not a Participant's
    # to relax. With no mode, the system prompt is byte-identical to what MS13 shipped.
    system = ASK_SYSTEM
    if mode:
        from .agent import mode_prompts

        system = mode_prompts.system_for(mode, ASK_SYSTEM)

    return [{"role": "system", "content": system}, {"role": "user", "content": body}]


async def answer(
    meeting_id: str,
    question: str,
    *,
    call: Callable[..., Awaitable[str]],
    now_ms: Optional[int] = None,
    limit: int = MAX_RETRIEVED,
    budget: int = TOKEN_BUDGET,
    vector_search: Optional[Callable[..., Sequence[Dict[str, Any]]]] = None,
    attachments: Optional[Sequence[Dict[str, Any]]] = None,
    mode: str = "",
) -> Dict[str, Any]:
    """Answer one question about one meeting, live or ended.

    Returns an ``answer`` frame. Never raises, and — past an empty question — never returns
    empty ``text``: a question that cannot be answered gets an answer *saying so*, because
    the alternative on the WebSocket path is a dropped meeting and on the HTTP path is a
    client inventing its own error message about a meeting it can see the transcript of.
    """
    question = (question or "").strip()
    if not question:
        return {"type": "answer", "text": "", "error": "empty_question", "cited": []}

    segments = store.get_segments(meeting_id)
    keyframes = store.get_keyframes(meeting_id)
    notes = store.get_notes(meeting_id)
    recap = ""
    body = export.notes_body(notes)
    if body:
        recap = (body.get("recap") or body.get("summary") or "").strip()

    end_ms = now_ms
    if end_ms is None:
        ends = [int(s.get("t1_ms") or s.get("t0_ms") or 0) for s in segments]
        end_ms = max(ends) if ends else 0

    verbatim_rows = verbatim(segments, now_ms=end_ms)
    floor = max(0, end_ms - VERBATIM_MS)
    keyword_rows = retrieve(segments, keyframes, question, limit=limit, exclude_after_ms=floor)

    # MS15. A live meeting is not indexed yet — indexing happens on stop — so this is empty
    # during the meeting and the keyword tier is the whole of retrieval, which is what MS13
    # shipped. Once the meeting has ended, both fire and `fuse` interleaves them.
    vector_rows: Sequence[Dict[str, Any]] = ()
    finder = vector_search
    if finder is None:
        from . import retrieval as retrieval_mod

        finder = retrieval_mod.search
    try:
        vector_rows = finder(question, meeting_id=meeting_id, k=limit, exclude_after_ms=floor) or ()
    except Exception:  # noqa: BLE001 — a missing vector store must not lose a keyword answer
        log.debug("meetingsense: vector retrieval unavailable for %s", meeting_id, exc_info=True)
        vector_rows = ()

    retrieved_rows = fuse(vector_rows, keyword_rows, limit=limit)
    attached = attachments if attachments is not None else _attachments(meeting_id)

    messages = build_prompt(
        question,
        recap=recap,
        verbatim_rows=verbatim_rows,
        retrieved_rows=retrieved_rows,
        attachments=attached,
        budget=budget,
        mode=mode,
    )
    degraded = False
    try:
        text = await call(messages, temperature=0.2)
    except Exception:  # noqa: BLE001 — a failed answer is never worth the meeting
        log.exception("meetingsense: ask generation failed for %s; using transcript fallback", meeting_id)
        text = _extractive_fallback(
            recap=recap,
            verbatim_rows=verbatim_rows,
            retrieved_rows=retrieved_rows,
            attachments=attached,
        )
        degraded = True

    text = (text or "").strip() if isinstance(text, str) else ""
    if not text:
        text = _extractive_fallback(
            recap=recap,
            verbatim_rows=verbatim_rows,
            retrieved_rows=retrieved_rows,
            attachments=attached,
        )
        degraded = bool(text)

    # Still nothing. Say which kind of nothing it is, in a sentence the user can act on,
    # rather than handing the client an empty string to guess about.
    reason: Optional[str] = None
    if not text:
        spoken = any((s.get("text") or "").strip() for s in segments)
        reason = "no_transcript" if not spoken else "no_meeting_context"
        text = NOTHING_MATCHED if spoken else NOTHING_TRANSCRIBED

    offered = {export.clock(r.get("t0_ms")) for r in list(retrieved_rows) + list(verbatim_rows)}
    return {
        "type": "answer",
        "text": text,
        # What the model was actually given, so a client can render the citations as links and
        # a test can check that nothing else was cited.
        "cited": sorted(stamp for stamp in offered if stamp in text),
        "sources": len(retrieved_rows) + len(verbatim_rows),
        # How the answer was produced, so a client can label it honestly: `extractive` means
        # the meeting's own words rather than a written answer, which is what an install with
        # no reachable model gets.
        "degraded": "extractive" if degraded else None,
        "attachments": len(attached),
        **({"error": reason} if reason else {}),
    }
