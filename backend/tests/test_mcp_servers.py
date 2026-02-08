"""
Mock tests for HomePilot agentic MCP servers and A2A agents.

These tests verify that all MCP servers and A2A agents:
- Are importable and create valid FastAPI apps
- Respond to /health (readiness)
- Support MCP initialize lifecycle (JSON-RPC 2.0)
- Advertise tools via tools/list with valid schemas
- Execute tools via tools/call and return MCP-compatible content
- A2A agents respond to a2a.message with structured output

These tests run WITHOUT a live Context Forge instance — they test the
servers directly via httpx ASGITransport (in-process, no network).

Usage:
    pytest backend/tests/test_mcp_servers.py -v
    make test-mcp-servers
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

# ── Path setup ──────────────────────────────────────────────────────────────
# The agentic/ tree lives at repo root, not inside backend/.
# Servers import "from agentic.integrations.mcp._common.server ..." — meaning
# "agentic" must be a package visible from sys.path.  We add the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Import all server apps ──────────────────────────────────────────────────
from unittest.mock import AsyncMock, patch

from agentic.integrations.mcp.personal_assistant_server import app as personal_assistant_app
from agentic.integrations.mcp.knowledge_server import app as knowledge_app
from agentic.integrations.mcp.decision_copilot_server import app as decision_copilot_app
from agentic.integrations.mcp.executive_briefing_server import app as executive_briefing_app
from agentic.integrations.mcp.web_search_server import app as web_search_app
from agentic.integrations.a2a.everyday_assistant_agent import app as everyday_assistant_app
from agentic.integrations.a2a.chief_of_staff_agent import app as chief_of_staff_app


# ── Helpers ─────────────────────────────────────────────────────────────────

def _rpc(method: str, params: Dict[str, Any] | None = None, req_id: str = "test-1") -> Dict[str, Any]:
    """Build a JSON-RPC 2.0 request body."""
    body: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


async def _post_rpc(app, method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Send a JSON-RPC request to an ASGI app and return the parsed response."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.post("/rpc", json=_rpc(method, params))
        assert r.status_code == 200, f"POST /rpc returned {r.status_code}: {r.text}"
        return r.json()


async def _get_health(app) -> Dict[str, Any]:
    """GET /health on an ASGI app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        return r.json()


# ═══════════════════════════════════════════════════════════════════════════
# MCP SERVER TESTS
# ═══════════════════════════════════════════════════════════════════════════

MCP_SERVERS = [
    ("personal-assistant", personal_assistant_app),
    ("knowledge", knowledge_app),
    ("decision-copilot", decision_copilot_app),
    ("executive-briefing", executive_briefing_app),
    ("web-search", web_search_app),
]


class TestMCPServerHealth:
    """All MCP servers respond to GET /health with {ok: true}."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_health(self, name, app):
        data = await _get_health(app)
        assert data["ok"] is True
        assert "name" in data


class TestMCPInitialize:
    """All MCP servers respond to initialize with protocol info."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_initialize(self, name, app):
        data = await _post_rpc(app, "initialize")
        result = data.get("result", {})
        assert "protocolVersion" in result
        assert "serverInfo" in result
        assert result["capabilities"]["tools"] is True


class TestMCPToolsList:
    """All MCP servers advertise tools via tools/list."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_tools_list_returns_tools(self, name, app):
        data = await _post_rpc(app, "tools/list")
        tools = data["result"]["tools"]
        assert isinstance(tools, list)
        assert len(tools) > 0, f"{name} has no tools"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_tools_have_valid_schema(self, name, app):
        data = await _post_rpc(app, "tools/list")
        tools = data["result"]["tools"]
        for tool in tools:
            assert "name" in tool, f"Tool missing name in {name}"
            assert "description" in tool, f"Tool {tool['name']} missing description"
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"
            schema = tool["inputSchema"]
            assert schema.get("type") == "object", f"Tool {tool['name']} schema type not object"
            assert "properties" in schema, f"Tool {tool['name']} schema missing properties"


class TestMCPToolsCall:
    """All MCP server tools execute successfully with valid args."""

    # ── Personal Assistant ──

    @pytest.mark.asyncio
    async def test_personal_search(self):
        data = await _post_rpc(
            personal_assistant_app,
            "tools/call",
            {"name": "hp.personal.search", "arguments": {"query": "test"}},
        )
        result = data["result"]
        assert "content" in result
        assert any(c["type"] == "text" for c in result["content"])

    @pytest.mark.asyncio
    async def test_personal_plan_day(self):
        data = await _post_rpc(
            personal_assistant_app,
            "tools/call",
            {"name": "hp.personal.plan_day", "arguments": {"title": "Monday"}},
        )
        result = data["result"]
        assert "content" in result

    # ── Knowledge ──

    @pytest.mark.asyncio
    async def test_knowledge_search_workspace(self):
        data = await _post_rpc(
            knowledge_app,
            "tools/call",
            {"name": "hp.search_workspace", "arguments": {"query": "project alpha"}},
        )
        result = data["result"]
        assert "results" in result
        assert isinstance(result["results"], list)

    @pytest.mark.asyncio
    async def test_knowledge_get_document(self):
        data = await _post_rpc(
            knowledge_app,
            "tools/call",
            {"name": "hp.get_document", "arguments": {"doc_id": "doc-42"}},
        )
        result = data["result"]
        assert result["doc_id"] == "doc-42"

    @pytest.mark.asyncio
    async def test_knowledge_answer_with_sources(self):
        data = await _post_rpc(
            knowledge_app,
            "tools/call",
            {"name": "hp.answer_with_sources", "arguments": {"question": "What is the status?"}},
        )
        result = data["result"]
        assert "answer" in result
        assert "sources" in result

    @pytest.mark.asyncio
    async def test_knowledge_summarize_project(self):
        data = await _post_rpc(
            knowledge_app,
            "tools/call",
            {"name": "hp.summarize_project", "arguments": {"project_id": "proj-1"}},
        )
        result = data["result"]
        assert "content" in result

    # ── Decision Copilot ──

    @pytest.mark.asyncio
    async def test_decision_options(self):
        data = await _post_rpc(
            decision_copilot_app,
            "tools/call",
            {"name": "hp.decision.options", "arguments": {"goal": "Reduce costs by 20%"}},
        )
        result = data["result"]
        assert "content" in result
        content_json = result["content"][0]
        assert content_json["type"] == "json"
        assert "options" in content_json["json"]

    @pytest.mark.asyncio
    async def test_decision_risk_assessment(self):
        data = await _post_rpc(
            decision_copilot_app,
            "tools/call",
            {"name": "hp.decision.risk_assessment", "arguments": {"proposal": "Migrate to cloud"}},
        )
        result = data["result"]
        assert "content" in result

    @pytest.mark.asyncio
    async def test_decision_recommend_next(self):
        options = [
            {"title": "Option A (Low risk)"},
            {"title": "Option B (Balanced)"},
        ]
        data = await _post_rpc(
            decision_copilot_app,
            "tools/call",
            {"name": "hp.decision.recommend_next", "arguments": {"options": options}},
        )
        result = data["result"]
        assert "content" in result

    @pytest.mark.asyncio
    async def test_decision_plan_next_steps(self):
        data = await _post_rpc(
            decision_copilot_app,
            "tools/call",
            {"name": "hp.decision.plan_next_steps", "arguments": {"decision": "Go with Option B"}},
        )
        result = data["result"]
        assert "content" in result

    # ── Executive Briefing ──

    @pytest.mark.asyncio
    async def test_brief_daily(self):
        data = await _post_rpc(
            executive_briefing_app,
            "tools/call",
            {"name": "hp.brief.daily", "arguments": {}},
        )
        result = data["result"]
        assert "content" in result
        assert any(c["type"] == "text" for c in result["content"])

    @pytest.mark.asyncio
    async def test_brief_weekly(self):
        data = await _post_rpc(
            executive_briefing_app,
            "tools/call",
            {"name": "hp.brief.weekly", "arguments": {"audience": "executive"}},
        )
        result = data["result"]
        assert "content" in result

    @pytest.mark.asyncio
    async def test_brief_what_changed_since(self):
        data = await _post_rpc(
            executive_briefing_app,
            "tools/call",
            {"name": "hp.brief.what_changed_since", "arguments": {"since": "2025-01-01T00:00:00Z"}},
        )
        result = data["result"]
        assert "content" in result

    @pytest.mark.asyncio
    async def test_brief_digest(self):
        data = await _post_rpc(
            executive_briefing_app,
            "tools/call",
            {"name": "hp.brief.digest", "arguments": {"items": ["Item 1", "Item 2"]}},
        )
        result = data["result"]
        assert "content" in result


class TestMCPUnknownTool:
    """Calling an unknown tool returns a JSON-RPC error."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_unknown_tool_returns_error(self, name, app):
        data = await _post_rpc(
            app,
            "tools/call",
            {"name": "nonexistent.tool", "arguments": {}},
        )
        assert "error" in data
        assert data["error"]["code"] == -32601


class TestMCPUnknownMethod:
    """Calling an unknown JSON-RPC method returns an error."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_unknown_method(self, name, app):
        data = await _post_rpc(app, "nonexistent/method")
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════
# WEB SEARCH MCP — SearXNG PROVIDER (MOCKED, NO API KEY)
# ═══════════════════════════════════════════════════════════════════════════

# Fake SearXNG JSON response used to mock httpx calls.
_FAKE_SEARXNG_RESPONSE = {
    "results": [
        {
            "title": "Example Result",
            "url": "https://example.com/article",
            "content": "This is a snippet from the search result.",
        },
        {
            "title": "Another Result",
            "url": "https://example.com/page2",
            "content": "Another snippet.",
        },
    ]
}


class TestWebSearchSearXNG:
    """Web-search MCP tool tests with a mocked SearXNG backend."""

    @pytest.mark.asyncio
    async def test_web_search_returns_results(self):
        """hp.web.search returns markdown-formatted results via SearXNG."""
        from agentic.integrations.mcp.web_search.providers import SearchResult

        fake_results = [
            SearchResult(
                title="Example Result",
                url="https://example.com/article",
                snippet="This is a snippet from the search result.",
                source="searxng",
            ),
            SearchResult(
                title="Another Result",
                url="https://example.com/page2",
                snippet="Another snippet.",
                source="searxng",
            ),
        ]

        with patch(
            "agentic.integrations.mcp.web_search_server.get_provider"
        ) as mock_get_provider:
            mock_provider = AsyncMock()
            mock_provider.search.return_value = fake_results
            mock_get_provider.return_value = mock_provider

            data = await _post_rpc(
                web_search_app,
                "tools/call",
                {"name": "hp.web.search", "arguments": {"query": "test search"}},
            )

        result = data["result"]
        assert "content" in result
        text = result["content"][0]["text"]
        assert "Example Result" in text
        assert "https://example.com/article" in text

    @pytest.mark.asyncio
    async def test_web_search_empty_query(self):
        """hp.web.search rejects empty queries."""
        data = await _post_rpc(
            web_search_app,
            "tools/call",
            {"name": "hp.web.search", "arguments": {"query": ""}},
        )
        result = data["result"]
        text = result["content"][0]["text"]
        assert "non-empty" in text.lower()

    @pytest.mark.asyncio
    async def test_web_fetch_empty_url(self):
        """hp.web.fetch rejects empty URL."""
        data = await _post_rpc(
            web_search_app,
            "tools/call",
            {"name": "hp.web.fetch", "arguments": {"url": ""}},
        )
        result = data["result"]
        text = result["content"][0]["text"]
        assert "non-empty" in text.lower()


# ═══════════════════════════════════════════════════════════════════════════
# A2A AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════

A2A_AGENTS = [
    ("everyday-assistant", everyday_assistant_app),
    ("chief-of-staff", chief_of_staff_app),
]


class TestA2AHealth:
    """All A2A agents respond to GET /health."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", A2A_AGENTS, ids=[a[0] for a in A2A_AGENTS])
    async def test_health(self, name, app):
        data = await _get_health(app)
        assert data["ok"] is True


class TestA2AInitialize:
    """A2A agents respond to initialize with agent info."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", A2A_AGENTS, ids=[a[0] for a in A2A_AGENTS])
    async def test_initialize(self, name, app):
        data = await _post_rpc(app, "initialize")
        result = data["result"]
        assert "name" in result
        assert "methods" in result
        assert "a2a.message" in result["methods"]


class TestA2AMessage:
    """A2A agents handle a2a.message and return structured responses."""

    @pytest.mark.asyncio
    async def test_everyday_assistant_message(self):
        data = await _post_rpc(
            everyday_assistant_app,
            "a2a.message",
            {"text": "What should I focus on today?", "meta": {}},
        )
        result = data["result"]
        assert "agent" in result
        assert result["agent"] == "everyday-assistant"
        assert "text" in result
        assert "policy" in result
        assert result["policy"]["can_act"] is False

    @pytest.mark.asyncio
    async def test_everyday_assistant_persona(self):
        data = await _post_rpc(
            everyday_assistant_app,
            "a2a.message",
            {"text": "Help me plan", "meta": {"persona": "focused"}},
        )
        result = data["result"]
        assert result["text"].startswith("Got it.")

    @pytest.mark.asyncio
    async def test_chief_of_staff_message(self):
        data = await _post_rpc(
            chief_of_staff_app,
            "a2a.message",
            {"text": "Prepare a status update", "meta": {}},
        )
        result = data["result"]
        assert "agent" in result
        assert result["agent"] == "chief-of-staff"
        assert "text" in result
        assert "policy" in result
        assert result["policy"]["can_act"] is False
        assert result["policy"]["needs_confirmation"] is True

    @pytest.mark.asyncio
    async def test_chief_of_staff_knowledge_mode(self):
        data = await _post_rpc(
            chief_of_staff_app,
            "a2a.message",
            {"text": "What do we know about project X?", "meta": {"mode": "knowledge"}},
        )
        result = data["result"]
        assert "What I know" in result["text"]
        assert "Options" in result["text"]


class TestA2AUnknownMethod:
    """A2A agents reject unknown methods."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", A2A_AGENTS, ids=[a[0] for a in A2A_AGENTS])
    async def test_unknown_method(self, name, app):
        data = await _post_rpc(app, "nonexistent.method")
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════
# FORGE COMPATIBILITY CHECKS
# ═══════════════════════════════════════════════════════════════════════════


class TestForgeCompatibility:
    """Verify servers follow MCP/Forge protocol conventions."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_mcp_tools_call_missing_name_returns_error(self, name, app):
        """tools/call without params.name should return -32602."""
        data = await _post_rpc(app, "tools/call", {"arguments": {}})
        assert "error" in data
        assert data["error"]["code"] == -32602

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_tools_list_returns_jsonrpc_envelope(self, name, app):
        """tools/list response must have jsonrpc 2.0 envelope."""
        data = await _post_rpc(app, "tools/list")
        assert data.get("jsonrpc") == "2.0"
        assert "id" in data
        assert "result" in data

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", MCP_SERVERS, ids=[s[0] for s in MCP_SERVERS])
    async def test_tool_names_are_namespaced(self, name, app):
        """Tool names should use hp.* namespace for Forge compatibility."""
        data = await _post_rpc(app, "tools/list")
        tools = data["result"]["tools"]
        for tool in tools:
            assert tool["name"].startswith("hp."), (
                f"Tool {tool['name']} in {name} should use hp.* namespace"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,app", A2A_AGENTS, ids=[a[0] for a in A2A_AGENTS])
    async def test_a2a_response_has_policy(self, name, app):
        """A2A message responses must include a policy block."""
        data = await _post_rpc(app, "a2a.message", {"text": "test", "meta": {}})
        result = data["result"]
        assert "policy" in result, f"{name} response missing policy block"
        assert "can_act" in result["policy"]
