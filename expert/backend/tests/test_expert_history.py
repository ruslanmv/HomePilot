"""Expert ("think") and Heavy see the conversation.

Before this, both pipelines accepted the history and dropped it: every step was a question
from nowhere, so "and for the second option?" had nothing to resolve against. Now each step
gets the recent turns as role-tagged messages ahead of its instruction, within a bounded
window — the same shape the fast path and every chat model use.
"""
import importlib

import pytest

router = importlib.import_module("app.expert.router")
thinking = importlib.import_module("app.expert.thinking")
heavy_mod = importlib.import_module("app.expert.heavy")

HISTORY = [
    {"role": "user", "content": "Compare Postgres and SQLite for a laptop app."},
    {"role": "assistant", "content": "1. SQLite: zero setup. 2. Postgres: real concurrency."},
]
QUERY = "And the second option — what does it need to run?"


def _reply(text: str = "ok"):
    return {"provider": "local", "model": "m", "choices": [{"message": {"content": text}}]}


def _capture(module, monkeypatch):
    """Replace the module's provider calls; return the list of message lists they received."""
    calls = []

    async def fake_dispatch(messages, provider, **kw):
        calls.append(messages)
        return _reply()

    async def fake_stream(messages, provider, **kw):
        calls.append(messages)
        yield "ok"

    async def fake_events(messages, provider, **kw):      # the tool loop's provider seam
        calls.append(messages)
        yield {"delta": "ok"}

    monkeypatch.setattr(module, "dispatch", fake_dispatch)
    monkeypatch.setattr(module, "dispatch_stream", fake_stream)
    monkeypatch.setattr(module, "stream_provider_events", fake_events)
    return calls


def _assert_threaded(messages):
    assert messages[0]["role"] == "system"
    assert [m["role"] for m in messages[1:-1]] == ["user", "assistant"]
    assert [m["content"] for m in messages[1:-1]] == [m["content"] for m in HISTORY]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"].startswith(router.CONTINUATION_NOTE)


def test_history_window_keeps_the_newest_clean_turns_opening_on_the_user():
    noisy = [
        {"role": "system", "content": "ignored"},
        {"role": "assistant", "content": "dangling"},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    assert router.history_window(noisy) == [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    # A budget that would open the window on the assistant's turn drops that turn too.
    assert router.history_window(noisy, max_turns=2) == [{"role": "user", "content": "c"}]
    assert router.history_window(noisy, max_chars=1) == [{"role": "user", "content": "c"}]
    assert router.history_window(None) == []


def test_build_messages_is_system_turns_query():
    messages = router.build_messages(QUERY, history=HISTORY)
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[-1]["content"] == QUERY                     # the fast path adds no note


@pytest.mark.asyncio
async def test_think_threads_the_conversation_into_every_step(monkeypatch):
    calls = _capture(thinking, monkeypatch)
    out = await thinking.think(QUERY, "local", history=HISTORY, with_critique=True)
    assert out["final_answer"] == "ok"
    assert len(calls) == 4                                      # analyze, plan, solve, critique
    for messages in calls:
        _assert_threaded(messages)
    assert QUERY in calls[0][-1]["content"]                     # the analysis reads the question


@pytest.mark.asyncio
async def test_heavy_threads_the_conversation_into_every_agent(monkeypatch):
    calls = _capture(heavy_mod, monkeypatch)
    out = await heavy_mod.heavy(QUERY, "local", history=HISTORY)
    assert out["final_answer"] == "ok"
    assert len(calls) == 4                                      # research, reason, synth, validate
    for messages in calls:
        _assert_threaded(messages)
    assert calls[0][0]["content"].startswith(heavy_mod._RESEARCHER_SYSTEM)   # roles kept


@pytest.mark.asyncio
async def test_streaming_pipelines_thread_it_too(monkeypatch):
    calls = _capture(thinking, monkeypatch)
    async for _ in thinking.stream_think(QUERY, "local", history=HISTORY):
        pass
    assert len(calls) == 3
    for messages in calls:
        _assert_threaded(messages)

    calls = _capture(heavy_mod, monkeypatch)
    async for _ in heavy_mod.stream_heavy(QUERY, "local", history=HISTORY):
        pass
    assert len(calls) == 4
    for messages in calls:
        _assert_threaded(messages)


@pytest.mark.asyncio
async def test_without_history_the_steps_are_unchanged(monkeypatch):
    calls = _capture(thinking, monkeypatch)
    await thinking.think(QUERY, "local", history=[])
    for messages in calls:
        assert [m["role"] for m in messages] == ["system", "user"]
        assert router.CONTINUATION_NOTE not in messages[-1]["content"]
