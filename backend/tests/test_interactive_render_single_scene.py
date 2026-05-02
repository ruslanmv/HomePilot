"""
EDIT-3: POST /v1/interactive/experiences/{id}/nodes/{node_id}/render.

Single-scene re-render for Editor "Regenerate" buttons. Verifies:

* Missing node → 404.
* Render flag off → status=skipped, reason="render_disabled_or_empty".
* Render flag on + successful adapter → status=rendered, asset_id
  returned, node.asset_ids updated (replaces, not appends, so
  stale ids don't leak into player session state).
* Adapter exception → status=failed with reason message.
* Scoping: rendering a node that belongs to a different user's
  experience returns 404 (no privacy leak).
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def tmp_db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ix_render_single")
    os.environ["SQLITE_PATH"] = str(tmp / "ix_test.db")
    from app import storage
    storage._RESOLVED_DB_PATH = None
    return os.environ["SQLITE_PATH"]


def _cfg():
    from app.interactive.config import InteractiveConfig
    return InteractiveConfig(
        enabled=True, max_branches=6, max_depth=4,
        max_nodes_per_experience=100, llm_model="llama3:8b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )


@pytest.fixture(autouse=True)
def _force_legacy(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_AUTOGEN_LEGACY", "true")
    yield


@pytest.fixture
def client(tmp_db_path):
    from app.interactive.router import build_router
    from app.interactive.routes._common import current_user
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    stable = f"u_render_{uuid.uuid4().hex[:6]}"
    app.dependency_overrides[current_user] = lambda: stable
    return TestClient(app)


def _seed_experience(client) -> tuple[str, str]:
    """Create + generate; return (experience_id, first_scene_id)."""
    r = client.post("/v1/interactive/experiences", json={
        "title": "Single-scene render test",
        "description": "A minimal two-scene project.",
        "experience_mode": "sfw_general",
        "policy_profile_id": "sfw_general",
        "audience_profile": {"render_media_type": "image"},
    })
    assert r.status_code == 200
    eid = r.json()["experience"]["id"]
    r2 = client.post(f"/v1/interactive/experiences/{eid}/auto-generate")
    assert r2.status_code == 200
    r3 = client.get(f"/v1/interactive/experiences/{eid}/nodes")
    nodes = r3.json()["items"]
    scene = next(
        n for n in nodes
        if n["kind"] in ("scene", "decision")
    )
    return eid, scene["id"]


# ── 404 paths ───────────────────────────────────────────────────

def test_missing_node_returns_404(client):
    eid, _ = _seed_experience(client)
    r = client.post(
        f"/v1/interactive/experiences/{eid}/nodes/nope/render",
    )
    assert r.status_code == 404


def test_missing_experience_returns_404(client):
    # Nonexistent experience still gates via scoped_experience → 404.
    r = client.post(
        "/v1/interactive/experiences/ixe_nothere/nodes/ixn_x/render",
    )
    assert r.status_code == 404


# ── Flag off → skipped ─────────────────────────────────────────

def test_render_flag_off_returns_skipped(client, monkeypatch):
    # Render default flipped ON — explicit opt-out exercises the
    # skip path.
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER", "false")
    eid, nid = _seed_experience(client)
    r = client.post(
        f"/v1/interactive/experiences/{eid}/nodes/{nid}/render",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "skipped"
    assert body["reason"] == "render_disabled_or_empty"


# ── Flag on + fake adapter → rendered ──────────────────────────

def test_render_flag_on_returns_asset_and_patches_node(
    client, monkeypatch,
):
    import app.interactive.playback.render_adapter as ra_mod

    async def fake_render(**kwargs):
        return "ixa_single_test"

    monkeypatch.setattr(ra_mod, "render_scene_async", fake_render)

    eid, nid = _seed_experience(client)
    r = client.post(
        f"/v1/interactive/experiences/{eid}/nodes/{nid}/render",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "rendered"
    assert body["asset_id"] == "ixa_single_test"
    assert body["media_type"] == "image"

    # Node's asset_ids has been updated (replace semantics).
    r2 = client.get(f"/v1/interactive/experiences/{eid}/nodes")
    node = next(n for n in r2.json()["items"] if n["id"] == nid)
    assert node["asset_ids"] == ["ixa_single_test"]


# ── Adapter exception → failed ─────────────────────────────────

def test_render_exception_returns_failed(client, monkeypatch):
    import app.interactive.playback.render_adapter as ra_mod

    async def boom(**kwargs):
        raise RuntimeError("comfy crashed")

    monkeypatch.setattr(ra_mod, "render_scene_async", boom)

    eid, nid = _seed_experience(client)
    r = client.post(
        f"/v1/interactive/experiences/{eid}/nodes/{nid}/render",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "failed"
    assert "comfy crashed" in body["reason"]


# ── Second call replaces (not appends) asset_ids ───────────────

def test_second_render_replaces_asset_ids(client, monkeypatch):
    import app.interactive.playback.render_adapter as ra_mod

    calls = {"n": 0}

    async def fake_render(**kwargs):
        calls["n"] += 1
        return f"ixa_round_{calls['n']}"

    monkeypatch.setattr(ra_mod, "render_scene_async", fake_render)

    eid, nid = _seed_experience(client)
    client.post(f"/v1/interactive/experiences/{eid}/nodes/{nid}/render")
    client.post(f"/v1/interactive/experiences/{eid}/nodes/{nid}/render")

    r2 = client.get(f"/v1/interactive/experiences/{eid}/nodes")
    node = next(n for n in r2.json()["items"] if n["id"] == nid)
    # Replace, not append — player uses the latest render.
    assert node["asset_ids"] == ["ixa_round_2"]
