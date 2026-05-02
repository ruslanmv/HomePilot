from typing import Dict
from expert.types import SessionState


class InMemorySessionStore:
    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}

    def get_state(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
        return self._sessions[session_id]

    def save_state(self, state: SessionState) -> None:
        self._sessions[state.session_id] = state


session_store = InMemorySessionStore()
