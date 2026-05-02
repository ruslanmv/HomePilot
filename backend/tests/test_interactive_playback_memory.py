"""
Tests for playback.scene_memory — rolling context builder.

Covers: missing session guard, defaults for a bare session,
chronological turn ordering, synopsis surfacing + freshness
counter, and the refresh trigger (normal + bootstrap paths).
"""
from __future__ import annotations

import uuid

from app.interactive import repo
from app.interactive.models import ExperienceCreate
from app.interactive.playback.scene_memory import (
    build_scene_memory,
    reset_session,
    set_synopsis,
    should_refresh_synopsis,
)


def _fresh_session(tag: str = "sm"):
    exp = repo.create_experience(
        f"user_{tag}_{uuid.uuid4().hex[:6]}",
        ExperienceCreate(title=f"Memory test {tag}"),
    )
    return exp, repo.create_session(exp.id, viewer_ref="viewer")


# ────────────────────────────────────────────────────────────────

def test_memory_returns_none_for_missing_session():
    assert build_scene_memory("ixs_does_not_exist_xyz") is None


def test_memory_snapshot_default_state():
    _, sess = _fresh_session("defaults")
    reset_session(sess.id)
    mem = build_scene_memory(sess.id)
    assert mem is not None
    assert mem.session_id == sess.id
    assert mem.experience_id == sess.experience_id
    assert mem.mood == "neutral"
    assert mem.affinity_score == 0.5
    assert mem.outfit_state == {}
    assert mem.recent_turns == []
    assert mem.total_turns == 0
    assert mem.synopsis == ""
    assert mem.turns_since_synopsis == 0


def test_memory_reads_turns_in_chronological_order():
    _, sess = _fresh_session("turns")
    repo.append_turn(sess.id, "viewer", "hi")
    repo.append_turn(sess.id, "character", "hello")
    repo.append_turn(sess.id, "viewer", "how are you")
    mem = build_scene_memory(sess.id)
    assert mem is not None
    texts = [t.text for t in mem.recent_turns]
    assert texts == ["hi", "hello", "how are you"]
    assert mem.total_turns == 3


def test_memory_caps_recent_turns_at_requested_n():
    _, sess = _fresh_session("cap")
    for i in range(8):
        repo.append_turn(sess.id, "viewer", f"m{i}")
    mem = build_scene_memory(sess.id, recent_n=3)
    assert mem is not None
    assert [t.text for t in mem.recent_turns] == ["m5", "m6", "m7"]
    assert mem.total_turns == 8


def test_set_synopsis_is_surfaced_by_builder():
    _, sess = _fresh_session("synopsis")
    reset_session(sess.id)
    repo.append_turn(sess.id, "viewer", "one")
    repo.append_turn(sess.id, "viewer", "two")
    set_synopsis(sess.id, "Two brief hellos.", at_turn_count=2)
    mem = build_scene_memory(sess.id)
    assert mem is not None
    assert mem.synopsis == "Two brief hellos."
    assert mem.turns_since_synopsis == 0


def test_turns_since_synopsis_grows_with_new_turns():
    _, sess = _fresh_session("drift")
    reset_session(sess.id)
    set_synopsis(sess.id, "start", at_turn_count=0)
    repo.append_turn(sess.id, "viewer", "a")
    repo.append_turn(sess.id, "character", "b")
    mem = build_scene_memory(sess.id)
    assert mem is not None
    assert mem.turns_since_synopsis == 2


def test_should_refresh_triggers_after_threshold():
    _, sess = _fresh_session("refresh")
    reset_session(sess.id)
    set_synopsis(sess.id, "initial", at_turn_count=0)
    for _ in range(6):
        repo.append_turn(sess.id, "viewer", "x")
    mem = build_scene_memory(sess.id)
    assert mem is not None
    assert should_refresh_synopsis(mem, every=6) is True


def test_should_not_refresh_before_threshold():
    _, sess = _fresh_session("no_refresh")
    reset_session(sess.id)
    set_synopsis(sess.id, "initial", at_turn_count=0)
    for _ in range(2):
        repo.append_turn(sess.id, "viewer", "x")
    mem = build_scene_memory(sess.id)
    assert mem is not None
    assert should_refresh_synopsis(mem, every=6) is False


def test_bootstrap_refresh_triggers_without_synopsis_after_half_threshold():
    _, sess = _fresh_session("bootstrap")
    reset_session(sess.id)
    for _ in range(3):
        repo.append_turn(sess.id, "viewer", "t")
    mem = build_scene_memory(sess.id)
    assert mem is not None
    # Half of default 6 = 3 → triggers bootstrap refresh
    assert should_refresh_synopsis(mem, every=6) is True
