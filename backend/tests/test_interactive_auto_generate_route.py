"""
HTTP tests for POST /v1/interactive/experiences/{id}/auto-generate.
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
    tmp = tmp_path_factory.mktemp("ix_auto_generate")
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
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    stable = f"u_auto_gen_{uuid.uuid4().hex[:6]}"
    app.dependency_overrides[current_user] = lambda: stable
    return TestClient(app)


def _make_experience(client) -> str:
    r = client.post(
        "/v1/interactive/experiences",
        json={
            "title": "Auto gen demo",
            "description": "Walk a new hire through 3 pricing tiers.",
            "experience_mode": "enterprise_training",
            "policy_profile_id": "enterprise_training",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["experience"]["id"]


_VALID_PAYLOAD = (
    '{'
    '"scenes": ['
    '  {"id": "intro", "type": "scene", "title": "Welcome",'
    '   "script": "Welcome aboard. Let\'s pick your path.",'
    '   "visual_direction": "warm studio light",'
    '   "next": ["pick"]},'
    '  {"id": "pick", "type": "decision", "title": "Choose",'
    '   "script": "Which tier matches?",'
    '   "visual_direction": "host framed center",'
    '   "interaction": {"type": "choice", "options": ['
    '      {"label": "Starter", "next": "end_starter"},'
    '      {"label": "Pro", "next": "end_pro"}'
    '   ]}},'
    '  {"id": "end_starter", "type": "ending", "title": "Starter",'
    '   "script": "Nice entry plan.", "visual_direction": "smile"},'
    '  {"id": "end_pro", "type": "ending", "title": "Pro",'
    '   "script": "Great for power users.", "visual_direction": "confident"}'
    '],'
    '"logic": {"start_scene": "intro"}'
    '}'
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


# ── Heuristic path ────────────────────────────────────────────

def test_heuristic_generates_and_persists_a_graph(client):
    eid = _make_experience(client)
    r = client.post(f"/v1/interactive/experiences/{eid}/auto-generate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["source"] == "heuristic"
    assert body["already_generated"] is False
    assert body["node_count"] >= 2
    assert body["edge_count"] >= 1
    # Nodes visible via the authoring API — persisted, not just
    # returned in-memory.
    listed = client.get(f"/v1/interactive/experiences/{eid}/nodes").json()
    assert len(listed["items"]) == body["node_count"]


# ── LLM path ──────────────────────────────────────────────────

def test_llm_path_persists_scenes_edges_and_actions(monkeypatch, client):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", "true")
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": _VALID_PAYLOAD}}]},
    )
    eid = _make_experience(client)
    r = client.post(f"/v1/interactive/experiences/{eid}/auto-generate")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "llm"
    assert body["node_count"] == 4
    assert body["action_count"] == 2
    # Confirm the action catalog got the two choice labels.
    actions = client.get(
        f"/v1/interactive/experiences/{eid}/actions",
    ).json()["items"]
    labels = sorted(a["label"] for a in actions)
    assert labels == ["Pro", "Starter"]


# ── Idempotency ───────────────────────────────────────────────

def test_second_call_is_idempotent(client):
    eid = _make_experience(client)
    first = client.post(
        f"/v1/interactive/experiences/{eid}/auto-generate",
    ).json()
    second = client.post(
        f"/v1/interactive/experiences/{eid}/auto-generate",
    ).json()
    assert second["already_generated"] is True
    assert second["source"] == "existing"
    assert second["node_count"] == first["node_count"]
    assert second["edge_count"] == first["edge_count"]


# ── Ownership / error paths ───────────────────────────────────

def test_unknown_experience_404s(client):
    r = client.post("/v1/interactive/experiences/ixe_does_not_exist/auto-generate")
    assert r.status_code == 404


def test_cross_user_experience_404s(tmp_db_path):
    # Two different TestClients, different user ids. The second
    # can't see (or mutate) the first one's experience.
    app1 = FastAPI()
    app1.include_router(build_router(_cfg()))
    app1.dependency_overrides[current_user] = lambda: "u_owner_A"
    c1 = TestClient(app1)

    eid = c1.post(
        "/v1/interactive/experiences",
        json={"title": "Owner A", "experience_mode": "sfw_general"},
    ).json()["experience"]["id"]

    app2 = FastAPI()
    app2.include_router(build_router(_cfg()))
    app2.dependency_overrides[current_user] = lambda: "u_owner_B"
    c2 = TestClient(app2)

    r = c2.post(f"/v1/interactive/experiences/{eid}/auto-generate")
    assert r.status_code == 404


# ── LLM failure fallback via the route ────────────────────────

def test_llm_failure_falls_back_to_heuristic_seamlessly(
    monkeypatch, client,
):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", "true")
    _install_chat(monkeypatch, RuntimeError("ollama offline"))
    eid = _make_experience(client)
    r = client.post(f"/v1/interactive/experiences/{eid}/auto-generate")
    assert r.status_code == 200
    assert r.json()["source"] == "heuristic"
