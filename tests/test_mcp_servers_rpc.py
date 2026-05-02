from fastapi.testclient import TestClient

from agentic.integrations.mcp.archive_workspace.app import app as archive_app
from agentic.integrations.mcp.citation_provenance.app import app as citation_app
from agentic.integrations.mcp.code_sandbox.app import app as sandbox_app
from agentic.integrations.mcp.cost_router.app import app as cost_app
from agentic.integrations.mcp.doc_retrieval.app import app as doc_app
from agentic.integrations.mcp.eval_runner.app import app as eval_app
from agentic.integrations.mcp.job_orchestrator.app import app as jobs_app
from agentic.integrations.mcp.memory_store.app import app as memory_app
from agentic.integrations.mcp.observability.app import app as obs_app
from agentic.integrations.mcp.safety_policy.app import app as safety_app
from agentic.integrations.mcp.web_search.app import app as web_app


def _rpc(client: TestClient, method: str, params: dict | None = None):
    return client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": "1", "method": method, "params": params or {}},
    )


def _assert_tools(client: TestClient, expected_tool: str):
    res = _rpc(client, "tools/list")
    assert res.status_code == 200
    names = [t["name"] for t in res.json()["result"]["tools"]]
    assert expected_tool in names


def test_new_mcp_servers_have_tools_and_calls_work():
    cases = [
        (web_app, "hp.web.search", {"name": "hp.web.search", "arguments": {"query": "python"}}),
        (doc_app, "hp.doc.query", {"name": "hp.doc.query", "arguments": {"text": "python"}}),
        (sandbox_app, "hp.code.run", {"name": "hp.code.run", "arguments": {"code": "print('ok')"}}),
        (citation_app, "hp.citation.verify", {"name": "hp.citation.verify", "arguments": {"response_text": "hello [1]"}}),
        (memory_app, "hp.memory.append", {"name": "hp.memory.append", "arguments": {"value": "remember this"}}),
        (safety_app, "hp.safety.check_output", {"name": "hp.safety.check_output", "arguments": {"text": "safe answer"}}),
        (obs_app, "hp.obs.emit_event", {"name": "hp.obs.emit_event", "arguments": {"event": "turn.completed"}}),
        (eval_app, "hp.eval.run_suite", {"name": "hp.eval.run_suite", "arguments": {"cases": [{"expected": 1, "actual": 1}]}}),
        (cost_app, "hp.cost.recommend_route", {"name": "hp.cost.recommend_route", "arguments": {"quality": "high", "budget_left": 2}}),
        (jobs_app, "hp.jobs.submit", {"name": "hp.jobs.submit", "arguments": {"task": "index", "payload": {"a": 1}}}),
        (archive_app, "hp.ws.search", {"name": "hp.ws.search", "arguments": {"workspace_id": "w1", "query": "x"}}),
    ]

    for app, expected_tool, tool_call in cases:
        client = TestClient(app)
        _assert_tools(client, expected_tool)
        res = _rpc(client, "tools/call", tool_call)
        assert res.status_code == 200
        payload = res.json()
        assert "result" in payload
        assert "content" in payload["result"]
