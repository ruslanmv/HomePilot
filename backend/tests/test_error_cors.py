"""An unexpected server error must reach the browser as a readable 500, not a CORS block."""
import logging
import uuid

from fastapi.testclient import TestClient


def _boom_route(app):
    path = f"/__test_boom_{uuid.uuid4().hex[:8]}"

    async def boom():
        raise RuntimeError("database is locked")

    app.add_api_route(path, boom, methods=["GET"])
    return path


def test_500_carries_cors_header_for_allowed_origin(app, caplog):
    path = _boom_route(app)
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="homepilot.errors"):
        r = client.get(path, headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert r.headers.get("access-control-allow-credentials") == "true"
    assert any("database is locked" in (rec.exc_text or str(rec.exc_info)) for rec in caplog.records)


def test_500_has_no_cors_header_for_unknown_origin(app):
    path = _boom_route(app)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(path, headers={"Origin": "http://evil.example"})
    assert r.status_code == 500
    assert "access-control-allow-origin" not in r.headers
