"""Tests for the additive, read-only container log streaming API.

Builds a minimal FastAPI app mounting only ``logs_api.router`` so we can drive
auth and tailing deterministically without the full backend.
"""
import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure the backend root (.../backend) is importable even if the session app
# fixture (which does this in conftest) hasn't run yet.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import config as cfg  # noqa: E402
from app.logs_api import router as logs_router  # noqa: E402

SPACE = "/api/spaces/ruslanmv/HomePilot/logs"


def _client(tmp_path, api_key="") -> TestClient:
    cfg.API_KEY = api_key
    os.environ["HOMEPILOT_LOG_DIR"] = str(tmp_path)
    app = FastAPI()
    app.include_router(logs_router)
    return TestClient(app)


def _seed(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_anonymous_remote_denied_even_without_api_key(tmp_path):
    # Fail-closed: no API key configured, TestClient host is not local → 401.
    client = _client(tmp_path, api_key="")
    r = client.get(f"{SPACE}/run", params={"follow": "false"})
    assert r.status_code == 401


def test_bad_api_key_denied(tmp_path):
    client = _client(tmp_path, api_key="s3cret-key-value-1234567890")
    r = client.get(f"{SPACE}/run", params={"follow": "false"},
                   headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_run_stream_returns_tail_with_valid_key(tmp_path):
    key = "s3cret-key-value-1234567890"
    _seed(tmp_path, "backend-stderr.log", "line-one\nline-two\nline-three\n")
    client = _client(tmp_path, api_key=key)
    r = client.get(
        f"{SPACE}/run",
        params={"follow": "false", "format": "raw", "tail": "2"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "line-three" in body and "line-two" in body
    assert "line-one" not in body  # tail=2 dropped the oldest


def test_x_api_key_header_and_json_format(tmp_path):
    key = "s3cret-key-value-1234567890"
    _seed(tmp_path, "supervisord.log", "spawned backend\nexited backend\n")
    client = _client(tmp_path, api_key=key)
    r = client.get(
        f"{SPACE}/build",
        params={"follow": "false"},   # default json format
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    assert 'data: {"timestamp"' in r.text
    assert "spawned backend" in r.text


def test_api_key_redacted_in_output(tmp_path):
    key = "supersecretkey1234567890abcdef"
    _seed(tmp_path, "backend-stderr.log", f"leaked token {key} in a traceback\n")
    client = _client(tmp_path, api_key=key)
    r = client.get(
        f"{SPACE}/run",
        params={"follow": "false", "format": "raw"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert key not in r.text
    assert "***REDACTED***" in r.text


def test_unknown_stream_404(tmp_path):
    key = "s3cret-key-value-1234567890"
    client = _client(tmp_path, api_key=key)
    r = client.get(f"{SPACE}/does-not-exist", params={"follow": "false"},
                   headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 404


def test_discovery_lists_streams(tmp_path):
    key = "s3cret-key-value-1234567890"
    _seed(tmp_path, "backend-stderr.log", "hello\n")
    client = _client(tmp_path, api_key=key)
    r = client.get(f"{SPACE}", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["streams"]["run"]["available"] is True
    assert data["streams"]["comfyui"]["available"] is False


def test_token_query_param_auth(tmp_path):
    # Browser EventSource can't set headers → token via query string works.
    key = "s3cret-key-value-1234567890"
    _seed(tmp_path, "backend-stderr.log", "via-query\n")
    client = _client(tmp_path, api_key=key)
    r = client.get(f"{SPACE}/run", params={"follow": "false", "format": "raw", "token": key})
    assert r.status_code == 200
    assert "via-query" in r.text
