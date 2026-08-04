"""
Streaming chat endpoint (P1 — token streaming).

Additive Server-Sent-Events route that streams a routed chat token-by-token, so
the UI can render a live typewriter and show *where* it ran when it finishes. The
existing non-streaming ``/chat`` is untouched.

Wire format (one JSON object per SSE ``data:`` frame):

    {"delta": "Hel"}                      # token deltas, in order
    {"error": "..."}                      # a failure surfaced mid-stream
    {"done": true, "compute": {...}}      # terminal frame + route diagnostics

Fallback happens only before the first token (see ``ComputeRouter.chat_stream``),
so a live typewriter never restarts on another device.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse

from ..auth import require_api_key
from .netguard import is_safe_outbound_url
from .router import build_diagnostics, route_chat_stream

router = APIRouter(
    prefix="/v1/compute", tags=["compute-stream"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/chat/stream")
async def chat_stream_endpoint(body: dict = Body(...)) -> StreamingResponse:
    messages = body.get("messages") or []
    model = body.get("model")
    provider = body.get("provider") or "openai_compat"
    modality = body.get("modality") or "chat"
    base_url = body.get("base_url")
    if base_url and not is_safe_outbound_url(base_url):
        base_url = None  # ignore a blocked base_url rather than dial it
    temperature = float(body.get("temperature", 0.7))
    max_tokens = int(body.get("max_tokens", 800))
    report: dict = {}

    async def gen() -> Any:
        try:
            async for delta in route_chat_stream(
                messages, provider=provider, model=model, modality=modality,
                base_url=base_url, temperature=temperature, max_tokens=max_tokens,
                report=report,
            ):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as exc:  # surfaced, not a 500 — the stream already started
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield f"data: {json.dumps({'done': True, 'compute': build_diagnostics(report)})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
