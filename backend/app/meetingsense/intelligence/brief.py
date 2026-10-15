"""The Executive Brief composer: polished wording for the one-page report, strictly grounded.

The visual page people expect reads like an executive brief — "Missing DNS verification
tools", not a transcript line. A model writes that wording here, but under rules the
validator can check:

* every card, row, step and the takeaway names the analysis item it rests on; an unknown
  or wrong-kind id is dropped;
* **facts are never the model's to set**: severity, decision status, due bucket and owner
  come from the verified analysis, and a proposal can never be worded as a decision;
* numbers and technical terms in the polished text must already appear in the source item
  (its text, quote and detail); anything else falls back to the item's own words;
* with no model, or a model that fails, the brief is composed deterministically from the
  analysis, so the page always exists and is always true.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set, Tuple

from .analyze import _headline, json_object
from .validate import normalise
from .schema import (
    ActionBucket, ActionItem, BriefCard, BriefRow, BriefStep, Decision, ExecutiveBrief, MeetingAnalysis, Risk,
)

log = logging.getLogger(__name__)

ModelCall = Callable[..., Awaitable[str]]

STATUS_LABEL = {"confirmed": "Selected", "proposed": "Proposed", "rejected": "Rejected"}
MAX_RISKS = 2
MAX_BLOCKERS = 2
MAX_DECISIONS = 6
MAX_ACTIONS = 3
MAX_TOKENS = 1200

SYSTEM = """\
You write the one-page executive brief of a meeting from its verified analysis.
Return ONLY a JSON object:
{"eyebrow":"<kind of meeting> · Executive brief","title":"...","intro":"...",
 "risks":[{"item":"r1","title":"...","summary":"...","note":"..."}],
 "blockers":[{"item":"r2","title":"...","summary":"..."}],
 "decisions":[{"item":"d1","option":"...","impact":"..."}],
 "actions":[{"item":"a1","text":"..."}],
 "takeaway":{"text":"...","items":["d1","r1"]}}

Rules:
- Use ONLY the items given, by their ids. Never add a risk, decision or action that is not listed.
- Titles: at most 6 words. Summaries: at most 2 sentences. "note": one short consequence or cause. \
"impact": at most 18 words on what the option costs or gains. Action "text": at most 14 words.
- Keep every number, name, product and technical term exactly as the source says it. Do not add facts.
- A decision's status is given; if it is "proposed", write it as an option under consideration, never \
as chosen, agreed or selected. If it is "rejected", say it was set aside.
- "blockers" are risks that depend on something missing or external (tools, access, another team); \
other risks stay in "risks". A risk appears in one list only.
- The takeaway is at most 40 words, cites the ids it rests on, and does not announce decisions that \
were only proposed.
- No commentary outside the JSON."""

_NUM_WORDS = ("zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
              "sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
              "hundred|thousand|million|billion|dozen|half|quarter|percent")
# Digits and spelled-out quantities alike: "50", "3.5", "12%", "fifty", "a dozen".
_NUM = re.compile(rf"\d+(?:[.,]\d+)?%?|\b(?:{_NUM_WORDS})\b", re.I)
_TERM = re.compile(r"\b(?:[A-Z][a-z]+(?:[A-Z][a-z]*)+|[A-Z]{2,}(?:[A-Z0-9-]*)|[a-z]+[A-Z][A-Za-z]*)\b")
_CHOSEN = re.compile(r"\b(selected|chosen|approved|agreed|decided|decision is|will adopt|adopted|go with|green-?lit)\b", re.I)
_BLOCKER = re.compile(r"\b(block\w*|missing|unavailable|depend\w*|waiting|access|not available|need\w* (?:the )?tool|"
                      r"environment|another team|external)\b", re.I)
_IMMEDIATE = re.compile(r"\b(today|now|immediately|asap|right away|tonight|tomorrow|this morning|this afternoon)\b", re.I)
_THIS_WEEK = re.compile(r"\b(this week|end of (?:the )?week|by friday|friday|thursday|wednesday|eow|in the next (?:few )?days|"
                        r"by (?:monday|tuesday|wednesday|thursday|friday)(?! next))\b", re.I)


def _words(text: str, limit: int) -> str:
    parts = (text or "").split()
    if len(parts) <= limit:
        return " ".join(parts)
    return " ".join(parts[:limit]).rstrip(",;:") + "…"


def _sentences(text: str, limit: int) -> str:
    pieces = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return " ".join(p for p in pieces[:limit] if p)


def _source_text(item: Any) -> str:
    parts = [getattr(item, "statement", ""), getattr(item, "title", ""), getattr(item, "text", ""),
             getattr(item, "detail", ""), getattr(item, "root_cause", "")]
    parts += list(getattr(item, "solutions", []) or [])
    parts += [e.quote for e in (getattr(item, "evidence", []) or [])]
    return " ".join(p for p in parts if p)


def _proper_nouns(text: str) -> List[str]:
    """Capitalised words that are not the first word of their sentence — names and products."""
    out: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        for token in sentence.split()[1:]:
            core = token.strip("\"'()[],.;:!?“”’")
            if re.fullmatch(r"[A-Z][a-z]{2,}", core):
                out.append(core)
    return out


def terms_preserved(polished: str, source: str, *, sentence_case: bool = True) -> bool:
    """Every number and every term that looks technical (CamelCase, ALLCAPS, mixedCase) in the
    polished text must already be in the source; in sentence-case fields, so must every
    capitalised word after the first (a name or a product). Ordinary words may change; facts
    may not. Title-case fields (card titles, option labels) skip the proper-noun rule, since
    there every word is capitalised."""
    src = (source or "").lower()
    for number in _NUM.findall(polished or ""):
        if number.lower() not in src:
            return False
    src_terms = {t.lower() for t in _TERM.findall(source or "")}
    for term in _TERM.findall(polished or ""):
        if term.lower() not in src_terms and term.lower() not in src:
            return False
    if sentence_case:
        for noun in _proper_nouns(polished):
            if noun.lower() not in src:
                return False
    return True


def bucket_for(action: ActionItem) -> Tuple[ActionBucket, str]:
    """The timeline column an action belongs to, from its own due words — never from a model."""
    due = f"{action.due_text or ''} {action.due or ''}"
    if _IMMEDIATE.search(due):
        return "Immediate", action.due_text or "Immediate"
    if _THIS_WEEK.search(due):
        return "This week", action.due_text or "This week"
    return "Next steps", action.due_text or action.due or "Next steps"


def is_blocker(risk: Risk) -> bool:
    return bool(_BLOCKER.search(_source_text(risk)))


def source_count(analysis: MeetingAnalysis, used: Iterable[str]) -> int:
    seen: Set[Any] = set()
    for item_id in used:
        item = analysis.item(item_id)
        for ev in getattr(item, "evidence", []) or []:
            seen.add(ev.segment_id or ev.t0_ms)
    return len(seen)


# ── deterministic composition (the floor) ──────────────────────────────────


def compose_fallback(analysis: MeetingAnalysis) -> ExecutiveBrief:
    """The brief built from the analysis alone: honest wording, same structure."""
    brief = ExecutiveBrief(title=analysis.title or "Meeting", intro=analysis.one_line or "")
    risks = sorted(analysis.risks, key=lambda r: ({"high": 0, "medium": 1, "low": 2}[r.severity],
                                                   r.evidence[0].t0_ms if r.evidence else 0))
    for r in risks:
        title = _headline(r.title, 60)
        card = BriefCard(item=r.id, title=title, summary=_rest(r.detail, title),
                         note=r.root_cause or (r.solutions[0] if r.solutions else ""), severity=r.severity)
        target = brief.blockers if is_blocker(r) and len(brief.blockers) < MAX_BLOCKERS else brief.risks
        if len(target) < (MAX_RISKS if target is brief.risks else MAX_BLOCKERS):
            target.append(card)
    ordered = sorted(analysis.decisions, key=lambda d: ({"confirmed": 0, "rejected": 1, "proposed": 2}[d.status],
                                                         d.evidence[0].t0_ms if d.evidence else 0))
    for d in ordered[:MAX_DECISIONS]:
        brief.decisions.append(BriefRow(item=d.id, option=_headline(d.statement, 96), status=d.status,
                                        status_label=STATUS_LABEL[d.status]))
    for a in analysis.action_items:
        bucket, label = bucket_for(a)
        brief.actions.append(BriefStep(item=a.id, bucket=bucket, label=label, text=_words(a.text, 16), owner=a.owner))
    brief.actions = _spread(brief.actions)[:MAX_ACTIONS]
    brief.open_questions = [q.id for q in analysis.open_questions[:4]]
    # The takeaway always rests on a verified item: a conclusion, else a confirmed decision,
    # else the gravest risk — and it is never the intro said twice.
    candidates: List[Tuple[str, str]] = [(c.id, c.text) for c in analysis.conclusions]
    candidates += [(d.id, d.statement) for d in analysis.decisions if d.status == "confirmed"]
    candidates += [(r.id, r.detail or r.title) for r in risks]
    for item_id, text in candidates:
        if text and normalise(text) != normalise(brief.intro):
            brief.takeaway, brief.takeaway_items = text, [item_id]
            break
    intro_n = normalise(brief.intro)
    if intro_n and any(normalise(c.summary) in intro_n or intro_n in normalise(c.summary)
                       for c in brief.risks + brief.blockers if c.summary):
        brief.intro = ""  # already said on a card
    used = [c.item for c in brief.risks + brief.blockers] + [r.item for r in brief.decisions] \
        + [s.item for s in brief.actions] + brief.open_questions + brief.takeaway_items
    brief.source_count = source_count(analysis, used)
    brief.eyebrow = _eyebrow(analysis)
    return brief


def _rest(detail: str, title: str) -> str:
    """What a card's sentence adds beyond its title: the remainder when the sentence opens with
    the title's words, the whole sentence otherwise, nothing when nothing is left."""
    d, t = (detail or "").strip(), (title or "").rstrip("…").strip()
    if not d or not t or d.lower() == t.lower():
        return "" if d.lower() == t.lower() else d
    if d.lower().startswith(t.lower()):
        rest = re.sub(r"^(?:so|and|but|which|because|while|then)\s+", "", d[len(t):].lstrip(" ,;:—-"), flags=re.I)
        if len(rest.split()) < 3:
            return ""
        return rest[:1].upper() + rest[1:]
    return d


def _spread(steps: List[BriefStep]) -> List[BriefStep]:
    """Prefer one step per bucket (Immediate, This week, Next steps) before filling a bucket twice."""
    order: Dict[str, int] = {"Immediate": 0, "This week": 1, "Next steps": 2}
    by_bucket: Dict[str, List[BriefStep]] = {}
    for s in steps:
        by_bucket.setdefault(s.bucket, []).append(s)
    out: List[BriefStep] = []
    for bucket in sorted(by_bucket, key=lambda b: order[b]):
        out.append(by_bucket[bucket][0])
    for bucket in sorted(by_bucket, key=lambda b: order[b]):
        out.extend(by_bucket[bucket][1:])
    return out


def _eyebrow(analysis: MeetingAnalysis) -> str:
    text = " ".join(t.label for t in analysis.topics).lower()
    if re.search(r"\b(deploy|pipeline|agent|api|dns|server|bug|latency|model|prompt|code|release)\b", text):
        return "Technical meeting · Executive brief"
    if re.search(r"\b(budget|revenue|cost|pricing|forecast|sales)\b", text):
        return "Business review · Executive brief"
    return "Meeting · Executive brief"


# ── the polished composition ───────────────────────────────────────────────


def _catalog(analysis: MeetingAnalysis) -> str:
    lines: List[str] = [f"Title as recorded: {analysis.title}", f"One line: {analysis.one_line}"]
    for r in analysis.risks:
        kind = "blocker-candidate" if is_blocker(r) else "risk"
        lines.append(f"{r.id} {kind} [{r.severity}]: {r.title} | detail: {r.detail} | cause: {r.root_cause} | "
                     f"solutions: {'; '.join(r.solutions)} | quote: \"{r.evidence[0].quote if r.evidence else ''}\"")
    for d in analysis.decisions:
        lines.append(f"{d.id} decision [{d.status}]: {d.statement} | quote: \"{d.evidence[0].quote if d.evidence else ''}\"")
    for a in analysis.action_items:
        lines.append(f"{a.id} action: {a.text} | owner: {a.owner or 'not stated'} | due: {a.due_text or 'not stated'}")
    for q in analysis.open_questions:
        lines.append(f"{q.id} open question: {q.text}")
    for c in analysis.conclusions:
        lines.append(f"{c.id} conclusion: {c.text}")
    return "\n".join(lines)


def _card(raw: Dict[str, Any], risk: Risk, *, notes: List[str], fallback: BriefCard) -> BriefCard:
    source = _source_text(risk)
    title = _words(str(raw.get("title") or ""), 6)
    summary = _sentences(str(raw.get("summary") or ""), 2)
    note = _words(str(raw.get("note") or ""), 20)
    ok = bool(title) and terms_preserved(title, source, sentence_case=False) \
        and all(terms_preserved(t, source) for t in (summary, note) if t)
    if not ok:
        notes.append(f"{risk.id}: polished wording dropped (unsupported term or number); the meeting's words are shown.")
        return fallback
    return BriefCard(item=risk.id, title=title, summary=summary, note=note, severity=risk.severity, polished=True)


def _row(raw: Dict[str, Any], decision: Decision, *, notes: List[str], fallback: BriefRow) -> BriefRow:
    source = _source_text(decision)
    option = _words(str(raw.get("option") or ""), 8)
    impact = _words(str(raw.get("impact") or ""), 18)
    if not option or not terms_preserved(option, source, sentence_case=False) or (impact and not terms_preserved(impact, source)):
        notes.append(f"{decision.id}: polished wording dropped (unsupported term or number).")
        return fallback
    if decision.status != "confirmed" and (_CHOSEN.search(option) or _CHOSEN.search(impact)):
        notes.append(f"{decision.id}: wording presented a {decision.status} item as decided; the verified wording is shown.")
        return fallback
    return BriefRow(item=decision.id, option=option, status=decision.status, status_label=STATUS_LABEL[decision.status],
                    impact=impact, polished=True)


def _step(raw: Dict[str, Any], action: ActionItem, *, notes: List[str], fallback: BriefStep) -> BriefStep:
    text = _words(str(raw.get("text") or ""), 14)
    if not text or not terms_preserved(text, _source_text(action)):
        notes.append(f"{action.id}: polished wording dropped (unsupported term or number).")
        return fallback
    return BriefStep(item=action.id, bucket=fallback.bucket, label=fallback.label, text=text, owner=action.owner, polished=True)


def merge(parsed: Dict[str, Any], analysis: MeetingAnalysis) -> ExecutiveBrief:
    """Fold the model's wording onto the deterministic brief, field by field, keeping each
    polished field only when the validator accepts it."""
    base = compose_fallback(analysis)
    notes: List[str] = []
    out = ExecutiveBrief(**base.model_dump())
    used_any = False

    eyebrow = _words(str(parsed.get("eyebrow") or ""), 6)
    if eyebrow and "brief" in eyebrow.lower():
        out.eyebrow = eyebrow
    title = _words(str(parsed.get("title") or ""), 12)
    if title and terms_preserved(title, _catalog(analysis), sentence_case=False):
        out.title, used_any = title, True
    intro = _sentences(str(parsed.get("intro") or ""), 1)
    if intro and terms_preserved(intro, _catalog(analysis)) and not (_CHOSEN.search(intro) and not any(
            d.status == "confirmed" for d in analysis.decisions)):
        out.intro, used_any = intro, True

    risks_by_id = {r.id: r for r in analysis.risks}
    base_cards = {c.item: c for c in base.risks + base.blockers}
    seen: Set[str] = set()
    new_risks: List[BriefCard] = []
    new_blockers: List[BriefCard] = []
    for key, target, cap in (("risks", new_risks, MAX_RISKS), ("blockers", new_blockers, MAX_BLOCKERS)):
        for raw in parsed.get(key) or []:
            if not isinstance(raw, dict):
                continue
            rid = str(raw.get("item") or "")
            risk = risks_by_id.get(rid)
            if risk is None or rid in seen or len(target) >= cap:
                continue
            seen.add(rid)
            fallback = base_cards.get(rid) or BriefCard(item=rid, title=_headline(risk.title, 60), summary=risk.detail,
                                                          note=risk.root_cause, severity=risk.severity)
            card = _card(raw, risk, notes=notes, fallback=fallback)
            used_any = used_any or card.polished
            target.append(card)
    if new_risks or new_blockers:
        out.risks, out.blockers = new_risks, new_blockers

    decisions_by_id = {d.id: d for d in analysis.decisions}
    base_rows = {r.item: r for r in base.decisions}
    new_rows: List[BriefRow] = []
    for raw in parsed.get("decisions") or []:
        if not isinstance(raw, dict):
            continue
        did = str(raw.get("item") or "")
        decision = decisions_by_id.get(did)
        if decision is None or any(r.item == did for r in new_rows) or len(new_rows) >= MAX_DECISIONS:
            continue
        fallback = base_rows.get(did) or BriefRow(item=did, option=_headline(decision.statement, 70), status=decision.status,
                                                   status_label=STATUS_LABEL[decision.status])
        row = _row(raw, decision, notes=notes, fallback=fallback)
        used_any = used_any or row.polished
        new_rows.append(row)
    if new_rows:
        out.decisions = new_rows

    actions_by_id = {a.id: a for a in analysis.action_items}
    base_steps = {s.item: s for s in base.actions}
    new_steps: List[BriefStep] = []
    for raw in parsed.get("actions") or []:
        if not isinstance(raw, dict):
            continue
        aid = str(raw.get("item") or "")
        action = actions_by_id.get(aid)
        if action is None or any(s.item == aid for s in new_steps):
            continue
        bucket, label = bucket_for(action)
        fallback = base_steps.get(aid) or BriefStep(item=aid, bucket=bucket, label=label, text=_words(action.text, 16), owner=action.owner)
        step = _step(raw, action, notes=notes, fallback=fallback)
        used_any = used_any or step.polished
        new_steps.append(step)
    if new_steps:
        out.actions = _spread(new_steps)[:MAX_ACTIONS]

    take = parsed.get("takeaway") if isinstance(parsed.get("takeaway"), dict) else {}
    text = _words(str(take.get("text") or ""), 40)
    ids = [str(i) for i in (take.get("items") or []) if analysis.item(str(i)) is not None]
    if text and ids:
        cited = " ".join(_source_text(analysis.item(i)) for i in ids)
        confirmed_cited = any(getattr(analysis.item(i), "status", "") == "confirmed" for i in ids)
        if terms_preserved(text, cited) and (confirmed_cited or not _CHOSEN.search(text)):
            out.takeaway, out.takeaway_items, used_any = text, ids, True
        else:
            notes.append("takeaway: polished wording dropped (unsupported term or an unconfirmed decision stated as made).")

    used = [c.item for c in out.risks + out.blockers] + [r.item for r in out.decisions] + [s.item for s in out.actions] \
        + out.open_questions + out.takeaway_items
    out.source_count = source_count(analysis, used)
    out.polished = used_any
    out.notes = notes
    return out


async def compose(analysis: MeetingAnalysis, *, call: Optional[ModelCall]) -> ExecutiveBrief:
    """The Executive Brief for an analysis: polished when a model answers and the validator
    agrees, the meeting's own words otherwise. Never raises."""
    if call is None or analysis.degraded is not None or not (analysis.risks or analysis.decisions or analysis.action_items):
        return compose_fallback(analysis)
    try:
        raw = await call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": _catalog(analysis)}],
                         temperature=0.2, max_tokens=MAX_TOKENS, response_format="json")
        parsed = json_object(raw) if isinstance(raw, str) else None
    except Exception as exc:  # noqa: BLE001 — a failed model is a state, not a crash
        log.warning("meetingsense: brief composer failed for %s (%s); using the meeting's own words", analysis.meeting_id, exc)
        parsed = None
    if not parsed:
        brief = compose_fallback(analysis)
        brief.notes.append("The model did not answer; wording is taken from the transcript.")
        return brief
    return merge(parsed, analysis)
