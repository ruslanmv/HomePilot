"""Tests for mcp-microsoft-graph server."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentic.integrations.mcp.microsoft_graph.app import app  # noqa: E402


def _rpc(method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"jsonrpc": "2.0", "id": "test-1", "method": method}
    if params is not None:
        body["params"] = params
    return body


async def _post_rpc(method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.post("/rpc", json=_rpc(method, params))
        assert r.status_code == 200
        return r.json()


async def _get_health() -> Dict[str, Any]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        return r.json()


@pytest.mark.asyncio
async def test_health():
    data = await _get_health()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_initialize():
    data = await _post_rpc("initialize")
    assert "protocolVersion" in data["result"]


@pytest.mark.asyncio
async def test_tools_list():
    data = await _post_rpc("tools/list")
    tools = data["result"]["tools"]
    assert len(tools) >= 6
    names = {t["name"] for t in tools}
    assert "hp.graph.mail.search" in names
    assert "hp.graph.mail.read" in names
    assert "hp.graph.mail.draft" in names
    assert "hp.graph.mail.send" in names
    assert "hp.graph.calendar.list_events" in names
    assert "hp.graph.calendar.read_event" in names


@pytest.mark.asyncio
async def test_mail_search():
    data = await _post_rpc("tools/call", {"name": "hp.graph.mail.search", "arguments": {"query": "test"}})
    result = data["result"]
    assert "content" in result
    assert "placeholder" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_mail_draft_write_disabled():
    data = await _post_rpc("tools/call", {"name": "hp.graph.mail.draft", "arguments": {"to": "a@b.com", "subject": "Hi", "body": "Hello"}})
    result = data["result"]
    assert "write disabled" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_calendar_list_events():
    data = await _post_rpc("tools/call", {"name": "hp.graph.calendar.list_events", "arguments": {"time_min": "2026-01-01", "time_max": "2026-01-02"}})
    result = data["result"]
    assert "content" in result
    assert "placeholder" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_tool_names_namespaced():
    data = await _post_rpc("tools/list")
    for tool in data["result"]["tools"]:
        assert tool["name"].startswith("hp.")
