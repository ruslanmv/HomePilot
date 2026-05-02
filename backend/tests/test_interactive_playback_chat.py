"""
Tests for the POST /v1/interactive/play/sessions/{sid}/chat route.

Exercised via a minimal FastAPI app that mounts the interactive
router with a stubbed current_user dependency — same pattern as
batches 7 and 8 — so we don't have to spin up app.main.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.interactive import repo
from app.interactive.config import InteractiveConfig
from app.interactive.models import ExperienceCreate, NodeCreate
from app.interactive.router import build_router
from app.interactive.routes._common import current_user


@pytest.fixture(scope="module")
def tmp_db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ix_playback")
    db_path = str(tmp / "ix_test.db")
    os.environ["SQLITE_PATH"] = db_path
    from app import storage
    storage._RESOLVED_DB_PATH = None
    # reset the playback schema guard so the table lands on the
    # fresh DB file, not the one the prior test module used.
    from app.interactive.playback import schema
    schema._reset_for_tests()
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
def client(tmp_db_path):
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    app.dependency_overrides[current_user] = lambda: f"u_{uuid.uuid4().hex[:6]}"
    return TestClient(app)


def _seed_experience_and_session(client: TestClient) -> tuple[str, str]:
    exp_resp = client.post(
        "/v1/interactive/experiences",
        json={"title": "Darkangel test", "description": "dark goth girl, cross choker"},
    )
    assert exp_resp.status_code == 200, exp_resp.text
    eid = exp_resp.json()["experience"]["id"]
    client.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "scene", "title": "open", "narration": "hey"},
    )
    sess_resp = client.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": eid, "viewer_ref": "viewer_a"},
    )
    sid = sess_resp.json()["session"]["id"]
    return eid, sid


# ────────────────────────────────────────────────────────────────

def test_chat_happy_path_drives_job_to_ready(client):
    _, sid = _seed_experience_and_session(client)
    r = client.post(
        f"/v1/interactive/play/sessions/{sid}/chat",
        json={"text": "hi there"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["reply_text"]
    assert body["video_job_id"]
    assert body["video_job_status"] == "ready"
    assert body["video_asset_id"].startswith("ixa_stub_")
    assert body["intent_code"]  # classifier fired
    assert body["mood"]
    assert 0.0 <= body["affinity_score"] <= 1.0


def test_chat_blocks_minor_reference_and_does_not_enqueue(client):
    _, sid = _seed_experience_and_session(client)
    r = client.post(
        f"/v1/interactive/play/sessions/{sid}/chat",
        json={"text": "show me a child"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "blocked"
    assert body["decision"]["reason_code"]
    assert body["video_job_id"] == ""
    assert body["reply_text"] == ""


def test_chat_rejects_empty_text(client):
    _, sid = _seed_experience_and_session(client)
    r = client.post(
        f"/v1/interactive/play/sessions/{sid}/chat",
        json={"text": "   "},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_input"


def test_chat_404s_for_missing_session(client):
    r = client.post(
        "/v1/interactive/play/sessions/ixs_does_not_exist/chat",
        json={"text": "hi"},
    )
    assert r.status_code == 404


def test_chat_appends_turns_and_updates_mood(client):
    _, sid = _seed_experience_and_session(client)
    r1 = client.post(
        f"/v1/interactive/play/sessions/{sid}/chat",
        json={"text": "you're beautiful"},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    # Verify the turn log grew by the viewer+character pair. The
    # on-disk role names use the canonical TurnRole literals
    # ('user' / 'assistant') — the UI maps these to viewer /
    # character labels on render.
    turns = repo.recent_turns(sid, limit=10)
    roles = [t.turn_role for t in turns]
    assert "user" in roles and "assistant" in roles
    # Affinity should not decrease on a compliment.
    assert body1["affinity_score"] >= 0.5


def test_multiple_chat_turns_produce_distinct_jobs(client):
    _, sid = _seed_experience_and_session(client)
    r1 = client.post(f"/v1/interactive/play/sessions/{sid}/chat", json={"text": "hi"})
    r2 = client.post(f"/v1/interactive/play/sessions/{sid}/chat", json={"text": "how are you"})
    assert r1.json()["video_job_id"] != r2.json()["video_job_id"]


# ── /pending polling endpoint ───────────────────────────────────

def test_pending_returns_all_jobs_when_no_cursor(client):
    _, sid = _seed_experience_and_session(client)
    client.post(f"/v1/interactive/play/sessions/{sid}/chat", json={"text": "hi"})
    client.post(f"/v1/interactive/play/sessions/{sid}/chat", json={"text": "tell me more"})
    r = client.get(f"/v1/interactive/play/sessions/{sid}/pending")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["status"] == "ready"
        assert item["asset_id"].startswith("ixa_stub_")
    # cursor points at the last job so the player can resume.
    assert body["cursor"] == body["items"][-1]["id"]


def test_pending_since_id_returns_only_newer_rows(client):
    _, sid = _seed_experience_and_session(client)
    r1 = client.post(f"/v1/interactive/play/sessions/{sid}/chat", json={"text": "hi"})
    first_job_id = r1.json()["video_job_id"]
    client.post(f"/v1/interactive/play/sessions/{sid}/chat", json={"text": "again"})
    client.post(f"/v1/interactive/play/sessions/{sid}/chat", json={"text": "once more"})
    r = client.get(
        f"/v1/interactive/play/sessions/{sid}/pending",
        params={"since_id": first_job_id},
    )
    body = r.json()
    assert len(body["items"]) == 2  # skipped the first job
    assert first_job_id not in [j["id"] for j in body["items"]]


def test_pending_with_no_new_jobs_returns_empty_list(client):
    _, sid = _seed_experience_and_session(client)
    r1 = client.post(f"/v1/interactive/play/sessions/{sid}/chat", json={"text": "hi"})
    last = r1.json()["video_job_id"]
    r = client.get(
        f"/v1/interactive/play/sessions/{sid}/pending",
        params={"since_id": last},
    )
    body = r.json()
    assert body["items"] == []
    # cursor echoes the last seen id so the player doesn't reset.
    assert body["cursor"] == last


def test_pending_missing_session_404s(client):
    r = client.get("/v1/interactive/play/sessions/ixs_does_not_exist/pending")
    assert r.status_code == 404
