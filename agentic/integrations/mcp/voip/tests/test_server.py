"""Tests for mcp-voip server."""

from __future__ import annotations

import sys
import importlib
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

voip_app = importlib.import_module("agentic.integrations.mcp.voip.app")  # noqa: E402

app = voip_app.app


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
    assert body["name"] == "homepilot-voip"


@pytest.mark.asyncio
async def test_tools_list_contains_voip_tools():
    data = await _post_rpc("tools/list")
    names = {t["name"] for t in data["result"]["tools"]}
    assert "hp.voip.call.create" in names
    assert "hp.voip.call.status" in names
    assert "hp.voip.call.end" in names
    assert "hp.voip.call.play_tts" in names
    assert "hp.voip.call.collect_ack" in names
    assert "hp.voip.did_route.upsert" in names
    assert "hp.voip.did_route.get" in names
    assert "hp.voip.did_route.delete" in names
    assert "hp.voip.ingress.route_call" in names
    assert "hp.voip.server.status" in names
    assert "hp.voip.audit.list" in names


@pytest.mark.asyncio
async def test_call_create_is_write_gated_by_default():
    original_state = voip_app.INSTALL_STATE
    voip_app.INSTALL_STATE = "ENABLED"
    try:
        data = await _post_rpc(
            "tools/call",
            {"name": "hp.voip.call.create", "arguments": {"to": "+391234"}},
        )
    finally:
        voip_app.INSTALL_STATE = original_state
    assert "write disabled" in data["result"]["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_ingress_route_call_requires_telephony_flag():
    original_state = voip_app.INSTALL_STATE
    voip_app.INSTALL_STATE = "ENABLED"
    data = await _post_rpc(
        "tools/call",
        {
            "name": "hp.voip.ingress.route_call",
            "arguments": {
                "to_did_e164": "+15550001111",
                "source_ip": "203.0.113.10",
                "provider_call_id": "abc",
            },
        },
    )
    voip_app.INSTALL_STATE = original_state
    assert "telephony ingress disabled" in data["result"]["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_ingress_route_call_allows_matching_cidr():
    original_write = voip_app.WRITE_ENABLED
    original_telephony = voip_app.TELEPHONY_ENABLED
    original_state = voip_app.INSTALL_STATE
    voip_app.WRITE_ENABLED = True
    voip_app.TELEPHONY_ENABLED = True
    voip_app.INSTALL_STATE = "ENABLED"
    voip_app._DID_ROUTES.clear()
    try:
        upsert = await _post_rpc(
            "tools/call",
            {
                "name": "hp.voip.did_route.upsert",
                "arguments": {
                    "did_e164": "+15550002222",
                    "persona_id": "secretary",
                    "allow_source_cidrs": ["203.0.113.0/24"],
                },
            },
        )
        assert "upserted" in upsert["result"]["content"][0]["text"].lower()
        routed = await _post_rpc(
            "tools/call",
            {
                "name": "hp.voip.ingress.route_call",
                "arguments": {
                    "to_did_e164": "+15550002222",
                    "from_number": "+14155551234",
                    "source_ip": "203.0.113.10",
                    "provider_call_id": "call-1",
                },
            },
        )
        assert routed["result"]["decision"] == "accept"
        assert routed["result"]["persona_id"] == "secretary"
    finally:
        voip_app._DID_ROUTES.clear()
        voip_app.WRITE_ENABLED = original_write
        voip_app.TELEPHONY_ENABLED = original_telephony
        voip_app.INSTALL_STATE = original_state


@pytest.mark.asyncio
async def test_collect_ack_maps_signal():
    original_state = voip_app.INSTALL_STATE
    voip_app.INSTALL_STATE = "ENABLED"
    try:
        data = await _post_rpc(
            "tools/call",
            {"name": "hp.voip.call.collect_ack", "arguments": {"call_id": "c1", "signal": "2"}},
        )
    finally:
        voip_app.INSTALL_STATE = original_state
    assert data["result"]["ack"]["decision"] == "snooze"


@pytest.mark.asyncio
async def test_call_create_requires_consent_when_writes_enabled():
    original_state = voip_app.INSTALL_STATE
    original_write = voip_app.WRITE_ENABLED
    voip_app.INSTALL_STATE = "ENABLED"
    voip_app.WRITE_ENABLED = True
    try:
        data = await _post_rpc(
            "tools/call",
            {"name": "hp.voip.call.create", "arguments": {"to": "+391234"}},
        )
    finally:
        voip_app.INSTALL_STATE = original_state
        voip_app.WRITE_ENABLED = original_write
    assert "consent" in data["result"]["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_did_route_respects_single_did_policy():
    original_state = voip_app.INSTALL_STATE
    original_write = voip_app.WRITE_ENABLED
    original_did = voip_app.APP_DID
    voip_app.INSTALL_STATE = "ENABLED"
    voip_app.WRITE_ENABLED = True
    voip_app.APP_DID = "+10000000000"
    try:
        data = await _post_rpc(
            "tools/call",
            {
                "name": "hp.voip.did_route.upsert",
                "arguments": {"did_e164": "+19999999999", "persona_id": "secretary"},
            },
        )
    finally:
        voip_app.INSTALL_STATE = original_state
        voip_app.WRITE_ENABLED = original_write
        voip_app.APP_DID = original_did
    assert "single-did policy" in data["result"]["content"][0]["text"].lower()
