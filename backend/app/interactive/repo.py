"""
Typed repository for the interactive service.

Mediates between the router (pydantic models, business flow) and
the ``store.py`` SQL primitives. Nothing in this module returns raw
SQLite rows — everything comes out as a pydantic model or a plain
dict with JSON fields already decoded.

Design rule: every function takes an optional ``user_id`` and
scopes reads/writes accordingly. The ``user_id`` check is the
isolation boundary (matches the pattern in inventory.py).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from . import store
from .errors import NotFoundError
from .models import (
    Action,
    ActionCreate,
    CharacterState,
    Edge,
    EdgeCreate,
    Experience,
    ExperienceCreate,
    ExperienceUpdate,
    Node,
    NodeCreate,
    NodeUpdate,
    Publication,
    QAReport,
    Session,
    SessionEvent,
    SessionTurn,
)


# ─────────────────────────────────────────────────────────────────
# Experiences
# ─────────────────────────────────────────────────────────────────

def _row_to_experience(row: Any) -> Experience:
    d = store.row_to_dict(row, json_fields=("audience_profile", "tags"))
    return Experience(**d)


def create_experience(user_id: str, payload: ExperienceCreate) -> Experience:
    store.ensure_schema()
    eid = store.new_id("ixe")
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_experiences (
                id, user_id, studio_video_id, title, description, objective,
                experience_mode, policy_profile_id, audience_profile, status, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
            """,
            (
                eid,
                user_id,
                payload.studio_video_id or "",
                payload.title,
                payload.description,
                payload.objective,
                payload.experience_mode,
                payload.policy_profile_id,
                store._dump_json(payload.audience_profile),
                store._dump_json(payload.tags),
            ),
        )
        con.commit()
        row = con.execute("SELECT * FROM ix_experiences WHERE id = ?", (eid,)).fetchone()
    return _row_to_experience(row)


def get_experience(eid: str, user_id: Optional[str] = None) -> Optional[Experience]:
    store.ensure_schema()
    with store._conn() as con:
        if user_id:
            row = con.execute(
                "SELECT * FROM ix_experiences WHERE id = ? AND user_id = ?",
                (eid, user_id),
            ).fetchone()
        else:
            row = con.execute("SELECT * FROM ix_experiences WHERE id = ?", (eid,)).fetchone()
    return _row_to_experience(row) if row else None


def list_experiences(user_id: str, limit: int = 100) -> List[Experience]:
    store.ensure_schema()
    with store._conn() as con:
        rows = con.execute(
            "SELECT * FROM ix_experiences WHERE user_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (user_id, max(1, min(limit, 500))),
        ).fetchall()
    return [_row_to_experience(r) for r in rows]


def update_experience(eid: str, user_id: str, patch: ExperienceUpdate) -> Experience:
    store.ensure_schema()
    current = get_experience(eid, user_id=user_id)
    if not current:
        raise NotFoundError(f"Experience {eid} not found")
    sets: List[str] = []
    params: List[Any] = []
    if patch.title is not None:
        sets.append("title = ?")
        params.append(patch.title)
    if patch.description is not None:
        sets.append("description = ?")
        params.append(patch.description)
    if patch.objective is not None:
        sets.append("objective = ?")
        params.append(patch.objective)
    if patch.experience_mode is not None:
        sets.append("experience_mode = ?")
        params.append(patch.experience_mode)
    if patch.policy_profile_id is not None:
        sets.append("policy_profile_id = ?")
        params.append(patch.policy_profile_id)
    if patch.audience_profile is not None:
        sets.append("audience_profile = ?")
        params.append(store._dump_json(patch.audience_profile))
    if patch.status is not None:
        sets.append("status = ?")
        params.append(patch.status)
    if patch.tags is not None:
        sets.append("tags = ?")
        params.append(store._dump_json(patch.tags))
    sets.append("updated_at = ?")
    params.append(store.now_iso())
    params.append(eid)
    params.append(user_id)
    with store._conn() as con:
        con.execute(
            f"UPDATE ix_experiences SET {', '.join(sets)} WHERE id = ? AND user_id = ?",
            tuple(params),
        )
        con.commit()
        row = con.execute("SELECT * FROM ix_experiences WHERE id = ?", (eid,)).fetchone()
    return _row_to_experience(row)


def delete_experience(eid: str, user_id: str) -> bool:
    """Cascade-delete an experience and all its dependent rows.

    Cascade is manual because we intentionally don't use FKs (keeps
    the interactive DDL isolated and drop-safe).
    """
    store.ensure_schema()
    current = get_experience(eid, user_id=user_id)
    if not current:
        return False
    with store._conn() as con:
        cur = con.cursor()
        # Gather dependent session ids first so we can clean their children.
        session_ids = [
            r[0] for r in cur.execute(
                "SELECT id FROM ix_sessions WHERE experience_id = ?", (eid,)
            ).fetchall()
        ]
        # Wipe children of sessions.
        for sid in session_ids:
            cur.execute("DELETE FROM ix_session_events WHERE session_id = ?", (sid,))
            cur.execute("DELETE FROM ix_session_turns WHERE session_id = ?", (sid,))
            cur.execute("DELETE FROM ix_session_progress WHERE session_id = ?", (sid,))
            cur.execute("DELETE FROM ix_character_state WHERE session_id = ?", (sid,))
        # Wipe node variants for each node.
        node_ids = [
            r[0] for r in cur.execute(
                "SELECT id FROM ix_nodes WHERE experience_id = ?", (eid,)
            ).fetchall()
        ]
        for nid in node_ids:
            cur.execute("DELETE FROM ix_node_variants WHERE node_id = ?", (nid,))
        # Wipe experience-scoped rows.
        cur.execute("DELETE FROM ix_sessions WHERE experience_id = ?", (eid,))
        cur.execute("DELETE FROM ix_edges WHERE experience_id = ?", (eid,))
        cur.execute("DELETE FROM ix_nodes WHERE experience_id = ?", (eid,))
        cur.execute("DELETE FROM ix_action_catalog WHERE experience_id = ?", (eid,))
        cur.execute("DELETE FROM ix_personalization_rules WHERE experience_id = ?", (eid,))
        cur.execute("DELETE FROM ix_intent_map WHERE experience_id = ?", (eid,))
        cur.execute("DELETE FROM ix_publications WHERE experience_id = ?", (eid,))
        cur.execute("DELETE FROM ix_qa_reports WHERE experience_id = ?", (eid,))
        cur.execute(
            "DELETE FROM ix_experiences WHERE id = ? AND user_id = ?",
            (eid, user_id),
        )
        con.commit()
    return True


# ─────────────────────────────────────────────────────────────────
# Nodes + edges
# ─────────────────────────────────────────────────────────────────

def _row_to_node(row: Any) -> Node:
    d = store.row_to_dict(row, json_fields=("storyboard", "interaction_layout", "asset_ids"))
    return Node(**d)


def create_node(eid: str, payload: NodeCreate) -> Node:
    store.ensure_schema()
    nid = store.new_id("ixn")
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_nodes (
                id, experience_id, kind, title, narration, image_prompt,
                video_prompt, duration_sec, storyboard, interaction_layout, asset_ids
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nid,
                eid,
                payload.kind,
                payload.title,
                payload.narration,
                payload.image_prompt,
                payload.video_prompt,
                int(payload.duration_sec or 5),
                store._dump_json(payload.storyboard),
                store._dump_json(payload.interaction_layout),
                store._dump_json(payload.asset_ids),
            ),
        )
        con.commit()
        row = con.execute("SELECT * FROM ix_nodes WHERE id = ?", (nid,)).fetchone()
    return _row_to_node(row)


def list_nodes(eid: str) -> List[Node]:
    store.ensure_schema()
    with store._conn() as con:
        rows = con.execute(
            "SELECT * FROM ix_nodes WHERE experience_id = ? ORDER BY created_at ASC",
            (eid,),
        ).fetchall()
    return [_row_to_node(r) for r in rows]


def get_node(nid: str) -> Optional[Node]:
    store.ensure_schema()
    with store._conn() as con:
        row = con.execute("SELECT * FROM ix_nodes WHERE id = ?", (nid,)).fetchone()
    return _row_to_node(row) if row else None


def update_node(nid: str, patch: NodeUpdate) -> Node:
    store.ensure_schema()
    current = get_node(nid)
    if not current:
        raise NotFoundError(f"Node {nid} not found")
    sets: List[str] = []
    params: List[Any] = []
    for key in ("kind", "title", "narration", "image_prompt", "video_prompt"):
        val = getattr(patch, key)
        if val is not None:
            sets.append(f"{key} = ?")
            params.append(val)
    if patch.duration_sec is not None:
        sets.append("duration_sec = ?")
        params.append(int(patch.duration_sec))
    if patch.storyboard is not None:
        sets.append("storyboard = ?")
        params.append(store._dump_json(patch.storyboard))
    if patch.interaction_layout is not None:
        sets.append("interaction_layout = ?")
        params.append(store._dump_json(patch.interaction_layout))
    if patch.asset_ids is not None:
        sets.append("asset_ids = ?")
        params.append(store._dump_json(patch.asset_ids))
    sets.append("updated_at = ?")
    params.append(store.now_iso())
    params.append(nid)
    with store._conn() as con:
        con.execute(
            f"UPDATE ix_nodes SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        con.commit()
        row = con.execute("SELECT * FROM ix_nodes WHERE id = ?", (nid,)).fetchone()
    return _row_to_node(row)


def delete_node(nid: str) -> bool:
    store.ensure_schema()
    with store._conn() as con:
        cur = con.cursor()
        cur.execute("DELETE FROM ix_node_variants WHERE node_id = ?", (nid,))
        cur.execute("DELETE FROM ix_edges WHERE from_node_id = ? OR to_node_id = ?", (nid, nid))
        result = cur.execute("DELETE FROM ix_nodes WHERE id = ?", (nid,))
        deleted = result.rowcount > 0
        con.commit()
    return deleted


def _row_to_edge(row: Any) -> Edge:
    d = store.row_to_dict(row, json_fields=("trigger_payload",))
    return Edge(**d)


def create_edge(eid: str, payload: EdgeCreate) -> Edge:
    store.ensure_schema()
    gid = store.new_id("ixg")
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_edges (
                id, experience_id, from_node_id, to_node_id,
                trigger_kind, trigger_payload, ordinal
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gid,
                eid,
                payload.from_node_id,
                payload.to_node_id,
                payload.trigger_kind,
                store._dump_json(payload.trigger_payload),
                int(payload.ordinal or 0),
            ),
        )
        con.commit()
        row = con.execute("SELECT * FROM ix_edges WHERE id = ?", (gid,)).fetchone()
    return _row_to_edge(row)


def list_edges(eid: str) -> List[Edge]:
    store.ensure_schema()
    with store._conn() as con:
        rows = con.execute(
            "SELECT * FROM ix_edges WHERE experience_id = ? ORDER BY ordinal ASC, created_at ASC",
            (eid,),
        ).fetchall()
    return [_row_to_edge(r) for r in rows]


def delete_edge(edge_id: str) -> bool:
    store.ensure_schema()
    with store._conn() as con:
        cur = con.cursor()
        result = cur.execute("DELETE FROM ix_edges WHERE id = ?", (edge_id,))
        deleted = result.rowcount > 0
        con.commit()
    return deleted


# ─────────────────────────────────────────────────────────────────
# Sessions (used by runtime in batch 7/8) — minimal shim
# ─────────────────────────────────────────────────────────────────

def _row_to_session(row: Any) -> Session:
    d = store.row_to_dict(row, json_fields=("personalization",))
    return Session(**d)


def create_session(
    eid: str, viewer_ref: str, *, language: str = "en", personalization: Optional[Dict[str, Any]] = None,
) -> Session:
    store.ensure_schema()
    sid = store.new_id("ixs")
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_sessions (
                id, experience_id, viewer_ref, language, personalization
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (sid, eid, viewer_ref, language, store._dump_json(personalization or {})),
        )
        con.commit()
        row = con.execute("SELECT * FROM ix_sessions WHERE id = ?", (sid,)).fetchone()
    return _row_to_session(row)


def get_session(sid: str) -> Optional[Session]:
    store.ensure_schema()
    with store._conn() as con:
        row = con.execute("SELECT * FROM ix_sessions WHERE id = ?", (sid,)).fetchone()
    return _row_to_session(row) if row else None


def append_event(
    session_id: str, event_kind: str, *,
    node_id: str = "", edge_id: str = "", action_id: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    """Append an analytics event row. Returns the event id.

    Safe-for-hot-path: single insert, no joins, no reads.
    """
    store.ensure_schema()
    ev_id = store.new_id("ixv")
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_session_events (
                id, session_id, event_kind, node_id, edge_id, action_id, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ev_id,
                session_id,
                event_kind,
                node_id,
                edge_id,
                action_id,
                store._dump_json(payload or {}),
            ),
        )
        con.commit()
    return ev_id


def append_turn(
    session_id: str, turn_role: str, text: str,
    *, action_id: str = "", node_id: str = "",
) -> str:
    """Append a chat turn. Returns the turn id."""
    store.ensure_schema()
    tid = store.new_id("ixt")
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_session_turns (
                id, session_id, turn_role, text, action_id, node_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tid, session_id, turn_role, text, action_id, node_id),
        )
        con.commit()
    return tid


def recent_turns(session_id: str, limit: int = 20) -> List[SessionTurn]:
    """Return the most recent N turns in chronological (oldest-first)
    order. Uses ``rowid`` as a secondary sort — SQLite timestamps
    have second-granularity so two turns written in the same second
    would otherwise tie-break on rowid ASC, producing wrong order
    once we reverse the DESC-sorted result.
    """
    store.ensure_schema()
    with store._conn() as con:
        rows = con.execute(
            "SELECT * FROM ix_session_turns WHERE session_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (session_id, max(1, min(limit, 200))),
        ).fetchall()
    out = [SessionTurn(**store.row_to_dict(r, json_fields=())) for r in rows]
    out.reverse()  # chronological for prompt assembly
    return out
