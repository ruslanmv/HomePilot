"""
BATCH B: GET /v1/interactive/experiences/{id}/generate-all/stream.

Full-project generation SSE: plan + graph (reuses /auto-generate
events) + per-scene asset rendering loop. Verifies:

* Rendering events are emitted once per scene/decision node.
* Render flag off → every scene emits ``scene_skipped``.
* Render flag on + successful adapter → ``scene_rendered`` events
  carry the asset_id and patch the node's asset_ids.
* Render flag on + adapter failure → ``scene_render_failed`` but
  the loop keeps going (non-fatal per scene).
* Idempotent: running /generate-all/stream a second time skips
  nodes that already carry asset_ids.
* Final ``result`` frame bundles the existing auto-generate
  payload + a ``rendering`` stats dict.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# NOTE: interactive modules are imported lazily via the autouse
# refresh fixture below. Top-level imports would freeze references
# to whichever module copy was live at pytest-collection time —
# conftest's ``app`` session fixture then purges + re-imports
# ``app.*`` modules so anything the test captured up top becomes
# an orphan. The runtime ``build_router`` closure must line up
# with the module the test patches; re-resolving both on each
# test function keeps them consistent.


@pytest.fixture(scope="module")
def tmp_db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ix_gen_all_stream")
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
def _force_legacy_autogen(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_AUTOGEN_LEGACY", "true")
    monkeypatch.delenv("INTERACTIVE_AUTOGEN_WORKFLOW", raising=False)
    yield


@pytest.fixture
def client(tmp_db_path):
    # Lazy-import + freshly resolve everything the TestClient
    # depends on — so build_router's closure captures the CURRENT
    # module graph, not a pre-purge orphan.
    from app.interactive.router import build_router
    from app.interactive.routes._common import current_user
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    stable = f"u_gen_all_{uuid.uuid4().hex[:6]}"
    app.dependency_overrides[current_user] = lambda: stable
    return TestClient(app)


def _make_experience(client, *, media_type: str = "video") -> str:
    r = client.post(
        "/v1/interactive/experiences",
        json={
            "title": "Generate-all demo",
            "description": "Walk a viewer through a two-path choice.",
            "experience_mode": "sfw_general",
            "policy_profile_id": "sfw_general",
            "audience_profile": {
                "role": "viewer",
                "level": "beginner",
                "language": "en",
                "render_media_type": media_type,
            },
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


# ── Render flag off: emits scene_skipped per node ───────────────

def test_stream_skips_scenes_when_render_disabled(client, monkeypatch):
    monkeypatch.delenv("INTERACTIVE_PLAYBACK_RENDER", raising=False)
    eid = _make_experience(client)
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/generate-all/stream",
    ) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes())

    frames = _parse_sse(body)
    kinds = [f["type"] for f in frames]

    # Graph phase still runs.
    assert "generating_graph" in kinds
    assert "graph_generated" in kinds
    assert "running_qa" in kinds

    # Render phase kicks in with a total scene count.
    rs = next(f for f in frames if f["type"] == "rendering_started")
    total = rs["payload"]["total"]
    assert total >= 1
    # Each scene emits a skip event (render flag off).
    skipped = [f for f in frames if f["type"] == "scene_skipped"]
    assert len(skipped) == total
    assert all(f["payload"]["reason"] in {
        "render_disabled_or_empty", "already_rendered",
    } for f in skipped)

    rd = next(f for f in frames if f["type"] == "rendering_done")
    assert rd["payload"]["total"] == total
    assert rd["payload"]["rendered"] == 0
    assert rd["payload"]["skipped"] == total
    assert rd["payload"]["failed"] == 0

    result = next(f for f in frames if f["type"] == "result")
    assert result["payload"]["ok"] is True
    assert result["payload"]["rendering"]["total"] == total
    assert kinds[-1] == "done"


# ── Render flag on: scene_rendered carries asset_id ─────────────

def test_stream_emits_scene_rendered_with_adapter(
    client, monkeypatch,
):
    # Patch the late-imported render_scene_async on the route
    # module so every scene lands a fake asset id. The shared
    # render_adapter module is left alone; other tests keep
    # working unchanged.
    import app.interactive.playback.render_adapter as ra_mod

    call_count = {"n": 0}

    async def fake_render(**kwargs):
        call_count["n"] += 1
        return f"ixa_test_{call_count['n']}"

    import sys
    print(f"\n[TST2-DBG] ra_mod id={id(ra_mod)} sys={id(sys.modules['app.interactive.playback.render_adapter'])} fn_id={id(ra_mod.render_scene_async)}")
    monkeypatch.setattr(ra_mod, "render_scene_async", fake_render)
    print(f"[TST2-DBG] after patch fn_id={id(ra_mod.render_scene_async)}")

    eid = _make_experience(client, media_type="image")
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/generate-all/stream",
    ) as r:
        body = b"".join(r.iter_bytes())
    frames = _parse_sse(body)

    rendered = [f for f in frames if f["type"] == "scene_rendered"]
    assert len(rendered) >= 1
    assert all(f["payload"]["asset_id"].startswith("ixa_test_") for f in rendered)

    rd = next(f for f in frames if f["type"] == "rendering_done")
    assert rd["payload"]["rendered"] == len(rendered)
    assert rd["payload"]["failed"] == 0

    # media_type propagated through the pipeline.
    rs = next(f for f in frames if f["type"] == "rendering_started")
    assert rs["payload"]["media_type"] == "image"

    # Node asset_ids actually persisted.
    for ev in rendered:
        scene_id = ev["payload"]["scene_id"]
        r2 = client.get(f"/v1/interactive/experiences/{eid}/nodes")
        nodes = r2.json()["items"]
        node = next(n for n in nodes if n["id"] == scene_id)
        assert ev["payload"]["asset_id"] in (node.get("asset_ids") or [])


# ── Adapter failure: emits scene_render_failed, loop continues ─

def test_stream_continues_when_one_scene_fails(client, monkeypatch):
    import app.interactive.playback.render_adapter as ra_mod

    fail_on_first = {"done": False}

    async def flaky(**kwargs):
        if not fail_on_first["done"]:
            fail_on_first["done"] = True
            raise RuntimeError("comfy is on fire")
        return "ixa_ok"

    monkeypatch.setattr(ra_mod, "render_scene_async", flaky)

    eid = _make_experience(client)
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/generate-all/stream",
    ) as r:
        body = b"".join(r.iter_bytes())
    frames = _parse_sse(body)
    kinds = [f["type"] for f in frames]

    assert "scene_render_failed" in kinds
    # Run still completes with result + done — one failure isn't fatal.
    assert kinds[-2] == "result"
    assert kinds[-1] == "done"

    rd = next(f for f in frames if f["type"] == "rendering_done")
    assert rd["payload"]["failed"] == 1
    # Remaining scenes produced ixa_ok.
    assert rd["payload"]["rendered"] == rd["payload"]["total"] - 1


# ── Idempotency: second call skips already-rendered nodes ──────

def test_stream_second_call_skips_already_rendered(client, monkeypatch):
    import app.interactive.playback.render_adapter as ra_mod

    async def fake_render(**kwargs):
        return "ixa_id_test"

    monkeypatch.setattr(ra_mod, "render_scene_async", fake_render)

    eid = _make_experience(client)
    # First call renders all scenes.
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/generate-all/stream",
    ) as r:
        body1 = b"".join(r.iter_bytes())
    frames1 = _parse_sse(body1)
    rd1 = next(f for f in frames1 if f["type"] == "rendering_done")
    assert rd1["payload"]["rendered"] >= 1
    assert rd1["payload"]["skipped"] == 0

    # Second call — graph already exists; scenes all carry asset_ids.
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/generate-all/stream",
    ) as r:
        body2 = b"".join(r.iter_bytes())
    frames2 = _parse_sse(body2)
    kinds2 = [f["type"] for f in frames2]

    # Graph phase short-circuits on already_generated.
    assert "already_generated" in kinds2
    assert "generating_graph" not in kinds2

    # Every scene emits already_rendered.
    skipped = [f for f in frames2 if f["type"] == "scene_skipped"]
    assert len(skipped) >= 1
    assert all(f["payload"]["reason"] == "already_rendered" for f in skipped)

    rd2 = next(f for f in frames2 if f["type"] == "rendering_done")
    assert rd2["payload"]["rendered"] == 0
    assert rd2["payload"]["skipped"] == rd2["payload"]["total"]


# ── Wire format: content-type + final done terminator ───────────

def test_stream_headers_and_terminator(client):
    eid = _make_experience(client)
    with client.stream(
        "GET", f"/v1/interactive/experiences/{eid}/generate-all/stream",
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes())
    frames = _parse_sse(body)
    assert frames[0]["type"] == "started"
    assert frames[-1]["type"] == "done"
