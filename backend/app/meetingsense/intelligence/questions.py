"""Suggested questions: three to five things a colleague who missed the meeting would ask.

Generated from the *analysis* (never the raw transcript) so they point at what the page
already knows how to answer, and so the call is small. Without a model, templates over the
analysis's own items produce questions that are still specific to this meeting.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, List, Optional

from .analyze import json_object
from .schema import MeetingAnalysis, SuggestedQuestion

ModelCall = Callable[..., Awaitable[str]]

SYSTEM = """\
Write the questions a colleague who missed this meeting would ask first. Each must be answerable \
from the meeting's transcript. Return ONLY JSON: {"questions":[{"text":"...","kind":"decisions|actions|risks|why|open|general"}]}. \
Four questions, each under 18 words, specific to this meeting (name the things discussed), no yes/no questions."""

KIND_VALUES = {"decisions", "actions", "risks", "why", "open", "general"}


def _brief(analysis: MeetingAnalysis) -> str:
    parts = [f"Title: {analysis.title}", f"Summary: {analysis.one_line}"]
    if analysis.decisions:
        parts.append("Decisions: " + "; ".join(f"{d.statement} [{d.status}]" for d in analysis.decisions[:6]))
    if analysis.risks:
        parts.append("Risks: " + "; ".join(r.title for r in analysis.risks[:5]))
    if analysis.action_items:
        parts.append("Actions: " + "; ".join(f"{a.text}{' (' + a.owner + ')' if a.owner else ''}" for a in analysis.action_items[:6]))
    if analysis.open_questions:
        parts.append("Open: " + "; ".join(q.text for q in analysis.open_questions[:4]))
    return "\n".join(parts)


def fallback_questions(analysis: MeetingAnalysis) -> List[SuggestedQuestion]:
    out: List[SuggestedQuestion] = []

    def add(text: str, kind: str) -> None:
        if len(out) < 5 and text and all(q.text != text for q in out):
            out.append(SuggestedQuestion(id=f"sq{len(out) + 1}", text=text, kind=kind))  # type: ignore[arg-type]

    if analysis.decisions:
        d = analysis.decisions[0]
        add(f"What was decided about “{_short(d.statement)}”, and was it confirmed?", "decisions")
    if analysis.action_items:
        a = analysis.action_items[0]
        add(f"Who is responsible for “{_short(a.text)}” and by when?", "actions")
    if analysis.risks:
        r = analysis.risks[0]
        add(f"What is the plan for the problem “{_short(r.title)}”?", "risks")
    if analysis.topics:
        add(f"Why did the discussion focus on {analysis.topics[0].label.lower()}?", "why")
    if analysis.open_questions:
        add("Which questions were left unresolved at the end?", "open")
    add("What are the next steps after this meeting?", "general")
    return out[:4]


def _short(text: str, limit: int = 60) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


async def suggest(analysis: MeetingAnalysis, *, call: Optional[ModelCall]) -> List[SuggestedQuestion]:
    if call is not None and analysis.degraded is None:
        try:
            raw = await call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": _brief(analysis)}],
                             temperature=0.3, max_tokens=400, response_format="json")
            parsed = json_object(raw) if isinstance(raw, str) else None
        except Exception:  # noqa: BLE001
            parsed = None
        rows: List[Any] = (parsed or {}).get("questions") or []
        out: List[SuggestedQuestion] = []
        for raw_q in rows:
            if not isinstance(raw_q, dict):
                continue
            text = " ".join(str(raw_q.get("text") or "").split())[:200]
            kind = str(raw_q.get("kind") or "general").strip().lower()
            if text:
                out.append(SuggestedQuestion(id=f"sq{len(out) + 1}", text=text,
                                             kind=kind if kind in KIND_VALUES else "general"))  # type: ignore[arg-type]
            if len(out) == 5:
                break
        if len(out) >= 3:
            return out
    return fallback_questions(analysis)
