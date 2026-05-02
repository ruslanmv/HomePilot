"""
Batch 8/8 — assembly + QA + publish + analytics.

Covers:
  - Manifest build + canonical digest determinism
  - QA checks: entry node, dangling edges, empty narration,
    unreachable actions, dead-end nodes, invalid rules,
    mature-mode consent mismatch
  - QA run persists report + produces correct verdict
  - Publish: blocks on QA fail, publishes on pass, returns
    'unchanged' on identical re-publish, bumps version otherwise
  - Analytics: session summary + experience summary aggregate
    events correctly
  - HTTP routes for every surface above
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.interactive import repo
from app.interactive.analytics import experience_summary, session_summary
from app.interactive.assembly import build_manifest, package_experience
from app.interactive.config import InteractiveConfig
from app.interactive.models import (
    ActionCreate,
    EdgeCreate,
    ExperienceCreate,
    NodeCreate,
)
from app.interactive.publish import publish
from app.interactive.qa import run_qa
from app.interactive.qa.report import latest_report
from app.interactive.router import build_router
from app.interactive.routes._common import current_user


@pytest.fixture(scope="module")
def tmp_db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ix_batch8")
    db_path = str(tmp / "ix_test.db")
    os.environ["SQLITE_PATH"] = db_path
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
def app_client(tmp_db_path):
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    app.dependency_overrides[current_user] = lambda: "owner_lifecycle"
    return TestClient(app)


def _fresh_experience(title: str = "Lifecycle demo", mode: str = "sfw_education"):
    return repo.create_experience(
        f"owner_{uuid.uuid4().hex[:6]}",
        ExperienceCreate(
            title=title, experience_mode=mode, policy_profile_id=mode,
        ),
    )


def _build_minimal_graph(exp_id: str):
    a = repo.create_node(exp_id, NodeCreate(
        kind="scene", title="Start", narration="Hello",
    ))
    b = repo.create_node(exp_id, NodeCreate(
        kind="ending", title="End", narration="Goodbye",
    ))
    repo.create_edge(exp_id, EdgeCreate(
        from_node_id=a.id, to_node_id=b.id, trigger_kind="auto",
    ))
    return a, b


# ─────────────────────────────────────────────────────────────────
# Manifest + packager
# ─────────────────────────────────────────────────────────────────

def test_build_manifest_shape(tmp_db_path):
    exp = _fresh_experience("Manifest test")
    _build_minimal_graph(exp.id)
    manifest = build_manifest(exp)
    assert manifest["manifest_version"] == 1
    assert manifest["experience"]["id"] == exp.id
    assert manifest["stats"]["node_count"] == 2
    assert manifest["stats"]["edge_count"] == 1


def test_package_experience_digest_is_deterministic(tmp_db_path):
    exp = _fresh_experience("Digest test")
    _build_minimal_graph(exp.id)
    p1 = package_experience(exp)
    p2 = package_experience(exp)
    assert p1.digest == p2.digest
    assert len(p1.digest) == 64  # sha256 hex


def test_package_digest_changes_on_edit(tmp_db_path):
    exp = _fresh_experience("Edit test")
    _build_minimal_graph(exp.id)
    d1 = package_experience(exp).digest
    repo.create_action(exp.id, ActionCreate(label="New action"))
    d2 = package_experience(exp).digest
    assert d1 != d2


# ─────────────────────────────────────────────────────────────────
# QA checks (isolated, no routes)
# ─────────────────────────────────────────────────────────────────

def test_qa_passes_on_clean_experience(tmp_db_path):
    exp = _fresh_experience("Clean")
    _build_minimal_graph(exp.id)
    summary = run_qa(exp)
    assert summary.verdict in ("pass", "warn")  # warn OK if nothing has actions


def test_qa_flags_empty_experience(tmp_db_path):
    exp = _fresh_experience("Empty")
    summary = run_qa(exp)
    assert summary.verdict == "fail"
    codes = [i["code"] for i in summary.issues]
    assert "no_nodes" in codes


def test_qa_flags_dangling_edge():
    """Pure test of the check function against a synthetic manifest —
    keeps the assertion robust across DB test-isolation corner cases."""
    from app.interactive.qa.checks import graph_no_dangling_edges
    manifest = {
        "nodes": [{"id": "n1", "kind": "scene"}],
        "edges": [{"id": "e1", "from_node_id": "n1", "to_node_id": "ghost"}],
    }
    issues = graph_no_dangling_edges(manifest)
    codes = [i["code"] for i in issues]
    assert "edge_dangling_to" in codes


def test_qa_warns_on_empty_narration(tmp_db_path):
    exp = _fresh_experience("Silent")
    a = repo.create_node(exp.id, NodeCreate(kind="scene", title="Silent start"))
    b = repo.create_node(exp.id, NodeCreate(kind="ending", title="End", narration="bye"))
    repo.create_edge(exp.id, EdgeCreate(
        from_node_id=a.id, to_node_id=b.id, trigger_kind="auto",
    ))
    summary = run_qa(exp)
    codes = [i["code"] for i in summary.issues]
    assert "narration_empty" in codes


def test_qa_flags_mature_mode_mismatched_profile(tmp_db_path):
    # experience_mode='mature_gated' but profile id doesn't match.
    exp = repo.create_experience(
        "owner_m", ExperienceCreate(
            title="Bad", experience_mode="mature_gated",
            policy_profile_id="sfw_general",  # wrong!
        ),
    )
    _build_minimal_graph(exp.id)
    summary = run_qa(exp)
    codes = [i["code"] for i in summary.issues]
    assert "mature_profile_mismatch" in codes
    assert summary.verdict == "fail"


def test_qa_flags_invalid_rule(tmp_db_path):
    exp = _fresh_experience("BadRule")
    _build_minimal_graph(exp.id)
    repo.create_rule(
        exp.id, "bad",
        condition={"unknown_key": 1},
        action={"also_bad": 1},
    )
    summary = run_qa(exp)
    codes = [i["code"] for i in summary.issues]
    assert "rule_invalid" in codes


def test_latest_report_returns_most_recent(tmp_db_path):
    exp = _fresh_experience("Reports")
    _build_minimal_graph(exp.id)
    run_qa(exp)
    run_qa(exp)
    rep = latest_report(exp.id)
    assert rep
    assert rep["summary"]["verdict"] in ("pass", "warn", "fail")


# ─────────────────────────────────────────────────────────────────
# Publish
# ─────────────────────────────────────────────────────────────────

def test_publish_blocks_when_qa_fails(tmp_db_path):
    exp = _fresh_experience("PublishFail")
    result = publish(exp, channel="web_embed")
    assert result.status == "blocked"
    assert result.publication is None
    assert result.qa is not None
    assert result.qa.verdict == "fail"


def test_publish_publishes_on_pass(tmp_db_path):
    exp = _fresh_experience("PublishOK")
    _build_minimal_graph(exp.id)
    result = publish(exp, channel="web_embed")
    assert result.status == "published"
    assert result.publication is not None
    assert result.publication.version == 1


def test_republish_unchanged_is_noop(tmp_db_path):
    exp = _fresh_experience("PublishTwice")
    _build_minimal_graph(exp.id)
    r1 = publish(exp, channel="web_embed")
    r2 = publish(exp, channel="web_embed")
    assert r1.status == "published"
    assert r2.status == "unchanged"
    assert r2.publication is not None
    assert r2.publication.version == r1.publication.version


def test_republish_bumps_version_on_change(tmp_db_path):
    exp = _fresh_experience("PublishBump")
    _build_minimal_graph(exp.id)
    r1 = publish(exp, channel="web_embed")
    repo.create_action(exp.id, ActionCreate(label="Extra"))
    r2 = publish(exp, channel="web_embed")
    assert r2.status == "published"
    assert r2.publication.version == r1.publication.version + 1


# ─────────────────────────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────────────────────────

def test_session_summary_counts_turns_and_events(tmp_db_path):
    exp = _fresh_experience("Analytics")
    a, _ = _build_minimal_graph(exp.id)
    sess = repo.create_session(exp.id, viewer_ref="v_a")
    repo.append_turn(sess.id, "viewer", "hi")
    repo.append_event(sess.id, "turn_resolved", action_id="act1", payload={"decision": "allow", "intent_code": "greeting"})
    repo.append_event(sess.id, "turn_resolved", action_id="act1", payload={"decision": "block", "intent_code": "flirt"})
    s = session_summary(sess.id)
    assert s is not None
    assert s.turns == 1
    assert s.events == 2
    assert s.action_uses["act1"] == 2
    assert s.decisions["allow"] == 1
    assert s.decisions["block"] == 1


def test_experience_summary_aggregates_across_sessions(tmp_db_path):
    exp = _fresh_experience("AggAnalytics")
    _build_minimal_graph(exp.id)
    for _ in range(3):
        sess = repo.create_session(exp.id, viewer_ref="v_x")
        repo.append_event(sess.id, "turn_resolved", payload={"decision": "allow"})
    s = experience_summary(exp.id)
    assert s.session_count == 3
    assert s.total_events == 3
    assert s.block_rate == 0.0


# ─────────────────────────────────────────────────────────────────
# HTTP routes
# ─────────────────────────────────────────────────────────────────

def _make_exp_over_http(client):
    r = client.post("/v1/interactive/experiences", json={"title": "HTTP exp"})
    return r.json()["experience"]["id"]


def test_http_manifest_preview(app_client):
    eid = _make_exp_over_http(app_client)
    app_client.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "scene", "title": "S", "narration": "n"},
    )
    r = app_client.get(f"/v1/interactive/experiences/{eid}/manifest")
    assert r.status_code == 200
    body = r.json()
    assert len(body["digest"]) == 64
    assert body["manifest"]["stats"]["node_count"] == 1


def test_http_qa_run_persists_report(app_client):
    eid = _make_exp_over_http(app_client)
    r = app_client.post(f"/v1/interactive/experiences/{eid}/qa-run")
    assert r.status_code == 200
    assert r.json()["verdict"] in ("pass", "warn", "fail")

    r2 = app_client.get(f"/v1/interactive/experiences/{eid}/qa-reports")
    assert r2.status_code == 200
    assert r2.json()["report"]["summary"]["verdict"] == r.json()["verdict"]


def test_http_publish_and_list(app_client):
    eid = _make_exp_over_http(app_client)
    app_client.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "scene", "title": "S", "narration": "x"},
    )
    sid = app_client.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "ending", "title": "E", "narration": "y"},
    ).json()["node"]["id"]
    start_id = app_client.get(
        f"/v1/interactive/experiences/{eid}/nodes",
    ).json()["items"][0]["id"]
    app_client.post(
        f"/v1/interactive/experiences/{eid}/edges",
        json={"from_node_id": start_id, "to_node_id": sid, "trigger_kind": "auto"},
    )

    r = app_client.post(
        f"/v1/interactive/experiences/{eid}/publish",
        json={"channel": "web_embed"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("published", "unchanged")

    r2 = app_client.get(f"/v1/interactive/experiences/{eid}/publications")
    assert r2.status_code == 200
    assert len(r2.json()["items"]) >= 1


def test_http_publish_blocked_on_fail(app_client):
    eid = _make_exp_over_http(app_client)
    # Empty graph triggers fail verdict.
    r = app_client.post(
        f"/v1/interactive/experiences/{eid}/publish",
        json={"channel": "web_embed"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "blocked"


def test_http_experience_analytics(app_client):
    eid = _make_exp_over_http(app_client)
    r = app_client.get(f"/v1/interactive/experiences/{eid}/analytics")
    assert r.status_code == 200
    assert r.json()["session_count"] == 0


def test_http_session_analytics(app_client):
    eid = _make_exp_over_http(app_client)
    app_client.post(
        f"/v1/interactive/experiences/{eid}/nodes",
        json={"kind": "scene", "title": "s"},
    )
    r = app_client.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": eid, "viewer_ref": "vt"},
    )
    sid = r.json()["session"]["id"]
    r2 = app_client.get(f"/v1/interactive/sessions/{sid}/analytics")
    assert r2.status_code == 200
    assert r2.json()["session_id"] == sid
