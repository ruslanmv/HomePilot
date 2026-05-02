"""
HTTP tests for POST /v1/interactive/plan-auto/stream (REV-5).

Verifies the SSE wire format (``data: {…}\\n\\n`` frames) and the
shape of each event kind emitted by the stage-1 workflow:

* workflow_started  — carries the step ids
* step_started      — one per attempt per step
* step_completed    — carries the duration + value preview
* workflow_completed — ok=True on success
* result            — final {form, source, …} payload
* done              — terminator

Abort path exercises the ``fallback`` event + heuristic result.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.interactive.config import InteractiveConfig
from app.interactive.router import build_router
from app.interactive.routes._common import current_user


@pytest.fixture(scope="module")
def tmp_db_path(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ix_plan_stream")
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
    user_id = f"u_plan_stream_{uuid.uuid4().hex[:6]}"
    app.dependency_overrides[current_user] = lambda: user_id
    return TestClient(app)


@pytest.fixture
def scripted(monkeypatch):
    from app.interactive.workflows import runner as runner_mod

    class _Scripted:
        def __init__(self):
            self.map: Dict[str, List[str]] = {}

        def feed(self, prompt_id: str, *responses: str) -> None:
            self.map.setdefault(prompt_id, []).extend(responses)

        async def __call__(self, prompt, policy, **_kw):
            q = self.map.get(prompt.prompt_id)
            if not q:
                raise AssertionError(f"No scripted response for {prompt.prompt_id}")
            return {"choices": [{"message": {"content": q.pop(0)}}]}

    s = _Scripted()
    monkeypatch.setattr(runner_mod, "call_prompt", s)
    return s


def _feed_happy(scripted):
    scripted.feed("autoplan.classify_mode", "enterprise_training")
    scripted.feed("autoplan.extract_topic", "Sales Pricing Training")
    scripted.feed(
        "autoplan.title",
        '["Sell Smarter on Tiers", "Pricing Playbook", "Tier Launch Day"]',
    )
    scripted.feed(
        "autoplan.brief",
        "Teach new sales reps three pricing tiers with quick decision points. "
        "Short scenes, one call each, with instant feedback after every pick.",
    )
    scripted.feed(
        "autoplan.audience",
        '{"role":"trainee","level":"beginner","language":"en"}',
    )
    scripted.feed(
        "autoplan.shape",
        '{"branch_count": 3, "depth": 2, "scenes_per_branch": 3}',
    )
    scripted.feed(
        "autoplan.seed_intents",
        '["welcome", "pricing_basics", "handle_objection", "call_recap"]',
    )


def _parse_sse(payload: bytes) -> List[Dict[str, Any]]:
    """Minimal SSE parser — splits on blank lines, strips ``data:``."""
    frames: List[Dict[str, Any]] = []
    for block in payload.decode("utf-8").split("\n\n"):
        block = block.strip()
        if not block or not block.startswith("data:"):
            continue
        body = block[len("data:"):].lstrip()
        frames.append(json.loads(body))
    return frames


# ── Happy path ────────────────────────────────────────────────

def test_stream_emits_events_and_result_frame(client, scripted):
    _feed_happy(scripted)
    with client.stream(
        "POST", "/v1/interactive/plan-auto/stream",
        json={"idea": "train new sales reps on pricing"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes())

    frames = _parse_sse(body)
    kinds = [f["type"] for f in frames]

    assert kinds[0] == "workflow_started"
    assert kinds.count("step_started") >= 7       # one per step
    assert kinds.count("step_completed") == 7     # no retries
    assert "workflow_completed" in kinds
    assert kinds[-2] == "result"
    assert kinds[-1] == "done"

    # The result frame mirrors the POST /plan-auto shape.
    result_frame = next(f for f in frames if f["type"] == "result")
    payload = result_frame["payload"]
    assert payload["ok"] is True
    assert payload["source"] == "llm"
    assert payload["form"]["experience_mode"] == "enterprise_training"
    assert payload["form"]["audience_role"] == "trainee"


def test_stream_carries_preview_on_step_completed(client, scripted):
    _feed_happy(scripted)
    with client.stream(
        "POST", "/v1/interactive/plan-auto/stream",
        json={"idea": "train new sales reps on pricing"},
    ) as r:
        body = b"".join(r.iter_bytes())
    frames = _parse_sse(body)
    completed = [f for f in frames if f["type"] == "step_completed"]
    # Every completed step carries a short preview string so the
    # frontend can show "Title: Pricing Playbook" style progress.
    assert all("preview" in f["payload"] for f in completed)
    assert all(len(f["payload"]["preview"]) <= 80 for f in completed)


# ── Abort + heuristic fallback ────────────────────────────────

def test_stream_emits_fallback_frame_on_abort(client, scripted):
    # Title step has retries=2 → 3 attempts. Feed non-JSON so all
    # 3 fail and the step's 'abort' fallback kicks in, which
    # halts the workflow.
    scripted.feed("autoplan.classify_mode", "sfw_general")
    scripted.feed("autoplan.extract_topic", "Chitchat")
    scripted.feed(
        "autoplan.title", "not-json", "still not json", "{broken",
    )

    with client.stream(
        "POST", "/v1/interactive/plan-auto/stream",
        json={"idea": "just say hello"},
    ) as r:
        body = b"".join(r.iter_bytes())
    frames = _parse_sse(body)
    kinds = [f["type"] for f in frames]

    assert "workflow_completed" in kinds
    assert "fallback" in kinds
    assert kinds[-1] == "done"

    # Fallback result is a valid form — heuristic path kicked in.
    result_frame = next(f for f in frames if f["type"] == "result")
    assert result_frame["payload"]["source"] == "heuristic"
    assert result_frame["payload"]["form"]["title"]


# ── Empty input ───────────────────────────────────────────────

def test_stream_rejects_empty_idea(client):
    r = client.post(
        "/v1/interactive/plan-auto/stream",
        json={"idea": "   "},
    )
    assert r.status_code == 400
