"""From a ``MeetingAnalysis`` to the one-page ``VisualSpec`` — deterministically.

The page InSight renders is a small vocabulary of blocks (risk cards, a status table, a
step timeline, a highlighted conclusion) filled from the analysis. Choosing those blocks is
a job rules do reliably and a model does inconsistently, so the layout is built here, by
rules, from the analysis alone: block order and tints follow what the meeting contains, and
every cell is either an item id or text copied verbatim from an analysis item.

A later batch may let a model *propose* a different arrangement; its output would be
validated against this schema and this builder stays the fallback.
"""

from __future__ import annotations

from typing import List

from .schema import MeetingAnalysis, VisualBlock, VisualSpec

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
STATUS_LABEL = {"confirmed": "Confirmed", "proposed": "Proposed", "rejected": "Rejected"}
STATUS_TONE = {"confirmed": "green", "proposed": "amber", "rejected": "rose"}


def _clock(ms: int) -> str:
    total = max(0, int(ms or 0)) // 1000
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_spec(analysis: MeetingAnalysis, *, analysis_id: str = "", template: str = "autopilot") -> VisualSpec:
    blocks: List[VisualBlock] = []
    counts = analysis.counts()

    blocks.append(VisualBlock(type="header", title=analysis.title or "Meeting", text=analysis.one_line or None,
                              meta={"degraded": analysis.degraded, "counts": counts}))

    kpis = [
        {"label": "Decisions", "value": counts["decisions"], "key": "decisions"},
        {"label": "Action items", "value": counts["actions"], "key": "actions"},
        {"label": "Risks", "value": counts["risks"], "key": "risks"},
        {"label": "Open questions", "value": counts["questions"], "key": "questions"},
    ]
    if analysis.speakers:
        lead = analysis.speakers[0]
        kpis.append({"label": "Most talk time", "value": f"{round(lead.share * 100)}%", "key": "speaker", "sub": lead.label})
    blocks.append(VisualBlock(type="kpi_row", meta={"kpis": kpis}))

    if analysis.risks:
        ordered = sorted(analysis.risks, key=lambda r: (SEVERITY_ORDER.get(r.severity, 1), r.evidence[0].t0_ms if r.evidence else 0))
        blocks.append(VisualBlock(type="risk_cards", title="Risks and problems", items=[r.id for r in ordered[:4]]))

    if analysis.decisions:
        ordered = sorted(analysis.decisions, key=lambda d: ({"confirmed": 0, "rejected": 1, "proposed": 2}[d.status],
                                                              d.evidence[0].t0_ms if d.evidence else 0))
        blocks.append(VisualBlock(type="decision_list", title="Decisions", items=[d.id for d in ordered[:8]]))
        if len(ordered) >= 2 and len({d.status for d in ordered}) >= 2:
            rows = [[d.statement, STATUS_LABEL[d.status], _clock(d.evidence[0].t0_ms) if d.evidence else ""] for d in ordered[:6]]
            blocks.append(VisualBlock(type="comparison_table", title="Decision status at a glance",
                                      columns=["Decision", "Status", "Said at"], rows=rows,
                                      meta={"status_column": 1, "time_column": 2, "items": [d.id for d in ordered[:6]]}))

    if analysis.action_items:
        ordered = sorted(analysis.action_items, key=lambda a: (a.due or "9999", a.evidence[0].t0_ms if a.evidence else 0))
        blocks.append(VisualBlock(type="timeline", title="Action items", items=[a.id for a in ordered[:6]]))

    if analysis.open_questions:
        blocks.append(VisualBlock(type="section", title="Still open", items=[q.id for q in analysis.open_questions[:6]], tone="amber"))

    if analysis.topics and len(analysis.topics) > 1:
        blocks.append(VisualBlock(type="section", title="The meeting in order", items=[t.id for t in analysis.topics[:8]], tone="slate"))

    conclusion = analysis.conclusions[0].text if analysis.conclusions else analysis.one_line
    if conclusion:
        blocks.append(VisualBlock(type="callout", title="Key conclusion", text=conclusion,
                                  items=[analysis.conclusions[0].id] if analysis.conclusions else [], tone="violet"))

    return VisualSpec(analysis_id=analysis_id, template=template, blocks=blocks)
