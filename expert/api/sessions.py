from fastapi import APIRouter
from expert.runtime.session_store import session_store

router = APIRouter()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    return session_store.get_state(session_id).model_dump()
