"""
The routes the UI and external clients call are all registered.

The Hugging Face Space ran without POST /v1/expert/chat — the Expert package was not in the
image — and the chat's default path answered every "Hello" with HTTP 405. The Space's
entry point (deploy/huggingface-space/hf_wrapper.py) logs this same list at boot.
"""
from __future__ import annotations

REQUIRED_ROUTES = (
    ("GET", "/health"),
    ("POST", "/chat"),
    ("POST", "/v1/chat/completions"),
    ("GET", "/v1/models"),
    ("POST", "/models/install"),
    ("GET", "/models/install/progress"),
    ("POST", "/v1/expert/chat"),
)


def missing_routes(app) -> list:
    """Asked of the router's own matching — routers FastAPI includes lazily count too."""
    from starlette.routing import Match

    missing = []
    for method, path in REQUIRED_ROUTES:
        scope = {"type": "http", "method": method, "path": path, "root_path": "",
                 "query_string": b"", "headers": [], "path_params": {}, "app": app}
        if not any(r.matches(scope)[0] == Match.FULL for r in app.router.routes):
            missing.append(f"{method} {path}")
    return missing


def test_every_required_route_is_registered():
    from app.main import app

    assert missing_routes(app) == []


def test_the_check_notices_a_missing_route():
    from fastapi import FastAPI

    bare = FastAPI()

    @bare.get("/health")
    def health():
        return {"ok": True}

    assert "POST /v1/expert/chat" in missing_routes(bare)
    assert "GET /health" not in missing_routes(bare)
