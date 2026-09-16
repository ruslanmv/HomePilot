"""Regression for the real /avatar/session adult-verification wiring.

Protocol-level tests already proved that a ProtocolHandler can answer an
``adult_verify_request`` when somebody injects ``verification.Session``. This file protects the
missing transport seam: the FastAPI WebSocket must actually construct that session for every
connection when the server-side adult gate is enabled.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.avatar_director.config import AdultConfig, AvatarDirectorConfig
from app.avatar_director.session import build_router
from app.avatar_director.verification import OwnerAttestProvider


def config(*, adult: bool) -> AvatarDirectorConfig:
    return AvatarDirectorConfig(
        enabled=True,
        adult=AdultConfig(enabled=adult, provider="owner-attest"),
    )


def hello(ws) -> dict:
    ws.send_json({"v": 1, "type": "hello", "client": "adult-wiring-test", "caps": [], "auth": "ok"})
    return ws.receive_json()


def test_enabled_avatar_socket_returns_trusted_adult_ack():
    app = FastAPI()
    provider = OwnerAttestProvider(count_users=lambda: 1).load()
    app.include_router(
        build_router(
            config(adult=True),
            authenticate=lambda _token: True,
            adult_provider=provider,
        )
    )

    with TestClient(app).websocket_connect("/avatar/session") as ws:
        assert hello(ws)["type"] == "ping"
        ws.send_json({"v": 1, "type": "adult_verify_request"})
        ack = ws.receive_json()

    assert ack["v"] == 1
    assert ack["type"] == "adult_ack"
    assert ack["verified"] is True
    assert ack["provider"] == "owner-attest"
    assert ack["exp"] > 0


def test_disabled_server_gate_cannot_be_bypassed_by_injected_provider():
    app = FastAPI()
    provider = OwnerAttestProvider(count_users=lambda: 1).load()
    app.include_router(
        build_router(
            config(adult=False),
            authenticate=lambda _token: True,
            adult_provider=provider,
        )
    )

    with TestClient(app).websocket_connect("/avatar/session") as ws:
        assert hello(ws)["type"] == "ping"
        ws.send_json({"v": 1, "type": "adult_verify_request"})
        refusal = ws.receive_json()

    assert refusal["type"] == "error"
    assert refusal["code"] == "adult_unavailable"
