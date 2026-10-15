"""The typed meeting analysis (schema v1) and the visual-summary spec built from it.

Pydantic models, because this is the contract three consumers share: the extraction
pipeline writes it, the visual renderer reads it, and a future DayPilot pulls it over HTTP.
``json_schema()`` publishes the same shape for them.

Every item that makes a claim about the meeting carries ``evidence``: the transcript line
(``segment_id`` / ``t0_ms``) and the verbatim ``quote`` the claim rests on. Topics and
speaker statistics are descriptive and carry none.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

DecisionStatus = Literal["confirmed", "proposed", "rejected"]
Severity = Literal["high", "medium", "low"]
RiskStatus = Literal["open", "mitigated", "resolved"]
ActionStatus = Literal["open", "done", "dropped"]


class Evidence(BaseModel):
    segment_id: Optional[str] = None
    t0_ms: int = 0
    t1_ms: Optional[int] = None
    quote: str = ""


class Topic(BaseModel):
    id: str
    label: str
    t0_ms: int = 0
    t1_ms: int = 0
    summary: str = ""


class Decision(BaseModel):
    id: str
    statement: str
    status: DecisionStatus = "proposed"
    topic_id: Optional[str] = None
    evidence: List[Evidence] = Field(default_factory=list)
    confidence: float = 0.5


class Risk(BaseModel):
    id: str
    title: str
    severity: Severity = "medium"
    detail: str = ""
    root_cause: str = ""
    solutions: List[str] = Field(default_factory=list)
    status: RiskStatus = "open"
    evidence: List[Evidence] = Field(default_factory=list)


class ActionItem(BaseModel):
    id: str
    text: str
    owner: Optional[str] = None
    due: Optional[str] = None
    due_text: Optional[str] = None
    status: ActionStatus = "open"
    evidence: List[Evidence] = Field(default_factory=list)
    confidence: float = 0.5


class OpenQuestion(BaseModel):
    id: str
    text: str
    owner: Optional[str] = None
    evidence: List[Evidence] = Field(default_factory=list)


class Conclusion(BaseModel):
    id: str
    text: str
    evidence: List[Evidence] = Field(default_factory=list)


class SpeakerStat(BaseModel):
    label: str
    talk_ms: int = 0
    share: float = 0.0
    lines: int = 0


class ValidatorReport(BaseModel):
    kept: int = 0
    dropped: int = 0
    repaired: int = 0
    notes: List[str] = Field(default_factory=list)


class MeetingAnalysis(BaseModel):
    schema_version: int = SCHEMA_VERSION
    meeting_id: str
    transcript_version_id: Optional[str] = None
    language: str = "en"
    title: str = ""
    one_line: str = ""
    topics: List[Topic] = Field(default_factory=list)
    decisions: List[Decision] = Field(default_factory=list)
    risks: List[Risk] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    open_questions: List[OpenQuestion] = Field(default_factory=list)
    conclusions: List[Conclusion] = Field(default_factory=list)
    speakers: List[SpeakerStat] = Field(default_factory=list)
    #: ``None`` when a model wrote it; ``"extractive"`` when it is the meeting's own words.
    degraded: Optional[str] = None
    model: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    validator: Optional[ValidatorReport] = None

    def item(self, item_id: str) -> Optional[BaseModel]:
        """Look an item up by id across every list (``d3`` → the third decision, …)."""
        for group in (self.decisions, self.risks, self.action_items, self.open_questions,
                      self.conclusions, self.topics):
            for entry in group:
                if entry.id == item_id:
                    return entry
        return None

    def counts(self) -> Dict[str, int]:
        return {
            "topics": len(self.topics), "decisions": len(self.decisions), "risks": len(self.risks),
            "actions": len(self.action_items), "questions": len(self.open_questions),
        }


class SuggestedQuestion(BaseModel):
    id: str
    text: str
    kind: Literal["decisions", "actions", "risks", "why", "open", "general"] = "general"


BlockType = Literal[
    "header", "kpi_row", "section", "risk_cards", "decision_list", "comparison_table",
    "timeline", "callout", "quote",
]


class VisualBlock(BaseModel):
    type: BlockType
    title: Optional[str] = None
    #: Analysis item ids this block renders (cards, lists, timeline steps).
    items: List[str] = Field(default_factory=list)
    #: Literal text for blocks that are not item lists (callout, quote, header lead). Always
    #: copied from the analysis by the layout step — never free text from a model.
    text: Optional[str] = None
    columns: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    tone: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


ActionBucket = Literal["Immediate", "This week", "Next steps"]


class BriefCard(BaseModel):
    """A risk or blocker card. ``severity`` always comes from the analysis item; the words
    may be the model's (``polished``) or the item's own."""
    item: str
    title: str
    summary: str = ""
    note: str = ""
    severity: Severity = "medium"
    polished: bool = False


class BriefRow(BaseModel):
    """One row of the decision comparison. ``status`` is the verified decision status and
    ``status_label`` is its fixed display word — never a model's choice."""
    item: str
    option: str
    status: DecisionStatus = "proposed"
    status_label: str = "Proposed"
    impact: str = ""
    polished: bool = False


class BriefStep(BaseModel):
    item: str
    bucket: ActionBucket = "Next steps"
    label: str = ""
    text: str
    owner: Optional[str] = None
    polished: bool = False


class ExecutiveBrief(BaseModel):
    """The one-page Executive Brief: what the paper report renders. Every entry carries the
    analysis item id it rests on, so the renderer can show the transcript evidence and the
    validator can refuse wording that drifted from it."""
    eyebrow: str = "Meeting · Executive brief"
    title: str = ""
    intro: str = ""
    risks: List[BriefCard] = Field(default_factory=list)
    blockers: List[BriefCard] = Field(default_factory=list)
    decisions: List[BriefRow] = Field(default_factory=list)
    actions: List[BriefStep] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    takeaway: str = ""
    takeaway_items: List[str] = Field(default_factory=list)
    #: Distinct transcript moments cited by everything on the page.
    source_count: int = 0
    #: True when at least one field carries model-written wording.
    polished: bool = False
    notes: List[str] = Field(default_factory=list)


class VisualSpec(BaseModel):
    schema_version: int = SCHEMA_VERSION
    analysis_id: str = ""
    template: str = "executive_brief"
    blocks: List[VisualBlock] = Field(default_factory=list)
    brief: Optional[ExecutiveBrief] = None


def json_schema() -> Dict[str, Any]:
    """The published contract: the analysis, the spec and the questions, one document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis": MeetingAnalysis.model_json_schema(),
        "visual": VisualSpec.model_json_schema(),
        "brief": ExecutiveBrief.model_json_schema(),
        "question": SuggestedQuestion.model_json_schema(),
    }
