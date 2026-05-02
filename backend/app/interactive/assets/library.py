"""
ix_character_assets library — reusable per-persona / per-mood clips.

Phase 1 provides the query + register primitives. Phase 2 will add
LLM/heuristic ranking to pick the 'most fitting' clip for a given
mood × action × language combination.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from .. import store
from ..models import CharacterAsset


def _row_to_asset(row: sqlite3.Row) -> CharacterAsset:
    d = store.row_to_dict(
        row,
        json_fields=("mood_tags", "action_tags", "outfit_tags"),
    )
    return CharacterAsset(**d)


def register_library_asset(
    *,
    persona_id: str,
    asset_id: str,
    kind: str,
    mood_tags: Optional[List[str]] = None,
    action_tags: Optional[List[str]] = None,
    language: str = "",
    outfit_tags: Optional[List[str]] = None,
    duration_sec: float = 0.0,
    intensity: float = 0.5,
) -> CharacterAsset:
    """Register a file_assets row as a character-library entry.

    The ``asset_id`` is expected to already exist in ``file_assets``
    — this module doesn't upload files; it only adds a tagged
    pointer row in ``ix_character_assets``.
    """
    store.ensure_schema()
    ix_id = store.new_id("ixa")
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_character_assets (
                id, persona_id, asset_id, kind,
                mood_tags, action_tags, language, outfit_tags,
                duration_sec, intensity
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ix_id,
                persona_id,
                asset_id,
                kind,
                store._dump_json(mood_tags or []),
                store._dump_json(action_tags or []),
                language,
                store._dump_json(outfit_tags or []),
                float(duration_sec),
                float(intensity),
            ),
        )
        con.commit()
        row = con.execute(
            "SELECT * FROM ix_character_assets WHERE id = ?", (ix_id,),
        ).fetchone()
    return _row_to_asset(row)


def query_library(
    persona_id: str,
    *,
    mood: Optional[str] = None,
    action: Optional[str] = None,
    language: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 20,
) -> List[CharacterAsset]:
    """Query the library for matching clips. Scoring is done in
    Python so the SQL stays simple and correct.

    Returned rows are sorted by match score (desc), then by
    intensity (desc). Score awards points for each tag hit.
    """
    store.ensure_schema()
    with store._conn() as con:
        rows = con.execute(
            "SELECT * FROM ix_character_assets WHERE persona_id = ? "
            + ("AND kind = ? " if kind else "")
            + "ORDER BY intensity DESC LIMIT ?",
            (persona_id, kind, max(1, min(limit, 200))) if kind
            else (persona_id, max(1, min(limit, 200))),
        ).fetchall()

    candidates: List[tuple] = []
    for row in rows:
        asset = _row_to_asset(row)
        score = 0
        if mood and mood in (asset.mood_tags or []):
            score += 3
        if action and action in (asset.action_tags or []):
            score += 2
        if language and (not asset.language or asset.language == language):
            score += 1
        candidates.append((score, asset))

    candidates.sort(key=lambda t: (-t[0], -t[1].intensity))
    return [c[1] for c in candidates]


# Bootstrap helper — lets tests create a minimal library without
# needing to pre-populate file_assets.
def seed_library_defaults(persona_id: str) -> List[str]:
    """Seed one no-op 'idle' + one 'reaction' asset for a persona.

    Returns the ix_character_assets.id list. Used by tests + the
    admin 'initialize library' action. Skips if the persona already
    has any entries.
    """
    store.ensure_schema()
    with store._conn() as con:
        existing = con.execute(
            "SELECT COUNT(*) FROM ix_character_assets WHERE persona_id = ?",
            (persona_id,),
        ).fetchone()[0]
    if existing:
        return []

    ids = []
    ids.append(register_library_asset(
        persona_id=persona_id, asset_id=f"placeholder-idle-{persona_id}",
        kind="idle_loop", mood_tags=["neutral"], duration_sec=6.0, intensity=0.3,
    ).id)
    ids.append(register_library_asset(
        persona_id=persona_id, asset_id=f"placeholder-reaction-{persona_id}",
        kind="reaction", mood_tags=["flirty"], action_tags=["a_greet"],
        duration_sec=3.0, intensity=0.6,
    ).id)
    return ids
