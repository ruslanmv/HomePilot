"""Tests for mcp-telegram server."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

telegram_app = importlib.import_module("agentic.integrations.mcp.telegram.app")  # noqa: E402

app = telegram_app.app


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


@pytest.mark.asyncio
async def test_health_endpoint_reports_ok():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        body = r.json()
    assert body["ok"] is True
    assert body["name"] == "homepilot-telegram"


@pytest.mark.asyncio
async def test_tools_list_contains_telegram_tools():
    data = await _post_rpc("tools/list")
    names = {t["name"] for t in data["result"]["tools"]}
    assert "hp.telegram.send_message" in names
    assert "hp.telegram.updates.get" in names
    assert "hp.telegram.voice_note.send" in names
    assert "hp.telegram.webhook.receive" in names
    assert "hp.telegram.server.status" in names


@pytest.mark.asyncio
async def test_send_message_is_write_gated_by_default():
    original_state = telegram_app.INSTALL_STATE
    telegram_app.INSTALL_STATE = "ENABLED"
    try:
        data = await _post_rpc(
            "tools/call",
            {"name": "hp.telegram.send_message", "arguments": {"chat_id": "123", "text": "hi"}},
        )
    finally:
        telegram_app.INSTALL_STATE = original_state
    assert "write disabled" in data["result"]["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_receive_webhook_exposes_update_payload():
    original_state = telegram_app.INSTALL_STATE
    telegram_app.INSTALL_STATE = "ENABLED"
    try:
        data = await _post_rpc(
            "tools/call",
            {
                "name": "hp.telegram.webhook.receive",
                "arguments": {"chat_id": "123", "text": "hello", "update_id": "u-1"},
            },
        )
    finally:
        telegram_app.INSTALL_STATE = original_state
    assert data["result"]["update"]["update_id"] == "u-1"


@pytest.mark.asyncio
async def test_send_message_requires_consent_when_writes_enabled():
    original_state = telegram_app.INSTALL_STATE
    original_write = telegram_app.WRITE_ENABLED
    telegram_app.INSTALL_STATE = "ENABLED"
    telegram_app.WRITE_ENABLED = True
    try:
        data = await _post_rpc(
            "tools/call",
            {"name": "hp.telegram.send_message", "arguments": {"chat_id": "123", "text": "hi"}},
        )
    finally:
        telegram_app.INSTALL_STATE = original_state
        telegram_app.WRITE_ENABLED = original_write
    assert "consent" in data["result"]["content"][0]["text"].lower()
