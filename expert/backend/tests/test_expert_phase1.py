"""Phase 1 — reliability and honesty: project context, adaptive effort, the structured
verdict, durable capability facts and probes, durable Deep research jobs."""
import asyncio
import importlib
import json

import pytest

policies = importlib.import_module("app.expert.policies")
project_context = importlib.import_module("app.expert.project_context")
tools_mod = importlib.import_module("app.expert.tools")
tool_loop = importlib.import_module("app.expert.tool_loop")
thinking = importlib.import_module("app.expert.thinking")
heavy_mod = importlib.import_module("app.expert.heavy")
capability = importlib.import_module("app.expert.capability")
state_store = importlib.import_module("app.expert.state_store")
deep = importlib.import_module("app.expert.deep")
routes = importlib.import_module("app.expert.routes")
schemas = importlib.import_module("app.expert.schemas")
providers = importlib.import_module("app.expert.providers")
target_mod = importlib.import_module("app.expert.target")


def _reply(text="ok", tool_calls=None):
    msg = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"provider": "local", "model": "m", "choices": [{"message": msg}]}


# ── 2. adaptive effort ───────────────────────────────────────────────────────

def test_effort_profiles_scale_with_the_request():
    assert policies.is_trivial("hello") and policies.is_trivial("ok thanks") and not policies.is_trivial("why is the sky blue?")
    fast = policies.effort_for("fast", 9)
    assert fast.level == "direct" and fast.tool_rounds == 2
    assert policies.effort_for("think", 2, trivial=True).level == "direct"
    standard = policies.effort_for("think", 3)
    assert standard.level == "standard" and standard.plan is False
    full = policies.effort_for("think", 7)
    assert full.level == "full" and full.plan is True and full.temperature < fast.temperature
    assert policies.effort_for("heavy", 1, trivial=True).level == "direct"
    light = policies.effort_for("heavy", 3)
    assert light.level == "standard" and light.research is False
    assert policies.effort_for("heavy", 3, forced_tools=True).research is True
    assert policies.effort_for("heavy", 8).research is True


@pytest.mark.asyncio
async def test_think_without_a_plan_is_one_generation(monkeypatch):
    calls = []

    async def fake_dispatch(messages, provider, **kw):
        calls.append(messages[-1]["content"])
        return _reply("answer")

    async def fake_events(messages, provider, **kw):
        calls.append(messages[-1]["content"])
        yield {"delta": "answer"}

    monkeypatch.setattr(thinking, "dispatch", fake_dispatch)
    monkeypatch.setattr(thinking, "stream_provider_events", fake_events)
    out = await thinking.think("what is 2+2?", "local", plan=False, registry=tools_mod.RequestTools(tools_mod.ToolRegistry(servers=[])))
    assert out["final_answer"] == "answer" and out["planned"] is False
    assert len(calls) == 1 and "Problem: what is 2+2?" in calls[0]
    assert "analysis" not in out["steps"]
    events = [e async for e in thinking.stream_think("what is 2+2?", "local", plan=False,
                                                     registry=tools_mod.RequestTools(tools_mod.ToolRegistry(servers=[])))]
    assert [e["step"] for e in events if e["type"] == "step_start"] == ["solve"]
    assert events[[e["type"] for e in events].index("step_start")]["label"] == "⚡ Answering…"


@pytest.mark.asyncio
async def test_heavy_without_research_gives_the_reasoner_the_tools(monkeypatch):
    seen = []

    async def fake_dispatch(messages, provider, **kw):
        seen.append((messages[0]["content"][:40], kw.get("tools")))
        return _reply('{"verdict": "validated", "issues": [], "method": "model review", "limitations": ""}'
                      if "validation agent" in messages[0]["content"] else "text")

    monkeypatch.setattr(heavy_mod, "dispatch", fake_dispatch)
    reg = tools_mod.RequestTools(tools_mod.ToolRegistry(servers=[]))
    out = await heavy_mod.heavy("explain monads", "local", research=False, registry=reg)
    assert out["researched"] is False and "research" not in out["agents"]
    assert [s[0][:12] for s in seen] == ["You are a lo", "You are a sy", "You are a va"]   # reason, synth, validate
    assert out["verdict"] == "validated" and out["verdict_detail"]["structured"] is True


def test_verdict_detail_reads_json_and_detects_disagreement():
    ok = heavy_mod.verdict_detail('{"verdict":"validated","issues":[],"method":"model review","limitations":"none"}', "A")
    assert (ok["verdict"], ok["final_answer"], ok["structured"]) == ("validated", "A", True)
    fixed = heavy_mod.verdict_detail(
        'Sure: {"verdict":"corrected","issues":[{"severity":"high","text":"17*24 is 408"}],"corrected_answer":"408","method":"calculation"}', "480")
    assert (fixed["verdict"], fixed["final_answer"], fixed["method"]) == ("corrected", "408", "calculation")
    assert fixed["issues"][0]["severity"] == "high"
    doubt = heavy_mod.verdict_detail('{"verdict":"corrected","issues":["unsure about the date"],"corrected_answer":null}', "A")
    assert doubt["verdict"] == "needs_review" and doubt["final_answer"] == "A"
    disagree = heavy_mod.verdict_detail('{"verdict":"validated","issues":[{"severity":"high","text":"the sum is wrong"}]}', "A")
    assert disagree["verdict"] == "needs_review"
    legacy = heavy_mod.verdict_detail("VALIDATED. Looks right.", "A")
    assert legacy["verdict"] == "validated" and legacy["structured"] is False
    assert heavy_mod.verdict_of("CORRECTION: B", "A")[:2] == ("corrected", "B")


# ── 1. project context ───────────────────────────────────────────────────────

def test_project_system_prompt_folds_in_instructions():
    prompt = project_context.project_system_prompt(None, {"id": "p1", "name": "Launch", "instructions": "Be terse.", "document_count": 2})
    assert "project “Launch”" in prompt and "Be terse." in prompt and "project_search" in prompt
    assert project_context.project_system_prompt("BASE", None) == "BASE"
    assert project_context.project_system_prompt("BASE", {"id": "p1"}) == "BASE"


@pytest.mark.asyncio
async def test_project_tool_searches_the_documents_through_the_backend_retrieval(monkeypatch):
    def fake_retrieval(project_id, query, n_results):
        assert project_id == "p1" and n_results == 5
        return [
            {"content": "Ship on Friday.", "metadata": {"source": "plan.md"}},
            {"content": "Budget is 10k.", "metadata": {"source": "plan.md"}},
            {"content": "Ana leads QA.", "metadata": {"source": "team.txt"}},
        ]

    tool = project_context.project_tool({"id": "p1", "name": "Launch", "document_count": 2}, retrieval=fake_retrieval)
    assert tool is not None and tool.spec.name == "project_search"
    assert project_context.project_tool({"id": "p1", "document_count": 0}, retrieval=fake_retrieval) is None
    reg = tools_mod.RequestTools(tools_mod.ToolRegistry(servers=[]), [tool])
    assert [t["function"]["name"] for t in await reg.openai_tools()] == ["project_search"]
    out = await reg.call("project_search", {"query": "when do we ship"})
    assert out.ok and "[Document 1: plan.md]" in out.text and "Ana leads QA." in out.text
    assert out.data["documents"] == ["plan.md", "team.txt"]
    assert tools_mod.label_for("hp.project.search", {"query": "ship"}) == "Searching the project’s documents for “ship”".replace("’", "'")


@pytest.mark.asyncio
async def test_routes_force_the_project_search_first_and_fold_the_instructions(monkeypatch):
    sent = []

    async def fake_dispatch(messages, provider, **kw):
        sent.append(messages)
        return _reply("From plan.md: Friday.")

    def fake_retrieval(project_id, query, n_results):
        return [{"content": "Ship on Friday.", "metadata": {"source": "plan.md"}}]

    monkeypatch.setattr(routes, "dispatch", fake_dispatch)
    monkeypatch.setattr(project_context, "_retrieval", lambda: fake_retrieval)
    monkeypatch.setattr(routes, "select_provider", lambda *a, **k: "local")
    req = schemas.ExpertChatRequest(
        query="When do we ship?", thinking_mode="fast",
        project={"id": "p1", "name": "Launch", "instructions": "Answer in one line.", "document_count": 1},
    )
    out = await routes.expert_chat(req)
    assert out.content == "From plan.md: Friday."
    system = sent[0][0]["content"]
    assert "project “Launch”" in system and "Answer in one line." in system
    assert sent[0][-1]["role"] == "tool" and "[Document 1: plan.md]" in sent[0][-1]["content"]   # searched first
    assert out.tool_trace[0]["name"] == "project_search" and out.effort["level"] == "direct"


@pytest.mark.asyncio
async def test_a_greeting_in_heavy_is_one_generation(monkeypatch):
    calls = []

    async def fake_dispatch(messages, provider, **kw):
        calls.append(messages)
        return _reply("Hello!")

    async def no_escalation(*a, **k):
        raise AssertionError("escalation must not run for a direct answer")

    monkeypatch.setattr(routes, "dispatch", fake_dispatch)
    monkeypatch.setattr(routes, "select_provider", lambda *a, **k: "local")
    monkeypatch.setattr(capability, "assess", no_escalation)
    out = await routes.expert_chat(schemas.ExpertChatRequest(query="hello", thinking_mode="heavy"))
    assert out.content == "Hello!" and len(calls) == 1
    assert out.thinking_mode_used == "heavy" and out.strategy_used == "direct" and out.effort["level"] == "direct"


# ── 4. durable capabilities ──────────────────────────────────────────────────

def test_state_store_kv_expires_and_survives_a_warm_cache_reset(tmp_path):
    state_store.kv_set("k", {"a": 1}, ttl_s=60)
    assert state_store.kv_get("k") == {"a": 1}
    state_store.kv_set("old", {"a": 1}, ttl_s=-1)
    assert state_store.kv_get("old") is None
    key = tool_loop.capability_key(target_mod.ChatTarget(provider="openai_compat", base_url="http://gw/v1", model="m"), "local", None)
    tool_loop.remember_tools(key, False)
    tool_loop._TOOL_FACTS.clear()
    assert tool_loop.tools_known(key) is False
    tool_loop.forget_tools(key)
    assert tool_loop.tools_known(key) is None


@pytest.mark.asyncio
async def test_probe_measures_tool_calling_once_and_gates_deep_research(monkeypatch):
    seen = {"n": 0}

    async def fake_dispatch(messages, provider, **kw):
        seen["n"] += 1
        if kw.get("tools"):
            return _reply("", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "ping", "arguments": '{"word":"pong"}'}}])
        return _reply('{"ok": true}')

    router_mod = importlib.import_module("app.expert.router")       # the module, not the APIRouter attribute
    monkeypatch.setattr(router_mod, "dispatch", fake_dispatch)
    gw = target_mod.ChatTarget(provider="openai_compat", base_url="http://gw/v1", model="openwebui/internal-gemma4-31b")
    found = await capability.probe(gw, gw.model)
    assert (found["tools"], found["json"]) == ("yes", "yes")
    again = await capability.probe(gw, gw.model)
    assert again == found and seen["n"] == 2                                  # cached: no new requests
    assert tool_loop.tools_known(tool_loop.capability_key(gw, "local", None)) is True

    async def refusing(messages, provider, **kw):
        if kw.get("tools"):
            raise providers.ToolsUnsupported("no")
        return _reply("plain")

    monkeypatch.setattr(router_mod, "dispatch", refusing)
    other = target_mod.ChatTarget(provider="openai_compat", base_url="http://gw/v1", model="openwebui/ext-claude-lite")
    found = await capability.probe(other, other.model)
    assert found["tools"] == "no"

    async def fake_models(base_url, api_key=""):
        return ["openwebui/ext-claude-lite"]

    monkeypatch.setattr(providers, "openai_compat_models", fake_models)
    capability.reset_cache()
    caps = await capability.assess(other, other.model)
    assert caps["verified"]["tools"] == "no" and caps["deep_research"]["enabled"] is True   # the harness searches for it
    assert "runs the searches" in caps["deep_research"]["reason"]


@pytest.mark.asyncio
async def test_assisted_search_grounds_a_model_that_cannot_call_tools(monkeypatch):
    """Heavy's research and Deep research stay grounded on a model that rejects tools: HomePilot
    runs the web search and hands the results over as plain turns."""
    seen = []

    async def refusing_then_answer(messages, provider, *, tools=None, **kw):
        seen.append((list(messages), tools))
        if tools:
            raise providers.ToolsUnsupported("no tools here")
        return _reply("Grounded answer [1].")

    async def fake_rpc(url, method, params, timeout_s):
        if method == "tools/list":
            return {"tools": [{"name": "hp.web.search", "description": "web", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}}]}
        return {"content": [{"type": "text", "text": "r"}], "structuredContent": {"results": [{"title": "T", "url": "https://t.test/a", "snippet": "s"}]}}

    monkeypatch.setattr(tools_mod, "rpc", fake_rpc)
    reg = tools_mod.ToolRegistry(servers=["http://fake/rpc"], allow="hp.web.search")
    out = await tool_loop.run_with_tools([{"role": "system", "content": "s"}, {"role": "user", "content": "q"}], "local",
                                         registry=reg, call=refusing_then_answer, assist=[("hp_web_search", {"query": "q"})])
    assert out["content"] == "Grounded answer [1]." and out["sources"][0]["url"] == "https://t.test/a"
    assert seen[0][1] is not None and seen[1][1] is None                       # tools offered once, then not
    plain = seen[1][0]
    assert all(m["role"] != "tool" for m in plain) and any("Results from hp web search" in m["content"] for m in plain)
    # Next time the fact is known, the assisted search runs before the first request.
    seen.clear()
    out = await tool_loop.run_with_tools([{"role": "user", "content": "q2"}], "local",
                                         registry=reg, call=refusing_then_answer, assist=[("hp_web_search", {"query": "q2"})])
    assert len(seen) == 1 and seen[0][1] is None and out["tool_trace"][0]["name"] == "hp_web_search"


# ── 5. durable Deep research ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deep_job_events_are_numbered_persisted_and_resumable(monkeypatch):
    async def fake_dispatch(messages, provider, **kw):
        return _reply('{"questions": ["What is X?"]}')

    class Writer:
        async def __call__(self, messages, provider, **kw):
            yield {"delta": "Report."}

    class SubAgent:
        async def __call__(self, messages, provider, **kw):
            yield {"delta": "Finding."}

    monkeypatch.setattr(deep, "dispatch", fake_dispatch)
    monkeypatch.setattr(deep, "stream_provider_events", Writer())
    monkeypatch.setattr(tool_loop, "stream_provider_events", SubAgent())
    reg = tools_mod.RequestTools(tools_mod.ToolRegistry(servers=[]))
    job = deep.start("Tell me about X", provider="local", model="big", history=[], chosen=None,
                     timezone=None, context=None, note=None, registry=reg, session_id="conv-1")
    await job.task
    assert job.status == "done"
    seqs = [e["seq"] for e in job.events]
    assert seqs == list(range(1, len(seqs) + 1))                              # numbered, no gaps
    plan_seq = next(e["seq"] for e in job.events if e["type"] == "plan")
    late = job.subscribe(after=plan_seq)
    replayed = [late.get_nowait()["type"] for _ in range(late.qsize())]
    assert "plan" not in replayed and replayed[-1] == "done"                  # only what was missed
    # Gone from memory (a restart): read back from the store with its events.
    deep.JOBS.clear()
    back = deep.get_job(job.id)
    assert back is not None and back.status == "done" and back.report == "Report."
    assert [e["type"] for e in back.events][-1] == "done" and back.seq == len(seqs)
    assert back.snapshot()["session_id"] == "conv-1"
    # A job that was running when the process died is closed as interrupted.
    state_store.job_save("ghost", "researching", {"job_id": "ghost", "query": "q", "status": "researching"}, created=1.0)
    deep._RECOVERED = False
    ghost = deep.get_job("ghost")
    assert ghost.status == "failed" and "Interrupted" in ghost.error
    assert state_store.events_after("ghost", 0)[-1]["type"] == "error"
