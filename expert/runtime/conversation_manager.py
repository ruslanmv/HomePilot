from expert.types import Message
from expert.runtime.summarizer import Summarizer
from expert.runtime.context_builder import ContextBuilder
from expert.runtime.session_store import InMemorySessionStore


class ConversationManager:
    def __init__(self, store: InMemorySessionStore):
        self.store = store
        self.summarizer = Summarizer()
        self.context_builder = ContextBuilder()

    def add_user_message(self, session_id: str, content: str) -> None:
        state = self.store.get_state(session_id)
        state.messages.append(Message(role="user", content=content))
        self._maybe_summarize(state)
        self.store.save_state(state)

    def add_assistant_message(self, session_id: str, content: str) -> None:
        state = self.store.get_state(session_id)
        state.messages.append(Message(role="assistant", content=content))
        self._maybe_summarize(state)
        self.store.save_state(state)

    def add_tool_message(self, session_id: str, tool_name: str, payload: dict) -> None:
        state = self.store.get_state(session_id)
        state.messages.append(
            Message(role="tool", content=str(payload), meta={"tool_name": tool_name})
        )
        self.store.save_state(state)

    def build_context(self, session_id: str, current_user_message: str):
        state = self.store.get_state(session_id)
        return self.context_builder.build(state, current_user_message)

    def _maybe_summarize(self, state):
        if len(state.messages) > 20:
            state.summary = self.summarizer.summarize(state.messages[:-10])
            state.messages = state.messages[-10:]
