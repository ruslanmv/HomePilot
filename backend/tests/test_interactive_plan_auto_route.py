"""
HTTP tests for POST /v1/interactive/plan-auto.

Exercises the route via a minimal FastAPI TestClient app, same
pattern as every other interactive route test. The underlying
chat_ollama is monkey-patched so CI never touches a real LLM.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.interactive.config import InteractiveConfig
from app.interactive.router import build_router
from app.interactive.routes._common import current_user


@pytest.fixture(scope="module")
def tmp_db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ix_plan_auto")
    os.environ["SQLITE_PATH"] = str(tmp / "ix_test.db")
    from app import storage
    storage._RESOLVED_DB_PATH = None
    return os.environ["SQLITE_PATH"]


def _cfg() -> InteractiveConfig:
    return InteractiveConfig(
        enabled=True, max_branches=6, max_depth=4,
        max_nodes_per_experience=100, llm_model="llama3:8b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )


@pytest.fixture
def client(tmp_db_path):
    """TestClient with LLM flag OFF by default — heuristic path.
    Individual tests flip INTERACTIVE_PLAYBACK_LLM via monkeypatch
    when they want to exercise the LLM branch."""
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    user_id = f"u_plan_auto_{uuid.uuid4().hex[:6]}"
    app.dependency_overrides[current_user] = lambda: user_id
    return TestClient(app)


_VALID_LLM_PAYLOAD = (
    '{"title": "Sales Rep Pricing Training",'
    ' "prompt": "Guide new sales reps through three pricing tiers.",'
    ' "experience_mode": "enterprise_training",'
    ' "policy_profile_id": "enterprise_training",'
    ' "audience_role": "trainee",'
    ' "audience_level": "beginner",'
    ' "audience_language": "en",'
    ' "audience_locale_hint": "us",'
    ' "branch_count": 3,'
    ' "depth": 2,'
    ' "scenes_per_branch": 3,'
    ' "objective": "Teach pricing tiers through decisions",'
    ' "topic": "Sales pricing",'
    ' "scheme": "xp_level",'
    ' "success_metric": "correct answers",'
    ' "seed_intents": ["greeting", "choose_plan", "quiz", "feedback"]}'
)


def _install_chat(
    monkeypatch: pytest.MonkeyPatch, response: Any,
) -> None:
    async def _fake(messages: List[Dict[str, Any]], **kwargs: Any):
        if isinstance(response, Exception):
            raise response
        return response
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_ollama", _fake)


# ── Happy paths ────────────────────────────────────────────────

def test_heuristic_path_returns_full_form_shape(client):
    r = client.post(
        "/v1/interactive/plan-auto",
        json={"idea": "train new sales reps on pricing"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["source"] == "heuristic"
    f = body["form"]
    # Every documented field is present and non-empty.
    for key in (
        "title", "prompt", "experience_mode", "policy_profile_id",
        "audience_role", "audience_level", "audience_language",
    ):
        assert isinstance(f[key], str) and f[key], f"missing {key!r}"
    # Structural fields clamped to the spec bounds.
    assert 2 <= f["branch_count"] <= 4
    assert 2 <= f["depth"] <= 3
    assert 2 <= f["scenes_per_branch"] <= 4
    assert f["experience_mode"] == "enterprise_training"


def test_llm_path_is_reported_in_source(monkeypatch, client):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", "true")
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": _VALID_LLM_PAYLOAD}}]},
    )
    r = client.post(
        "/v1/interactive/plan-auto",
        json={"idea": "train new sales reps on pricing"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "llm"
    assert body["form"]["title"] == "Sales Rep Pricing Training"


def test_response_shape_carries_planner_preview_fields(client):
    r = client.post(
        "/v1/interactive/plan-auto",
        json={"idea": "teach beginners photosynthesis"},
    )
    assert r.status_code == 200
    body = r.json()
    for key in ("objective", "topic", "scheme", "success_metric", "seed_intents"):
        assert key in body
    assert isinstance(body["seed_intents"], list)


# ── Input validation ───────────────────────────────────────────

def test_empty_idea_is_400(client):
    r = client.post("/v1/interactive/plan-auto", json={"idea": ""})
    assert r.status_code == 400
    body = r.json()["detail"]
    assert body["code"] == "invalid_input"


def test_whitespace_only_idea_is_400(client):
    r = client.post("/v1/interactive/plan-auto", json={"idea": "   "})
    assert r.status_code == 400


def test_very_short_idea_is_still_accepted(client):
    # Zero-friction: no 10-char minimum. 'hi' is enough to return
    # a heuristic form (mode defaults to sfw_general).
    r = client.post("/v1/interactive/plan-auto", json={"idea": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["form"]["experience_mode"] == "sfw_general"


# ── Fallback behaviour ─────────────────────────────────────────

def test_llm_exception_gracefully_falls_back(monkeypatch, client):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", "true")
    _install_chat(monkeypatch, RuntimeError("ollama down"))
    r = client.post(
        "/v1/interactive/plan-auto",
        json={"idea": "onboard new hires on compliance"},
    )
    assert r.status_code == 200  # never surfaces the LLM error
    body = r.json()
    assert body["source"] == "heuristic"
    assert body["form"]["experience_mode"] == "enterprise_training"
