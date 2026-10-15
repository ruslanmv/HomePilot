"""Evidence validation: an item stays only if its quote really is in the line it cites.

The model is asked for verbatim quotes and the timestamp of the line they come from. Models
paraphrase, shift a stamp by a line, or invent a tidy sentence nobody said. This module is
the difference between a page that *looks* grounded and one that is: it resolves each
citation to a real segment (by id, else by nearest start time), compares the quote with the
segment text (substring after normalisation, else a fuzzy ratio against the best window),
tries the neighbouring lines, and drops the item when nothing matches.

Dropping is reported, not hidden: the ``ValidatorReport`` travels with the analysis and the
page shows the count.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .schema import Evidence, MeetingAnalysis, ValidatorReport

#: Fuzzy threshold for "the quote is this line, give or take a word".
MATCH_RATIO = 0.85
#: A quote shorter than this (in normalised characters) matches too easily to count.
MIN_QUOTE_CHARS = 8
#: How far (ms) a cited start may sit from a real segment start before it is "not that line".
STAMP_TOLERANCE_MS = 4000

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalise(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", (text or "").lower())).strip()


class SegmentIndex:
    """Segments by id and by start time, with neighbours."""

    def __init__(self, segments: Sequence[Dict[str, Any]]):
        self.rows: List[Dict[str, Any]] = [s for s in segments if (s.get("text") or "").strip()]
        self.rows.sort(key=lambda s: int(s.get("t0_ms") or 0))
        self.by_id = {str(s.get("id")): i for i, s in enumerate(self.rows) if s.get("id")}

    def locate(self, ev: Evidence) -> Optional[int]:
        if ev.segment_id and ev.segment_id in self.by_id:
            return self.by_id[ev.segment_id]
        if not self.rows:
            return None
        best, best_gap = None, None
        for i, s in enumerate(self.rows):
            gap = abs(int(s.get("t0_ms") or 0) - int(ev.t0_ms or 0))
            if best_gap is None or gap < best_gap:
                best, best_gap = i, gap
        if best is not None and best_gap is not None and best_gap <= STAMP_TOLERANCE_MS:
            return best
        return best if ev.quote else None

    def neighbours(self, i: int, span: int = 1) -> List[int]:
        return [j for j in range(i - span, i + span + 1) if 0 <= j < len(self.rows)]


def quote_matches(quote: str, text: str) -> Tuple[bool, float]:
    """Does ``quote`` appear in ``text``? Exact (normalised) substring first, then the best
    fuzzy window of the same word length."""
    q = normalise(quote)
    t = normalise(text)
    if len(q) < MIN_QUOTE_CHARS:
        return (bool(q) and q in t, 1.0 if q and q in t else 0.0)
    if q in t:
        return True, 1.0
    qw = q.split()
    tw = t.split()
    if not qw or not tw:
        return False, 0.0
    best = 0.0
    width = len(qw)
    for start in range(0, max(1, len(tw) - width + 1)):
        window = " ".join(tw[start:start + width])
        ratio = difflib.SequenceMatcher(None, q, window).ratio()
        if ratio > best:
            best = ratio
            if best >= 0.98:
                break
    return best >= MATCH_RATIO, best


def verify(ev: Evidence, index: SegmentIndex) -> Optional[Evidence]:
    """The evidence re-anchored to the segment that really carries the quote, or ``None``."""
    i = index.locate(ev)
    if i is None:
        return None
    candidates = [i] + [j for j in index.neighbours(i) if j != i]
    for j in candidates:
        seg = index.rows[j]
        ok, _ = quote_matches(ev.quote, seg.get("text") or "")
        if ok:
            return Evidence(segment_id=str(seg.get("id")) if seg.get("id") else None,
                            t0_ms=int(seg.get("t0_ms") or 0), t1_ms=seg.get("t1_ms"), quote=ev.quote)
    return None


def validate(analysis: MeetingAnalysis, segments: Sequence[Dict[str, Any]]) -> MeetingAnalysis:
    """Return the analysis with unverifiable items removed and a report attached.

    Items with no evidence at all are dropped too, except when the analysis is extractive
    (every extractive item is its own line, so this is a consistency check there).
    """
    index = SegmentIndex(segments)
    report = ValidatorReport()

    def keep(items: List[Any], name: str) -> List[Any]:
        kept: List[Any] = []
        for item in items:
            verified: List[Evidence] = []
            repaired = False
            for ev in item.evidence:
                good = verify(ev, index)
                if good is None:
                    continue
                if good.segment_id != ev.segment_id or good.t0_ms != ev.t0_ms:
                    repaired = True
                verified.append(good)
            if verified:
                item.evidence = verified
                kept.append(item)
                report.kept += 1
                if repaired:
                    report.repaired += 1
            else:
                report.dropped += 1
                label = getattr(item, "statement", None) or getattr(item, "title", None) or getattr(item, "text", "")
                report.notes.append(f"{name}: dropped “{str(label)[:80]}” — its quote is not in the transcript.")
        return kept

    analysis.decisions = keep(list(analysis.decisions), "decision")
    analysis.risks = keep(list(analysis.risks), "risk")
    analysis.action_items = keep(list(analysis.action_items), "action")
    analysis.open_questions = keep(list(analysis.open_questions), "question")
    analysis.conclusions = keep(list(analysis.conclusions), "conclusion")
    analysis.validator = report
    return analysis
