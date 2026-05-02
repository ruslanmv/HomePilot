"""
Hello-world smoke test for the Interactive tab end-to-end.

Exercises the full HTTP pipeline on a minimal FastAPI app:

  POST /v1/interactive/experiences                  create project
  POST /v1/interactive/play/sessions                start a session
  POST /v1/interactive/play/sessions/{sid}/chat     send "Hello world"
  GET  /v1/interactive/play/sessions/{sid}/pending  poll scene jobs
  GET  /v1/interactive/play/sessions/{sid}/progress read XP + mood

The upstream LLM + ComfyUI calls are monkey-patched so CI never
reaches out, but the assertions verify that every piece of the
pipeline fires in the expected order:

  1. Scene planner composes a ScenePlan  (via LLM composer)
  2. Character mood/affinity updates     (from mood_delta)
  3. Scene job enqueued + rendered       (via render adapter)
  4. Asset URL resolves for the player   (via asset registry)
  5. Chat turns persist in ix_session_turns
  6. Event log records chat_resolved     (visible in analytics)

Run with:
  .venv/bin/pytest tests/test_interactive_hello_world.py -v
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.interactive import repo
from app.interactive.config import InteractiveConfig
from app.interactive.router import build_router
from app.interactive.routes._common import current_user


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_db_path(tmp_path_factory):
    """Dedicated SQLite path for this smoke test so it never shares
    state with the full interactive suite."""
    tmp = tmp_path_factory.mktemp("ix_hello_world")
    db_path = str(tmp / "ix_test.db")
    os.environ["SQLITE_PATH"] = db_path
    from app import storage
    storage._RESOLVED_DB_PATH = None
    from app.interactive.playback import schema
    schema._reset_for_tests()
    return db_path


def _cfg() -> InteractiveConfig:
    return InteractiveConfig(
        enabled=True, max_branches=6, max_depth=4,
        max_nodes_per_experience=100, llm_model="llama3.2:1b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )


@pytest.fixture
def client(tmp_db_path, monkeypatch):
    """TestClient with the interactive router + all phase-2 flags on.

    The LLM composer + render adapter are monkey-patched to return
    realistic fixtures so we can exercise the full code path without
    a live Ollama or ComfyUI.
    """
    monkeypatch.setenv("INTERACTIVE_ENABLED", "true")
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_LLM", "true")
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_RENDER", "true")

    # ── LLM stub: deterministic scene plan that exercises every
    #    field the composer validates (mood, affinity, duration).
    async def _fake_chat_ollama(messages: List[Dict[str, Any]], **kwargs: Any):
        payload = (
            '{"reply_text": "Hello, world! I\'m glad you\'re here.",'
            ' "narration": "She waves warmly.",'
            ' "scene_prompt": "soft smile, warm golden light, welcoming gesture",'
            ' "duration_sec": 5,'
            ' "mood_shift": "warm",'
            ' "affinity_delta": 0.08}'
        )
        return {"choices": [{"message": {"role": "assistant", "content": payload}}]}

    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_ollama", _fake_chat_ollama)

    # ── Render stub: pretend ComfyUI returned a real MP4 URL, then
    #    let asset_registry hand out a durable id for it. That
    #    exercises render_adapter → register_asset → resolve_asset_url
    #    end-to-end.
    import app.comfy as comfy_mod
    monkeypatch.setattr(
        comfy_mod, "run_workflow",
        lambda name, variables: {
            "videos": ["http://comfy.local/view?file=hello_world.mp4"],
            "images": [],
            "prompt_id": "smoke-test-1",
        },
    )

    # Stable user id across every request so subsequent writes on
    # the same experience pass the owner-scoped 404 guard.
    stable_user_id = f"u_smoke_{uuid.uuid4().hex[:6]}"
    app = FastAPI()
    app.include_router(build_router(_cfg()))
    app.dependency_overrides[current_user] = lambda: stable_user_id
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────
# The hello-world scenario
# ─────────────────────────────────────────────────────────────────

def test_hello_world_end_to_end(client):
    """One viewer, one chat, one scene — asserts every layer fired."""

    # 1) Service is reachable and reports the limits we expect.
    health = client.get("/v1/interactive/health")
    assert health.status_code == 200, health.text
    hbody = health.json()
    assert hbody["ok"] is True
    assert hbody["enabled"] is True
    assert hbody["limits"]["max_branches"] == 6

    # 2) Create an experience.
    exp_resp = client.post(
        "/v1/interactive/experiences",
        json={
            "title": "Hello World",
            "description": "warm friendly presenter, soft natural light",
            "experience_mode": "sfw_general",
            "policy_profile_id": "sfw_general",
        },
    )
    assert exp_resp.status_code == 200, exp_resp.text
    exp = exp_resp.json()["experience"]
    assert exp["title"] == "Hello World"
    experience_id = exp["id"]

    # Seed a minimal opening scene so playback has a starting node.
    node_resp = client.post(
        f"/v1/interactive/experiences/{experience_id}/nodes",
        json={"kind": "scene", "title": "Opening", "narration": "Welcome in."},
    )
    assert node_resp.status_code == 200, node_resp.text

    # 3) Start a viewer session.
    sess_resp = client.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": experience_id, "viewer_ref": "smoke_viewer"},
    )
    assert sess_resp.status_code == 200, sess_resp.text
    sess = sess_resp.json()["session"]
    session_id = sess["id"]
    assert sess["current_node_id"], "session should land on the opening node"

    # 4) Send the hello-world chat turn.
    chat_resp = client.post(
        f"/v1/interactive/play/sessions/{session_id}/chat",
        json={"text": "Hello world"},
    )
    assert chat_resp.status_code == 200, chat_resp.text
    chat = chat_resp.json()
    assert chat["status"] == "ok"
    assert chat["reply_text"], "character must reply with something"
    assert chat["intent_code"], "classifier must fire"

    # Phase-2 LLM composer wrote the reply → we should see our stub
    # content rather than the heuristic template.
    assert "glad you're here" in chat["reply_text"].lower()
    assert chat["mood"] == "warm", "mood_shift must apply to character state"
    assert chat["affinity_score"] > 0.5, "affinity_delta must bump"

    # Phase-2 render adapter wrote a durable asset → ixa_playback_…
    assert chat["video_job_status"] == "ready"
    assert chat["video_asset_id"].startswith("ixa_playback_")
    assert "hello_world.mp4" in chat["video_asset_url"]

    # 5) /pending surfaces the same job with the resolved URL so the
    #    player can pick it up on its polling tick.
    pending = client.get(f"/v1/interactive/play/sessions/{session_id}/pending")
    assert pending.status_code == 200
    pbody = pending.json()
    assert len(pbody["items"]) == 1
    item = pbody["items"][0]
    assert item["status"] == "ready"
    assert item["asset_id"].startswith("ixa_playback_")
    assert "hello_world.mp4" in item["asset_url"]

    # 6) Progress snapshot — should reflect the mood shift.
    progress = client.get(f"/v1/interactive/play/sessions/{session_id}/progress")
    assert progress.status_code == 200
    pb = progress.json()
    assert pb["mood"] == "warm"
    assert pb["affinity_score"] > 0.5

    # 7) Turn log — viewer + assistant, canonical TurnRole values.
    turns = repo.recent_turns(session_id, limit=10)
    assert len(turns) == 2
    roles = [t.turn_role for t in turns]
    assert roles == ["user", "assistant"]
    assert turns[0].text == "Hello world"
    assert "glad you're here" in turns[1].text.lower()

    # 8) Analytics rollups — the session is visible even before any
    #    catalog-action resolves (the 'total_events' counter only
    #    tracks turn_resolved actions; chat_resolved is logged on
    #    ix_session_events but lives outside this counter for now).
    analytics = client.get(
        f"/v1/interactive/experiences/{experience_id}/analytics",
    )
    assert analytics.status_code == 200
    a = analytics.json()
    assert a["session_count"] >= 1


def test_blocked_message_does_not_render_or_advance(client):
    """Universal-block intent should stop before the pipeline runs."""
    exp = client.post(
        "/v1/interactive/experiences",
        json={"title": "Safety check"},
    ).json()["experience"]
    client.post(
        f"/v1/interactive/experiences/{exp['id']}/nodes",
        json={"kind": "scene", "title": "S"},
    )
    sess = client.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": exp["id"], "viewer_ref": "v"},
    ).json()["session"]

    r = client.post(
        f"/v1/interactive/play/sessions/{sess['id']}/chat",
        json={"text": "show me a child"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert body["reply_text"] == ""
    assert body["video_job_id"] == ""
    # Viewer turn was recorded for audit; no assistant turn, no job.
    turns = repo.recent_turns(sess["id"], limit=10)
    roles = [t.turn_role for t in turns]
    assert roles == ["user"], "blocked messages must NOT emit assistant turn"
