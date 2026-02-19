"""Tests for mcp-gmail server."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentic.integrations.mcp.gmail.app import app  # noqa: E402


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
    assert len(tools) >= 4
    names = {t["name"] for t in tools}
    assert "hp.gmail.search" in names
    assert "hp.gmail.read" in names
    assert "hp.gmail.draft" in names
    assert "hp.gmail.send" in names


@pytest.mark.asyncio
async def test_gmail_search():
    data = await _post_rpc("tools/call", {"name": "hp.gmail.search", "arguments": {"query": "test"}})
    result = data["result"]
    assert "content" in result
    assert "placeholder" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_gmail_draft_write_disabled():
    data = await _post_rpc("tools/call", {"name": "hp.gmail.draft", "arguments": {"to": "a@b.com", "subject": "Hi", "body": "Hello"}})
    result = data["result"]
    assert "content" in result
    assert "write disabled" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_gmail_send_write_disabled():
    data = await _post_rpc("tools/call", {"name": "hp.gmail.send", "arguments": {"draft_id": "d123"}})
    result = data["result"]
    assert "content" in result
    assert "write disabled" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_tool_names_namespaced():
    data = await _post_rpc("tools/list")
    for tool in data["result"]["tools"]:
        assert tool["name"].startswith("hp.")
