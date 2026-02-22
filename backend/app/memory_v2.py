"""
Memory V2 — Brain-inspired hierarchical memory engine (additive).

Implements Working -> Consolidation -> Semantic memory with:
  - Exponential decay (activation fades over time)
  - Reinforcement (accessed/confirmed memories grow stronger)
  - Consolidation (repeated working items promote to semantic)
  - Pruning (low-activation + low-importance semantic items are forgotten)
  - Persona Integrity Kernel isolation (never modifies persona identity)

Memory types:
  P = Pinned   (user-approved "core memories"; never auto-pruned, tau=infinity)
  S = Semantic  (stable facts/preferences; slow decay tau~30 days; prunable)
  W = Working   (short-lived context traces; fast decay tau~6 hours)
  A = Anchor    (profile/persona kernel — not stored here; injected from profile.py)

IMPORTANT: This module is additive-only.
  - Reuses the existing persona_memory table
  - Adds optional columns via safe ALTER TABLE (ignored by V1 code)
  - V1 (ltm.py) continues to work unchanged
  - V2 is opt-in via memoryEngine='v2' in settings

IMPORTANT: Persona identity is NEVER learned/changed here.
  This stores only user-overlay memories (facts about the user, preferences,
  boundaries). The persona's voice/role/rules remain immutable in the
  PersonalityAgent definitions.
"""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .storage import _get_db_path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class V2Config:
    # Decay time constants (seconds)
    tau_working: float = 6 * 3600.0          # 6 hours
    tau_semantic: float = 30 * 24 * 3600.0   # 30 days

    # Reinforcement increments (eta in the saturating update: s <- 1-(1-s)*e^{-eta})
    eta_user_confirmed: float = 0.25
    eta_inferred: float = 0.05

    # Consolidation thresholds (promote W -> S)
    consolidate_min_repeats: int = 2
    consolidate_min_importance: float = 0.45
    consolidate_min_activation: float = 0.25

    # Prune thresholds (S only; Pinned never auto-pruned)
    prune_activation_thresh: float = 0.05
    prune_importance_thresh: float = 0.25

    # Retrieval budget (items per category injected into prompt)
    top_pinned: int = 4
    top_semantic: int = 8
    top_working: int = 1

    # Safety: max value length stored
    max_value_chars: int = 600

    # Throttle: min seconds between consolidation/pruning passes
    maintenance_interval: float = 30.0


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return time.time()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _activation(strength: float, last_access_at: float, tau: float) -> float:
    """Compute retrievability: A(t) = s * exp(-dt / tau)."""
    dt = max(0.0, _now() - (last_access_at or _now()))
    return float(strength) * math.exp(-dt / tau)


def _reinforce(strength: float, eta: float) -> float:
    """Saturating reinforcement: s <- 1 - (1-s) * exp(-eta)."""
    s = _clamp(float(strength), 0.0, 1.0)
    return 1.0 - (1.0 - s) * math.exp(-float(eta))


def _stable_hash(text: str) -> str:
    """Deterministic hash (stable across Python restarts, unlike hash())."""
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _clean_value(s: str, max_chars: int) -> str:
    s2 = (s or "").strip()
    s2 = re.sub(r"\s+", " ", s2)
    if len(s2) > max_chars:
        s2 = s2[:max_chars - 1].rstrip() + "..."
    return s2


def _keyword_score(query: str, text: str) -> float:
    """Lightweight relevance: normalized token overlap."""
    q = set(re.findall(r"[a-z0-9]{3,}", (query or "").lower()))
    t = set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))
    if not q or not t:
        return 0.0
    overlap = len(q.intersection(t))
    return overlap / max(1, min(len(q), 8))


# ---------------------------------------------------------------------------
# Explicit "remember this" detector (conservative — avoids false positives)
# ---------------------------------------------------------------------------

_RE_REMEMBER = re.compile(
    r"\b(remember this|remember that|don't forget|do not forget|please remember)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Schema extension (additive ALTER TABLE — safe to run repeatedly)
# ---------------------------------------------------------------------------

def ensure_v2_columns() -> None:
    """
    Add V2-specific columns to persona_memory table.
    Safe to call on every startup — skips columns that already exist.
    V1 code ignores these columns (uses SELECT * with sqlite3.Row).
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(persona_memory)")
    existing = {row[1] for row in cur.fetchall()}

    additions = [
        ("mem_type",       "TEXT DEFAULT 'S'"),     # P/S/W
        ("strength",       "REAL DEFAULT 0.5"),     # reinforcement strength
        ("importance",     "REAL DEFAULT 0.3"),     # importance score
        ("last_access_at", "REAL DEFAULT 0"),       # unix timestamp of last retrieval
        ("access_count",   "INTEGER DEFAULT 0"),    # how many times retrieved/reinforced
        ("last_seen_at",   "REAL DEFAULT 0"),       # unix timestamp when last ingested/seen
    ]

    for col_name, col_def in additions:
        if col_name not in existing:
            cur.execute(f"ALTER TABLE persona_memory ADD COLUMN {col_name} {col_def}")

    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# DB helpers (using sqlite3.Row for safe column-name access)
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    """Create a connection with Row factory (dict-like access by column name)."""
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def _select_memories(project_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all V2 memories for a project, optionally scoped to user."""
    con = _connect()
    cur = con.cursor()
    if user_id:
        cur.execute(
            "SELECT * FROM persona_memory WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
    else:
        cur.execute("SELECT * FROM persona_memory WHERE project_id = ?", (project_id,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def _upsert_memory(
    project_id: str,
    category: str,
    key: str,
    value: str,
    mem_type: str,
    source_type: str,
    confidence: float,
    strength: float,
    importance: float,
    seen_now: bool = True,
    reinforce_eta: Optional[float] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Additive upsert using existing UNIQUE(project_id, category, key).
    On conflict: updates value/confidence/source_type, preserves V2 fields.
    """
    con = sqlite3.connect(_get_db_path())
    cur = con.cursor()
    now_ts = _now()
    now_dt = time.strftime("%Y-%m-%d %H:%M:%S")
    value = _clean_value(value, max_chars=600)

    # Try update first
    cur.execute(
        """
        UPDATE persona_memory
        SET
            value = ?,
            confidence = ?,
            source_type = ?,
            updated_at = ?,
            mem_type = COALESCE(mem_type, ?),
            strength = COALESCE(strength, 0.5),
            importance = COALESCE(importance, ?),
            last_seen_at = CASE WHEN ? THEN ? ELSE COALESCE(last_seen_at, 0) END
        WHERE project_id = ? AND category = ? AND key = ?
        """,
        (value, float(confidence), source_type, now_dt,
         mem_type, float(importance),
         1 if seen_now else 0, now_ts,
         project_id, category, key),
    )

    if cur.rowcount == 0:
        # Insert new
        cur.execute(
            """
            INSERT INTO persona_memory
                (project_id, category, key, value, confidence, source_session,
                 source_type, created_at, updated_at,
                 mem_type, strength, importance, last_access_at, access_count, last_seen_at,
                 user_id)
            VALUES
                (?, ?, ?, ?, ?, NULL,
                 ?, ?, ?,
                 ?, ?, ?, 0, 0, ?,
                 ?)
            """,
            (project_id, category, key, value, float(confidence),
             source_type, now_dt, now_dt,
             mem_type, float(_clamp(strength, 0.0, 1.0)),
             float(_clamp(importance, 0.0, 1.0)),
             now_ts if seen_now else 0.0,
             user_id),
        )

    # Reinforce if requested (on existing or just-inserted row)
    if reinforce_eta is not None:
        cur.execute(
            """
            UPDATE persona_memory
            SET
                strength = MIN(1.0, 1.0 - (1.0 - COALESCE(strength, 0.5)) * EXP(-?)),
                last_access_at = ?,
                access_count = COALESCE(access_count, 0) + 1
            WHERE project_id = ? AND category = ? AND key = ?
            """,
            (float(reinforce_eta), now_ts, project_id, category, key),
        )

    con.commit()
    con.close()


def _touch_access(project_id: str, mem_id: int, eta: float) -> None:
    """Reinforce an existing memory entry by ID (light touch on retrieval)."""
    con = sqlite3.connect(_get_db_path())
    cur = con.cursor()
    now_ts = _now()
    cur.execute(
        """
        UPDATE persona_memory
        SET
            strength = MIN(1.0, 1.0 - (1.0 - COALESCE(strength, 0.5)) * EXP(-?)),
            last_access_at = ?,
            access_count = COALESCE(access_count, 0) + 1
        WHERE project_id = ? AND id = ?
        """,
        (float(eta), now_ts, project_id, int(mem_id)),
    )
    con.commit()
    con.close()


def _delete_by_id(project_id: str, mem_id: int) -> None:
    con = sqlite3.connect(_get_db_path())
    cur = con.cursor()
    cur.execute(
        "DELETE FROM persona_memory WHERE project_id = ? AND id = ?",
        (project_id, int(mem_id)),
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# V2 Engine
# ---------------------------------------------------------------------------

class MemoryV2Engine:
    def __init__(self, config: Optional[V2Config] = None) -> None:
        self.cfg = config or V2Config()
        self._last_maintenance: Dict[str, float] = {}  # project_id -> timestamp

    # ---- ingest (called per user message) ----

    def ingest_user_text(self, project_id: str, user_text: str, user_id: Optional[str] = None) -> None:
        """
        Ingest user text as memory. Three paths:
          1. Explicit "remember this" -> Pinned (P), never decays
          2. Default -> Working trace (W), fast decay
        Consolidation + pruning run on a throttled schedule (not every message).
        """
        t = _clean_value(user_text, self.cfg.max_value_chars)
        if not t or len(t) < 5:
            return

        # Path 1: Explicit "remember" -> pinned
        if _RE_REMEMBER.search(t):
            _upsert_memory(
                project_id=project_id,
                category="user",
                key=f"pinned:{_stable_hash(t)}",
                value=t,
                mem_type="P",
                source_type="user",
                confidence=1.0,
                strength=1.0,
                importance=0.95,
                reinforce_eta=self.cfg.eta_user_confirmed,
                user_id=user_id,
            )
            return

        # Path 2: Working trace (fast decay, cheap to store)
        _upsert_memory(
            project_id=project_id,
            category="working",
            key=f"w:{_stable_hash(t)}",
            value=t,
            mem_type="W",
            source_type="user",
            confidence=0.5,
            strength=0.5,
            importance=0.25,
            reinforce_eta=None,
            user_id=user_id,
        )

        # Throttled maintenance (consolidation + pruning)
        self._maybe_maintain(project_id, user_id=user_id)

    # ---- throttled maintenance ----

    def _maybe_maintain(self, project_id: str, user_id: Optional[str] = None) -> None:
        """Run consolidation + pruning at most once per maintenance_interval."""
        now = _now()
        last = self._last_maintenance.get(project_id, 0.0)
        if now - last < self.cfg.maintenance_interval:
            return
        self._last_maintenance[project_id] = now
        try:
            self.consolidate(project_id, user_id=user_id)
            self.prune(project_id, user_id=user_id)
        except Exception as e:
            print(f"[MEMORY_V2] Maintenance warning (non-fatal): {e}")

    # ---- consolidate (promote W -> S when reinforced) ----

    def consolidate(self, project_id: str, user_id: Optional[str] = None) -> None:
        """
        Promote Working -> Semantic if:
          - Repetition (similar to 2+ other W items OR similar to existing S item)
          - Still active (activation >= threshold)
          - Important enough (importance >= threshold)

        Also: when W overlaps with an existing S entry, reinforce that S entry.
        """
        mem = _select_memories(project_id, user_id=user_id)
        working = [m for m in mem if (m.get("mem_type") or "S") == "W"]
        semantic = [m for m in mem if (m.get("mem_type") or "S") == "S"]

        if not working:
            return

        # Recent working items only
        working_sorted = sorted(
            working,
            key=lambda x: float(x.get("last_seen_at") or 0),
            reverse=True,
        )[:15]

        for w in working_sorted:
            w_text = w.get("value") or ""
            w_strength = float(w.get("strength") or 0.5)
            w_last = float(w.get("last_access_at") or w.get("last_seen_at") or 0.0)
            if w_last <= 0:
                w_last = _now()

            # Activation in working space
            act = _activation(w_strength, w_last, self.cfg.tau_working)

            # Repetition: count similar W items
            rep = 0
            for w2 in working_sorted:
                if w2["id"] == w["id"]:
                    continue
                if _keyword_score(w2.get("value") or "", w_text) >= 0.6:
                    rep += 1

            # Importance heuristic: longer text + specific words
            imp = float(w.get("importance") or 0.25)
            if re.search(r"\b(prefer|always|never|important|boundary|hate|love)\b", w_text, re.I):
                imp = max(imp, 0.5)

            # Check overlap with existing semantic entries
            best_sem = None
            best_score = 0.0
            for s in semantic:
                sc = _keyword_score(w_text, s.get("value") or "")
                if sc > best_score:
                    best_score = sc
                    best_sem = s

            # If it maps to existing semantic, reinforce that entry
            if best_sem and best_score >= 0.45:
                _touch_access(project_id, int(best_sem["id"]), self.cfg.eta_inferred)
                continue

            # Otherwise: promote W -> S if thresholds met
            if (
                rep >= self.cfg.consolidate_min_repeats
                and imp >= self.cfg.consolidate_min_importance
                and act >= self.cfg.consolidate_min_activation
            ):
                _upsert_memory(
                    project_id=project_id,
                    category="semantic",
                    key=f"s:{_stable_hash(w_text)}",
                    value=f"Stable note: {w_text}",
                    mem_type="S",
                    source_type="inferred",
                    confidence=0.55,
                    strength=0.55,
                    importance=_clamp(imp, 0.0, 1.0),
                    reinforce_eta=self.cfg.eta_inferred,
                    user_id=user_id,
                )
                # Clean up promoted working item
                _delete_by_id(project_id, int(w["id"]))

    # ---- prune (human-like forgetting) ----

    def prune(self, project_id: str, user_id: Optional[str] = None) -> None:
        """
        Prune low-activation + low-importance Semantic entries (forgetting).
        Never prune Pinned (P). Trim excessive Working noise to ~25 items.
        """
        mem = _select_memories(project_id, user_id=user_id)

        # Prune semantic (decay-based)
        for s in mem:
            if (s.get("mem_type") or "S") != "S":
                continue
            strength = float(s.get("strength") or 0.5)
            last = float(s.get("last_access_at") or s.get("last_seen_at") or 0.0)
            if last <= 0:
                last = _now()
            imp = float(s.get("importance") or 0.3)
            act = _activation(strength, last, self.cfg.tau_semantic)
            if act < self.cfg.prune_activation_thresh and imp < self.cfg.prune_importance_thresh:
                _delete_by_id(project_id, int(s["id"]))

        # Trim Working noise: keep only latest ~25
        working = [m for m in mem if (m.get("mem_type") or "S") == "W"]
        if len(working) > 25:
            working_sorted = sorted(
                working,
                key=lambda x: float(x.get("last_seen_at") or 0.0),
                reverse=True,
            )
            for w in working_sorted[25:]:
                _delete_by_id(project_id, int(w["id"]))

    # ---- retrieve (build context for system prompt injection) ----

    def build_context(self, project_id: str, query: str, user_id: Optional[str] = None) -> str:
        """
        Build a compact memory context block for the system prompt.
        Retrieves: top Pinned + top Semantic (scored by relevance+activation) + 1 Working.
        Reinforces retrieved Semantic entries (light touch).
        """
        mem = _select_memories(project_id, user_id=user_id)

        pinned = [m for m in mem if (m.get("mem_type") or "S") == "P"]
        sem = [m for m in mem if (m.get("mem_type") or "S") == "S"]
        working = [m for m in mem if (m.get("mem_type") or "S") == "W"]

        # Rank pinned by importance then recency
        pinned_sorted = sorted(
            pinned,
            key=lambda x: (
                float(x.get("importance") or 0.9),
                float(x.get("last_seen_at") or 0.0),
            ),
            reverse=True,
        )[:self.cfg.top_pinned]

        # Rank semantic by composite score: relevance + activation + importance
        scored_sem: List[Tuple[float, Dict[str, Any]]] = []
        for s in sem:
            strength = float(s.get("strength") or 0.5)
            last = float(s.get("last_access_at") or s.get("last_seen_at") or 0.0)
            if last <= 0:
                last = _now()
            imp = float(s.get("importance") or 0.3)
            act = _activation(strength, last, self.cfg.tau_semantic)
            rel = _keyword_score(query, s.get("value") or "")
            score = 0.55 * rel + 0.30 * act + 0.15 * imp
            scored_sem.append((score, s))
        scored_sem.sort(key=lambda x: x[0], reverse=True)
        sem_top = [s for _, s in scored_sem[:self.cfg.top_semantic]]

        # Reinforce retrieved semantic memories (light touch)
        for s in sem_top:
            try:
                _touch_access(project_id, int(s["id"]), self.cfg.eta_inferred)
            except Exception:
                pass

        # Working: keep 1 most recent
        working_sorted = sorted(
            working,
            key=lambda x: float(x.get("last_seen_at") or 0.0),
            reverse=True,
        )[:self.cfg.top_working]

        # Build output
        lines: List[str] = []

        if pinned_sorted:
            lines.append("PINNED MEMORY (user-approved, permanent):")
            for m in pinned_sorted:
                lines.append(f"  - {m.get('value')}")
            lines.append("")

        if sem_top:
            lines.append("LEARNED MEMORY (semantic, long-term):")
            for m in sem_top:
                conf = float(m.get("confidence") or 0.5)
                tag = "" if conf >= 0.8 else " (uncertain)"
                lines.append(f"  - {m.get('value')}{tag}")
            lines.append("")

        if working_sorted:
            lines.append("WORKING CONTEXT (short-lived):")
            for m in working_sorted:
                lines.append(f"  - {m.get('value')}")
            lines.append("")

        return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Singleton (lazy)
# ---------------------------------------------------------------------------

_engine: Optional[MemoryV2Engine] = None


def get_memory_v2() -> MemoryV2Engine:
    global _engine
    if _engine is None:
        _engine = MemoryV2Engine()
    return _engine
