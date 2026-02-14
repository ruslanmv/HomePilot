"""
Durable Async Job Processing — Persona Companion System

Lightweight job queue stored in SQLite. Survives server restarts.
Jobs are processed lazily (on next request) or via background tick.

Job types:
  - summarize_session: Generate an LLM summary of a session's messages
  - extract_memory: Extract facts/preferences from recent messages into LTM

Design:
  - No external dependencies (no Redis, no Celery)
  - Jobs stored in persona_jobs table with status lifecycle:
    pending → processing → done | error
  - Processing is bounded: max 1 job per request, max frequency limits
  - Non-blocking: voice responses are never delayed by job processing

Golden rule: ADDITIVE ONLY.
"""
from __future__ import annotations

import json
import sqlite3
import time
import traceback
from typing import Any, Dict, List, Optional


def _get_db_path() -> str:
    from .storage import _get_db_path as _storage_db_path
    return _storage_db_path()


# Rate limiting: don't process jobs too frequently
_last_process_time: float = 0.0
_MIN_PROCESS_INTERVAL_SECONDS = 10.0  # At most once per 10 seconds


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

def enqueue_job(
    project_id: str,
    job_type: str,
    session_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Enqueue a new job. Returns the job ID.
    Deduplicates: won't create if an identical pending job already exists.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    # Dedup check: don't create duplicate pending jobs
    cur.execute(
        """
        SELECT id FROM persona_jobs
        WHERE project_id = ? AND session_id IS ? AND job_type = ? AND status = 'pending'
        LIMIT 1
        """,
        (project_id, session_id, job_type),
    )
    existing = cur.fetchone()
    if existing:
        con.close()
        return existing[0]

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    payload_json = json.dumps(payload) if payload else None
    cur.execute(
        """
        INSERT INTO persona_jobs(project_id, session_id, job_type, status, payload, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', ?, ?, ?)
        """,
        (project_id, session_id, job_type, payload_json, now, now),
    )
    job_id = cur.lastrowid
    con.commit()
    con.close()
    return job_id


def get_pending_jobs(limit: int = 5) -> List[Dict[str, Any]]:
    """Get oldest pending jobs."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT * FROM persona_jobs
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]


def mark_job(job_id: int, status: str, result: Optional[str] = None) -> None:
    """Update job status (processing/done/error)."""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE persona_jobs SET status = ?, result = ?, updated_at = ? WHERE id = ?",
        (status, result, now, job_id),
    )
    con.commit()
    con.close()


def cleanup_old_jobs(days: int = 30) -> int:
    """Remove completed/errored jobs older than N days."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        DELETE FROM persona_jobs
        WHERE status IN ('done', 'error')
        AND created_at < datetime('now', ?)
        """,
        (f"-{days} days",),
    )
    count = cur.rowcount
    con.commit()
    con.close()
    return count


# ---------------------------------------------------------------------------
# Job processing (lazy — called opportunistically)
# ---------------------------------------------------------------------------

async def process_one_pending_job() -> Optional[Dict[str, Any]]:
    """
    Process at most one pending job, if enough time has passed.
    Called opportunistically from request handlers.
    Non-blocking: returns immediately if rate-limited.

    Returns the job dict if processed, None if skipped.
    """
    global _last_process_time

    now = time.time()
    if now - _last_process_time < _MIN_PROCESS_INTERVAL_SECONDS:
        return None
    _last_process_time = now

    jobs = get_pending_jobs(limit=1)
    if not jobs:
        return None

    job = jobs[0]
    job_id = job["id"]
    job_type = job["job_type"]

    mark_job(job_id, "processing")

    try:
        if job_type == "summarize_session":
            await _process_summarize_session(job)
        elif job_type == "extract_memory":
            await _process_extract_memory(job)
        else:
            mark_job(job_id, "error", f"Unknown job type: {job_type}")
            return job

        mark_job(job_id, "done")
        print(f"[JOBS] Completed job {job_id} ({job_type})")
    except Exception as e:
        mark_job(job_id, "error", str(e))
        print(f"[JOBS] Error processing job {job_id}: {e}")
        traceback.print_exc()

    return job


async def _process_summarize_session(job: Dict[str, Any]) -> None:
    """
    Summarize a session's messages and store the summary.
    Uses a small/fast model for efficiency.
    """
    from .storage import get_recent
    from .sessions import get_session, update_session_summary

    session_id = job.get("session_id")
    if not session_id:
        return

    session = get_session(session_id)
    if not session:
        return

    conversation_id = session["conversation_id"]
    messages = get_recent(conversation_id, limit=50)

    if len(messages) < 2:
        update_session_summary(session_id, "Brief interaction — too short to summarize.")
        return

    # Build transcript for summarization
    transcript_lines = []
    for role, content in messages:
        speaker = "User" if role == "user" else "Persona"
        transcript_lines.append(f"{speaker}: {content}")
    transcript = "\n".join(transcript_lines[-30:])  # Last 30 messages max

    # Use LLM to generate summary
    try:
        from .llm import chat as llm_chat

        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "You are a concise summarizer. Summarize this conversation in 1-2 sentences. "
                    "Focus on: main topics discussed, user's emotional state, any important facts "
                    "or preferences revealed. Keep it under 100 words."
                ),
            },
            {"role": "user", "content": f"Summarize this conversation:\n\n{transcript}"},
        ]

        response = await llm_chat(
            summary_prompt,
            temperature=0.3,
            max_tokens=150,
        )
        summary = (
            (response.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            or "Conversation occurred but summary generation failed."
        )
        update_session_summary(session_id, summary.strip())
        print(f"[JOBS] Generated summary for session {session_id}: {summary[:80]}...")
    except Exception as e:
        # Non-fatal: store a fallback summary
        update_session_summary(
            session_id,
            f"Conversation with {len(messages)} messages. (Auto-summary unavailable)",
        )
        print(f"[JOBS] Summary generation failed for session {session_id}: {e}")


async def _process_extract_memory(job: Dict[str, Any]) -> None:
    """
    Extract facts, preferences, and important dates from recent messages
    and store them in Long-Term Memory (LTM).
    """
    from .storage import get_recent
    from .sessions import get_session
    from .ltm import upsert_memory, memory_count, MAX_ENTRIES_PER_PERSONA

    session_id = job.get("session_id")
    project_id = job["project_id"]

    # Check if we're at capacity
    current_count = memory_count(project_id)
    if current_count >= MAX_ENTRIES_PER_PERSONA:
        print(f"[JOBS] Memory at capacity ({current_count}) for project {project_id}, skipping extraction")
        return

    # Get conversation messages
    conversation_id = None
    if session_id:
        session = get_session(session_id)
        if session:
            conversation_id = session["conversation_id"]

    if not conversation_id:
        return

    messages = get_recent(conversation_id, limit=20)
    if len(messages) < 2:
        return

    # Build transcript for extraction
    transcript_lines = []
    for role, content in messages[-10:]:  # Last 10 messages only
        speaker = "User" if role == "user" else "Persona"
        transcript_lines.append(f"{speaker}: {content}")
    transcript = "\n".join(transcript_lines)

    try:
        from .llm import chat as llm_chat

        extract_prompt = [
            {
                "role": "system",
                "content": """You are a memory extraction agent. From the conversation below, extract any NEW factual information about the user.

Return a JSON array of objects, each with:
- "category": one of "fact", "preference", "important_date", "emotion_pattern", "boundary"
- "key": short identifier (snake_case, e.g. "user_name", "favorite_food", "birthday")
- "value": the actual information
- "confidence": 0.0 to 1.0 (how certain you are)

Rules:
- Only extract information the USER explicitly stated or strongly implied
- Do NOT extract from persona/assistant messages
- Do NOT extract explicit/sexual content details
- Keep keys short and reusable (same key = same fact, updated)
- Max 5 extractions per batch
- If nothing new to extract, return empty array: []

Return ONLY the JSON array, no markdown or explanation.""",
            },
            {"role": "user", "content": f"Extract memories from:\n\n{transcript}"},
        ]

        response = await llm_chat(
            extract_prompt,
            temperature=0.1,
            max_tokens=500,
        )
        raw = (
            (response.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "[]")
        )

        # Parse JSON (handle markdown code blocks)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

        memories = json.loads(raw)
        if not isinstance(memories, list):
            return

        stored = 0
        for mem in memories[:5]:  # Hard cap: 5 per extraction
            cat = mem.get("category", "fact")
            key = mem.get("key", "")
            value = mem.get("value", "")
            conf = float(mem.get("confidence", 0.5))

            if not key or not value or conf < 0.5:
                continue

            upsert_memory(
                project_id=project_id,
                category=cat,
                key=key,
                value=value,
                confidence=conf,
                source_session=session_id,
                source_type="inferred",
            )
            stored += 1

        if stored:
            print(f"[JOBS] Extracted {stored} memories for project {project_id}")

    except (json.JSONDecodeError, ValueError) as e:
        print(f"[JOBS] Memory extraction parse error: {e}")
    except Exception as e:
        print(f"[JOBS] Memory extraction failed: {e}")


# ---------------------------------------------------------------------------
# Convenience: schedule jobs for a session
# ---------------------------------------------------------------------------

def schedule_session_jobs(project_id: str, session_id: str) -> None:
    """
    Schedule both summarize + extract jobs for a session.
    Called when a session ends or on inactivity timeout.
    """
    enqueue_job(project_id, "summarize_session", session_id=session_id)
    enqueue_job(project_id, "extract_memory", session_id=session_id)
    print(f"[JOBS] Scheduled summarize + extract for session {session_id}")
