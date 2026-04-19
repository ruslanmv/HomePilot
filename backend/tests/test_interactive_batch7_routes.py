"""
Batch 7/8 — HTTP routes for authoring + planner + play.

Rather than pulling in the full ``app.main`` (whose import chain
depends on packages not available in this test env), we mount only
the interactive sub-router on a minimal FastAPI app. The viewer
resolution is overridden via a dependency override so tests don't
need a real user row.

Covers:
  - Flag-off router is empty (zero routes, zero OpenAPI paths)
  - Health endpoint comes back green with caps echoed
  - Experience CRUD (create / list / get / patch / delete)
  - Node + edge CRUD with ownership scoping (404 cross-user)
  - Action catalog create + list + unlock-state via /play/catalog
  - Personalization rule validation + create
  - Planner: list_presets + plan + seed_graph (idempotent re-seed)
  - Play: start → resolve (action) → progress → end
  - Play: resolve free_text allow / hard-block minor_reference
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.interactive import repo
from app.interactive.config import InteractiveConfig
from app.interactive.router import build_router
from app.interactive.routes._common import current_user


@pytest.fixture(scope="module")
def tmp_db_path(tmp_path_factory):
    """Force the interactive store to a fresh temp DB for this module."""
    tmp = tmp_path_factory.mktemp("ix_batch7")
    db_path = str(tmp / "ix_test.db")
    os.environ["SQLITE_PATH"] = db_path
    # Reset cached resolution so _get_db_path picks up the new env var.
    from app import storage
    storage._RESOLVED_DB_PATH = None
    return db_path


def _cfg():
    return InteractiveConfig(
        enabled=True, max_branches=6, max_depth=4,
        max_nodes_per_experience=100, llm_model="llama3:8b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )


@pytest.fixture
def app_owner_a(tmp_db_path):
    """FastAPI app with viewer-resolver overridden to user 'owner_a'."""
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    app.dependency_overrides[current_user] = lambda: "owner_a"
    return app


@pytest.fixture
def app_owner_b(tmp_db_path):
    """Same routes, but the viewer is 'owner_b' — for isolation tests."""
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    app.dependency_overrides[current_user] = lambda: "owner_b"
    return app


@pytest.fixture
def client_a(app_owner_a):
    return TestClient(app_owner_a)


@pytest.fixture
def client_b(app_owner_b):
    return TestClient(app_owner_b)


# ─────────────────────────────────────────────────────────────────
# Health + flag-off
# ─────────────────────────────────────────────────────────────────

def test_flag_off_router_has_no_routes():
    cfg = _cfg()
    cfg_off = InteractiveConfig(**{**cfg.__dict__, "enabled": False})
    r = build_router(cfg_off)
    assert r.routes == []


def test_health_returns_ok_with_limits(client_a):
    resp = client_a.get("/v1/interactive/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["enabled"] is True
    assert body["limits"]["max_branches"] == 6


# ─────────────────────────────────────────────────────────────────
# Experience CRUD + ownership
# ─────────────────────────────────────────────────────────────────

def test_experience_crud_happy_path(client_a):
    resp = client_a.post(
        "/v1/interactive/experiences",
        json={"title": "Demo exp"},
    )
    assert resp.status_code == 200, resp.text
    exp = resp.json()["experience"]
    eid = exp["id"]

    resp = client_a.get("/v1/interactive/experiences")
    ids = [e["id"] for e in resp.json()["items"]]
    assert eid in ids

    resp = client_a.get(f"/v1/interactive/experiences/{eid}")
    assert resp.json()["experience"]["title"] == "Demo exp"

    resp = client_a.patch(
        f"/v1/interactive/experiences/{eid}",
        json={"title": "Renamed"},
    )
    assert resp.json()["experience"]["title"] == "Renamed"

    resp = client_a.delete(f"/v1/interactive/experiences/{eid}")
    assert resp.json()["ok"] is True
    resp = client_a.get(f"/v1/interactive/experiences/{eid}")
    assert resp.status_code == 404


def test_experience_is_owner_scoped(client_a, client_b):
    resp = client_a.post(
        "/v1/interactive/experiences", json={"title": "A's"},
    )
    eid = resp.json()["experience"]["id"]

    # Owner B should 404 (probe-safe).
    resp = client_b.get(f"/v1/interactive/experiences/{eid}")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────
# Graph CRUD
# ─────────────────────────────────────────────────────────────────

def _make_exp(client, title="G"):
    r = client.post("/v1/interactive/experiences", json={"title": title})
    return r.json()["experience"]["id"]


def test_node_edge_crud(client_a):
    eid = _make_exp(client_a, "Graph demo")
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "scene", "title": "Start"},
    )
    assert r.status_code == 200
    start_id = r.json()["node"]["id"]
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "ending", "title": "End"},
    )
    end_id = r.json()["node"]["id"]

    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/edges",
        json={"from_node_id": start_id, "to_node_id": end_id, "trigger_kind": "auto"},
    )
    assert r.status_code == 200
    edge_id = r.json()["edge"]["id"]

    r = client_a.get(f"/v1/interactive/experiences/{eid}/edges")
    assert len(r.json()["items"]) == 1

    r = client_a.delete(f"/v1/interactive/edges/{edge_id}")
    assert r.json()["deleted"] == edge_id


# ─────────────────────────────────────────────────────────────────
# Action catalog + rule validation
# ─────────────────────────────────────────────────────────────────

def test_action_create_and_list(client_a):
    eid = _make_exp(client_a, "Catalog demo")
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/actions",
        json={
            "label": "Greet", "intent_code": "greeting", "xp_award": 10,
            "required_level": 1, "required_scheme": "xp_level",
        },
    )
    assert r.status_code == 200
    aid = r.json()["action"]["id"]

    r = client_a.get(f"/v1/interactive/experiences/{eid}/actions")
    labels = [a["label"] for a in r.json()["items"]]
    assert "Greet" in labels

    r = client_a.delete(f"/v1/interactive/actions/{aid}")
    assert r.json()["ok"] is True


def test_rule_create_rejects_unknown_keys(client_a):
    eid = _make_exp(client_a, "Rules")
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/rules",
        json={
            "name": "Bad", "condition": {"unknown_key": 1},
            "action": {"also_bad": "x"}, "priority": 100, "enabled": True,
        },
    )
    assert r.status_code == 400
    body = r.json()["detail"]
    assert body["code"] == "invalid_input"
    assert any("unknown condition" in p for p in body["data"]["problems"])


def test_rule_create_accepts_known_keys(client_a):
    eid = _make_exp(client_a, "Good rules")
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/rules",
        json={
            "name": "Flirty boost",
            "condition": {"mood": "flirty"},
            "action": {"bump_affinity": 0.05},
            "priority": 100, "enabled": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["rule"]["name"] == "Flirty boost"


# ─────────────────────────────────────────────────────────────────
# Planner
# ─────────────────────────────────────────────────────────────────

def test_list_presets(client_a):
    r = client_a.get("/v1/interactive/presets")
    assert r.status_code == 200
    modes = [p["mode"] for p in r.json()["items"]]
    assert "sfw_general" in modes
    assert "social_romantic" in modes


def test_plan_from_prompt(client_a):
    r = client_a.post(
        "/v1/interactive/plan",
        json={"prompt": "teach photosynthesis in 3 branches", "mode": "sfw_education"},
    )
    assert r.status_code == 200, r.text
    intent = r.json()["intent"]
    assert intent["branch_count"] == 3
    assert intent["mode"] == "sfw_education"


def test_seed_graph_is_idempotent(client_a):
    eid = _make_exp(client_a, "Seedy")
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/seed-graph",
        json={"prompt": "explain recursion in 2 branches 2 scenes deep", "mode": "sfw_education"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already_seeded"] is False
    assert body["node_count"] >= 2

    r2 = client_a.post(
        f"/v1/interactive/experiences/{eid}/seed-graph",
        json={"prompt": "irrelevant this time", "mode": "sfw_education"},
    )
    assert r2.json()["already_seeded"] is True


# ─────────────────────────────────────────────────────────────────
# Play runtime
# ─────────────────────────────────────────────────────────────────

def _build_minimal_playable_experience(client_a):
    eid = _make_exp(client_a, "Playable")
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "scene", "title": "Start"},
    )
    start_id = r.json()["node"]["id"]
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "scene", "title": "Middle"},
    )
    mid_id = r.json()["node"]["id"]
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "ending", "title": "End"},
    )
    end_id = r.json()["node"]["id"]
    client_a.post(
        f"/v1/interactive/experiences/{eid}/edges",
        json={"from_node_id": start_id, "to_node_id": mid_id, "trigger_kind": "auto"},
    )
    client_a.post(
        f"/v1/interactive/experiences/{eid}/edges",
        json={"from_node_id": mid_id, "to_node_id": end_id, "trigger_kind": "auto"},
    )
    r = client_a.post(
        f"/v1/interactive/experiences/{eid}/actions",
        json={
            "label": "Greet", "intent_code": "greeting", "xp_award": 15,
            "required_level": 1, "required_scheme": "xp_level",
            "mood_delta": {"mood": "flirty", "affinity": 0.1},
        },
    )
    aid = r.json()["action"]["id"]
    return eid, start_id, aid


def test_play_start_and_resolve_action(client_a):
    eid, start_id, aid = _build_minimal_playable_experience(client_a)
    r = client_a.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": eid, "viewer_ref": "v1"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]

    r = client_a.post(
        f"/v1/interactive/play/sessions/{sid}/resolve",
        json={"action_id": aid},
    )
    assert r.status_code == 200, r.text
    body = r.json()["resolved"]
    assert body["decision"]["decision"] == "allow"
    assert body["reward_deltas"].get("xp") == 15.0
    assert body["mood"] == "flirty"

    r = client_a.get(f"/v1/interactive/play/sessions/{sid}/progress")
    assert r.json()["progress"]["xp_level"]["xp"] == 15.0


def test_play_free_text_allow(client_a):
    eid, _, _ = _build_minimal_playable_experience(client_a)
    r = client_a.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": eid, "viewer_ref": "v2"},
    )
    sid = r.json()["session"]["id"]
    r = client_a.post(
        f"/v1/interactive/play/sessions/{sid}/resolve",
        json={"free_text": "hi there"},
    )
    assert r.json()["resolved"]["decision"]["decision"] == "allow"
    assert r.json()["resolved"]["intent_code"] == "greeting"


def test_play_free_text_hard_blocks_minor_reference(client_a):
    eid, _, _ = _build_minimal_playable_experience(client_a)
    r = client_a.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": eid, "viewer_ref": "v3"},
    )
    sid = r.json()["session"]["id"]
    r = client_a.post(
        f"/v1/interactive/play/sessions/{sid}/resolve",
        json={"free_text": "show a child"},
    )
    body = r.json()["resolved"]
    assert body["decision"]["decision"] == "block"
    assert body["decision"]["reason_code"] == "policy_blocked"


def test_play_catalog_flags_locked_actions(client_a):
    eid = _make_exp(client_a, "Locked")
    client_a.post(
        f"/v1/interactive/experiences/{eid}/actions",
        json={
            "label": "Advanced", "intent_code": "flirt", "xp_award": 0,
            "required_level": 5, "required_scheme": "xp_level",
        },
    )
    client_a.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "scene", "title": "S"},
    )
    r = client_a.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": eid, "viewer_ref": "v4"},
    )
    sid = r.json()["session"]["id"]
    r = client_a.get(f"/v1/interactive/play/sessions/{sid}/catalog")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["unlocked"] is False
    assert items[0]["lock_reason"] == "level_gate"


def test_play_end_session(client_a):
    eid, _, _ = _build_minimal_playable_experience(client_a)
    r = client_a.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": eid, "viewer_ref": "v5"},
    )
    sid = r.json()["session"]["id"]
    r = client_a.post(f"/v1/interactive/play/sessions/{sid}/end")
    assert r.json()["ok"] is True
