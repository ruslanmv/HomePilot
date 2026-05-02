import asyncio
import json
from collections import defaultdict
from fastapi import APIRouter
from starlette.responses import StreamingResponse
from expert.types import AgentEvent

router = APIRouter()

_session_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)


async def emit_session_event(session_id: str, event: AgentEvent) -> None:
    await _session_queues[session_id].put(event.model_dump())


def get_session_emitter(session_id: str):
    async def emitter(event: AgentEvent):
        await emit_session_event(session_id, event)
    return emitter


@router.get("/stream/{session_id}")
async def stream_session(session_id: str):
    async def event_generator():
        queue = _session_queues[session_id]
        while True:
            event = await queue.get()
            payload = json.dumps(event["data"])
            yield f"event: {event['type']}\ndata: {payload}\n\n"
            if event["type"] == "done":
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")
