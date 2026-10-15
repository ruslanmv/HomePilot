"""Transcript → ``MeetingAnalysis``: map each chunk to cited candidates, reduce once.

The shape follows ``minutes.py`` on purpose — the same chunker, the same bounded prompts,
the same "one outage, one log line" rule — but the output is data, not prose:

* **map**: every chunk yields candidate topics, decisions, risks, actions and questions,
  each with a verbatim quote and the stamp of the line it came from;
* **reduce**: one call merges the candidates into the final lists and *cites candidate
  ids* instead of re-quoting, so evidence survives the merge untouched;
* **validate** (``validate.py``): anything whose quote is not in the transcript is dropped.

Without a model the analysis is **extractive**: cue words pick the lines that sound like
decisions, actions, risks and questions, each citing itself, and ``degraded`` says so. That is
the honest floor — the meeting's own words, never a guess dressed as a summary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from .. import export, minutes
from .schema import (
    ActionItem, Conclusion, Decision, Evidence, MeetingAnalysis, OpenQuestion, Risk, SpeakerStat, Topic,
    ValidatorReport,
)
from .validate import normalise, validate

log = logging.getLogger(__name__)

ModelCall = Callable[..., Awaitable[str]]

#: Parallel map calls per analysis. Four keeps a 60-minute meeting to a handful of rounds
#: without starving the chat model that shares the GPU.
MAP_CONCURRENCY = 4
MAP_MAX_TOKENS = 900
REDUCE_MAX_TOKENS = 1400
#: Candidate caps per kind before the reduce — a bound on the prompt, not on the meeting.
CANDIDATE_CAP = {"topics": 48, "decisions": 40, "risks": 30, "actions": 40, "questions": 30}

MAP_SYSTEM = """\
You read one consecutive slice of a meeting transcript and list what it establishes.
Return ONLY a JSON object with the keys topics, decisions, risks, actions, questions.

Rules:
- Quote verbatim. Every decision, risk, action and question carries "quote": the exact words \
of ONE transcript line (copy them, never paraphrase) and "t0": that line's [hh:mm:ss] stamp.
- A decision is "confirmed" only when the speakers agree ("we agreed", "let's go with", \
"the decision is"); "proposed" for a suggestion ("we could", "maybe", "I think we should"); \
"rejected" when it was turned down.
- Never invent owners or dates: leave them empty unless said. Owners use speaker names as \
written.
- Keep every text under 30 words. Any list may be empty. No commentary outside the JSON.

Shape:
{"topics":[{"label":"...","summary":"..."}],
 "decisions":[{"statement":"...","status":"confirmed|proposed|rejected","quote":"...","t0":"hh:mm:ss"}],
 "risks":[{"title":"...","severity":"high|medium|low","detail":"...","root_cause":"...",\
"solutions":["..."],"quote":"...","t0":"hh:mm:ss"}],
 "actions":[{"text":"...","owner":"","due_text":"","quote":"...","t0":"hh:mm:ss"}],
 "questions":[{"text":"...","quote":"...","t0":"hh:mm:ss"}]}"""

REDUCE_SYSTEM = """\
You merge candidate findings from consecutive parts of ONE meeting into its final analysis.
Return ONLY a JSON object:
{"title":"...","one_line":"...",
 "topics":[{"label":"...","summary":"...","from":["t3","t7"]}],
 "decisions":[{"statement":"...","status":"confirmed|proposed|rejected","from":["d2","d9"]}],
 "risks":[{"title":"...","severity":"high|medium|low","detail":"...","root_cause":"...",\
"solutions":["..."],"from":["r1"]}],
 "actions":[{"text":"...","owner":"","due_text":"","from":["a4"]}],
 "questions":[{"text":"...","from":["q2"]}],
 "conclusions":[{"text":"...","from":["d2","r1"]}]}

Rules:
- "from" lists the candidate ids you merged, copied exactly. An item with no candidate id is \
dropped, so always cite at least one.
- Merge duplicates. When a proposal was later agreed, the result is ONE confirmed decision \
citing both candidates. Keep "rejected" items; they matter.
- The title is specific to this meeting and under 12 words. one_line is the one sentence a \
colleague who missed the meeting needs.
- 2 to 4 conclusions, each tied to the candidates that support it. No commentary outside the JSON."""

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_STAMP = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")


def json_object(text: str) -> Optional[Dict[str, Any]]:
    """The first JSON object in a model reply — fenced, bare, or buried in prose."""
    if not isinstance(text, str) or not text.strip():
        return None
    body = text.strip()
    fenced = _FENCE.search(body)
    if fenced:
        body = fenced.group(1).strip()
    start = body.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(body)):
        ch = body[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(body[start:i + 1])
                except ValueError:
                    return None
                return value if isinstance(value, dict) else None
    return None


def stamp_ms(value: Any) -> Optional[int]:
    """``"00:12:34"`` → 754000. Accepts an int of milliseconds as well."""
    if isinstance(value, (int, float)):
        return int(value)
    m = _STAMP.search(str(value or ""))
    if not m:
        return None
    h, mi, s = (int(x) for x in m.groups())
    return (h * 3600 + mi * 60 + s) * 1000


def _text(value: Any, limit: int = 240) -> str:
    out = " ".join(str(value or "").split())
    return out[:limit]


def _list(value: Any) -> List[Any]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _strings(value: Any, limit: int = 6) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_text(v, 160) for v in value if _text(v, 160)][:limit]


def _status(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in ("confirmed", "proposed", "rejected") else "proposed"


def _severity(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in ("high", "medium", "low") else "medium"


# ── candidates ──────────────────────────────────────────────────────────────


class Candidates:
    """Everything the map step produced, each with a stable id for the reduce to cite."""

    def __init__(self) -> None:
        self.items: Dict[str, Dict[str, Any]] = {}
        self.counts = {"t": 0, "d": 0, "r": 0, "a": 0, "q": 0}

    def add(self, kind: str, payload: Dict[str, Any]) -> str:
        self.counts[kind] += 1
        cid = f"{kind}{self.counts[kind]}"
        self.items[cid] = {"id": cid, **payload}
        return cid

    def of(self, kind: str) -> List[Dict[str, Any]]:
        return [v for k, v in self.items.items() if k.startswith(kind)]

    def evidence(self, ids: Sequence[str]) -> List[Evidence]:
        out: List[Evidence] = []
        seen = set()
        for cid in ids:
            item = self.items.get(str(cid))
            if not item:
                continue
            ev = item.get("evidence")
            if isinstance(ev, Evidence) and (ev.t0_ms, ev.quote) not in seen:
                seen.add((ev.t0_ms, ev.quote))
                out.append(ev)
        return out


def _candidate(kind: str, raw: Dict[str, Any], chunk: Dict[str, Any]) -> Dict[str, Any]:
    t0 = stamp_ms(raw.get("t0"))
    if t0 is None:
        t0 = int(chunk.get("t0_ms") or 0)
    ev = Evidence(t0_ms=t0, quote=_text(raw.get("quote"), 300))
    base = {"chunk": chunk.get("index", 0), "t0_ms": t0, "evidence": ev}
    if kind == "d":
        return {**base, "statement": _text(raw.get("statement")), "status": _status(raw.get("status"))}
    if kind == "r":
        return {**base, "title": _text(raw.get("title"), 120), "severity": _severity(raw.get("severity")),
                "detail": _text(raw.get("detail")), "root_cause": _text(raw.get("root_cause")),
                "solutions": _strings(raw.get("solutions"))}
    if kind == "a":
        return {**base, "text": _text(raw.get("text")), "owner": _text(raw.get("owner"), 80) or None,
                "due_text": _text(raw.get("due_text"), 80) or None}
    return {**base, "text": _text(raw.get("text"))}


def _collect(cands: Candidates, parsed: Dict[str, Any], chunk: Dict[str, Any]) -> None:
    for raw in _list(parsed.get("topics")):
        label = _text(raw.get("label"), 80)
        if label:
            cands.add("t", {"label": label, "summary": _text(raw.get("summary")), "chunk": chunk.get("index", 0),
                            "t0_ms": int(chunk.get("t0_ms") or 0), "t1_ms": int(chunk.get("t1_ms") or 0)})
    for kind, key, text_key in (("d", "decisions", "statement"), ("r", "risks", "title"),
                                ("a", "actions", "text"), ("q", "questions", "text")):
        for raw in _list(parsed.get(key)):
            if not _text(raw.get(text_key)) or not _text(raw.get("quote")):
                continue
            cands.add(kind, _candidate(kind, raw, chunk))


def render_candidates(cands: Candidates) -> str:
    """The reduce prompt's body: one line per candidate, ids first so the model can cite."""
    lines: List[str] = []
    for item in cands.of("t")[:CANDIDATE_CAP["topics"]]:
        lines.append(f"{item['id']} topic: {item['label']} — {item.get('summary', '')}".rstrip(" —"))
    for item in cands.of("d")[:CANDIDATE_CAP["decisions"]]:
        lines.append(f"{item['id']} decision [{item['status']}] ({export.clock(item['t0_ms'])}): "
                     f"{item['statement']} — \"{item['evidence'].quote}\"")
    for item in cands.of("r")[:CANDIDATE_CAP["risks"]]:
        lines.append(f"{item['id']} risk [{item['severity']}] ({export.clock(item['t0_ms'])}): {item['title']}"
                     f"{' — ' + item['detail'] if item.get('detail') else ''}")
    for item in cands.of("a")[:CANDIDATE_CAP["actions"]]:
        owner = f" owner={item['owner']}" if item.get("owner") else ""
        due = f" due={item['due_text']}" if item.get("due_text") else ""
        lines.append(f"{item['id']} action ({export.clock(item['t0_ms'])}):{owner}{due} {item['text']}")
    for item in cands.of("q")[:CANDIDATE_CAP["questions"]]:
        lines.append(f"{item['id']} question ({export.clock(item['t0_ms'])}): {item['text']}")
    return "\n".join(lines)


# ── model steps ─────────────────────────────────────────────────────────────


async def _ask(call: Optional[ModelCall], messages: List[Dict[str, str]], *, max_tokens: int,
               outage: Optional[minutes._Outage], what: str) -> Optional[Dict[str, Any]]:
    if call is None:
        return None
    try:
        raw = await call(messages, temperature=0.1, max_tokens=max_tokens, response_format="json")
    except Exception as exc:  # noqa: BLE001 — a failed model is a state, not a crash
        if outage is not None:
            outage.record(exc, what)
        return None
    return json_object(raw) if isinstance(raw, str) else None


async def map_candidates(chunks: Sequence[Dict[str, Any]], *, call: Optional[ModelCall],
                         outage: Optional[minutes._Outage] = None) -> Tuple[Candidates, int]:
    """Candidates from every chunk, ``MAP_CONCURRENCY`` at a time. Returns the candidates and
    how many chunks a model actually answered for."""
    cands = Candidates()
    if call is None or not chunks:
        return cands, 0
    sem = asyncio.Semaphore(MAP_CONCURRENCY)

    async def one(chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with sem:
            messages = [
                {"role": "system", "content": MAP_SYSTEM},
                {"role": "user", "content": f"Transcript lines {minutes._range_label(chunk)}:\n\n"
                                            f"{minutes.render_chunk(chunk['segments'])}"},
            ]
            return await _ask(call, messages, max_tokens=MAP_MAX_TOKENS, outage=outage, what="analysis map")

    results = await asyncio.gather(*(one(c) for c in chunks))
    answered = 0
    for chunk, parsed in zip(chunks, results):
        if parsed is None:
            continue
        answered += 1
        _collect(cands, parsed, chunk)
    return cands, answered


async def reduce_candidates(cands: Candidates, *, meeting_title: str, call: Optional[ModelCall],
                            outage: Optional[minutes._Outage] = None) -> Optional[Dict[str, Any]]:
    body = render_candidates(cands)
    if not body.strip():
        return None
    messages = [
        {"role": "system", "content": REDUCE_SYSTEM},
        {"role": "user", "content": f"Meeting title as recorded: {meeting_title or 'untitled'}\n\nCandidates:\n{body}"},
    ]
    return await _ask(call, messages, max_tokens=REDUCE_MAX_TOKENS, outage=outage, what="analysis reduce")


# ── assembling the analysis ─────────────────────────────────────────────────


def speaker_stats(segments: Sequence[Dict[str, Any]]) -> List[SpeakerStat]:
    talk: Dict[str, int] = {}
    lines: Dict[str, int] = {}
    for seg in segments:
        label = export.speaker_label(seg.get("speaker")) if seg.get("speaker") in ("me", "them") \
            else (seg.get("speaker") or "")
        if not label:
            continue
        t0 = int(seg.get("t0_ms") or 0)
        t1 = seg.get("t1_ms")
        dur = max(0, int(t1) - t0) if t1 is not None else 4000
        talk[label] = talk.get(label, 0) + dur
        lines[label] = lines.get(label, 0) + 1
    total = sum(talk.values()) or 1
    out = [SpeakerStat(label=k, talk_ms=v, share=round(v / total, 3), lines=lines[k]) for k, v in talk.items()]
    out.sort(key=lambda s: -s.talk_ms)
    return out


def _topics_from_candidates(cands: Candidates, reduced: Optional[Dict[str, Any]]) -> List[Topic]:
    out: List[Topic] = []
    rows = _list((reduced or {}).get("topics"))
    if rows:
        for i, raw in enumerate(rows[:12], start=1):
            label = _text(raw.get("label"), 80)
            if not label:
                continue
            refs = [cands.items[c] for c in (raw.get("from") or []) if str(c) in cands.items]
            t0 = min((r["t0_ms"] for r in refs), default=0)
            t1 = max((r.get("t1_ms", r["t0_ms"]) for r in refs), default=t0)
            out.append(Topic(id=f"t{i}", label=label, t0_ms=int(t0), t1_ms=int(t1), summary=_text(raw.get("summary"))))
        if out:
            return out
    # No reduce: one topic per candidate label, de-duplicated, in time order.
    seen = set()
    for item in sorted(cands.of("t"), key=lambda c: c["t0_ms"]):
        key = normalise(item["label"])
        if key in seen:
            continue
        seen.add(key)
        out.append(Topic(id=f"t{len(out) + 1}", label=item["label"], t0_ms=item["t0_ms"],
                         t1_ms=item.get("t1_ms", item["t0_ms"]), summary=item.get("summary", "")))
    return out[:12]


def assemble(cands: Candidates, reduced: Optional[Dict[str, Any]], *, meeting_id: str, meeting_title: str,
             segments: Sequence[Dict[str, Any]], model: Optional[str]) -> MeetingAnalysis:
    """Turn reduce output (or, failing that, the raw candidates) into the typed analysis."""
    analysis = MeetingAnalysis(meeting_id=meeting_id, title=meeting_title or "Meeting", model=model)
    analysis.speakers = speaker_stats(segments)
    analysis.topics = _topics_from_candidates(cands, reduced)

    def merged(kind: str, key: str) -> List[Tuple[Dict[str, Any], List[Evidence]]]:
        rows = _list((reduced or {}).get(key))
        out: List[Tuple[Dict[str, Any], List[Evidence]]] = []
        if rows:
            for raw in rows:
                ids = [str(c) for c in (raw.get("from") or [])]
                ev = cands.evidence(ids)
                if ev:
                    out.append((raw, ev))
            return out
        seen = set()
        text_key = {"d": "statement", "r": "title", "a": "text", "q": "text"}[kind]
        for item in cands.of(kind):
            k = normalise(item[text_key])
            if not k or k in seen:
                continue
            seen.add(k)
            out.append((item, [item["evidence"]]))
        return out

    analysis.title = _text((reduced or {}).get("title"), 120) or analysis.title
    analysis.one_line = _text((reduced or {}).get("one_line"), 300)

    for i, (raw, ev) in enumerate(merged("d", "decisions"), start=1):
        analysis.decisions.append(Decision(id=f"d{i}", statement=_text(raw.get("statement")), status=_status(raw.get("status")),
                                           evidence=ev, confidence=0.8 if reduced else 0.6))
    for i, (raw, ev) in enumerate(merged("r", "risks"), start=1):
        analysis.risks.append(Risk(id=f"r{i}", title=_text(raw.get("title"), 120), severity=_severity(raw.get("severity")),
                                   detail=_text(raw.get("detail")), root_cause=_text(raw.get("root_cause")),
                                   solutions=_strings(raw.get("solutions")), evidence=ev))
    for i, (raw, ev) in enumerate(merged("a", "actions"), start=1):
        analysis.action_items.append(ActionItem(id=f"a{i}", text=_text(raw.get("text")), owner=_text(raw.get("owner"), 80) or None,
                                                due_text=_text(raw.get("due_text"), 80) or None, evidence=ev,
                                                confidence=0.8 if reduced else 0.6))
    for i, (raw, ev) in enumerate(merged("q", "questions"), start=1):
        analysis.open_questions.append(OpenQuestion(id=f"q{i}", text=_text(raw.get("text")), evidence=ev))
    for i, raw in enumerate(_list((reduced or {}).get("conclusions"))[:4], start=1):
        ev = cands.evidence([str(c) for c in (raw.get("from") or [])])
        text = _text(raw.get("text"), 300)
        if text and ev:
            analysis.conclusions.append(Conclusion(id=f"c{i}", text=text, evidence=ev))
    return analysis


# ── the extractive floor ────────────────────────────────────────────────────

_DECIDED = re.compile(r"\b(we agreed|agreed to|we decided|decided to|let'?s go with|the decision is|we will go with|"
                      r"go ahead with|approved|sign(?:ed)? off)\b", re.I)
_PROPOSED = re.compile(r"\b(we could|could we|maybe we|i think we should|we should|what if we|how about|i propose|we propose|"
                       r"propose that|proposing|i suggest|we might|one option is|an option would be)\b", re.I)
_REJECTED = re.compile(r"\b(we won'?t|we will not|not going to|rejected|drop that|decided against|ruled out|"
                       r"let'?s not)\b", re.I)
_ACTION = re.compile(r"\b(i will|i'?ll|we will|we'?ll|we need to|needs to|has to|to do|action item|follow up|follow-up|"
                     r"send (?:you|the)|schedule|set up|prepare|complete|launch|inject|review)\b", re.I)
_DUE = re.compile(r"\b(today|tomorrow|tonight|this week|next week|end of (?:the )?(?:week|month|day)|by (?:monday|tuesday|"
                  r"wednesday|thursday|friday|saturday|sunday|tomorrow|eod|next week)|on (?:monday|tuesday|wednesday|thursday|"
                  r"friday)|next (?:monday|tuesday|wednesday|thursday|friday))\b", re.I)
_RISK = re.compile(r"\b(risk|problem|issue|blocked|blocker|fails?|failure|error|bug|concern|broken|missing|unavailable|"
                   r"cannot|can'?t|doesn'?t work|not working|outage)\b", re.I)
_HIGH = re.compile(r"\b(critical|urgent|high priority|blocked|blocker|outage|data loss|security)\b", re.I)


def fallback_analysis(segments: Sequence[Dict[str, Any]], *, meeting_id: str, meeting_title: str) -> MeetingAnalysis:
    """The no-model analysis: lines that sound like decisions, actions, risks and questions,
    each citing itself. Topics are the transcript in order, one per chunk, named by their
    most frequent words. ``degraded`` is set so every surface can say what this is."""
    rows = [s for s in segments if (s.get("text") or "").strip()]
    analysis = MeetingAnalysis(meeting_id=meeting_id, title=meeting_title or "Meeting", degraded="extractive")
    analysis.speakers = speaker_stats(rows)

    def ev(seg: Dict[str, Any]) -> List[Evidence]:
        return [Evidence(segment_id=str(seg.get("id")) if seg.get("id") else None, t0_ms=int(seg.get("t0_ms") or 0),
                         t1_ms=seg.get("t1_ms"), quote=_text(seg.get("text"), 300))]

    def who(seg: Dict[str, Any]) -> Optional[str]:
        sp = seg.get("speaker")
        if not sp:
            return None
        return export.speaker_label(sp) if sp in ("me", "them") else str(sp)

    def decision(seg: Dict[str, Any], text: str, status: str) -> None:
        analysis.decisions.append(Decision(id=f"d{len(analysis.decisions) + 1}", statement=text, status=status,  # type: ignore[arg-type]
                                           evidence=ev(seg), confidence=0.4))

    # Strong cues first (an explicit agreement or refusal), then problems, then commitments,
    # then mere suggestions: a line that says "that is a real problem" is a risk even when it
    # also contains a softer phrase.
    for seg in rows:
        text = _text(seg.get("text"), 300)
        if len(analysis.decisions) < 12 and _DECIDED.search(text):
            decision(seg, _cue_sentence(text, _DECIDED), "confirmed")
            continue
        if len(analysis.decisions) < 12 and _REJECTED.search(text):
            decision(seg, _cue_sentence(text, _REJECTED), "rejected")
            continue
        if len(analysis.risks) < 8 and _RISK.search(text):
            analysis.risks.append(Risk(id=f"r{len(analysis.risks) + 1}", title=_headline(_cue_sentence(text, _RISK)),
                                       severity="high" if _HIGH.search(text) else "medium", detail=_clean(text), evidence=ev(seg)))
            continue
        if len(analysis.action_items) < 12 and _ACTION.search(text):
            due = _DUE.search(text)
            analysis.action_items.append(ActionItem(id=f"a{len(analysis.action_items) + 1}", text=_cue_sentence(text, _ACTION),
                                                    owner=who(seg), due_text=due.group(0) if due else None, evidence=ev(seg),
                                                    confidence=0.4))
            continue
        if len(analysis.decisions) < 12 and _PROPOSED.search(text):
            decision(seg, _cue_sentence(text, _PROPOSED), "proposed")
            continue
        if len(analysis.open_questions) < 8 and text.rstrip().endswith("?") and len(text.split()) >= 4:
            analysis.open_questions.append(OpenQuestion(id=f"q{len(analysis.open_questions) + 1}", text=_clean(text), owner=who(seg),
                                                        evidence=ev(seg)))

    chunks = minutes.chunk(rows, max_words=400, overlap_words=0, max_chunks=12)
    for i, chunk in enumerate(chunks, start=1):
        digest = minutes.extractive_digest(chunk["segments"], limit=1)
        analysis.topics.append(Topic(id=f"t{i}", label=_topic_label(chunk["segments"]), t0_ms=chunk["t0_ms"],
                                     t1_ms=chunk["t1_ms"], summary=_strip_stamps(digest)))
    if chunks:
        first = minutes.extractive_digest(rows[: min(len(rows), 40)], limit=1)
        analysis.one_line = _strip_stamps(first)
    analysis.validator = ValidatorReport(kept=len(analysis.decisions) + len(analysis.action_items) + len(analysis.risks)
                                         + len(analysis.open_questions),
                                         notes=["No language model answered; items are the meeting's own lines, chosen by cue words."])
    return analysis


def _strip_stamps(text: str) -> str:
    return re.sub(r"\[\d{2}:\d{2}:\d{2}\]\s*", "", text or "").strip()


_LABEL = re.compile(r"^(?:(?:another|a|the|one|first|second|big|main|core|key)\s+)?"
                    r"(?:risk|problem|issue|concern|blocker|summary|note|update|open question|question|action item|action|"
                    r"decision|proposal|suggestion|recap|takeaway)\s*:\s*", re.I)
_OPENER = re.compile(r"^(?:(?:the|a|one|another)\s+(?:core|main|big|real|key|other|first)?\s*(?:problem|issue|risk|concern|thing|point)"
                     r"\s+(?:is|was|here is)\s+that\s+|that\s+is\s+(?:a|an|the)\s+|there\s+is\s+(?:a|an)\s+|this\s+is\s+(?:a|an)\s+|"
                     r"i\s+think\s+(?:that\s+)?|so\s+|also,?\s+|and\s+|but\s+|well,?\s+|ok(?:ay)?,?\s+|fine\.?\s+)", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _trim_lead(text: str) -> str:
    """Drop a leading label ("Another risk:") or opener ("The core problem is that") so a
    title or statement starts on the substance. Words only; the evidence quote stays whole."""
    out = (text or "").strip()
    for _ in range(2):
        out = _OPENER.sub("", _LABEL.sub("", out))
    return out.strip()


def _clean(text: str) -> str:
    out = _trim_lead(text) or (text or "").strip()
    return out[:1].upper() + out[1:]


def _cue_sentence(text: str, pattern: "re.Pattern[str]") -> str:
    """The sentence of a line that carries the cue. A cue sentence too short to stand alone
    ("Agreed.") gives way to the next sentence when that one carries the cue too, and is
    joined with it otherwise."""
    pieces = [p for p in _SENTENCE.split((text or "").strip()) if p]
    for i, piece in enumerate(pieces):
        if not pattern.search(piece):
            continue
        out = piece
        if len(piece.split()) < 5 and i + 1 < len(pieces):
            out = pieces[i + 1] if pattern.search(pieces[i + 1]) else f"{piece} {pieces[i + 1]}"
        return _clean(out)
    return _clean(text)


def _headline(text: str, limit: int = 90) -> str:
    """A card title from a transcript line: its first clause, cut at a word, never mid-word."""
    lead = _trim_lead(text) or (text or "").strip()
    first = re.split(r"(?<=[.!?])\s+|;\s+|,\s+(?=(?:and|but|so|which|because|while|although)\b)|\s+so that\b",
                     lead, maxsplit=1)[0].strip()
    first = first[:1].upper() + first[1:]
    if len(first) <= limit:
        return first.rstrip(".,;:")
    cut = first[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{cut}…"


def _topic_label(segments: Sequence[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for seg in segments:
        for m in minutes._WORD.finditer((seg.get("text") or "").lower()):
            w = m.group(0)
            if w in minutes._STOP or len(w) < 4:
                continue
            counts[w] = counts.get(w, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return ", ".join(w for w, _ in top).capitalize() or "Discussion"


# ── entry point ─────────────────────────────────────────────────────────────


async def analyse(segments: Sequence[Dict[str, Any]], *, meeting_id: str, meeting_title: str,
                  call: Optional[ModelCall], model: Optional[str] = None) -> MeetingAnalysis:
    """The whole pipeline for one transcript. Never raises on a model failure."""
    rows = [s for s in segments if (s.get("text") or "").strip()]
    if not rows:
        return MeetingAnalysis(meeting_id=meeting_id, title=meeting_title or "Meeting", degraded="extractive",
                               validator=ValidatorReport(notes=["There is no transcript to analyse."]))
    outage = minutes._Outage(meeting_id)
    chunks = minutes.chunk(rows)
    cands, answered = await map_candidates(chunks, call=call, outage=outage)
    if answered == 0:
        return validate(fallback_analysis(rows, meeting_id=meeting_id, meeting_title=meeting_title), rows)
    reduced = await reduce_candidates(cands, meeting_title=meeting_title, call=call, outage=outage)
    analysis = assemble(cands, reduced, meeting_id=meeting_id, meeting_title=meeting_title, segments=rows, model=model)
    analysis = validate(analysis, rows)
    if reduced is None and analysis.validator is not None:
        analysis.validator.notes.append("The merge step did not answer; items were de-duplicated by text instead.")
    if answered < len(chunks) and analysis.validator is not None:
        analysis.validator.notes.append(f"{len(chunks) - answered} of {len(chunks)} parts went unanswered by the model.")
    return analysis
