from expert.runtime.context_builder import ContextBuilder
from expert.types import SessionState, Message


def test_context_builder():
    state = SessionState(session_id="s1", messages=[Message(role="user", content="hello")], summary="")
    ctx = ContextBuilder().build(state, "next")
    assert ctx[-1].content == "next"
