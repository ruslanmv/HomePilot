"""The one entry point the job and the routes call: analyse a meeting and store the result."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from .. import store as ms_store
from . import analyze, brief as brief_mod, layout, questions as questions_mod, store
from .schema import MeetingAnalysis, VisualSpec

log = logging.getLogger(__name__)

ModelCall = Callable[..., Awaitable[str]]


async def compose_spec(analysis: MeetingAnalysis, *, call: Optional[ModelCall], analysis_id: str = "") -> VisualSpec:
    """The visual spec for an analysis: the block list (reusable by any renderer) plus the
    Executive Brief composed on top of it."""
    spec = layout.build_spec(analysis, analysis_id=analysis_id)
    spec.template = "executive_brief"
    spec.brief = await brief_mod.compose(analysis, call=call)
    return spec


async def run_analysis(meeting_id: str, *, call: Optional[ModelCall], model: Optional[str] = None,
                       transcript_version_id: Optional[str] = None,
                       progress: Optional[Callable[[str, float], None]] = None) -> Dict[str, Any]:
    """Analyse the meeting's current transcript, build the page and the questions, store all
    three. Returns what :func:`store.latest` returns. Raises ``ValueError`` when there is no
    transcript — the caller turns that into a 409 or a failed job, never into a fake page."""
    meeting = ms_store.get_meeting(meeting_id) or {}
    segments = ms_store.get_segments(meeting_id)
    if not segments:
        raise ValueError("no_transcript")

    def tick(stage: str, fraction: float) -> None:
        if progress is not None:
            try:
                progress(stage, fraction)
            except Exception:  # noqa: BLE001
                pass

    tick("analysing", 0.1)
    analysis = await analyze.analyse(segments, meeting_id=meeting_id, meeting_title=meeting.get("title") or "",
                                     call=call, model=model)
    tick("writing the brief", 0.7)
    spec = await compose_spec(analysis, call=call)
    tick("questions", 0.85)
    suggested = await questions_mod.suggest(analysis, call=call)
    tick("saving", 0.95)
    store.save(meeting_id, analysis, spec, suggested, transcript_version_id=transcript_version_id)
    return store.latest(meeting_id) or {}


async def recompose(meeting_id: str, *, call: Optional[ModelCall]) -> Dict[str, Any]:
    """Write the brief again for the latest analysis without re-extracting. Raises
    ``ValueError("no_analysis")`` when there is nothing to lay out."""
    current_row = store.latest(meeting_id)
    if not current_row:
        raise ValueError("no_analysis")
    analysis = MeetingAnalysis.model_validate(current_row["analysis"])
    spec = await compose_spec(analysis, call=call, analysis_id=current_row["id"])
    store.save_spec(meeting_id, current_row["id"], spec)
    return store.latest(meeting_id) or {}


def current(meeting_id: str) -> Optional[Dict[str, Any]]:
    return store.latest(meeting_id)
