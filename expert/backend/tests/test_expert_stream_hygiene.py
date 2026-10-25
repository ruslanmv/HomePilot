"""Stream hygiene: the keep-alive heartbeat on /stream, and the citation note the model gets
once there are numbered results to cite."""
import asyncio
import importlib

import pytest

routes = importlib.import_module("app.expert.routes")
tool_loop = importlib.import_module("app.expert.tool_loop")
tools_mod = importlib.import_module("app.expert.tools")

KEEP_ALIVE = ": keep-alive\n\n"


async def _slow_source():
    yield "event: meta\ndata: {}\n\n"
    await asyncio.sleep(0.25)          # a model call before its first token
    yield "data: hi\n\n"


def test_heartbeat_fills_a_silence_and_keeps_the_frames_in_order():
    async def run():
        return [f async for f in routes.with_heartbeat(_slow_source(), every=0.05)]
    frames = asyncio.run(run())
    assert frames[0].startswith("event: meta") and frames[-1] == "data: hi\n\n"
    assert KEEP_ALIVE in frames[1:-1]
    assert [f for f in frames if f != KEEP_ALIVE] == ["event: meta\ndata: {}\n\n", "data: hi\n\n"]


def test_heartbeat_off_passes_frames_through_unchanged():
    async def run():
        return [f async for f in routes.with_heartbeat(_slow_source(), every=0)]
    assert asyncio.run(run()) == ["event: meta\ndata: {}\n\n", "data: hi\n\n"]


def test_heartbeat_reraises_what_the_source_raises():
    async def broken():
        yield "a"
        raise RuntimeError("boom")

    async def run():
        return [f async for f in routes.with_heartbeat(broken(), every=0.05)]
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run())


def test_heartbeat_stops_the_source_when_the_reader_goes_away():
    """A reader that disconnects must take the model call down with it, not leave it running."""
    stopped = asyncio.Event()

    async def endless():
        try:
            while True:
                await asyncio.sleep(10)
                yield "never"
        finally:
            stopped.set()

    async def run():
        gen = routes.with_heartbeat(endless(), every=0.05)
        assert await gen.__anext__() == KEEP_ALIVE
        await gen.aclose()                                   # what Starlette does on disconnect
        return stopped.is_set()
    assert asyncio.run(run()) is True


def test_citation_note_is_added_once_there_is_something_to_cite():
    book = tool_loop.SourceBook()
    convo = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]
    assert tool_loop._round_messages(convo, offer=False, book=book) == convo       # nothing to cite yet
    with_tools = tool_loop._round_messages(convo, offer=True, book=book)
    assert tools_mod.TOOLS_NOTE in with_tools[0]["content"] and tool_loop.CITE_NOTE not in with_tools[0]["content"]

    book.add([{"title": "T", "url": "https://example.com/t"}])
    out = tool_loop._round_messages(convo, offer=True, book=book)
    assert out[0]["role"] == "system"
    assert tools_mod.TOOLS_NOTE in out[0]["content"] and tool_loop.CITE_NOTE in out[0]["content"]
    assert out[1:] == convo[1:] and convo[0]["content"] == "sys"                    # the caller's list is untouched
    no_tools = tool_loop._round_messages(convo, offer=False, book=book)            # a model that cannot call tools
    assert tool_loop.CITE_NOTE in no_tools[0]["content"] and tools_mod.TOOLS_NOTE not in no_tools[0]["content"]


# ── compaction, shown while it happens ───────────────────────────────────────

compaction = importlib.import_module("app.expert.compaction")
target_mod = importlib.import_module("app.expert.target")


def _turns(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(n)]


def test_needs_summary_counts_only_what_a_model_call_would_cover(monkeypatch):
    async def fake_summarize(previous, transcript, provider, model, temperature):
        return "note"

    monkeypatch.setattr(compaction, "summarize", fake_summarize)
    compaction._CACHE.clear()
    assert compaction.needs_summary(_turns(6), "s") == 0                        # fits the window
    assert compaction.needs_summary(_turns(20), "s") == 8                       # 8 older turns
    asyncio.run(compaction.prepare(_turns(20), session_id="s", provider="local"))
    assert compaction.needs_summary(_turns(20), "s") == 0                       # already covered
    assert compaction.needs_summary(_turns(22), "s") == 2                       # only the delta


def test_the_stream_shows_compaction_first_and_summarizes_with_the_chat_model(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    seen = {}

    async def fake_summarize(previous, transcript, provider, model, temperature):
        seen["target"] = target_mod.current()
        return "the earlier note"

    async def fake_stream(messages, provider, **kw):
        yield {"delta": "Hello"}

    monkeypatch.setattr(compaction, "summarize", fake_summarize)
    monkeypatch.setattr(tool_loop, "stream_provider_events", fake_stream)
    monkeypatch.setattr(routes, "EXPERT_SSE_HEARTBEAT_S", 0, raising=False)
    compaction._CACHE.clear()
    app = FastAPI()
    app.include_router(routes.router)
    body = {"query": "and now?", "thinking_mode": "fast", "history": _turns(20), "session_id": "c1",
            "target": {"provider": "openai_compat", "base_url": "http://gw/v1", "model": "m"}}
    with TestClient(app).stream("POST", "/v1/expert/stream", json=body) as r:
        text = "".join(r.iter_text())
    names = [line[len("event: "):] for line in text.splitlines() if line.startswith("event: ")]
    assert names[:2] == ["compacting", "meta"]
    assert "summarizing 8 earlier messages" in text and '"compacted": true' in text
    assert seen["target"] is not None and seen["target"].model == "m"           # the chat's own model


def test_a_stream_error_names_a_bug_but_keeps_a_provider_message():
    # The Space's Fast "hello" came back as "error 4": a bare str(KeyError(4)).
    assert routes._stream_error_text(KeyError(4)) == "KeyError: 4"
    assert routes._stream_error_text(IndexError()) == "IndexError"
    assert routes._stream_error_text(NotImplementedError("x")) == "NotImplementedError: x"
    msg = "Could not reach http://localhost:8001/v1 for the selected model (ConnectError). Is it running?"
    assert routes._stream_error_text(RuntimeError(msg)) == msg
    providers = importlib.import_module("app.expert.providers")
    assert routes._stream_error_text(providers.ToolsUnsupported("no tools")) == "no tools"


def test_the_state_store_finds_a_home_outside_the_repo(monkeypatch, tmp_path):
    # The Space ships Expert as /app/expert: Path(__file__).parents[4] raised IndexError(4),
    # and every Fast chat there answered "error 4".
    state_store = importlib.import_module("app.expert.state_store")
    monkeypatch.setattr(state_store, "EXPERT_STATE_DB", "")
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(state_store, "__file__", "/app/expert/state_store.py")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "data" / "homepilot.db"))
    assert state_store._default_path() == tmp_path / "data" / "expert_state.sqlite"
    monkeypatch.delenv("SQLITE_PATH")
    assert state_store._default_path().name == "homepilot-expert-state.sqlite"
    # In the repo it stays where it was: backend/data next to the main database.
    monkeypatch.setattr(state_store, "__file__", "/repo/expert/backend/app/expert/state_store.py")
    assert str(state_store._default_path()) == "/repo/backend/data/expert_state.sqlite"
