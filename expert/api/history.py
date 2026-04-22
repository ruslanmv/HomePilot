from fastapi import APIRouter
from expert.runtime.session_store import session_store

router = APIRouter()


@router.get("/sessions/{session_id}/history")
async def get_history(session_id: str):
    state = session_store.get_state(session_id)
    return {"session_id": session_id, "messages": [m.model_dump() for m in state.messages]}
