"""Resilience against a busy gateway: error classification, pacing, retries with backoff,
Heavy going on without an agent that cannot run, and Expert's visible analysis at standard
effort (two paced calls instead of one silent one)."""
import asyncio
import importlib
import json
import time

import pytest

providers = importlib.import_module("app.expert.providers")
heavy_mod = importlib.import_module("app.expert.heavy")
thinking = importlib.import_module("app.expert.thinking")
policies = importlib.import_module("app.expert.policies")
tools_mod = importlib.import_module("app.expert.tools")

GW = "http://gw/v1"
TOOLS = [{"type": "function", "function": {"name": "ping", "parameters": {"type": "object", "properties": {}}}}]


def _err(status, detail, headers=None, tools=False):
    return providers._openai_compat_error(status, detail, headers or {}, base_url=GW, model="m", tools=tools)


def test_errors_are_read_by_what_the_endpoint_said():
    rate = _err(429, "slow down", {"retry-after": "2"})
    assert isinstance(rate, providers._RateLimited) and rate.retry_after == 2.0
    # Open WebUI says it with a 400; the words decide, not the status.
    assert isinstance(_err(400, "Rate limit exceeded. Please try again later."), providers._RateLimited)
    assert isinstance(_err(400, "Rate limit exceeded", tools=True), providers._RateLimited)      # never "no tools"
    assert isinstance(_err(503, "", {"retry-after": "5"}), providers._Overloaded)
    assert isinstance(_err(400, "model does not support tools", tools=True), providers.ToolsUnsupported)
    assert isinstance(_err(400, '{"code": "tools_unsupported"}', tools=True), providers.ToolsUnsupported)
    legacy = _err(500, "Client error '404 Not Found' for url 'http://localhost:11434/api/chat'", tools=True)
    assert isinstance(legacy, providers.ToolsUnsupported)
    assert type(_err(400, "unknown field", tools=False)) is RuntimeError
    assert type(_err(400, "model does not support tools", tools=False)) is RuntimeError           # no tools were sent
    assert providers._detail_text('{"error": {"message": "inner"}}') == "inner"
    assert providers._detail_text('{"detail": "Rate limit exceeded."}') == "Rate limit exceeded."
    assert providers._detail_text("plain text") == "plain text"


class _Resp:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


class _ScriptedClient:
    """httpx.AsyncClient stand-in: scripted answers for .post(), with the time of each call."""
    script = []
    posts = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _ScriptedClient.posts.append(time.monotonic())
        return _ScriptedClient.script.pop(0)


def _ok(text="x"):
    return _Resp(200, {"choices": [{"message": {"role": "assistant", "content": text}}], "model": "m"})


@pytest.mark.asyncio
async def test_chat_waits_out_a_rate_limit_and_a_503_then_answers(monkeypatch):
    monkeypatch.setattr(providers.httpx, "AsyncClient", _ScriptedClient)
    monkeypatch.setattr(providers, "_backoff_s", lambda attempt, retry_after: 0.0)
    _ScriptedClient.script = [
        _Resp(429, {"error": {"message": "Rate limit exceeded"}}, {"retry-after": "1"}),
        _Resp(503, {"detail": "queue full"}),
        _ok("after the wait"),
    ]
    _ScriptedClient.posts = []
    out = await providers.chat_openai_compat([{"role": "user", "content": "hi"}], base_url=GW, model="m", tools=TOOLS)
    assert out["choices"][0]["message"]["content"] == "after the wait"
    assert len(_ScriptedClient.posts) == 3


@pytest.mark.asyncio
async def test_chat_gives_up_after_the_retries_and_says_rate_limited_not_no_tools(monkeypatch):
    monkeypatch.setattr(providers.httpx, "AsyncClient", _ScriptedClient)
    monkeypatch.setattr(providers, "_backoff_s", lambda attempt, retry_after: 0.0)
    monkeypatch.setattr(providers, "EXPERT_PROVIDER_RETRIES", 1)
    _ScriptedClient.script = [_Resp(400, {"detail": "Rate limit exceeded. Please try again later."}) for _ in range(2)]
    _ScriptedClient.posts = []
    with pytest.raises(RuntimeError, match="rate limited") as excinfo:
        await providers.chat_openai_compat([{"role": "user", "content": "hi"}], base_url=GW, model="m", tools=TOOLS)
    assert not isinstance(excinfo.value, providers.ToolsUnsupported)
    assert len(_ScriptedClient.posts) == 2


@pytest.mark.asyncio
async def test_the_pacer_slows_down_on_a_rate_limit_and_recovers_on_success():
    pacer = providers._EndpointPacer(max_inflight=2, min_interval=0.5, max_interval=8.0)
    assert pacer.interval(GW) == 0.5
    assert pacer.penalize(GW) == 2.0                    # at least 2 s after the first limit
    assert pacer.penalize(GW) == 4.0                    # doubles
    assert pacer.penalize(GW, retry_after=30) == 8.0    # capped
    for _ in range(40):
        pacer.reward(GW)
    assert pacer.interval(GW) == 0.5                    # back to normal after a quiet stretch
    assert pacer.interval("http://other/v1") == 0.5     # per endpoint


@pytest.mark.asyncio
async def test_a_rate_limit_holds_every_caller_for_the_cooldown(monkeypatch):
    pacer = providers._EndpointPacer(max_inflight=4, min_interval=0.0, max_interval=0.2)
    pacer.penalize(GW)                                  # 0.2 s cooldown (capped)
    started = time.monotonic()
    async with pacer.slot(GW):
        pass
    assert time.monotonic() - started >= 0.18


def test_an_older_ollabridge_provider_failure_is_waited_out_without_tools():
    body = "Client error '404 Not Found' for url 'http://localhost:11434/api/chat'"
    assert isinstance(_err(500, body, tools=False), providers._RateLimited)
    assert isinstance(_err(500, body, tools=True), providers.ToolsUnsupported)


@pytest.mark.asyncio
async def test_requests_to_one_endpoint_are_spaced_out(monkeypatch):
    monkeypatch.setattr(providers.httpx, "AsyncClient", _ScriptedClient)
    monkeypatch.setattr(providers._PACER, "min_interval", 0.05)
    monkeypatch.setattr(providers._PACER, "max_interval", 0.05)
    _ScriptedClient.script = [_ok(), _ok(), _ok()]
    _ScriptedClient.posts = []
    await asyncio.gather(*[
        providers.chat_openai_compat([{"role": "user", "content": "hi"}], base_url=GW, model="m") for _ in range(3)
    ])
    starts = sorted(_ScriptedClient.posts)
    assert len(starts) == 3
    assert all(later - earlier >= 0.045 for earlier, later in zip(starts, starts[1:]))


class _StreamResp:
    def __init__(self, status, body, content_type="application/json"):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self._body = body

    async def aread(self):
        return self._body.encode()

    async def aiter_lines(self):
        for line in self._body.splitlines():
            yield line


class _ScriptedStreamClient:
    script = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None):
        resp = _ScriptedStreamClient.script.pop(0)

        class _Ctx:
            async def __aenter__(self_inner):
                return resp

            async def __aexit__(self_inner, *a):
                return False
        return _Ctx()


@pytest.mark.asyncio
async def test_stream_retries_before_the_first_token(monkeypatch):
    monkeypatch.setattr(providers.httpx, "AsyncClient", _ScriptedStreamClient)
    monkeypatch.setattr(providers, "_backoff_s", lambda attempt, retry_after: 0.0)
    _ScriptedStreamClient.script = [
        _StreamResp(429, json.dumps({"error": {"message": "Rate limit exceeded"}})),
        _StreamResp(200, json.dumps({"choices": [{"message": {"role": "assistant", "content": "Hi"}}]})),
    ]
    events = [ev async for ev in providers.stream_openai_compat_events(
        [{"role": "user", "content": "hi"}], base_url=GW, model="m",
    )]
    waits = [ev["wait"] for ev in events if "wait" in ev]
    assert [ev for ev in events if "wait" not in ev] == [{"delta": "Hi"}]
    assert len(waits) == 1 and waits[0]["text"].startswith("The model provider is busy; retrying in")
    assert waits[0]["attempt"] == 1 and waits[0]["retry_in"] >= 0


@pytest.mark.asyncio
async def test_heavy_answers_unverified_when_the_validator_cannot_run(monkeypatch):
    async def fake_events(messages, provider, **kw):              # the reasoner, through the tool loop
        yield {"delta": "reasoned"}

    async def fake_dispatch_stream(messages, provider, **kw):
        if "validation agent" in messages[0]["content"]:
            raise RuntimeError("m at http://gw/v1 is being rate limited by its provider (HTTP 429). Try again in a moment.")
        yield "the synthesis"

    monkeypatch.setattr(heavy_mod, "stream_provider_events", fake_events)
    monkeypatch.setattr(heavy_mod, "dispatch_stream", fake_dispatch_stream)
    reg = tools_mod.RequestTools(tools_mod.ToolRegistry(servers=[]))
    events = [e async for e in heavy_mod.stream_heavy("explain monads", "local", research=False, registry=reg)]
    kinds = [e["type"] for e in events]
    assert "error" not in kinds and kinds[-1] == "done"
    notice = next(e for e in events if e["type"] == "notice")
    assert "validator could not run" in notice["text"] and "rate limited" in notice["text"]
    verdict = next(e for e in events if e["type"] == "verdict")
    assert verdict["verdict"] == "reviewed" and verdict["note"].startswith("Not validated")
    assert verdict["detail"]["limitations"] == notice["text"]
    assert next(e for e in events if e["type"] == "final")["content"] == "the synthesis"


@pytest.mark.asyncio
async def test_heavy_reasons_directly_when_the_research_agent_cannot_run(monkeypatch):
    async def fake_events(messages, provider, **kw):
        if "research agent" in messages[0]["content"]:
            raise RuntimeError("m at http://gw/v1 is overloaded or restarting (HTTP 503). Try again in a moment.")
        yield {"delta": "reasoned directly"}

    async def fake_dispatch_stream(messages, provider, **kw):
        yield ('{"verdict": "validated", "issues": [], "method": "model review", "limitations": ""}'
               if "validation agent" in messages[0]["content"] else "the synthesis")

    monkeypatch.setattr(heavy_mod, "stream_provider_events", fake_events)
    monkeypatch.setattr(heavy_mod, "dispatch_stream", fake_dispatch_stream)
    reg = tools_mod.RequestTools(tools_mod.ToolRegistry(servers=[]))
    events = [e async for e in heavy_mod.stream_heavy("explain monads", "local", research=True, registry=reg)]
    assert [e["step"] for e in events if e["type"] == "step_start"] == ["research", "reasoning", "synthesis", "validation"]
    assert any(e["type"] == "notice" and "research agent could not run" in e["text"] for e in events)
    assert "".join(e["content"] for e in events if e["type"] == "token" and e.get("step") == "reasoning") == "reasoned directly"
    assert next(e for e in events if e["type"] == "verdict")["verdict"] == "validated"
    assert next(e for e in events if e["type"] == "final")["content"] == "the synthesis"


def test_standard_expert_effort_keeps_the_reasoning_visible():
    standard = policies.effort_for("think", 3)
    assert standard.level == "standard" and standard.analyze is True and standard.plan is False
    assert policies.effort_for("think", 7).analyze is True
    assert policies.effort_for("think", 1, trivial=True).analyze is False
    assert "analyze" in standard.as_dict()


@pytest.mark.asyncio
async def test_expert_at_standard_effort_analyzes_then_answers_from_the_analysis(monkeypatch):
    prompts = []

    async def fake_dispatch_stream(messages, provider, **kw):
        prompts.append(messages[-1]["content"])
        yield "the analysis"

    async def fake_dispatch(messages, provider, **kw):              # the non-streaming path: analyze, then solve
        prompts.append(messages[-1]["content"])
        text = "the answer" if "Final answer:" in messages[-1]["content"] else "the analysis"
        return {"provider": "local", "model": "m", "choices": [{"message": {"role": "assistant", "content": text}}]}

    async def fake_events(messages, provider, **kw):
        prompts.append(messages[-1]["content"])
        yield {"delta": "the answer"}

    monkeypatch.setattr(thinking, "dispatch_stream", fake_dispatch_stream)
    monkeypatch.setattr(thinking, "dispatch", fake_dispatch)
    monkeypatch.setattr(thinking, "stream_provider_events", fake_events)
    reg = tools_mod.RequestTools(tools_mod.ToolRegistry(servers=[]))

    events = [e async for e in thinking.stream_think("why is the sky blue?", "local", plan=False, analyze=True, registry=reg)]
    assert [(e["step"], e["role"]) for e in events if e["type"] == "step_start"] == [("analyze", "work"), ("solve", "answer")]
    assert "the analysis" in prompts[1] and "do not repeat the analysis" in prompts[1]
    assert next(e for e in events if e["type"] == "final")["content"] == "the answer"

    prompts.clear()
    out = await thinking.think("why is the sky blue?", "local", plan=False, analyze=True, registry=reg)
    assert out["steps"]["analysis"] == "the analysis" and "plan" not in out["steps"]
    assert out["final_answer"] == "the answer" and len(prompts) == 2


# ── the queue and the usage meter ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_queue_serves_a_person_before_background_work():
    gate = providers._PriorityGate(capacity=1)
    await gate.acquire(providers.INTERACTIVE)                 # the endpoint is busy
    order = []

    async def wait_for(priority, name):
        await gate.acquire(priority)
        order.append(name)
        gate.release()

    background = asyncio.ensure_future(wait_for(providers.BACKGROUND, "deep research"))
    await asyncio.sleep(0)
    person = asyncio.ensure_future(wait_for(providers.INTERACTIVE, "chat"))
    await asyncio.sleep(0)
    assert gate.waiting() == 2
    gate.release()
    await asyncio.gather(background, person)
    assert order == ["chat", "deep research"]                 # queued later, served first
    assert gate.inflight == 0 and gate.waiting() == 0


@pytest.mark.asyncio
async def test_a_cancelled_waiter_leaves_the_queue():
    gate = providers._PriorityGate(capacity=1)
    await gate.acquire(providers.INTERACTIVE)
    waiter = asyncio.ensure_future(gate.acquire(providers.INTERACTIVE))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    gate.release()
    assert gate.inflight == 0 and gate.waiting() == 0


@pytest.mark.asyncio
async def test_the_meter_learns_the_endpoints_limit_and_keeps_under_it():
    pacer = providers._EndpointPacer(max_inflight=4, min_interval=0.0, max_interval=0.0, window=0.3)
    for _ in range(3):                                        # three calls go through…
        async with pacer.slot(GW):
            pass
        pacer.reward(GW)
    pacer.penalize(GW)                                        # …the fourth is rate limited
    assert pacer.cap(GW) == 3
    started = time.monotonic()
    async with pacer.slot(GW):                                # waits one learned interval (window / cap)
        pass
    assert time.monotonic() - started >= 0.08
    usage = pacer.usage()[0]
    assert usage["endpoint"] == GW and usage["cap_per_window"] == 3 and usage["window_s"] == 0.3
    assert usage["rate_limited_in_window"] == 1 and usage["totals"] == {"requests": 4, "ok": 3, "rate_limited": 1}
    pacer.penalize(GW)                                        # limited again under the cap: lower it
    assert pacer.cap(GW) == 2


@pytest.mark.asyncio
async def test_the_learned_cap_grows_back_after_quiet_windows(monkeypatch):
    pacer = providers._EndpointPacer(max_inflight=2, min_interval=0.0, max_interval=0.0, window=0.05)
    pacer.reward(GW)
    pacer.penalize(GW)
    assert pacer.cap(GW) == 1
    await asyncio.sleep(0.2)                                  # more than three windows without a limit
    pacer.reward(GW)
    assert pacer.cap(GW) == 2


@pytest.mark.asyncio
async def test_a_person_waits_up_to_the_budget_then_gets_a_clear_message(monkeypatch):
    monkeypatch.setattr(providers, "EXPERT_PROVIDER_WAIT_S", 0.5)
    monkeypatch.setattr(providers, "_backoff_s", lambda attempt, retry_after: 1.0)
    err = providers._RateLimited("raw upstream text")
    with pytest.raises(providers._RateLimited) as excinfo:
        providers._next_retry(err, 0, time.monotonic(), GW, "openwebui/internal-gemma4-31b")
    msg = str(excinfo.value)
    assert msg.startswith("The model provider for internal-gemma4-31b is busy right now (rate limited).")
    assert "try again in a minute" in msg and "raw upstream" not in msg


@pytest.mark.asyncio
async def test_background_work_may_wait_longer(monkeypatch):
    monkeypatch.setattr(providers, "EXPERT_PROVIDER_WAIT_S", 0.5)
    monkeypatch.setattr(providers, "EXPERT_PROVIDER_BACKGROUND_WAIT_S", 60.0)

    async def job():
        providers.mark_background()
        return providers._wait_budget()

    assert await asyncio.ensure_future(job()) == 60.0
    assert providers._wait_budget() == 0.5                    # the caller's own context is untouched


def test_error_messages_are_found_however_they_are_nested():
    assert providers._message_in({"detail": {"error": {"message": "inner"}}}) == "inner"
    assert providers._message_in({"error": "flat"}) == "flat"
    assert providers._detail_text('{"detail": {"error": {"message": "x", "code": "rate_limited"}}}') == "x"


@pytest.mark.asyncio
async def test_the_usage_route_reports_the_meter():
    routes = importlib.import_module("app.expert.routes")
    out = await routes.expert_usage()
    assert isinstance(out["endpoints"], list)
    assert set(out["policy"]) == {"max_in_flight", "interactive_wait_s", "background_wait_s"}


@pytest.mark.asyncio
async def test_a_rate_limit_without_any_success_learns_no_cap():
    """A 429 before any call of ours went through says nothing about the limit's size (another
    client may have used it up): no cap, so the next try is not held back a whole window."""
    pacer = providers._EndpointPacer(max_inflight=2, min_interval=0.0, max_interval=0.0, window=60.0)
    async with pacer.slot(GW):
        pass
    pacer.penalize(GW)
    assert pacer.cap(GW) is None
    started = time.monotonic()
    async with pacer.slot(GW):
        pass
    assert time.monotonic() - started < 0.5


@pytest.mark.asyncio
async def test_the_bucket_spreads_starts_at_the_learned_rate():
    pacer = providers._EndpointPacer(max_inflight=4, min_interval=0.0, max_interval=0.0, window=0.4)
    for _ in range(2):
        async with pacer.slot(GW):
            pass
        pacer.reward(GW)
    pacer.penalize(GW)                                        # cap 2 per 0.4 s: one start every 0.2 s
    stamps = []

    async def go():
        async with pacer.slot(GW):
            stamps.append(time.monotonic())

    await asyncio.gather(go(), go(), go())
    stamps.sort()
    assert all(b - a >= 0.17 for a, b in zip(stamps, stamps[1:]))


def test_exit_status_4_with_tools_is_a_local_incompatibility_and_nothing_else():
    """qwen2.5:0.5b on CPU Ollama dies with exit status 4 when the request includes tools.
    That retries once without tools. A memory error, and the same crash with no tools sent,
    stay real failures."""
    crash = "llama runner process has terminated: exit status 4"
    assert isinstance(_err(500, crash, tools=True), providers.ToolsUnsupported)
    assert isinstance(_err(500, "4", tools=True), providers.ToolsUnsupported)
    assert isinstance(_err(200, '{"error": "4"}', tools=True), providers.ToolsUnsupported)
    bare = _err(500, crash, tools=False)
    assert type(bare) is RuntimeError and not isinstance(bare, providers.ToolsUnsupported)
    memory = _err(500, "model requires more system memory", tools=True)
    assert type(memory) is RuntimeError and not isinstance(memory, providers.ToolsUnsupported)
    assert providers.local_tool_crash_exception(RuntimeError("4"))
    assert not providers.local_tool_crash_exception(RuntimeError("model requires more system memory"))


def test_a_local_model_without_tools_behind_ollabridge_reads_as_no_tools():
    """llama3:8b through OllaBridge: Ollama answers 400 "does not support tools", an older
    OllaBridge wraps it in a 500. With tools, that is "no tools here" (retry without them);
    without tools it is a real error, not a rate limit to wait out."""
    wrapped = "Client error '400 Bad Request' for url 'http://localhost:11434/api/chat'"
    assert isinstance(_err(500, wrapped, tools=True), providers.ToolsUnsupported)
    assert type(_err(500, wrapped, tools=False)) is RuntimeError
    # The current OllaBridge says it plainly.
    assert isinstance(_err(400, "llama3:8b does not support tools on local Ollama", tools=True), providers.ToolsUnsupported)


def test_an_ollama_target_with_an_openai_base_url_is_openai_compatible():
    target_mod = importlib.import_module("app.expert.target")
    t = target_mod.from_request({"provider": "ollama", "base_url": "http://localhost:11435/v1/", "model": "openwebui/internal-gemma4-31b"})
    assert t.provider == "openai_compat" and t.base_url == "http://localhost:11435/v1" and not t.is_ollama
    local = target_mod.from_request({"provider": "ollama", "base_url": "http://localhost:11434", "model": "llama3:8b"})
    assert local.provider == "ollama" and local.is_ollama


class _LocalResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _local_client(resp):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return resp

    return _Client


@pytest.mark.asyncio
async def test_chat_local_classifies_exit_status_4_only_when_tools_were_sent(monkeypatch):
    async def resolve(name):
        return name or "qwen2.5:0.5b"

    monkeypatch.setattr(providers, "_resolve_local_model", resolve)
    crash = {"error": "llama runner process has terminated: exit status 4"}
    monkeypatch.setattr(providers.httpx, "AsyncClient", _local_client(_LocalResp(500, crash)))
    with pytest.raises(providers.ToolsUnsupported):
        await providers.chat_local([{"role": "user", "content": "hello"}], model="qwen2.5:0.5b", tools=TOOLS)

    monkeypatch.setattr(providers.httpx, "AsyncClient", _local_client(_LocalResp(500, crash)))
    with pytest.raises(RuntimeError, match="exit status 4") as bare:
        await providers.chat_local([{"role": "user", "content": "hello"}], model="qwen2.5:0.5b")
    assert not isinstance(bare.value, providers.ToolsUnsupported)

    monkeypatch.setattr(
        providers.httpx, "AsyncClient",
        _local_client(_LocalResp(500, {"error": "model requires more system memory"})),
    )
    with pytest.raises(RuntimeError, match="system memory") as memory:
        await providers.chat_local([{"role": "user", "content": "hello"}], model="qwen2.5:0.5b", tools=TOOLS)
    assert not isinstance(memory.value, providers.ToolsUnsupported)

    monkeypatch.setattr(providers.httpx, "AsyncClient", _local_client(_LocalResp(200, {"error": "4"})))
    with pytest.raises(providers.ToolsUnsupported):
        await providers.chat_local([{"role": "user", "content": "hello"}], model="qwen2.5:0.5b", tools=TOOLS)
