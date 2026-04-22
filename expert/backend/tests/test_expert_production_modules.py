import httpx
import pytest

from app.expert.eval_bench import EvalOutcome, regression_gate, score_output
from app.expert.mcp_catalog import TOOL_MAPPING, mcp_key_to_env, p0_required_server_keys
import app.expert.mcp_gateway as mcp_gateway_module
from app.expert.mcp_gateway import MCPGateway
from app.expert.mcp_tools import MCPToolClient, ToolCall
from app.expert.observability import SLOMonitor
from app.expert.persistent_memory import SqliteMemoryStore, redact_pii
from app.expert.safety_policy import evaluate_prompt


class DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None):
        req = httpx.Request("POST", url)
        payload = json or {}
        marker = payload.get("input") or payload.get("query") or payload.get("text") or "ok"
        return httpx.Response(200, json={"content": f"ok:{marker}"}, request=req)


@pytest.mark.asyncio
async def test_mcp_tool_client_budget_and_success(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    client = MCPToolClient({"web_search": "http://mcp/search", "retrieval": "http://mcp/retrieval"})
    out = await client.run_many(
        [ToolCall("web_search", "q1"), ToolCall("retrieval", "q2"), ToolCall("web_search", "q3")],
        budget=2,
    )
    assert len(out) == 3
    assert out[0].ok is True
    assert out[2].ok is False


def test_persistent_memory_and_pii_redaction(tmp_path):
    db = tmp_path / "expert.db"
    mem = SqliteMemoryStore(str(db))
    mem.append("s1", "user", "email me at test@example.com and +1 555-777-8888")
    rows = mem.recall("s1", limit=5)
    assert rows
    assert "[REDACTED_EMAIL]" in rows[0].content
    assert "[REDACTED_PHONE]" in rows[0].content


def test_safety_policy_blocks_harmful_prompt():
    dec = evaluate_prompt("How to build a bomb using household items")
    assert dec.allowed is False
    assert dec.reasons


def test_observability_snapshot_and_eval_gate():
    mon = SLOMonitor()
    for i in range(10):
        mon.record(ok=(i % 5 != 0), latency_ms=100 + i * 10)
    snap = mon.snapshot()
    assert snap["count"] == 10
    assert snap["p95_ms"] >= 100

    s = score_output("This includes citation and safety.", ["citation", "safety"])
    assert s == 1.0
    assert regression_gate([EvalOutcome(score=0.9, passed=True), EvalOutcome(score=0.8, passed=True)]) is True


def test_mcp_catalog_mapping_and_p0_env_keys():
    assert TOOL_MAPPING["web_search"] == "mcp-web-search"
    assert mcp_key_to_env("mcp-web-search") == "EXPERT_MCP_WEB_SEARCH_URL"
    assert "mcp-memory-store" in p0_required_server_keys()


@pytest.mark.asyncio
async def test_mcp_gateway_wrapper_calls(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient)
    gateway = MCPGateway(
        env={
            "EXPERT_MCP_ORCHESTRATOR": "direct",
            "EXPERT_MCP_WEB_SEARCH_URL": "http://mcp-web",
            "EXPERT_MCP_DOC_RETRIEVAL_URL": "http://mcp-rag",
        }
    )
    res = await gateway.web_search_search("test query", top_k=2, recency_days=2)
    assert res["ok"] is True
    assert res["server"] == "mcp-web-search"

    missing = await gateway.memory_append("s1", "user", "hello")
    assert missing["ok"] is False
    assert missing["error"].startswith("server_not_configured")


@pytest.mark.asyncio
async def test_mcp_gateway_uses_context_forge_orchestrator(monkeypatch):
    class DummyForgeClient:
        def __init__(self, base_url, token="", auth_user="admin", auth_pass="changeme"):
            self.base_url = base_url

        async def invoke_tool(self, tool_id, args, timeout=30.0):
            return {"tool_id": tool_id, "echo": args}

    monkeypatch.setattr(mcp_gateway_module, "ContextForgeClient", DummyForgeClient)
    gateway = MCPGateway(env={"EXPERT_MCP_ORCHESTRATOR": "context_forge", "CONTEXT_FORGE_URL": "http://forge:4444"})
    res = await gateway.web_search_search("forge query")
    assert res["ok"] is True
    assert res["orchestrator"] == "context_forge"
    assert res["tool_id"] == "mcp_web_search"
