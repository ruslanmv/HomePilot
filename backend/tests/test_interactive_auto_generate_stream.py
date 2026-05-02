"""
PIPE-2: GET /v1/interactive/experiences/{id}/auto-generate/stream.

Verifies the SSE wire format + per-phase events are emitted in
the right order, and that the final result mirrors the POST
route's payload. Uses the heuristic path so no LLM mocking is
needed — still gives us four real phases (generating_graph,
persisting_nodes, persisting_edges, persisting_actions, etc.).
"""
from __future__ import annotations

import json
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
    tmp = tmp_path_factory.mktemp("ix_auto_gen_stream")
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


@pytest.fixture(autouse=True)
def _force_legacy_autogen(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_AUTOGEN_LEGACY", "true")
    monkeypatch.delenv("INTERACTIVE_AUTOGEN_WORKFLOW", raising=False)
    yield


@pytest.fixture
def client(tmp_db_path):
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    stable = f"u_stream_{uuid.uuid4().hex[:6]}"
    app.dependency_overrides[current_user] = lambda: stable
    return TestClient(app)


def _make_experience(client) -> str:
    r = client.post(
        "/v1/interactive/experiences",
        json={
            "title": "Stream gen demo",
            "description": "Walk a viewer through a two-path choice.",
            "experience_mode": "sfw_general",
            "policy_profile_id": "sfw_general",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["experience"]["id"]


def _parse_sse(body: bytes) -> List[Dict[str, Any]]:
    frames: List[Dict[str, Any]] = []
    for block in body.decode("utf-8").split("\n\n"):
        block = block.strip()
        if not block or not block.startswith("data:"):
            continue
        frames.append(json.loads(block[len("data:"):].lstrip()))
    return frames


# ── Happy path ────────────────────────────────────────────────

def test_stream_emits_phase_events_in_order(client):
    eid = _make_experience(client)
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/auto-generate/stream",
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes())

    frames = _parse_sse(body)
    kinds = [f["type"] for f in frames]

    assert kinds[0] == "started"
    assert "generating_graph" in kinds
    assert "graph_generated" in kinds
    assert "persisting_nodes" in kinds
    assert "persisting_edges" in kinds
    assert "persisting_actions" in kinds
    assert "seeding_rule" in kinds
    assert "running_qa" in kinds
    assert kinds[-2] == "result"
    assert kinds[-1] == "done"

    # Result frame mirrors the POST payload.
    result_frame = next(f for f in frames if f["type"] == "result")
    payload = result_frame["payload"]
    assert payload["ok"] is True
    assert payload["already_generated"] is False
    assert payload["node_count"] >= 2
    assert payload["edge_count"] >= 1


def test_stream_phase_payloads_carry_counts(client):
    eid = _make_experience(client)
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/auto-generate/stream",
    ) as r:
        body = b"".join(r.iter_bytes())
    frames = _parse_sse(body)

    graph_generated = next(f for f in frames if f["type"] == "graph_generated")
    assert graph_generated["payload"]["node_count"] >= 2
    assert graph_generated["payload"]["edge_count"] >= 1

    persist_nodes = next(f for f in frames if f["type"] == "persisting_nodes")
    assert persist_nodes["payload"]["count"] >= 2


# ── Idempotent second call ────────────────────────────────────

def test_stream_on_already_generated_short_circuits(client):
    eid = _make_experience(client)
    # Seed the graph via the POST route first.
    r1 = client.post(f"/v1/interactive/experiences/{eid}/auto-generate")
    assert r1.status_code == 200 and r1.json()["already_generated"] is False

    # Now stream — should emit already_generated + result + done.
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/auto-generate/stream",
    ) as r:
        body = b"".join(r.iter_bytes())
    frames = _parse_sse(body)
    kinds = [f["type"] for f in frames]

    assert kinds[0] == "started"
    assert "already_generated" in kinds
    # No generation phase events on the idempotent path.
    assert "generating_graph" not in kinds
    assert "persisting_nodes" not in kinds
    assert kinds[-2] == "result"
    assert kinds[-1] == "done"

    result_frame = next(f for f in frames if f["type"] == "result")
    assert result_frame["payload"]["already_generated"] is True
    assert result_frame["payload"]["source"] == "existing"


# ── Result frame matches POST body ─────────────────────────────

def test_stream_result_matches_post_payload_shape(client):
    eid_stream = _make_experience(client)
    eid_post = _make_experience(client)

    # Stream path.
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid_stream}/auto-generate/stream",
    ) as r:
        body = b"".join(r.iter_bytes())
    stream_frames = _parse_sse(body)
    stream_result = next(f for f in stream_frames if f["type"] == "result")["payload"]

    # POST path for a sibling experience.
    post_body = client.post(
        f"/v1/interactive/experiences/{eid_post}/auto-generate",
    ).json()

    # Same keys, same top-level structure.
    assert set(stream_result.keys()) == set(post_body.keys())
    for key in ("ok", "source", "already_generated"):
        assert stream_result[key] == post_body[key]
