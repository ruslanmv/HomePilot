"""
Tests for playback.video_job — ix_scene_queue + state machine.
"""
from __future__ import annotations

import uuid

from app.interactive import repo
from app.interactive.models import ExperienceCreate
from app.interactive.playback.scene_memory import SceneMemory
from app.interactive.playback.scene_planner import plan_next_scene
from app.interactive.playback.video_job import (
    get_job,
    list_jobs,
    mark_failed,
    mark_ready,
    mark_rendering,
    render_now,
    submit_scene_job,
)


def _fresh_session(tag: str = "vj"):
    exp = repo.create_experience(
        f"user_{tag}_{uuid.uuid4().hex[:6]}",
        ExperienceCreate(title=f"Video job {tag}"),
    )
    return exp, repo.create_session(exp.id, viewer_ref="viewer")


def _memory(session_id: str, experience_id: str) -> SceneMemory:
    return SceneMemory(
        session_id=session_id, experience_id=experience_id,
        persona_id="persona_x", current_node_id="",
        mood="neutral", affinity_score=0.5, outfit_state={},
        recent_turns=[], total_turns=0, synopsis="", turns_since_synopsis=0,
    )


# ── submit + fetch ──────────────────────────────────────────────

def test_submit_job_returns_pending_row():
    _, sess = _fresh_session("submit")
    plan = plan_next_scene(_memory(sess.id, sess.experience_id), "hi")
    job = submit_scene_job(sess.id, "turn_1", plan)
    assert job.status == "pending"
    assert job.session_id == sess.id
    assert job.turn_id == "turn_1"
    assert job.prompt == plan.scene_prompt
    assert job.asset_id == ""
    assert job.duration_sec == plan.duration_sec


def test_get_job_round_trips():
    _, sess = _fresh_session("get")
    plan = plan_next_scene(_memory(sess.id, sess.experience_id), "hi")
    job = submit_scene_job(sess.id, "turn_1", plan)
    roundtrip = get_job(job.id)
    assert roundtrip is not None
    assert roundtrip.id == job.id
    assert roundtrip.prompt == job.prompt


def test_get_job_missing_is_none():
    assert get_job("ixj_does_not_exist") is None


# ── state transitions ──────────────────────────────────────────

def test_mark_rendering_updates_status_and_job_id():
    _, sess = _fresh_session("rendering")
    plan = plan_next_scene(_memory(sess.id, sess.experience_id), "hi")
    job = submit_scene_job(sess.id, "turn_1", plan)
    updated = mark_rendering(job.id, "backend-42")
    assert updated is not None
    assert updated.status == "rendering"
    assert updated.job_id == "backend-42"


def test_mark_ready_sets_asset_id():
    _, sess = _fresh_session("ready")
    plan = plan_next_scene(_memory(sess.id, sess.experience_id), "hi")
    job = submit_scene_job(sess.id, "turn_1", plan)
    updated = mark_ready(job.id, "ixa_xyz")
    assert updated is not None
    assert updated.status == "ready"
    assert updated.asset_id == "ixa_xyz"


def test_mark_failed_records_error():
    _, sess = _fresh_session("failed")
    plan = plan_next_scene(_memory(sess.id, sess.experience_id), "hi")
    job = submit_scene_job(sess.id, "turn_1", plan)
    updated = mark_failed(job.id, "backend crashed")
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error == "backend crashed"


# ── render_now (phase-1 synchronous completion) ────────────────

def test_render_now_drives_job_to_ready_with_placeholder():
    _, sess = _fresh_session("render")
    plan = plan_next_scene(_memory(sess.id, sess.experience_id), "hi")
    job = submit_scene_job(sess.id, "turn_1", plan)
    done = render_now(job.id)
    assert done is not None
    assert done.status == "ready"
    assert done.asset_id.startswith("ixa_stub_")
    assert done.job_id.startswith("stub-")


def test_render_now_missing_job_is_none():
    assert render_now("ixj_does_not_exist") is None


# ── list_jobs + since_id cursor ────────────────────────────────

def test_list_jobs_returns_in_creation_order():
    _, sess = _fresh_session("list")
    plan = plan_next_scene(_memory(sess.id, sess.experience_id), "hi")
    a = submit_scene_job(sess.id, "t1", plan)
    b = submit_scene_job(sess.id, "t2", plan)
    c = submit_scene_job(sess.id, "t3", plan)
    ids = [j.id for j in list_jobs(sess.id)]
    assert ids == [a.id, b.id, c.id]


def test_list_jobs_since_id_skips_earlier_rows():
    _, sess = _fresh_session("cursor")
    plan = plan_next_scene(_memory(sess.id, sess.experience_id), "hi")
    a = submit_scene_job(sess.id, "t1", plan)
    b = submit_scene_job(sess.id, "t2", plan)
    c = submit_scene_job(sess.id, "t3", plan)
    later = list_jobs(sess.id, since_id=a.id)
    assert [j.id for j in later] == [b.id, c.id]
    empty = list_jobs(sess.id, since_id=c.id)
    assert empty == []
