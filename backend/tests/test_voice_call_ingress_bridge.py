"""Tests for the VoIP-to-voice_call ingress bridge.

These do NOT spin up FastAPI — the bridge is deliberately transport-free,
so we can drive it with synthetic ``hp.voip.ingress.route_call`` decisions
and assert the resulting ``voice_call`` session row has the right shape.
"""
from __future__ import annotations

import os
import sys
import importlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def cfg_and_bridge(monkeypatch, tmp_path):
    """Reload voice_call modules against a temp SQLite so the default
    user + voice_call tables exist on a clean slate per test."""
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("VOICE_CALL_ENABLED", "true")
    monkeypatch.setenv("TELEPHONY_ENABLED", "true")
    for name in list(sys.modules):
        if name.startswith("app."):
            sys.modules.pop(name, None)
    from app.voice_call import config as cfg_mod  # noqa: WPS433
    from app.voice_call import ingress_bridge  # noqa: WPS433
    from app.voice_call import store  # noqa: WPS433
    from app.users import ensure_users_tables, get_or_create_default_user  # noqa: WPS433
    ensure_users_tables()
    store.ensure_schema()
    user = get_or_create_default_user()
    cfg = cfg_mod.load()
    return cfg, ingress_bridge, user


def test_reject_decision_does_not_create_session(cfg_and_bridge):
    cfg, ingress_bridge, user = cfg_and_bridge
    decision = {"decision": "reject_no_route", "provider": "twilio"}
    with pytest.raises(ingress_bridge.IngressBridgeError) as exc_info:
        ingress_bridge.open_session_from_decision(
            decision=decision, cfg=cfg, user_id=user["id"],
        )
    assert exc_info.value.code == "ingress_not_accepted"
    assert exc_info.value.http_status == 403


def test_telephony_disabled_flag_short_circuits(cfg_and_bridge, monkeypatch):
    cfg, ingress_bridge, user = cfg_and_bridge
    monkeypatch.setenv("TELEPHONY_ENABLED", "false")
    decision = {"decision": "accept", "persona_id": "secretary"}
    with pytest.raises(ingress_bridge.IngressBridgeError) as exc_info:
        ingress_bridge.open_session_from_decision(
            decision=decision, cfg=cfg, user_id=user["id"],
        )
    assert exc_info.value.code == "telephony_disabled"
    assert exc_info.value.http_status == 503


def test_accept_decision_creates_voice_call_session(cfg_and_bridge):
    cfg, ingress_bridge, user = cfg_and_bridge
    decision = {
        "decision": "accept",
        "persona_id": "secretary",
        "provider": "twilio",
        "provider_call_id": "CAxxx",
        "from_number": "+14155551212",
        "route": {"project_id": "conv-42"},
    }
    row = ingress_bridge.open_session_from_decision(
        decision=decision, cfg=cfg, user_id=user["id"],
    )
    assert row["user_id"] == user["id"]
    assert row["persona_id"] == "secretary"
    assert row["entry_mode"] == "call"
    assert row["status"] in {"connecting", "live"}
    assert row["id"]


def test_accept_without_persona_raises(cfg_and_bridge):
    cfg, ingress_bridge, user = cfg_and_bridge
    decision = {"decision": "accept"}
    with pytest.raises(ingress_bridge.IngressBridgeError) as exc_info:
        ingress_bridge.open_session_from_decision(
            decision=decision, cfg=cfg, user_id=user["id"],
        )
    assert exc_info.value.code == "missing_persona"


def test_telephony_enabled_reads_env_at_call_time(monkeypatch, cfg_and_bridge):
    _, ingress_bridge, _ = cfg_and_bridge
    monkeypatch.setenv("TELEPHONY_ENABLED", "true")
    assert ingress_bridge.telephony_enabled() is True
    monkeypatch.setenv("TELEPHONY_ENABLED", "false")
    assert ingress_bridge.telephony_enabled() is False
