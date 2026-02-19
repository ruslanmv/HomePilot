"""Tests for mcp-local-notes server."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentic.integrations.mcp.local_notes.app import app  # noqa: E402


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
    assert "name" in data


@pytest.mark.asyncio
async def test_initialize():
    data = await _post_rpc("initialize")
    result = data["result"]
    assert "protocolVersion" in result
    assert result["capabilities"]["tools"] is True


@pytest.mark.asyncio
async def test_tools_list():
    data = await _post_rpc("tools/list")
    tools = data["result"]["tools"]
    assert len(tools) >= 4
    names = {t["name"] for t in tools}
    assert "hp.notes.search" in names
    assert "hp.notes.read" in names
    assert "hp.notes.create" in names
    assert "hp.notes.append" in names


@pytest.mark.asyncio
async def test_notes_search():
    data = await _post_rpc("tools/call", {"name": "hp.notes.search", "arguments": {"query": "test"}})
    result = data["result"]
    # Empty store — should report no results or return results structure
    assert "results" in result or "content" in result


@pytest.mark.asyncio
async def test_notes_read_missing():
    data = await _post_rpc("tools/call", {"name": "hp.notes.read", "arguments": {"note_id": "nonexistent"}})
    result = data["result"]
    assert "content" in result
    assert "not found" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_notes_create_write_disabled():
    data = await _post_rpc("tools/call", {"name": "hp.notes.create", "arguments": {"title": "Test", "content": "Body"}})
    result = data["result"]
    assert "content" in result
    assert "write disabled" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_unknown_tool():
    data = await _post_rpc("tools/call", {"name": "nonexistent.tool", "arguments": {}})
    assert "error" in data
    assert data["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_tool_names_namespaced():
    data = await _post_rpc("tools/list")
    for tool in data["result"]["tools"]:
        assert tool["name"].startswith("hp.")
