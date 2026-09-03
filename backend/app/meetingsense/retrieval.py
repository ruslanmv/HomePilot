"""Searching a meeting, and every meeting (batch MS15, wave W5 — "Memory").

MS13 answers questions by keyword-scoring this meeting's own rows. That works, and it stops
working at exactly the point people start asking the questions worth asking: *"when did we
last talk about the vendor contract?"* is a question about six meetings, and *"what did they
decide about pricing?"* asked of a two-hour meeting needs a passage that shares no words with
the question.

So on stop, a meeting is embedded. What that buys is retrieval **across** meetings and beyond
the words actually used; what it costs is a second store to keep in step, which is why the
delete path grew a third thing to remove.

**A meeting is retrieved from, never absorbed (D4).** The vectors live in their own Chroma
namespace — ``meetings``, never ``project_*`` — so ``get_project_document_count``,
``query_project_knowledge`` and ``delete_project_knowledge`` cannot see them. A user who
records a call must not watch their project's document count jump, and a persona answering
from project knowledge must not quote a meeting nobody attached. Attaching a meeting to a
project is a deliberate act, and MS16's route for it is the existing upload path.

**One collection, filtered, not one per meeting.** The batch row says "per-meeting and global";
this is the same capability at half the storage. Both queries a per-meeting collection would
serve — search this meeting, search all of them — are the global collection with and without a
``meeting_id`` filter, and deleting a meeting has to run the filtered delete either way, so the
second copy would buy nothing and double every index.

**Deterministic pruning, not model-decided (D9).** What is embedded is decided by rules a
person can check: segments under three words are dropped, a slide shown twice is embedded
once, images never (captions only), and consecutive segments are windowed into paragraphs. A
sentence embedded alone is a fragment that matches nothing.

**No Chroma is not a broken meeting.** An install without the package records, transcribes,
captions and exports exactly as before; `search` returns nothing and MS13 falls back to its
keyword scoring. Every function here swallows its failures for that reason.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import export, store

log = logging.getLogger(__name__)

#: The Chroma namespace. Anything but ``project`` keeps these out of the project functions —
#: see ``vectordb.collection_name``.
NAMESPACE = "meetings"

#: One collection holds every meeting, filtered by ``meeting_id``. The key is a constant
#: because there is nothing to key on: this is *the* meetings collection.
COLLECTION_KEY = "all"

#: Words per embedded chunk. A segment is about eight seconds of speech and often half a
#: sentence; embedded alone it is a fragment that matches nothing. A paragraph is the unit a
#: reader would quote, which is also the unit worth returning.
CHUNK_WORDS = 120

#: Segments shorter than this are dropped before embedding. "Yeah", "mm-hm" and "right" are
#: most of a meeting's segments and none of its content, and each one embedded is a row that
#: can be returned instead of an answer.
MIN_CHUNK_WORDS = 3

#: Default number of hits.
DEFAULT_K = 8


def _client(client: Any = None) -> Any:
    """Chroma, or ``None`` when this install has none."""
    if client is not None:
        return client
    try:
        from ..vectordb import get_chroma_client

        return get_chroma_client()
    except Exception:  # noqa: BLE001 — no Chroma is a capability, not a failure
        log.debug("meetingsense: no vector store available", exc_info=True)
        return None


def collection(client: Any = None) -> Any:
    """The meetings collection, or ``None``."""
    handle = _client(client)
    if handle is None:
        return None
    try:
        from ..vectordb import collection_name

        return handle.get_or_create_collection(
            name=collection_name(COLLECTION_KEY, NAMESPACE),
            metadata={"namespace": NAMESPACE, "key": COLLECTION_KEY},
        )
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: could not open the meetings collection", exc_info=True)
        return None


def word_count(text: str) -> int:
    return len((text or "").split())


def chunks(
    segments: Sequence[Dict[str, Any]],
    keyframes: Sequence[Dict[str, Any]] = (),
    *,
    chunk_words: int = CHUNK_WORDS,
) -> List[Dict[str, Any]]:
    """What gets embedded, and nothing else — D9's pre-compaction pruning, made explicit.

    Transcript first, windowed into paragraphs of roughly ``chunk_words``; then one row per
    *distinct* slide caption. Each carries the ``t0_ms`` of where it starts, because a hit that
    cannot be cited to a moment is a hit nobody can check.

    A window is closed at the word count rather than at a time boundary: a dense two minutes
    and a quiet ten are different amounts of content, and slicing by the clock would embed
    silence as though it were a paragraph.
    """
    rows: List[Dict[str, Any]] = []
    buffer: List[str] = []
    words = 0
    start: Optional[int] = None
    end: Optional[int] = None
    speakers: List[str] = []

    def flush() -> None:
        nonlocal buffer, words, start, end, speakers
        text = " ".join(buffer).strip()
        if text and words >= MIN_CHUNK_WORDS:
            rows.append(
                {
                    "kind": "transcript",
                    "t0_ms": int(start or 0),
                    "t1_ms": int(end if end is not None else (start or 0)),
                    # A window can span both sides of a conversation; "both" says so rather
                    # than picking whichever spoke first.
                    "speaker": speakers[0] if len(set(speakers)) == 1 and speakers else "both",
                    "text": text,
                }
            )
        buffer, words, start, end, speakers = [], 0, None, None, []

    for segment in segments:
        text = (segment.get("text") or "").strip()
        # Dropped before the window, not inside it: a filler segment absorbed into a paragraph
        # costs nothing, but one that becomes a chunk of its own is a row that can be returned
        # instead of an answer.
        if word_count(text) < MIN_CHUNK_WORDS and not buffer:
            continue
        if not text:
            continue
        if start is None:
            start = int(segment.get("t0_ms") or 0)
        end = int(segment.get("t1_ms") or segment.get("t0_ms") or end or 0)
        speakers.append(str(segment.get("speaker") or "?"))
        buffer.append(text)
        words += word_count(text)
        if words >= chunk_words:
            flush()
    flush()

    # Slides: the caption, never the image. A dHash seen already is the same slide shown
    # again — the timeline records that it was up twice, and the index does not need it twice.
    seen: set = set()
    for frame in keyframes:
        caption = (frame.get("caption") or "").strip()
        if not caption:
            continue
        key = frame.get("hash") or caption
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "kind": "slide",
                "t0_ms": int(frame.get("t_ms") or 0),
                "t1_ms": int(frame.get("t_ms") or 0),
                "speaker": "slide",
                "text": caption,
            }
        )

    rows.sort(key=lambda r: (r["t0_ms"], r["kind"]))
    return rows


def chunk_id(meeting_id: str, row: Dict[str, Any]) -> str:
    """Stable, so re-indexing a meeting replaces its rows rather than doubling them."""
    return f"{meeting_id}:{row['kind']}:{row['t0_ms']}"


def index_meeting(
    meeting_id: str,
    *,
    client: Any = None,
    meeting: Optional[Dict[str, Any]] = None,
) -> int:
    """Embed one finished meeting. Returns rows written — ``0`` for every kind of nothing.

    Called from `stop`, **after** the client has its `final` frame, and never allowed to
    raise: a meeting that recorded and summarised perfectly must not fail because a vector
    store was busy. The transcript is in SQLite, which is the copy that cannot be rebuilt;
    this one can, by stopping and re-indexing.

    Idempotent. Ids are derived from the meeting and the chunk's start, so re-indexing
    upserts rather than appending a second copy of the meeting to every search.
    """
    handle = collection(client)
    if handle is None:
        return 0
    try:
        record = meeting if meeting is not None else store.get_meeting(meeting_id)
        rows = chunks(store.get_segments(meeting_id), store.get_keyframes(meeting_id))
        if not rows:
            return 0
        title = ((record or {}).get("title") or "").strip() or "Meeting"
        started = (record or {}).get("started_at")
        metadatas = [
            {
                "meeting_id": meeting_id,
                # Denormalised so a hit can be cited without a database read per result, and
                # so a search still cites correctly on an install whose rows have been deleted.
                "title": title,
                "kind": row["kind"],
                "t0_ms": row["t0_ms"],
                "t1_ms": row["t1_ms"],
                "speaker": row["speaker"],
                "started_at": float(started) if started else 0.0,
            }
            for row in rows
        ]
        handle.upsert(
            ids=[chunk_id(meeting_id, row) for row in rows],
            documents=[row["text"] for row in rows],
            metadatas=metadatas,
        )
        log.info("meetingsense: indexed %d chunks for %s", len(rows), meeting_id)
        return len(rows)
    except Exception:  # noqa: BLE001 — an unsearchable meeting is still a meeting
        log.exception("meetingsense: could not index %s", meeting_id)
        return 0


def forget_meeting(meeting_id: str, *, client: Any = None) -> bool:
    """Remove one meeting's vectors. Returns whether the store was reachable.

    Called from the delete path, and the reason it exists: a meeting deleted from SQLite but
    left in the index is a meeting that still answers questions after the user deleted it,
    which is the worst possible reading of "delete".
    """
    handle = collection(client)
    if handle is None:
        return False
    try:
        handle.delete(where={"meeting_id": meeting_id})
        return True
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: could not remove %s from the index", meeting_id)
        return False


def cite(row: Dict[str, Any]) -> str:
    """``<title> · <hh:mm:ss>`` — what a cross-meeting answer points at.

    The title, not the id: an answer that says "meeting a3f9c2… at 00:12:03" is a citation
    nobody can follow. A meeting-scoped answer drops the title, because the reader is already
    looking at the meeting it names.
    """
    stamp = export.clock(row.get("t0_ms"))
    title = (row.get("title") or "").strip()
    return f"{title} · {stamp}" if title else stamp


def search(
    query: str,
    *,
    meeting_id: Optional[str] = None,
    k: int = DEFAULT_K,
    client: Any = None,
    exclude_after_ms: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Nearest chunks, in **time order**. Empty when there is no store or no query.

    ``meeting_id`` scopes to one meeting; without it this searches every meeting ever
    recorded, which is the capability the batch exists for.

    Time order rather than score order, the same rule MS13 follows: a model reading an answer
    out of fragments does better when they are in the order they were said, and so does a
    reader checking a citation. Score decides *which* rows; time decides how they are laid out.
    """
    query = (query or "").strip()
    if not query or k <= 0:
        return []
    handle = collection(client)
    if handle is None:
        return []

    where: Optional[Dict[str, Any]] = {"meeting_id": meeting_id} if meeting_id else None
    try:
        # Over-fetched, because `exclude_after_ms` drops what the verbatim tier already
        # carries and filtering after the query would otherwise return fewer than k.
        raw = handle.query(
            query_texts=[query],
            n_results=max(1, k * 2) if exclude_after_ms is not None else max(1, k),
            **({"where": where} if where else {}),
        )
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: vector search failed")
        return []

    rows = _rows(raw)
    if exclude_after_ms is not None:
        rows = [r for r in rows if r["t0_ms"] < exclude_after_ms]
    rows = rows[:k]
    rows.sort(key=lambda r: (r.get("started_at") or 0.0, r["t0_ms"]))
    return rows


def _rows(raw: Any) -> List[Dict[str, Any]]:
    """One Chroma answer → plain dicts, score order preserved.

    Written against the shape rather than trusting it: Chroma returns lists-of-lists and omits
    ``distances`` on some paths, and an index error here would take down a question the
    keyword tier could have answered.
    """
    if not isinstance(raw, dict):
        return []
    documents = (raw.get("documents") or [[]])[0] or []
    metadatas = (raw.get("metadatas") or [[]])[0] or []
    distances = (raw.get("distances") or [[]])[0] or []
    rows: List[Dict[str, Any]] = []
    for index, text in enumerate(documents):
        meta = metadatas[index] if index < len(metadatas) else {}
        meta = meta if isinstance(meta, dict) else {}
        distance = distances[index] if index < len(distances) else None
        rows.append(
            {
                "meeting_id": meta.get("meeting_id"),
                "title": meta.get("title"),
                "t0_ms": int(meta.get("t0_ms") or 0),
                "kind": meta.get("kind") or "transcript",
                "speaker": meta.get("speaker"),
                "started_at": float(meta.get("started_at") or 0.0),
                "text": text or "",
                # Reported, never thresholded on: a distance is only comparable to other
                # distances from the same query, so "similarity > 0.7" is a number that means
                # a different thing for every question asked.
                "similarity": None if distance is None else 1.0 - float(distance),
            }
        )
    return rows


def available(client: Any = None) -> bool:
    """Whether searching is possible here at all — for `/status` and for the card."""
    return collection(client) is not None


#: The tool surface personas reach meetings through (design part 2, §D.1). Named here so MS16's
#: brief and W6's grounded chat call one function rather than three copies of this signature.
def ms_search(query: str, meeting_id: Optional[str] = None, k: int = DEFAULT_K) -> List[Dict[str, Any]]:
    """``ms.search(query, meeting_id?|all, k)`` — returns rows carrying their own citation."""
    rows = search(query, meeting_id=meeting_id, k=k)
    for row in rows:
        row["cite"] = cite(row)
    return rows
