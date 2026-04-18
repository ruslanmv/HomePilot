"""Tests for mcp-whatsapp server."""

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

whatsapp_app = importlib.import_module("agentic.integrations.mcp.whatsapp.app")  # noqa: E402

app = whatsapp_app.app


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
    assert body["name"] == "homepilot-whatsapp"


@pytest.mark.asyncio
async def test_tools_list_contains_whatsapp_tools():
    data = await _post_rpc("tools/list")
    names = {t["name"] for t in data["result"]["tools"]}
    assert "hp.whatsapp.send_message" in names
    assert "hp.whatsapp.message_status" in names
    assert "hp.whatsapp.templates.list" in names
    assert "hp.whatsapp.webhook.receive" in names
    assert "hp.whatsapp.server.status" in names
    assert "hp.whatsapp.audit.list" in names


@pytest.mark.asyncio
async def test_send_message_is_write_gated_by_default():
    original_state = whatsapp_app.INSTALL_STATE
    whatsapp_app.INSTALL_STATE = "ENABLED"
    try:
        data = await _post_rpc(
            "tools/call",
            {"name": "hp.whatsapp.send_message", "arguments": {"to": "+391234", "text": "hi"}},
        )
    finally:
        whatsapp_app.INSTALL_STATE = original_state
    assert "write disabled" in data["result"]["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_receive_webhook_supports_ack_detection():
    original_state = whatsapp_app.INSTALL_STATE
    whatsapp_app.INSTALL_STATE = "ENABLED"
    try:
        data = await _post_rpc(
            "tools/call",
            {
                "name": "hp.whatsapp.webhook.receive",
                "arguments": {"from": "+39123", "text": "ACK", "provider_message_id": "m-1"},
            },
        )
    finally:
        whatsapp_app.INSTALL_STATE = original_state
    assert data["result"]["webhook"]["ack_action"] == "ack"


@pytest.mark.asyncio
async def test_server_status_exposes_lifecycle_state():
    data = await _post_rpc(
        "tools/call",
        {"name": "hp.whatsapp.server.status", "arguments": {}},
    )
    assert "install_state" in data["result"]["server"]


@pytest.mark.asyncio
async def test_send_message_requires_consent_when_writes_enabled():
    original_state = whatsapp_app.INSTALL_STATE
    original_write = whatsapp_app.WRITE_ENABLED
    whatsapp_app.INSTALL_STATE = "ENABLED"
    whatsapp_app.WRITE_ENABLED = True
    try:
        data = await _post_rpc(
            "tools/call",
            {"name": "hp.whatsapp.send_message", "arguments": {"to": "+391234", "text": "hi"}},
        )
    finally:
        whatsapp_app.INSTALL_STATE = original_state
        whatsapp_app.WRITE_ENABLED = original_write
    assert "consent" in data["result"]["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_webhook_verify_accepts_valid_meta_signature():
    import hashlib
    import hmac
    original_state = whatsapp_app.INSTALL_STATE
    whatsapp_app.INSTALL_STATE = "ENABLED"
    try:
        payload = '{"entry":[{"changes":[{"value":{"messages":[{"from":"+391234","text":{"body":"ACK"}}]}}]}]}'
        secret = "meta-app-secret-test"
        sig = "sha256=" + hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        data = await _post_rpc(
            "tools/call",
            {
                "name": "hp.whatsapp.webhook.verify",
                "arguments": {"payload": payload, "signature": sig, "secret": secret},
            },
        )
    finally:
        whatsapp_app.INSTALL_STATE = original_state
    assert data["result"]["verified"] is True


@pytest.mark.asyncio
async def test_webhook_verify_rejects_bad_signature():
    original_state = whatsapp_app.INSTALL_STATE
    whatsapp_app.INSTALL_STATE = "ENABLED"
    try:
        data = await _post_rpc(
            "tools/call",
            {
                "name": "hp.whatsapp.webhook.verify",
                "arguments": {
                    "payload": "body",
                    "signature": "sha256=" + "0" * 64,
                    "secret": "meta-app-secret-test",
                },
            },
        )
    finally:
        whatsapp_app.INSTALL_STATE = original_state
    assert data["result"]["verified"] is False
