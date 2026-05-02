"""
Batch 2/8 — data-model tests.

Verifies:
  - DDL applies cleanly (15 tables present after ensure_schema)
  - Pydantic models round-trip through the repo
  - User-scoped reads: user A can't see user B's experience
  - Cascade delete wipes nodes / edges / sessions / children

Still runs with the flag OFF — store/repo are usable as libraries
independent of the router mount state.
"""
from __future__ import annotations

import sqlite3

from app.interactive import store
from app.interactive.repo import (
    append_event,
    append_turn,
    create_edge,
    create_experience,
    create_node,
    create_session,
    delete_experience,
    get_experience,
    get_node,
    list_edges,
    list_experiences,
    list_nodes,
    recent_turns,
    update_experience,
    update_node,
)
from app.interactive.models import (
    EdgeCreate,
    ExperienceCreate,
    ExperienceUpdate,
    NodeCreate,
    NodeUpdate,
)


# ─────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────

_EXPECTED_TABLES = {
    "ix_experiences",
    "ix_nodes",
    "ix_edges",
    "ix_node_variants",
    "ix_sessions",
    "ix_session_events",
    "ix_session_turns",
    "ix_character_state",
    "ix_character_assets",
    "ix_action_catalog",
    "ix_session_progress",
    "ix_personalization_rules",
    "ix_intent_map",
    "ix_publications",
    "ix_qa_reports",
}


def test_ddl_creates_all_fifteen_tables():
    store.ensure_schema()
    with store._conn() as con:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ix_%'"
        ).fetchall()
    present = {r[0] for r in rows}
    missing = _EXPECTED_TABLES - present
    assert not missing, f"missing tables: {sorted(missing)}"


def test_ensure_schema_is_idempotent():
    store.ensure_schema()
    store.ensure_schema()  # second call must not raise
    store.ensure_schema()


# ─────────────────────────────────────────────────────────────────
# Experience CRUD + scoping
# ─────────────────────────────────────────────────────────────────

def test_create_and_get_experience():
    store.ensure_schema()
    exp = create_experience(
        "user-a",
        ExperienceCreate(
            title="Language A1",
            description="Basic vocabulary",
            objective="Teach 50 common words",
            experience_mode="language_learning",
            policy_profile_id="language_learning",
            audience_profile={"level": "beginner"},
            tags=["language", "italian"],
        ),
    )
    assert exp.id.startswith("ixe_")
    assert exp.user_id == "user-a"
    assert exp.title == "Language A1"
    assert exp.experience_mode == "language_learning"
    assert exp.tags == ["language", "italian"]
    assert exp.audience_profile == {"level": "beginner"}

    fetched = get_experience(exp.id, user_id="user-a")
    assert fetched is not None
    assert fetched.id == exp.id


def test_experience_not_visible_to_other_user():
    store.ensure_schema()
    exp = create_experience(
        "user-owner", ExperienceCreate(title="Private demo"),
    )
    assert get_experience(exp.id, user_id="user-stranger") is None
    # No user_id filter means admin-style read; still works.
    assert get_experience(exp.id) is not None


def test_update_experience_persists_changes():
    store.ensure_schema()
    exp = create_experience("user-a", ExperienceCreate(title="v1"))
    updated = update_experience(
        exp.id, user_id="user-a",
        patch=ExperienceUpdate(title="v2", status="planning", tags=["a", "b"]),
    )
    assert updated.title == "v2"
    assert updated.status == "planning"
    assert updated.tags == ["a", "b"]


def test_list_experiences_scoped_by_user():
    store.ensure_schema()
    for i in range(3):
        create_experience("user-list", ExperienceCreate(title=f"exp-{i}"))
    create_experience("user-other", ExperienceCreate(title="other"))
    mine = list_experiences("user-list")
    titles = {e.title for e in mine}
    assert "exp-0" in titles and "exp-1" in titles and "exp-2" in titles
    assert "other" not in titles


# ─────────────────────────────────────────────────────────────────
# Nodes + edges
# ─────────────────────────────────────────────────────────────────

def test_create_and_list_nodes():
    store.ensure_schema()
    exp = create_experience("user-graph", ExperienceCreate(title="graph"))
    n1 = create_node(exp.id, NodeCreate(
        kind="scene", title="Intro", narration="Welcome!",
        storyboard={"camera": "wide"},
        interaction_layout={"hotspots": []},
        asset_ids=["asset-1"],
    ))
    n2 = create_node(exp.id, NodeCreate(kind="decision", title="Pick"))
    assert n1.id.startswith("ixn_")
    assert n1.storyboard == {"camera": "wide"}
    assert n1.asset_ids == ["asset-1"]

    all_nodes = list_nodes(exp.id)
    ids = {n.id for n in all_nodes}
    assert n1.id in ids and n2.id in ids


def test_update_node_partial_patch():
    store.ensure_schema()
    exp = create_experience("user-patch", ExperienceCreate(title="patch"))
    n = create_node(exp.id, NodeCreate(title="Original", narration="A"))
    updated = update_node(n.id, NodeUpdate(title="Renamed"))
    assert updated.title == "Renamed"
    assert updated.narration == "A"  # unchanged


def test_create_edge_and_list():
    store.ensure_schema()
    exp = create_experience("user-edge", ExperienceCreate(title="edges"))
    a = create_node(exp.id, NodeCreate(title="A"))
    b = create_node(exp.id, NodeCreate(title="B"))
    edge = create_edge(exp.id, EdgeCreate(
        from_node_id=a.id, to_node_id=b.id,
        trigger_kind="choice", trigger_payload={"label": "Go"},
        ordinal=0,
    ))
    assert edge.id.startswith("ixg_")
    assert edge.trigger_payload == {"label": "Go"}
    all_edges = list_edges(exp.id)
    assert len(all_edges) == 1 and all_edges[0].id == edge.id


# ─────────────────────────────────────────────────────────────────
# Cascade delete
# ─────────────────────────────────────────────────────────────────

def test_delete_experience_cascades_children():
    store.ensure_schema()
    exp = create_experience("user-del", ExperienceCreate(title="to-delete"))
    a = create_node(exp.id, NodeCreate(title="A"))
    b = create_node(exp.id, NodeCreate(title="B"))
    create_edge(exp.id, EdgeCreate(from_node_id=a.id, to_node_id=b.id, trigger_kind="auto"))
    sess = create_session(exp.id, viewer_ref="v1")
    append_event(sess.id, "enter_node", node_id=a.id)
    append_turn(sess.id, "assistant", "hello")

    assert delete_experience(exp.id, "user-del") is True
    assert get_experience(exp.id) is None
    # All children gone.
    with store._conn() as con:
        for t in ("ix_nodes", "ix_edges", "ix_sessions",
                  "ix_session_events", "ix_session_turns"):
            row = con.execute(
                f"SELECT COUNT(*) FROM {t} WHERE "
                + ("experience_id = ?" if t in {"ix_nodes", "ix_edges", "ix_sessions"}
                   else "session_id = ?"),
                (exp.id if t in {"ix_nodes", "ix_edges", "ix_sessions"} else sess.id,),
            ).fetchone()
            assert row[0] == 0, f"{t} still has rows after delete"


def test_delete_experience_nonexistent_is_noop():
    store.ensure_schema()
    assert delete_experience("ixe_doesnotexist", "any-user") is False


# ─────────────────────────────────────────────────────────────────
# Session turns + events
# ─────────────────────────────────────────────────────────────────

def test_turns_return_chronological_order():
    store.ensure_schema()
    exp = create_experience("user-turns", ExperienceCreate(title="turns"))
    sess = create_session(exp.id, viewer_ref="v")
    append_turn(sess.id, "user", "hello")
    append_turn(sess.id, "assistant", "hi there")
    append_turn(sess.id, "user", "how are you?")
    turns = recent_turns(sess.id, limit=10)
    assert [t.turn_role for t in turns] == ["user", "assistant", "user"]
    assert turns[0].text == "hello"
    assert turns[-1].text == "how are you?"
