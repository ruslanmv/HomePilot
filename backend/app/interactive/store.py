"""
SQLite DDL + low-level row CRUD for the interactive service.

Batch 2/8 — schema only. Higher-level logic lives in ``repo.py``
on top of these primitives; routers never touch store.py directly.

All tables are prefixed ``ix_`` to keep the interactive namespace
separated from other HomePilot modules (studio_*, voice_call_*,
users, file_assets, etc.). No foreign keys into non-interactive
tables — links are stored as string ids and resolved in code, so
dropping the whole interactive subsystem ( = DROP TABLE ix_* )
leaves the rest of the DB untouched.

Schema stability: this is v1. Future migrations live in a parallel
``migrations/`` package if / when they're needed.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..storage import _get_db_path


# ── Schema ────────────────────────────────────────────────────────

# Fifteen tables. Ordering matters only for documentation; SQLite
# doesn't enforce FKs by default and we never declare them on
# non-interactive targets.
_DDL: List[str] = [
    # 1. ix_experiences — top-level interactive experience
    """
    CREATE TABLE IF NOT EXISTS ix_experiences (
        id                  TEXT PRIMARY KEY,
        user_id             TEXT NOT NULL,
        studio_video_id     TEXT DEFAULT '',
        title               TEXT NOT NULL,
        description         TEXT DEFAULT '',
        objective           TEXT DEFAULT '',
        experience_mode     TEXT NOT NULL DEFAULT 'sfw_general',
        policy_profile_id   TEXT NOT NULL DEFAULT 'sfw_general',
        audience_profile    TEXT DEFAULT '{}',
        branch_count        INTEGER DEFAULT 0,
        max_depth           INTEGER DEFAULT 0,
        status              TEXT NOT NULL DEFAULT 'draft',
        tags                TEXT DEFAULT '[]',
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_experiences_user ON ix_experiences(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_ix_experiences_mode ON ix_experiences(experience_mode)",

    # 2. ix_nodes — scenes in the branch graph
    """
    CREATE TABLE IF NOT EXISTS ix_nodes (
        id                  TEXT PRIMARY KEY,
        experience_id       TEXT NOT NULL,
        kind                TEXT NOT NULL DEFAULT 'scene',
        title               TEXT DEFAULT '',
        narration           TEXT DEFAULT '',
        image_prompt        TEXT DEFAULT '',
        video_prompt        TEXT DEFAULT '',
        duration_sec        INTEGER DEFAULT 5,
        storyboard          TEXT DEFAULT '{}',
        interaction_layout  TEXT DEFAULT '{}',
        asset_ids           TEXT DEFAULT '[]',
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_nodes_experience ON ix_nodes(experience_id)",

    # 3. ix_edges — directed transitions
    """
    CREATE TABLE IF NOT EXISTS ix_edges (
        id                  TEXT PRIMARY KEY,
        experience_id       TEXT NOT NULL,
        from_node_id        TEXT NOT NULL,
        to_node_id          TEXT NOT NULL,
        trigger_kind        TEXT NOT NULL,
        trigger_payload     TEXT DEFAULT '{}',
        ordinal             INTEGER DEFAULT 0,
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_edges_experience ON ix_edges(experience_id)",
    "CREATE INDEX IF NOT EXISTS idx_ix_edges_from ON ix_edges(from_node_id)",

    # 4. ix_node_variants — language variants of a node
    """
    CREATE TABLE IF NOT EXISTS ix_node_variants (
        id                  TEXT PRIMARY KEY,
        node_id             TEXT NOT NULL,
        language            TEXT NOT NULL,
        narration           TEXT DEFAULT '',
        subtitles           TEXT DEFAULT '',
        audio_asset_id      TEXT DEFAULT '',
        video_asset_id      TEXT DEFAULT '',
        UNIQUE(node_id, language)
    )
    """,

    # 5. ix_sessions — per-viewer playback session
    """
    CREATE TABLE IF NOT EXISTS ix_sessions (
        id                  TEXT PRIMARY KEY,
        experience_id       TEXT NOT NULL,
        viewer_ref          TEXT DEFAULT '',
        current_node_id     TEXT DEFAULT '',
        language            TEXT DEFAULT 'en',
        personalization     TEXT DEFAULT '{}',
        consent_version     TEXT DEFAULT '',
        started_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_event_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at        DATETIME
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_sessions_experience ON ix_sessions(experience_id)",

    # 6. ix_session_events — analytics event log
    """
    CREATE TABLE IF NOT EXISTS ix_session_events (
        id                  TEXT PRIMARY KEY,
        session_id          TEXT NOT NULL,
        ts                  DATETIME DEFAULT CURRENT_TIMESTAMP,
        event_kind          TEXT NOT NULL,
        node_id             TEXT DEFAULT '',
        edge_id             TEXT DEFAULT '',
        action_id           TEXT DEFAULT '',
        payload             TEXT DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_session_events_session ON ix_session_events(session_id)",

    # 7. ix_session_turns — chat transcript
    """
    CREATE TABLE IF NOT EXISTS ix_session_turns (
        id                  TEXT PRIMARY KEY,
        session_id          TEXT NOT NULL,
        turn_role           TEXT NOT NULL,
        text                TEXT NOT NULL,
        action_id           TEXT DEFAULT '',
        node_id             TEXT DEFAULT '',
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_session_turns_session ON ix_session_turns(session_id)",

    # 8. ix_character_state — live persona state per session
    """
    CREATE TABLE IF NOT EXISTS ix_character_state (
        id                  TEXT PRIMARY KEY,
        session_id          TEXT NOT NULL,
        persona_id          TEXT NOT NULL DEFAULT '',
        mood                TEXT DEFAULT 'neutral',
        affinity_score      REAL DEFAULT 0.5,
        outfit_state        TEXT DEFAULT '{}',
        recent_flags        TEXT DEFAULT '[]',
        language            TEXT DEFAULT 'en',
        updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id)
    )
    """,

    # 9. ix_character_assets — reusable character media library
    """
    CREATE TABLE IF NOT EXISTS ix_character_assets (
        id                  TEXT PRIMARY KEY,
        persona_id          TEXT NOT NULL,
        asset_id            TEXT NOT NULL,
        kind                TEXT NOT NULL,
        mood_tags           TEXT DEFAULT '[]',
        action_tags         TEXT DEFAULT '[]',
        language            TEXT DEFAULT '',
        outfit_tags         TEXT DEFAULT '[]',
        duration_sec        REAL DEFAULT 0,
        intensity           REAL DEFAULT 0.5,
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_character_assets_persona ON ix_character_assets(persona_id)",

    # 10. ix_action_catalog — actions offered to the viewer
    """
    CREATE TABLE IF NOT EXISTS ix_action_catalog (
        id                  TEXT PRIMARY KEY,
        experience_id       TEXT NOT NULL,
        label               TEXT NOT NULL,
        intent_code         TEXT DEFAULT '',
        required_level      INTEGER DEFAULT 1,
        required_scheme     TEXT DEFAULT 'xp_level',
        required_metric_key TEXT DEFAULT 'level',
        policy_scope        TEXT DEFAULT '[]',
        cooldown_sec        INTEGER DEFAULT 0,
        mood_delta          TEXT DEFAULT '{}',
        xp_award            INTEGER DEFAULT 0,
        max_uses_per_session INTEGER DEFAULT 0,
        repeat_penalty      REAL DEFAULT 0,
        requires_consent    TEXT DEFAULT '',
        applicable_modes    TEXT DEFAULT '[]',
        ordinal             INTEGER DEFAULT 0,
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_action_catalog_experience ON ix_action_catalog(experience_id)",

    # 11. ix_session_progress — generic progression metrics
    """
    CREATE TABLE IF NOT EXISTS ix_session_progress (
        id                  TEXT PRIMARY KEY,
        session_id          TEXT NOT NULL,
        scheme              TEXT NOT NULL,
        metric_key          TEXT NOT NULL,
        metric_value        REAL NOT NULL,
        updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id, scheme, metric_key)
    )
    """,

    # 12. ix_personalization_rules — viewer-aware routing rules
    """
    CREATE TABLE IF NOT EXISTS ix_personalization_rules (
        id                  TEXT PRIMARY KEY,
        experience_id       TEXT NOT NULL,
        name                TEXT NOT NULL,
        condition           TEXT NOT NULL DEFAULT '{}',
        action              TEXT NOT NULL DEFAULT '{}',
        priority            INTEGER DEFAULT 100,
        enabled             INTEGER DEFAULT 1,
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_pers_rules_experience ON ix_personalization_rules(experience_id)",

    # 13. ix_intent_map — free-text intent → action routing
    """
    CREATE TABLE IF NOT EXISTS ix_intent_map (
        id                  TEXT PRIMARY KEY,
        experience_id       TEXT NOT NULL,
        intent_code         TEXT NOT NULL,
        action_id           TEXT DEFAULT '',
        fallback_node_id    TEXT DEFAULT '',
        priority            INTEGER DEFAULT 100,
        applicable_modes    TEXT DEFAULT '[]'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_intent_map_experience ON ix_intent_map(experience_id)",

    # 14. ix_publications — published channel snapshots
    """
    CREATE TABLE IF NOT EXISTS ix_publications (
        id                  TEXT PRIMARY KEY,
        experience_id       TEXT NOT NULL,
        channel             TEXT NOT NULL,
        manifest_url        TEXT DEFAULT '',
        version             INTEGER DEFAULT 1,
        metadata            TEXT DEFAULT '{}',
        published_at        DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_publications_experience ON ix_publications(experience_id)",

    # 15. ix_qa_reports — snapshot of last QA run
    """
    CREATE TABLE IF NOT EXISTS ix_qa_reports (
        id                  TEXT PRIMARY KEY,
        experience_id       TEXT NOT NULL,
        kind                TEXT NOT NULL,
        summary             TEXT NOT NULL DEFAULT '{}',
        issues              TEXT NOT NULL DEFAULT '[]',
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ix_qa_reports_experience ON ix_qa_reports(experience_id)",
]


# ── Connection helpers ────────────────────────────────────────────

@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Short-lived SQLite connection. Same DB as everything else."""
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        try:
            con.close()
        except Exception:
            pass


def ensure_schema() -> None:
    """Idempotently apply the interactive DDL.

    Safe to call from anywhere — FastAPI startup, migrations, tests.
    All statements are ``CREATE TABLE IF NOT EXISTS`` / ``CREATE
    INDEX IF NOT EXISTS`` so repeat invocations are no-ops.
    """
    with _conn() as con:
        cur = con.cursor()
        for stmt in _DDL:
            cur.execute(stmt)
        con.commit()


# ── Id generation ─────────────────────────────────────────────────

def new_id(prefix: str) -> str:
    """Generate a short prefixed id. Uses uuid4 hex (no dashes).

    Prefixes are deliberately short — ``ixe``, ``ixn``, ``ixe``
    collide, so we use distinct ones per table:
      ixe → experience
      ixn → node
      ixg → edge (graph edge)
      ixs → session
      ixv → node variant
      ixt → session turn
      ixa → character asset / action catalog entry (context disambiguates)
      ixp → progress row / publication (context disambiguates)
      ixr → personalization rule / QA report
      ixm → intent map entry
      ixc → character state
    """
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


def now_iso() -> str:
    """ISO timestamp for manually-set updated_at fields."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


# ── JSON helpers (centralised so the row → dict conversion is uniform) ──

def _parse_json(val: Any, default: Any) -> Any:
    if val is None or val == "":
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return default


def _dump_json(val: Any) -> str:
    try:
        return json.dumps(val, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


def row_to_dict(row: sqlite3.Row, json_fields: Tuple[str, ...]) -> Dict[str, Any]:
    """Convert a Row into a dict, JSON-decoding the named fields.

    ``json_fields`` that are missing from the row are silently
    skipped — safe for partial SELECTs.
    """
    out: Dict[str, Any] = {k: row[k] for k in row.keys()}
    for k in json_fields:
        if k in out:
            default: Any = {} if k.endswith("_state") or k == "storyboard" or k == "interaction_layout" \
                or k == "personalization" or k == "audience_profile" \
                or k == "condition" or k == "action" or k == "trigger_payload" \
                or k == "mood_delta" or k == "outfit_state" or k == "metadata" \
                or k == "payload" or k == "summary" else []
            out[k] = _parse_json(out[k], default)
    return out
