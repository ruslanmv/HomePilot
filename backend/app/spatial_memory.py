"""
Spatial Memory Builder — converts embodiment trace events into persistent
spatial memories that feed back into the perceive→think→decide pipeline.

Design principles:
  - ADDITIVE ONLY: New file, new table. Does not modify memory_v2.py.
  - NON-DESTRUCTIVE: Uses its own `spatial_trace` table alongside existing
    persona_memory. V2 code is completely unaware of this module.
  - Brain-inspired: Events are compressed into spatial "episodes" that
    consolidate over time (mirroring hippocampal replay).
  - Designed for the LangGraph agent's `perceive` node to query.

Storage model:
  ┌──────────────────────────────────────────────────────┐
  │ spatial_trace  (append-only event log)               │
  │  trace_id, seq, timestamp, kind, name, data_json     │
  ├──────────────────────────────────────────────────────┤
  │ spatial_episode (consolidated summaries)              │
  │  episode_id, persona_id, start_ts, end_ts,           │
  │  summary, tags, activation, importance                │
  └──────────────────────────────────────────────────────┘

Episode consolidation runs lazily: when new traces arrive, if the oldest
un-consolidated trace is >5 minutes old, a consolidation pass runs.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .storage import _get_db_path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SpatialConfig:
    """Tuning knobs for the spatial memory subsystem."""

    # Episode window: traces within this gap (seconds) form one episode.
    episode_gap_s: float = 300.0  # 5 minutes

    # Consolidation: minimum events to form an episode.
    min_events_per_episode: int = 3

    # Episode decay (seconds).  Episodes fade after ~7 days.
    tau_episode: float = 7 * 24 * 3600.0

    # Retrieval budget for the perceive node.
    top_episodes: int = 5

    # Max data_json chars stored per trace event.
    max_data_chars: int = 2000

    # Maintenance throttle.
    maintenance_interval: float = 60.0


_DEFAULT_CFG = SpatialConfig()


# ---------------------------------------------------------------------------
# Math helpers (same conventions as memory_v2)
# ---------------------------------------------------------------------------

def _now() -> float:
    return time.time()


def _decay(activation: float, elapsed_s: float, tau: float) -> float:
    """Exponential decay: a(t) = a_0 · exp(-elapsed / tau)."""
    if tau <= 0:
        return 0.0
    return activation * math.exp(-elapsed_s / tau)


def _episode_id(persona_id: str, start_ts: float) -> str:
    """Deterministic episode ID from persona + start time."""
    raw = f"{persona_id}:{start_ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Schema migration (additive, safe to re-run)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS spatial_trace (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id    TEXT    NOT NULL DEFAULT '',
    trace_id      TEXT    NOT NULL,
    seq           INTEGER NOT NULL,
    timestamp     TEXT    NOT NULL,
    elapsed_ms    REAL    NOT NULL DEFAULT 0,
    kind          TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    data_json     TEXT    NOT NULL DEFAULT '{}',
    ingested_at   REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spatial_trace_persona
    ON spatial_trace(persona_id, ingested_at);

CREATE INDEX IF NOT EXISTS idx_spatial_trace_kind
    ON spatial_trace(kind);

CREATE TABLE IF NOT EXISTS spatial_episode (
    episode_id    TEXT    PRIMARY KEY,
    persona_id    TEXT    NOT NULL,
    start_ts      REAL    NOT NULL,
    end_ts        REAL    NOT NULL,
    event_count   INTEGER NOT NULL DEFAULT 0,
    summary       TEXT    NOT NULL DEFAULT '',
    tags          TEXT    NOT NULL DEFAULT '[]',
    activation    REAL    NOT NULL DEFAULT 1.0,
    importance    REAL    NOT NULL DEFAULT 0.5,
    created_at    REAL    NOT NULL,
    last_accessed REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_spatial_episode_persona
    ON spatial_episode(persona_id, activation DESC);
"""


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Run additive schema migration. Safe to call repeatedly."""
    conn.executescript(_SCHEMA_SQL)


# ---------------------------------------------------------------------------
# SpatialMemoryBuilder
# ---------------------------------------------------------------------------

class SpatialMemoryBuilder:
    """
    Ingests trace events, stores them, and consolidates into episodes.

    Thread-safety: each method acquires its own connection from the DB path.
    Use one instance per persona (or share with persona_id parameter).
    """

    def __init__(self, persona_id: str = "", cfg: Optional[SpatialConfig] = None):
        self._persona_id = persona_id
        self._cfg = cfg or _DEFAULT_CFG
        self._db_path = str(_get_db_path())
        self._last_maintenance = 0.0
        self._ensure_schema()

    # ── Schema ───────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            _ensure_tables(conn)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Ingest ───────────────────────────────────────────────────────

    def ingest_batch(self, trace_id: str, events: List[Dict[str, Any]]) -> int:
        """
        Ingest a batch of trace events from the client.

        Args:
            trace_id: Session-scoped trace identifier.
            events: List of TraceEvent dicts from the client.

        Returns:
            Number of events ingested.
        """
        if not events:
            return 0

        now = _now()
        rows = []
        for ev in events:
            data_json = json.dumps(ev.get("data", {}))
            if len(data_json) > self._cfg.max_data_chars:
                data_json = data_json[:self._cfg.max_data_chars]

            rows.append((
                self._persona_id,
                trace_id,
                ev.get("seq", 0),
                ev.get("timestamp", ""),
                ev.get("elapsed_ms", 0),
                ev.get("kind", "custom"),
                ev.get("name", ""),
                data_json,
                now,
            ))

        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO spatial_trace
                   (persona_id, trace_id, seq, timestamp, elapsed_ms,
                    kind, name, data_json, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

        # Lazy maintenance
        if now - self._last_maintenance > self._cfg.maintenance_interval:
            self._maybe_consolidate()
            self._last_maintenance = now

        return len(rows)

    # ── Consolidation ────────────────────────────────────────────────

    def _maybe_consolidate(self) -> int:
        """
        Scan un-consolidated traces and group into episodes.

        Grouping rule: consecutive events within `episode_gap_s` of each
        other form a single episode.

        Returns number of new episodes created.
        """
        with self._conn() as conn:
            # Get traces not yet assigned to an episode
            # We detect "un-consolidated" by checking which traces have
            # ingested_at > the latest episode.end_ts for this persona.
            latest_ep = conn.execute(
                "SELECT MAX(end_ts) FROM spatial_episode WHERE persona_id = ?",
                (self._persona_id,),
            ).fetchone()
            cutoff = latest_ep[0] if latest_ep and latest_ep[0] else 0

            traces = conn.execute(
                """SELECT id, ingested_at, kind, name, data_json
                   FROM spatial_trace
                   WHERE persona_id = ? AND ingested_at > ?
                   ORDER BY ingested_at ASC""",
                (self._persona_id, cutoff),
            ).fetchall()

            if len(traces) < self._cfg.min_events_per_episode:
                return 0

            # Group into episodes by time gap
            episodes: List[List[sqlite3.Row]] = []
            current_group: List[sqlite3.Row] = [traces[0]]

            for t in traces[1:]:
                gap = t["ingested_at"] - current_group[-1]["ingested_at"]
                if gap > self._cfg.episode_gap_s:
                    if len(current_group) >= self._cfg.min_events_per_episode:
                        episodes.append(current_group)
                    current_group = [t]
                else:
                    current_group.append(t)

            # Don't consolidate the current (still-active) group
            # Only finalize groups whose last event is >episode_gap_s old
            now = _now()
            if current_group and (now - current_group[-1]["ingested_at"]) > self._cfg.episode_gap_s:
                if len(current_group) >= self._cfg.min_events_per_episode:
                    episodes.append(current_group)

            created = 0
            for group in episodes:
                start_ts = group[0]["ingested_at"]
                end_ts = group[-1]["ingested_at"]
                eid = _episode_id(self._persona_id, start_ts)

                # Build summary from event kinds/names
                summary = self._summarize_episode(group)
                tags = self._extract_tags(group)
                importance = self._score_importance(group)

                conn.execute(
                    """INSERT OR IGNORE INTO spatial_episode
                       (episode_id, persona_id, start_ts, end_ts, event_count,
                        summary, tags, activation, importance, created_at, last_accessed)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, 0)""",
                    (
                        eid, self._persona_id, start_ts, end_ts,
                        len(group), summary, json.dumps(tags),
                        importance, now,
                    ),
                )
                created += 1

            return created

    def _summarize_episode(self, group: List[sqlite3.Row]) -> str:
        """Build a human-readable summary of an episode."""
        kinds = {}
        names = []
        for t in group:
            k = t["kind"]
            kinds[k] = kinds.get(k, 0) + 1
            names.append(t["name"])

        parts = []
        for k, count in sorted(kinds.items(), key=lambda x: -x[1]):
            parts.append(f"{k}×{count}")

        duration_s = group[-1]["ingested_at"] - group[0]["ingested_at"]
        duration_label = (
            f"{int(duration_s)}s" if duration_s < 60
            else f"{duration_s / 60:.1f}min"
        )

        return f"Episode ({duration_label}): {', '.join(parts)}"

    def _extract_tags(self, group: List[sqlite3.Row]) -> List[str]:
        """Extract searchable tags from an episode's events."""
        tags = set()
        for t in group:
            tags.add(t["kind"])
            # Extract key event names (first word before dot)
            name = t["name"]
            if "." in name:
                tags.add(name.split(".")[0])
        return sorted(tags)

    def _score_importance(self, group: List[sqlite3.Row]) -> float:
        """Score episode importance (0..1) based on event diversity and count."""
        kinds = set(t["kind"] for t in group)
        # More diverse events = more important interaction
        diversity = min(len(kinds) / 5.0, 1.0)
        # More events = more substantial
        volume = min(len(group) / 20.0, 1.0)
        return round(0.6 * diversity + 0.4 * volume, 3)

    # ── Retrieval (for perceive node) ────────────────────────────────

    def get_recent_episodes(
        self,
        limit: Optional[int] = None,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent spatial episodes for the perceive node.

        Returns episodes sorted by activation (decayed), filtered
        by minimum importance.
        """
        limit = limit or self._cfg.top_episodes
        now = _now()

        with self._conn() as conn:
            rows = conn.execute(
                """SELECT episode_id, start_ts, end_ts, event_count,
                          summary, tags, activation, importance, created_at
                   FROM spatial_episode
                   WHERE persona_id = ? AND importance >= ?
                   ORDER BY activation DESC
                   LIMIT ?""",
                (self._persona_id, min_importance, limit * 3),
            ).fetchall()

        # Apply decay and re-sort
        results = []
        for row in rows:
            elapsed = now - row["created_at"]
            decayed = _decay(row["activation"], elapsed, self._cfg.tau_episode)
            if decayed < 0.01:
                continue  # effectively forgotten
            results.append({
                "episode_id": row["episode_id"],
                "start_ts": row["start_ts"],
                "end_ts": row["end_ts"],
                "event_count": row["event_count"],
                "summary": row["summary"],
                "tags": json.loads(row["tags"]),
                "activation": round(decayed, 4),
                "importance": row["importance"],
            })

        results.sort(key=lambda e: -e["activation"])
        return results[:limit]

    def get_trace_events(
        self,
        trace_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query raw trace events (for replay or debugging).
        """
        with self._conn() as conn:
            clauses = ["persona_id = ?"]
            params: list = [self._persona_id]

            if trace_id:
                clauses.append("trace_id = ?")
                params.append(trace_id)
            if kind:
                clauses.append("kind = ?")
                params.append(kind)

            params.append(limit)
            rows = conn.execute(
                f"""SELECT trace_id, seq, timestamp, elapsed_ms, kind, name, data_json
                    FROM spatial_trace
                    WHERE {' AND '.join(clauses)}
                    ORDER BY ingested_at DESC
                    LIMIT ?""",
                params,
            ).fetchall()

        return [
            {
                "trace_id": r["trace_id"],
                "seq": r["seq"],
                "timestamp": r["timestamp"],
                "elapsed_ms": r["elapsed_ms"],
                "kind": r["kind"],
                "name": r["name"],
                "data": json.loads(r["data_json"]),
            }
            for r in rows
        ]

    def reinforce_episode(self, episode_id: str, eta: float = 0.15) -> bool:
        """
        Reinforce an episode's activation (called when the episode
        proves useful in a conversation).

        Uses the same saturating update as memory_v2:
          activation <- 1 - (1 - activation) * exp(-eta)
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT activation FROM spatial_episode WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
            if not row:
                return False

            new_act = 1.0 - (1.0 - row["activation"]) * math.exp(-eta)
            conn.execute(
                """UPDATE spatial_episode
                   SET activation = ?, last_accessed = ?
                   WHERE episode_id = ?""",
                (new_act, _now(), episode_id),
            )
            return True

    def get_spatial_context_block(self) -> str:
        """
        Generate a text block for injection into the LLM system prompt.
        Returns empty string if no relevant episodes exist.
        """
        episodes = self.get_recent_episodes()
        if not episodes:
            return ""

        lines = ["<spatial_memory>"]
        for ep in episodes:
            tags_str = ", ".join(ep["tags"])
            lines.append(
                f"  [{ep['summary']}] "
                f"(tags: {tags_str}, "
                f"importance: {ep['importance']}, "
                f"activation: {ep['activation']})"
            )
        lines.append("</spatial_memory>")
        return "\n".join(lines)
