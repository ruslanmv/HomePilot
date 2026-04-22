from expert.types import SessionState, Message


class ContextBuilder:
    def build(self, state: SessionState, current_user_message: str) -> list[Message]:
        context = []
        if state.summary:
            context.append(Message(role="system", content=state.summary))
        context.extend(state.messages[-12:])
        context.append(Message(role="user", content=current_user_message))
        return context
