"""
Spatial Memory Routes — REST API for trace ingestion and episode retrieval.

ADDITIVE ONLY: New file, new router. Mounted via app.include_router()
in main.py or as a standalone sub-application.

Endpoints:
  POST /api/spatial/traces         — Ingest a batch of trace events
  GET  /api/spatial/episodes       — Retrieve consolidated episodes
  GET  /api/spatial/traces         — Query raw trace events
  GET  /api/spatial/context-block  — Get LLM-ready spatial context
  POST /api/spatial/reinforce      — Reinforce an episode's activation
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .spatial_memory import SpatialMemoryBuilder, SpatialConfig

router = APIRouter(prefix="/api/spatial", tags=["spatial-memory"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class TraceEvent(BaseModel):
    """Single trace event from the client-side TraceRecorder."""
    trace_id: str = ""
    event_id: str = ""
    seq: int = 0
    timestamp: str = ""
    elapsed_ms: float = 0
    kind: str = "custom"
    name: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None


class IngestRequest(BaseModel):
    """Batch trace ingestion request."""
    trace_id: str
    persona_id: str = ""
    events: List[TraceEvent]
    flushed_at: str = ""


class IngestResponse(BaseModel):
    """Batch trace ingestion response."""
    ingested: int
    trace_id: str


class EpisodeResponse(BaseModel):
    """A consolidated spatial episode."""
    episode_id: str
    start_ts: float
    end_ts: float
    event_count: int
    summary: str
    tags: List[str]
    activation: float
    importance: float


class ReinforceRequest(BaseModel):
    """Reinforce an episode's activation."""
    episode_id: str
    persona_id: str = ""
    eta: float = 0.15


# ---------------------------------------------------------------------------
# Builder cache (one per persona_id, lazily created)
# ---------------------------------------------------------------------------

_builders: Dict[str, SpatialMemoryBuilder] = {}


def _get_builder(persona_id: str) -> SpatialMemoryBuilder:
    """Get or create a SpatialMemoryBuilder for a persona."""
    if persona_id not in _builders:
        _builders[persona_id] = SpatialMemoryBuilder(
            persona_id=persona_id,
            cfg=SpatialConfig(),
        )
    return _builders[persona_id]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/traces", response_model=IngestResponse)
async def ingest_traces(req: IngestRequest):
    """
    Ingest a batch of trace events from the client-side TraceRecorder.

    Called by the 3D-Avatar-Chatbot's TraceRecorder.flush() method.
    """
    builder = _get_builder(req.persona_id)
    events_dicts = [ev.model_dump() for ev in req.events]
    count = builder.ingest_batch(req.trace_id, events_dicts)
    return IngestResponse(ingested=count, trace_id=req.trace_id)


@router.get("/episodes", response_model=List[EpisodeResponse])
async def get_episodes(
    persona_id: str = Query("", description="Filter by persona ID"),
    limit: int = Query(5, ge=1, le=50, description="Max episodes to return"),
    min_importance: float = Query(0.0, ge=0.0, le=1.0),
):
    """
    Retrieve consolidated spatial episodes for the perceive node.
    """
    builder = _get_builder(persona_id)
    episodes = builder.get_recent_episodes(limit=limit, min_importance=min_importance)
    return [EpisodeResponse(**ep) for ep in episodes]


@router.get("/traces")
async def get_traces(
    persona_id: str = Query("", description="Filter by persona ID"),
    trace_id: Optional[str] = Query(None, description="Filter by trace ID"),
    kind: Optional[str] = Query(None, description="Filter by event kind"),
    limit: int = Query(100, ge=1, le=1000),
):
    """
    Query raw trace events (for replay, debugging, or analytics).
    """
    builder = _get_builder(persona_id)
    return builder.get_trace_events(trace_id=trace_id, kind=kind, limit=limit)


@router.get("/context-block")
async def get_context_block(
    persona_id: str = Query("", description="Persona ID"),
):
    """
    Get a pre-formatted spatial memory block for LLM system prompt injection.

    Returns plain text wrapped in <spatial_memory> tags.
    """
    builder = _get_builder(persona_id)
    block = builder.get_spatial_context_block()
    return {"persona_id": persona_id, "context_block": block}


@router.post("/reinforce")
async def reinforce_episode(req: ReinforceRequest):
    """
    Reinforce an episode that proved useful in conversation.

    Called by the decide/respond nodes when spatial memory contributed
    to a good response.
    """
    builder = _get_builder(req.persona_id)
    success = builder.reinforce_episode(req.episode_id, eta=req.eta)
    if not success:
        raise HTTPException(status_code=404, detail="Episode not found")
    return {"reinforced": True, "episode_id": req.episode_id}
