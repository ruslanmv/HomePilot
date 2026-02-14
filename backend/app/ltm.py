"""
Long-Term Memory (LTM) — The Persona's "Soul"

Persistent per-persona memory that survives across all sessions.
Stores facts, preferences, important dates, emotional patterns,
and relationship milestones learned from conversation.

Key design:
  - UPSERT by (project_id, category, key) — "latest wins", no duplicates
  - Bounded: max ~200 entries per persona (configurable)
  - Safety fields: source_type, visibility, confidence
  - Compact injection: generates a small (~200-500 token) context block
    for system prompt injection

Golden rule: ADDITIVE ONLY — this module only adds new tables/features.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


def _get_db_path() -> str:
    from .storage import _get_db_path as _storage_db_path
    return _storage_db_path()


# Valid categories for persona memory entries
VALID_CATEGORIES = {
    "fact",              # User facts: name, job, location, etc.
    "preference",        # Likes/dislikes: favorite food, music, etc.
    "important_date",    # Birthdays, anniversaries, deadlines
    "emotion_pattern",   # How user typically feels: "stressed on Mondays"
    "milestone",         # Relationship milestones: "first deep conversation"
    "boundary",          # User-set boundaries: tone, topics to avoid
    "summary",           # High-level relationship summary (auto-updated)
}

# Maximum entries per persona (prevent unbounded growth)
MAX_ENTRIES_PER_PERSONA = 200


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def upsert_memory(
    project_id: str,
    category: str,
    key: str,
    value: str,
    confidence: float = 1.0,
    source_session: Optional[str] = None,
    source_type: str = "inferred",
) -> Dict[str, Any]:
    """
    Insert or update a memory entry. Uses UPSERT on (project_id, category, key).
    "Latest wins" — if the same key exists, value/confidence are updated.
    """
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    cur.execute(
        """
        INSERT INTO persona_memory(project_id, category, key, value, confidence,
                                    source_session, source_type, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, category, key) DO UPDATE SET
            value = excluded.value,
            confidence = excluded.confidence,
            source_session = excluded.source_session,
            source_type = excluded.source_type,
            updated_at = excluded.updated_at
        """,
        (project_id, category, key, value, confidence, source_session, source_type, now, now),
    )
    con.commit()
    con.close()

    return {
        "project_id": project_id,
        "category": category,
        "key": key,
        "value": value,
        "confidence": confidence,
        "source_type": source_type,
        "updated_at": now,
    }


def get_memories(
    project_id: str,
    category: Optional[str] = None,
    min_confidence: float = 0.0,
    limit: int = MAX_ENTRIES_PER_PERSONA,
) -> List[Dict[str, Any]]:
    """
    Retrieve memories for a persona project, optionally filtered by category.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if category:
        cur.execute(
            """
            SELECT * FROM persona_memory
            WHERE project_id = ? AND category = ? AND confidence >= ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (project_id, category, min_confidence, limit),
        )
    else:
        cur.execute(
            """
            SELECT * FROM persona_memory
            WHERE project_id = ? AND confidence >= ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (project_id, min_confidence, limit),
        )

    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]


def delete_memory(project_id: str, category: str, key: str) -> bool:
    """Delete a single memory entry. Returns True if found and deleted."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "DELETE FROM persona_memory WHERE project_id = ? AND category = ? AND key = ?",
        (project_id, category, key),
    )
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def forget_all(project_id: str) -> int:
    """
    'Forget me' button — wipe all memories for a persona project.
    Returns count of deleted entries.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM persona_memory WHERE project_id = ?",
        (project_id,),
    )
    count = cur.fetchone()[0]
    cur.execute(
        "DELETE FROM persona_memory WHERE project_id = ?",
        (project_id,),
    )
    con.commit()
    con.close()
    return count


def memory_count(project_id: str) -> int:
    """Count total memory entries for a persona."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM persona_memory WHERE project_id = ?",
        (project_id,),
    )
    count = cur.fetchone()[0]
    con.close()
    return count


# ---------------------------------------------------------------------------
# Context injection (for system prompt assembly)
# ---------------------------------------------------------------------------

def build_ltm_context(project_id: str, max_tokens_hint: int = 500) -> str:
    """
    Build a compact context string from LTM for injection into the system prompt.
    Organized by category for clarity.

    Returns empty string if no memories exist.
    Target: ~200-500 tokens (compact enough for every voice turn).
    """
    memories = get_memories(project_id, min_confidence=0.3)
    if not memories:
        return ""

    # Group by category
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for m in memories:
        cat = m["category"]
        by_cat.setdefault(cat, []).append(m)

    lines: List[str] = ["WHAT YOU REMEMBER ABOUT THE USER (long-term memory):"]

    category_labels = {
        "fact": "Facts",
        "preference": "Preferences",
        "important_date": "Important Dates",
        "emotion_pattern": "Emotional Patterns",
        "milestone": "Relationship Milestones",
        "boundary": "Boundaries (respect these)",
        "summary": "Relationship Summary",
    }

    for cat in ["summary", "fact", "preference", "important_date",
                "emotion_pattern", "milestone", "boundary"]:
        entries = by_cat.get(cat, [])
        if not entries:
            continue
        label = category_labels.get(cat, cat.title())
        lines.append(f"  {label}:")
        for entry in entries[:15]:  # Cap per category
            conf_tag = "" if entry["confidence"] >= 0.8 else " (uncertain)"
            lines.append(f"    - {entry['key']}: {entry['value']}{conf_tag}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session summary context (recent session summaries for continuity)
# ---------------------------------------------------------------------------

def build_session_summaries_context(
    project_id: str, max_sessions: int = 5
) -> str:
    """
    Build context from recent session summaries.
    Gives the persona awareness of past conversations.
    """
    from .sessions import list_sessions

    sessions = list_sessions(project_id, limit=max_sessions, include_ended=True)
    # Filter to those that have summaries
    summarized = [s for s in sessions if s.get("summary")]

    if not summarized:
        return ""

    lines: List[str] = ["YOUR RECENT CONVERSATIONS TOGETHER:"]
    for s in reversed(summarized):  # oldest first
        date = (s.get("started_at") or "unknown")[:10]
        mode = s.get("mode", "text")
        msgs = s.get("message_count", 0)
        summary = s.get("summary", "")
        lines.append(f"  - {date} ({mode}, {msgs} msgs): {summary}")

    return "\n".join(lines)
