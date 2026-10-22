"""The ChatGPT-shaped turn: tools in the loop, compaction, capability gate, verdict, Deep research.

Everything runs against fakes: a scripted model (what the provider streams per call) and a
fake JSON-RPC server (what the tools answer). No network, no Ollama.
"""
import asyncio
import importlib
import json

import pytest

router = importlib.import_module("app.expert.router")
tools_mod = importlib.import_module("app.expert.tools")
tool_loop = importlib.import_module("app.expert.tool_loop")
compaction = importlib.import_module("app.expert.compaction")
capability = importlib.import_module("app.expert.capability")
heavy_mod = importlib.import_module("app.expert.heavy")
deep = importlib.import_module("app.expert.deep")
providers = importlib.import_module("app.expert.providers")
routes = importlib.import_module("app.expert.routes")
schemas = importlib.import_module("app.expert.schemas")

WEB_TOOL = {
    "name": "hp.web.search", "description": "Search the web.",
    "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}
SECRET_TOOL = {"name": "hp.secret", "description": "not in the allowlist", "inputSchema": {"type": "object"}}


async def fake_rpc(url, method, params, timeout_s):
    if method == "tools/list":
        return {"tools": [WEB_TOOL, SECRET_TOOL]}
    assert method == "tools/call" and params["name"] == "hp.web.search"
    q = params["arguments"]["query"]
    return {
        "content": [{"type": "text", "text": f"results for {q}"}],
        "structuredContent": {"results": [
            {"title": "HomePilot", "url": "https://github.com/ruslanmv/HomePilot", "snippet": "the repo"},
        ]},
        "isError": False,
    }


class FakeModel:
    """Streams what the script says, call after call: ('text', ...) or ('calls', [...])."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []                       # (messages, tools) per provider call

    async def __call__(self, messages, provider, *, tools=None, model=None, temperature=0.7, max_tokens=2048):
        self.calls.append((list(messages), tools))
        kind, payload = self.script.pop(0) if self.script else ("text", "fallback answer")
        if kind == "raise":
            raise payload
        if kind == "calls" and tools:
            yield {"tool_calls": [
                {"id": f"call_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                for i, c in enumerate(payload, 1)
            ]}
            return
        if kind == "calls":                   # no tools offered → the model has to answer
            payload = "forced answer"
        half = len(payload) // 2
        for piece in (payload[:half], payload[half:]):
            if piece:
                yield {"delta": piece}


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(tools_mod, "rpc", fake_rpc)
    monkeypatch.setattr(tools_mod, "_REGISTRY", None)
    tool_loop.forget_tools()
    compaction._CACHE.clear()
    capability.reset_cache()
    yield


def _events(gen):
    return asyncio.get_event_loop().run_until_complete(_collect(gen))


async def _collect(gen):
    return [ev async for ev in gen]


# ── tools.py ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_discovers_allowed_tools_and_calls_them(fresh):
    reg = tools_mod.ToolRegistry(servers=["http://fake/rpc"], allow="hp.web.search")
    specs = await reg.discover()
    assert [s.name for s in specs] == ["hp_web_search"]                      # OpenAI-safe name, allowlist applied
    assert (await reg.openai_tools())[0]["function"]["parameters"]["required"] == ["query"]
    out = await reg.call("hp_web_search", {"query": "homepilot"})
    assert out.ok and out.text.startswith("results for homepilot")
    assert out.sources[0]["domain"] == "github.com"
    assert tools_mod.label_for("hp.web.search", {"query": "homepilot"}) == "Searching the web for “homepilot”"


# ── tool_loop.py ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_loop_runs_the_calls_numbers_the_sources_and_answers(fresh, monkeypatch):
    model = FakeModel([
        ("calls", [{"name": "hp_web_search", "arguments": {"query": "homepilot"}}]),
        ("text", "HomePilot is on GitHub [1]."),
    ])
    monkeypatch.setattr(tool_loop, "stream_provider_events", model)
    reg = tools_mod.ToolRegistry(servers=["http://fake/rpc"], allow="hp.web.search")
    events = await _collect(tool_loop.stream_with_tools(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "where is HomePilot?"}], "local", registry=reg,
    ))
    kinds = [e["type"] for e in events]
    assert kinds[:3] == ["tool_start", "tool_end", "sources"]
    assert kinds[-1] == "done"
    done = events[-1]
    assert done["content"] == "HomePilot is on GitHub [1]." and done["rounds"] == 1
    assert done["sources"][0]["n"] == 1 and done["tool_trace"][0]["sources"] == [1]
    assert events[0]["label"] == "Searching the web for “homepilot”"
    # Round 1 offered the tools and the tools note; round 2 read the numbered result back.
    first_messages, first_tools = model.calls[0]
    assert first_tools and tools_mod.TOOLS_NOTE in first_messages[0]["content"]
    second_messages, _ = model.calls[1]
    assert second_messages[-1]["role"] == "tool" and second_messages[-1]["content"].startswith("[1] HomePilot")
    assert second_messages[-2]["tool_calls"][0]["function"]["name"] == "hp_web_search"


@pytest.mark.asyncio
async def test_run_with_tools_caps_the_rounds_and_then_forces_an_answer(fresh):
    """The non-streaming loop goes through the caller's dispatch and stops offering tools
    after max_rounds, so a model that keeps calling must finally answer."""
    offered = []

    async def fake_dispatch(messages, provider, *, tools=None, **kw):
        offered.append(tools)
        if tools:
            return {"provider": "local", "model": "m", "choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "hp_web_search", "arguments": '{"query": "a"}'}},
            ]}}]}
        return {"provider": "local", "model": "m", "choices": [{"message": {"content": "forced answer"}}]}

    reg = tools_mod.ToolRegistry(servers=["http://fake/rpc"], allow="hp.web.search")
    done = await tool_loop.run_with_tools([{"role": "user", "content": "q"}], "local",
                                          registry=reg, max_rounds=2, call=fake_dispatch)
    assert done["rounds"] == 2 and done["content"] == "forced answer" and done["model"] == "m"
    assert offered[-1] is None and len(offered) == 3                          # two tool rounds, then no tools
    assert len(done["tool_trace"]) == 2 and done["sources"][0]["n"] == 1      # the same URL twice → one source


@pytest.mark.asyncio
async def test_forced_web_search_runs_before_the_model_speaks(fresh):
    """"Search the web" on: the search runs first and its numbered results are in the
    conversation when the model is asked; an unknown forced tool only leaves a notice."""
    seen = []

    async def fake_dispatch(messages, provider, *, tools=None, **kw):
        seen.append(messages)
        return {"provider": "local", "model": "m", "choices": [{"message": {"content": "Found it [1]."}}]}

    reg = tools_mod.ToolRegistry(servers=["http://fake/rpc"], allow="hp.web.search")
    done = await tool_loop.run_with_tools(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "latest HomePilot news?"}], "local",
        registry=reg, call=fake_dispatch, forced=[("hp_web_search", {"query": "latest HomePilot news?"})],
    )
    assert done["rounds"] == 1 and done["content"] == "Found it [1]." and done["sources"][0]["n"] == 1
    assert seen[0][-1]["role"] == "tool" and seen[0][-1]["content"].startswith("[1] HomePilot")
    assert seen[0][-2]["tool_calls"][0]["id"] == "forced_1"
    missing = await tool_loop.run_with_tools([{"role": "user", "content": "q"}], "local",
                                             registry=reg, call=fake_dispatch, forced=[("hp_nope", {})])
    assert missing["rounds"] == 0 and "not available right now" in missing["notices"][0]


def test_think_filter_drops_reasoning_and_leaked_tags_across_split_tokens():
    f = tool_loop.ThinkFilter()
    out = "".join(f.feed(t) for t in ["<thi", "nk>secret ", "plan</th", "ink>Hello", " world <", "b>"]) + f.flush()
    assert out == "Hello world <b>"
    leaked = tool_loop.ThinkFilter()
    assert "".join(leaked.feed(t) for t in [">\n\n", "Answer."]) + leaked.flush() == "Answer."
    closing = tool_loop.ThinkFilter()
    assert "".join(closing.feed(t) for t in ["</think> Based", " on it."]) + closing.flush() == "Based on it."
    quote = tool_loop.ThinkFilter()                                           # a real blockquote survives
    assert "".join(quote.feed(t) for t in ["> quoted", " line"]) + quote.flush() == "> quoted line"
    assert tool_loop.strip_think("<think>x</think>\nok") == "ok"
    assert tool_loop.strip_think("</think> VALIDATED. fine") == "VALIDATED. fine"


def test_without_tool_roles_keeps_gathered_results_as_plain_turns():
    convo = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "forced_1"}]},
        {"role": "tool", "tool_call_id": "forced_1", "name": "hp_web_search", "content": "[1] A\nhttps://a.test"},
    ]
    assert tool_loop.without_tool_roles(convo) == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q"},
        {"role": "user", "content": "Results from hp web search:\n[1] A\nhttps://a.test"},
    ]


@pytest.mark.asyncio
async def test_tool_loop_remembers_a_model_without_tool_support(fresh, monkeypatch):
    """A refusal of the tools field is a capability fact: logged, remembered durably, and the
    answer continues without tools — the reader sees no notice about it."""
    model = FakeModel([("raise", providers.ToolsUnsupported("no tools")), ("text", "plain answer")])
    monkeypatch.setattr(tool_loop, "stream_provider_events", model)
    reg = tools_mod.ToolRegistry(servers=["http://fake/rpc"], allow="hp.web.search")
    events = await _collect(tool_loop.stream_with_tools([{"role": "user", "content": "q"}], "local", registry=reg, model="tiny"))
    assert [e["type"] for e in events if e["type"] == "notice"] == []
    assert events[-1]["content"] == "plain answer"
    assert model.calls[1][1] is None                                          # retried without tools
    key = tool_loop.capability_key(None, "local", "tiny")
    assert tool_loop.tools_known(key) is False
    tool_loop._TOOL_FACTS.clear()                                             # a restart: the store still knows
    assert tool_loop.tools_known(key) is False
    # The next turn never offers tools to that model again.
    second = FakeModel([("text", "again")])
    monkeypatch.setattr(tool_loop, "stream_provider_events", second)
    await _collect(tool_loop.stream_with_tools([{"role": "user", "content": "q"}], "local", registry=reg, model="tiny"))
    assert second.calls[0][1] is None


# ── compaction.py ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compaction_summarizes_the_overflow_incrementally(fresh, monkeypatch):
    seen = []

    async def fake_summarize(previous, transcript, provider, model, temperature):
        seen.append((previous, transcript))
        return f"note{len(seen)}"

    monkeypatch.setattr(compaction, "summarize", fake_summarize)
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(20)]
    window, note, notice = await compaction.prepare(turns, session_id="s1", provider="local")
    assert len(window) == 12 and note == "note1" and notice is None
    assert "turn 7" in seen[0][1] and "turn 8" not in seen[0][1]              # exactly the 8 older turns
    # The same overflow again costs nothing; two more turns summarize only the delta.
    assert (await compaction.prepare(turns, session_id="s1", provider="local"))[1] == "note1"
    more = turns + [{"role": "user", "content": "turn 20"}, {"role": "assistant", "content": "turn 21"}]
    _, note2, _ = await compaction.prepare(more, session_id="s1", provider="local")
    assert note2 == "note2" and seen[1][0] == "note1"
    assert seen[1][1].splitlines() == ["User: turn 8", "Assistant: turn 9"]
    with compaction.using(note2):
        assert "note2" in router.build_messages("q")[0]["content"]
    assert "note2" not in router.build_messages("q")[0]["content"]


@pytest.mark.asyncio
async def test_compaction_failure_keeps_the_window_and_says_so(fresh, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(compaction, "summarize", boom)
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"t{i}"} for i in range(16)]
    window, note, notice = await compaction.prepare(turns, session_id="s2", provider="local")
    assert len(window) == 12 and note is None and "could not be summarized" in notice


# ── capability.py ────────────────────────────────────────────────────────────

def test_capability_reads_tiers_from_gateway_model_names():
    high = ["internal-gpt-oss-120b", "internal-gemma4-31b", "internal-qwen3-8-27b", "ext-claude-lite",
            "internal-glm-5.3-flash", "ext-gemini-standard", "internal-kimi-k3", "internal-deepseek-v4-1-flash"]
    for name in high:
        assert capability.profile(name).tier == "high", name
    assert capability.params_from_name("internal-qwen3-8-27b") == 27
    local = capability.profile("deepseek-r1:latest", 8.2)
    assert local.tier == "medium" and local.tools_likely is False
    assert capability.profile("llama3.2:3b", 3.2).tier == "low"
    assert capability.deep_research_enabled(capability.best_of([capability.profile(n) for n in high]))["enabled"]
    gate = capability.deep_research_enabled(local)
    assert gate["enabled"] is False and "high-end" in gate["reason"]


def test_stronger_never_swaps_one_high_end_model_for_another():
    assert capability.stronger({"name": "b", "rank": 2, "params_b": 120}, {"name": "a", "rank": 2, "params_b": 31}) is False
    assert capability.stronger({"name": "b", "rank": 1, "params_b": 14}, {"name": "a", "rank": 1, "params_b": 7}) is True
    assert capability.stronger({"name": "b", "rank": 2, "params_b": None}, {"name": "a", "rank": 1, "params_b": 8}) is True
    assert capability.stronger({"name": "a", "rank": 2}, {"name": "a", "rank": 2}) is False


class _FakeStreamResponse:
    def __init__(self, status, body, content_type):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self._body = body

    async def aread(self):
        return self._body.encode()

    async def aiter_lines(self):
        for line in self._body.splitlines():
            yield line


class _FakeClient:
    """httpx.AsyncClient stand-in: one scripted response for .stream()."""
    response = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None):
        client = self

        class _Ctx:
            async def __aenter__(self_inner):
                return client.response

            async def __aexit__(self_inner, *a):
                return False
        return _Ctx()


@pytest.mark.asyncio
async def test_openai_compat_stream_takes_a_json_body_and_treats_errors_on_tools_as_no_tools(monkeypatch):
    """OllaBridge answers stream=true with one JSON completion, and fails any request that
    carries tools (HTTP 500 after falling through to a runtime without the model)."""
    monkeypatch.setattr(providers.httpx, "AsyncClient", _FakeClient)
    _FakeClient.response = _FakeStreamResponse(
        200, json.dumps({"choices": [{"message": {"role": "assistant", "content": "Hi there!"}}]}), "application/json",
    )
    events = [ev async for ev in providers.stream_openai_compat_events(
        [{"role": "user", "content": "hi"}], base_url="http://gw/v1", model="openwebui/internal-gemma4-31b",
    )]
    assert events == [{"delta": "Hi there!"}]
    _FakeClient.response = _FakeStreamResponse(500, '{"detail":"Client error 404 for url http://localhost:11434/api/chat"}', "application/json")
    with pytest.raises(providers.ToolsUnsupported):
        async for _ in providers.stream_openai_compat_events(
            [{"role": "user", "content": "hi"}], base_url="http://gw/v1", model="m", tools=[{"type": "function", "function": {"name": "t"}}],
        ):
            pass
    # Without tools, an older OllaBridge's 500 hides a provider failure (usually its rate limit):
    # it is waited out, and past the budget the reader gets a clear "busy" message.
    monkeypatch.setattr(providers, "_backoff_s", lambda attempt, retry_after: 0.0)
    monkeypatch.setattr(providers, "EXPERT_PROVIDER_RETRIES", 1)
    with pytest.raises(RuntimeError, match="busy right now"):
        async for _ in providers.stream_openai_compat_events([{"role": "user", "content": "hi"}], base_url="http://gw/v1", model="m"):
            pass
    _FakeClient.response = _FakeStreamResponse(500, '{"detail":"model crashed"}', "application/json")
    with pytest.raises(RuntimeError, match="HTTP 500: model crashed"):     # any other 500 is a real error
        async for _ in providers.stream_openai_compat_events([{"role": "user", "content": "hi"}], base_url="http://gw/v1", model="m"):
            pass


@pytest.mark.asyncio
async def test_assess_measures_ollama_and_gateways(fresh, monkeypatch):
    async def fake_tags(base_url=None):
        return [{"name": "deepseek-r1:latest", "params_b": 8.2}, {"name": "qwen3:32b", "params_b": 32.8}]

    async def fake_models(base_url, api_key=""):
        return ["ext-openai-lite", "internal-muse-glimmer-30b"]

    monkeypatch.setattr(providers, "ollama_models_detail", fake_tags)
    monkeypatch.setattr(providers, "openai_compat_models", fake_models)
    caps = await capability.assess(None, "deepseek-r1:latest")
    assert caps["selected"]["tier"] == "medium" and caps["best"]["name"] == "qwen3:32b"
    # The chosen model is the one that would research: a medium one is not offered Deep research,
    # whatever else is installed.
    assert caps["deep_research"]["enabled"] is False and "deepseek-r1" in caps["deep_research"]["reason"]
    assert capability.stronger(caps["best"], caps["selected"])
    caps = await capability.assess(None, "qwen3:32b")
    assert caps["deep_research"]["enabled"] and caps["deep_research"]["model"] == "qwen3:32b"
    gateway = router.target_mod.ChatTarget(provider="openai_compat", base_url="http://gw/v1", model="ext-openai-lite")
    caps = await capability.assess(gateway)
    assert caps["connection"] == "openai_compat" and caps["selected"]["tier"] == "high"
    assert capability.stronger(caps["best"], caps["selected"]) is False        # both high: no pointless swap


# ── heavy.py verdict ─────────────────────────────────────────────────────────

def test_verdict_of_reads_the_validator():
    assert heavy_mod.verdict_of("VALIDATED. Minor: add units.", "A")[0:2] == ("validated", "A")
    assert heavy_mod.verdict_of("**CORRECTION:** B is right", "A")[0:2] == ("corrected", "B is right")
    assert heavy_mod.verdict_of("Looks plausible overall.", "A")[0:2] == ("reviewed", "A")


# ── deep.py ──────────────────────────────────────────────────────────────────

def test_parse_plan_accepts_json_lists_and_falls_back():
    assert deep.parse_plan('Sure: {"questions": ["What is X?", "Who makes X?"]}', "q", 5) == ["What is X?", "Who makes X?"]
    assert deep.parse_plan("1. First thing\n2) Second thing\n- Third", "q", 2) == ["First thing", "Second thing"]
    assert deep.parse_plan("", "the request", 5) == ["the request"]
    assert deep.renumber("see [1] and [2]", {1: 4, 2: 5}) == "see [4] and [5]"


@pytest.mark.asyncio
async def test_deep_research_plans_researches_with_tools_and_writes_a_cited_report(fresh, monkeypatch):
    async def fake_dispatch(messages, provider, **kw):
        return {"choices": [{"message": {"content": '{"questions": ["What is HomePilot?", "Who maintains it?"]}'}}]}

    sub_agents = FakeModel([
        ("calls", [{"name": "hp_web_search", "arguments": {"query": "HomePilot"}}]), ("text", "It is a local AI hub [1]."),
        ("calls", [{"name": "hp_web_search", "arguments": {"query": "HomePilot maintainer"}}]), ("text", "ruslanmv maintains it [1]."),
    ])
    writer = FakeModel([("text", "# Report\nHomePilot is a local AI hub [1].")])
    monkeypatch.setattr(deep, "dispatch", fake_dispatch)
    monkeypatch.setattr(tool_loop, "stream_provider_events", sub_agents)
    monkeypatch.setattr(deep, "stream_provider_events", writer)

    job = deep.start("Tell me about HomePilot", provider="local", model="big", history=[], chosen=None,
                     timezone=None, context=None, note=None)
    await job.task
    assert job.status == "done", job.error
    assert [p.status for p in job.plan] == ["done", "done"]
    assert len(job.sources) == 1 and job.sources[0]["n"] == 1               # the same URL twice → one source
    assert job.plan[1].finding == "ruslanmv maintains it [1]."
    assert job.report.startswith("# Report")
    kinds = [e["type"] for e in job.events]
    assert kinds[0] == "status" and "plan" in kinds and "tool_start" in kinds and kinds[-1] == "done"
    assert job.events[-1]["plan"][0]["summary"] == "It is a local AI hub [1]."
    snap = job.snapshot()
    assert snap["status"] == "done" and snap["plan"][0]["title"] == "What is HomePilot?"
    # A late subscriber gets the whole history replayed.
    q = job.subscribe()
    assert q.get_nowait()["type"] == "status"


@pytest.mark.asyncio
async def test_deep_research_survives_a_failed_item_and_a_failed_writer(fresh, monkeypatch):
    """A busy gateway can fail any one call: the job goes on, says what is missing, and still
    hands back what it found."""
    async def fake_dispatch(messages, provider, **kw):
        return {"choices": [{"message": {"content": '{"questions": ["What is HomePilot?", "Who maintains it?"]}'}}]}

    calls = {"n": 0}

    async def sub_agent(messages, provider, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("gw is overloaded or restarting (HTTP 503). Try again in a moment.")
        yield {"delta": "ruslanmv maintains it [1]."}

    async def broken_writer(messages, provider, **kw):
        raise RuntimeError("gw is being rate limited by its provider (HTTP 429). Try again in a moment.")
        yield {}  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(deep, "dispatch", fake_dispatch)
    monkeypatch.setattr(tool_loop, "stream_provider_events", sub_agent)
    monkeypatch.setattr(deep, "stream_provider_events", broken_writer)
    job = deep.start("Tell me about HomePilot", provider="local", model="big", history=[], chosen=None,
                     timezone=None, context=None, note=None)
    await job.task
    assert job.status == "done", job.error
    assert [p.status for p in job.plan] == ["failed", "done"]
    failed = next(e for e in job.events if e["type"] == "item" and e["status"] == "failed")
    assert failed["summary"].startswith("Could not be researched") and "503" in failed["summary"]
    assert any("could not be researched" in n for n in job.notices)
    assert any("writer could not finish" in n for n in job.notices)
    assert "### Who maintains it?" in job.report and "ruslanmv maintains it [1]." in job.report


@pytest.mark.asyncio
async def test_deep_research_answers_a_greeting_directly_without_researching(fresh, monkeypatch):
    async def no_planner(messages, provider, **kw):  # pragma: no cover - must not be called
        raise AssertionError("a greeting must not be planned")

    async def no_sub_agent(messages, provider, **kw):  # pragma: no cover - must not be called
        raise AssertionError("a greeting must not be researched")
        yield {}

    async def reply(messages, provider, **kw):
        yield {"delta": "Hello! What would you like me to research?"}

    monkeypatch.setattr(deep, "dispatch", no_planner)
    monkeypatch.setattr(tool_loop, "stream_provider_events", no_sub_agent)
    monkeypatch.setattr(deep, "stream_provider_events", reply)
    job = deep.start("hello", provider="local", model="big", history=[], chosen=None,
                     timezone=None, context=None, note=None)
    await job.task
    assert job.status == "done", job.error
    assert job.plan == [] and job.report.startswith("Hello!")
    assert any("needs no research" in n for n in job.notices)
    assert job.events[-1]["type"] == "done" and job.events[-1]["plan"] == []


@pytest.mark.asyncio
async def test_deep_research_without_a_planner_researches_the_request_itself(fresh, monkeypatch):
    async def failing_planner(messages, provider, **kw):
        raise RuntimeError("gw is being rate limited by its provider (HTTP 429). Try again in a moment.")

    async def sub_agent(messages, provider, **kw):
        yield {"delta": "It is a local AI hub."}

    async def writer(messages, provider, **kw):
        yield {"delta": "# Report"}

    monkeypatch.setattr(deep, "dispatch", failing_planner)
    monkeypatch.setattr(tool_loop, "stream_provider_events", sub_agent)
    monkeypatch.setattr(deep, "stream_provider_events", writer)
    job = deep.start("Tell me about HomePilot", provider="local", model="big", history=[], chosen=None,
                     timezone=None, context=None, note=None)
    await job.task
    assert job.status == "done", job.error
    assert [p.title for p in job.plan] == ["Tell me about HomePilot"]
    assert any("planner could not run" in n for n in job.notices)
    assert job.report == "# Report"


@pytest.mark.asyncio
async def test_deep_route_is_refused_without_a_high_end_model(fresh, monkeypatch):
    async def weak(target, selected_model=None):
        return {"selected": {"name": "llama3.2:3b", "rank": 0}, "best": {"name": "llama3.2:3b", "rank": 0},
                "deep_research": {"enabled": False, "reason": "Deep research needs a high-end model", "model": None}}

    monkeypatch.setattr(capability, "assess", weak)
    with pytest.raises(routes.HTTPException) as err:
        await routes.deep_start(schemas.ExpertChatRequest(query="deep question"))
    assert err.value.status_code == 403 and "high-end" in err.value.detail


@pytest.mark.asyncio
async def test_capabilities_route_reports_the_gate(fresh, monkeypatch):
    async def fake_tags(base_url=None):
        return [{"name": "gpt-oss:120b", "params_b": 116.8}]

    monkeypatch.setattr(providers, "ollama_models_detail", fake_tags)
    out = await routes.expert_capabilities(schemas.CapabilitiesRequest(target=None, model="gpt-oss:120b"))
    assert out["tier"] == "high" and out["deep_research"]["enabled"] is True
