"""
Minimal unit tests for the companion-grade persona system.

Tests:
  - Sessions: create, list, end, resume algorithm
  - LTM: upsert, get, forget, context builder
  - Jobs: enqueue, dedup, pending list
  - API endpoints: session + memory CRUD via HTTP

Non-destructive: uses the temp DB from conftest.py.
CI-friendly: no real LLM calls, no network, pure logic.
"""
import pytest


# ═══════════════════════════════════════════════════════════════════════
# 1. SESSIONS — unit tests (direct module calls)
# ═══════════════════════════════════════════════════════════════════════


class TestSessions:
    """Session lifecycle: create, list, end, resume algorithm."""

    PROJECT_ID = "test-persona-sessions-001"

    def test_create_session(self, app):
        from app.sessions import create_session, list_sessions

        s = create_session(self.PROJECT_ID, mode="voice", title="Hello")
        assert s["project_id"] == self.PROJECT_ID
        assert s["mode"] == "voice"
        assert s["title"] == "Hello"
        assert s["conversation_id"]  # non-empty UUID
        assert s["ended_at"] is None
        assert s["message_count"] == 0

        sessions = list_sessions(self.PROJECT_ID)
        assert any(x["id"] == s["id"] for x in sessions)

    def test_end_session(self, app):
        from app.sessions import create_session, end_session, get_session

        s = create_session(self.PROJECT_ID, mode="text")
        assert end_session(s["id"]) is True

        ended = get_session(s["id"])
        assert ended is not None
        assert ended["ended_at"] is not None

        # Ending again is a no-op (already ended)
        assert end_session(s["id"]) is False

    def test_resolve_returns_open_session(self, app):
        from app.sessions import create_session, resolve_session

        proj = "test-resolve-open"
        s = create_session(proj, mode="voice")
        resolved = resolve_session(proj)
        assert resolved is not None
        assert resolved["id"] == s["id"]

    def test_resolve_falls_back_to_ended(self, app):
        """If all sessions are ended, resolve still returns the most recent."""
        proj = "test-resolve-fallback"
        from app.sessions import create_session, end_session, resolve_session

        s = create_session(proj, mode="text")
        end_session(s["id"])

        resolved = resolve_session(proj)
        assert resolved is not None
        assert resolved["id"] == s["id"]

    def test_resolve_returns_none_when_empty(self, app):
        from app.sessions import resolve_session

        assert resolve_session("non-existent-project-xyz") is None

    def test_get_or_create_creates_when_empty(self, app):
        from app.sessions import get_or_create_session

        proj = "test-get-or-create"
        s = get_or_create_session(proj, mode="voice")
        assert s["project_id"] == proj
        assert s["mode"] == "voice"

    def test_message_count_increments(self, app):
        from app.sessions import create_session, get_session
        from app.storage import add_message

        s = create_session(self.PROJECT_ID, mode="text")
        # Add real messages so enrichment can count them
        add_message(s["conversation_id"], "user", "Hello")
        add_message(s["conversation_id"], "assistant", "Hi there!")

        updated = get_session(s["id"])
        assert updated["message_count"] == 2

    def test_session_summary(self, app):
        from app.sessions import create_session, update_session_summary, get_session

        s = create_session(self.PROJECT_ID, mode="voice")
        update_session_summary(s["id"], "Talked about weekend plans.")

        updated = get_session(s["id"])
        assert updated["summary"] == "Talked about weekend plans."

    def test_get_session_by_conversation(self, app):
        from app.sessions import create_session, get_session_by_conversation

        s = create_session(self.PROJECT_ID, mode="text")
        found = get_session_by_conversation(s["conversation_id"])
        assert found is not None
        assert found["id"] == s["id"]


# ═══════════════════════════════════════════════════════════════════════
# 2. LONG-TERM MEMORY — unit tests
# ═══════════════════════════════════════════════════════════════════════


class TestLTM:
    """Long-term memory: upsert, get, forget, context injection."""

    PROJECT_ID = "test-persona-ltm-001"

    def test_upsert_and_get(self, app):
        from app.ltm import upsert_memory, get_memories

        upsert_memory(self.PROJECT_ID, "fact", "user_name", "Alex")
        upsert_memory(self.PROJECT_ID, "preference", "food", "Italian")

        mems = get_memories(self.PROJECT_ID)
        assert len(mems) >= 2
        keys = {m["key"] for m in mems}
        assert "user_name" in keys
        assert "food" in keys

    def test_upsert_overwrites(self, app):
        """Same (project, category, key) → update, not duplicate."""
        from app.ltm import upsert_memory, get_memories

        upsert_memory(self.PROJECT_ID, "fact", "job", "Engineer")
        upsert_memory(self.PROJECT_ID, "fact", "job", "Manager")

        mems = get_memories(self.PROJECT_ID, category="fact")
        jobs = [m for m in mems if m["key"] == "job"]
        assert len(jobs) == 1
        assert jobs[0]["value"] == "Manager"

    def test_filter_by_category(self, app):
        from app.ltm import upsert_memory, get_memories

        upsert_memory(self.PROJECT_ID, "important_date", "birthday", "March 15")
        mems = get_memories(self.PROJECT_ID, category="important_date")
        assert all(m["category"] == "important_date" for m in mems)

    def test_confidence_filter(self, app):
        from app.ltm import upsert_memory, get_memories

        upsert_memory(self.PROJECT_ID, "fact", "low_conf", "maybe", confidence=0.2)
        mems = get_memories(self.PROJECT_ID, min_confidence=0.5)
        assert not any(m["key"] == "low_conf" for m in mems)

    def test_delete_single(self, app):
        from app.ltm import upsert_memory, delete_memory, get_memories

        upsert_memory(self.PROJECT_ID, "fact", "delete_me", "gone")
        assert delete_memory(self.PROJECT_ID, "fact", "delete_me") is True
        assert delete_memory(self.PROJECT_ID, "fact", "delete_me") is False  # already gone

    def test_forget_all(self, app):
        from app.ltm import upsert_memory, forget_all, memory_count

        proj = "test-forget-all"
        upsert_memory(proj, "fact", "a", "1")
        upsert_memory(proj, "fact", "b", "2")
        assert memory_count(proj) == 2

        forgotten = forget_all(proj)
        assert forgotten == 2
        assert memory_count(proj) == 0

    def test_build_ltm_context_empty(self, app):
        from app.ltm import build_ltm_context

        ctx = build_ltm_context("no-such-project")
        assert ctx == ""

    def test_build_ltm_context_populated(self, app):
        from app.ltm import upsert_memory, build_ltm_context

        proj = "test-ltm-ctx"
        upsert_memory(proj, "fact", "name", "Sofia")
        upsert_memory(proj, "preference", "color", "Blue")

        ctx = build_ltm_context(proj)
        assert "WHAT YOU REMEMBER" in ctx
        assert "Sofia" in ctx
        assert "Blue" in ctx


# ═══════════════════════════════════════════════════════════════════════
# 3. JOBS — unit tests
# ═══════════════════════════════════════════════════════════════════════


class TestJobs:
    """Durable async job queue: enqueue, dedup, pending list."""

    PROJECT_ID = "test-persona-jobs-001"

    def test_enqueue_and_list(self, app):
        from app.jobs import enqueue_job, get_pending_jobs

        jid = enqueue_job(self.PROJECT_ID, "summarize_session", session_id="s1")
        assert isinstance(jid, int)

        pending = get_pending_jobs()
        assert any(j["id"] == jid for j in pending)

    def test_dedup(self, app):
        """Same (project, session, type) pending → no duplicate."""
        from app.jobs import enqueue_job

        proj = "test-dedup"
        id1 = enqueue_job(proj, "extract_memory", session_id="s2")
        id2 = enqueue_job(proj, "extract_memory", session_id="s2")
        assert id1 == id2

    def test_mark_done(self, app):
        from app.jobs import enqueue_job, mark_job, get_pending_jobs

        proj = "test-mark-done"
        jid = enqueue_job(proj, "summarize_session", session_id="s3")
        mark_job(jid, "done", "Summary generated")

        pending = get_pending_jobs()
        assert not any(j["id"] == jid for j in pending)

    def test_schedule_session_jobs(self, app):
        from app.jobs import schedule_session_jobs, get_pending_jobs

        proj = "test-schedule"
        schedule_session_jobs(proj, "s4")

        pending = get_pending_jobs()
        types = {j["job_type"] for j in pending if j["project_id"] == proj}
        assert "summarize_session" in types
        assert "extract_memory" in types


# ═══════════════════════════════════════════════════════════════════════
# 4. API ENDPOINTS — integration tests (via TestClient)
# ═══════════════════════════════════════════════════════════════════════


class TestSessionAPI:
    """HTTP-level tests for /persona/sessions/* endpoints."""

    PROJECT_ID = "test-api-sessions"

    def test_create_session_endpoint(self, client):
        r = client.post("/persona/sessions", json={
            "project_id": self.PROJECT_ID,
            "mode": "voice",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["ok"] is True
        assert data["session"]["mode"] == "voice"

    def test_list_sessions_endpoint(self, client):
        # Create one first
        client.post("/persona/sessions", json={
            "project_id": self.PROJECT_ID,
            "mode": "text",
        })
        r = client.get(f"/persona/sessions?project_id={self.PROJECT_ID}")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["sessions"]) >= 1

    def test_resolve_session_endpoint(self, client):
        r = client.post("/persona/sessions/resolve", json={
            "project_id": self.PROJECT_ID,
            "mode": "text",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["session"]["project_id"] == self.PROJECT_ID

    def test_end_session_endpoint(self, client):
        # Create then end
        cr = client.post("/persona/sessions", json={
            "project_id": self.PROJECT_ID,
            "mode": "voice",
        })
        sid = cr.json()["session"]["id"]

        r = client.post(f"/persona/sessions/{sid}/end")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_get_session_endpoint(self, client):
        cr = client.post("/persona/sessions", json={
            "project_id": self.PROJECT_ID,
            "mode": "text",
        })
        sid = cr.json()["session"]["id"]

        r = client.get(f"/persona/sessions/{sid}")
        assert r.status_code == 200
        assert r.json()["session"]["id"] == sid

    def test_get_nonexistent_session_404(self, client):
        r = client.get("/persona/sessions/does-not-exist")
        assert r.status_code == 404

    def test_resolve_missing_project_id_400(self, client):
        r = client.post("/persona/sessions/resolve", json={})
        assert r.status_code == 400


class TestMemoryAPI:
    """HTTP-level tests for /persona/memory endpoints."""

    PROJECT_ID = "test-api-memory"

    def test_upsert_and_get(self, client):
        # Upsert
        r = client.post("/persona/memory", json={
            "project_id": self.PROJECT_ID,
            "category": "fact",
            "key": "user_name",
            "value": "TestUser",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Get
        r = client.get(f"/persona/memory?project_id={self.PROJECT_ID}")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["count"] >= 1
        assert any(m["key"] == "user_name" for m in data["memories"])

    def test_delete_specific(self, client):
        client.post("/persona/memory", json={
            "project_id": self.PROJECT_ID,
            "category": "preference",
            "key": "color",
            "value": "red",
        })
        r = client.request("DELETE", "/persona/memory", json={
            "project_id": self.PROJECT_ID,
            "category": "preference",
            "key": "color",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_forget_all(self, client):
        proj = "test-api-forget-all"
        client.post("/persona/memory", json={
            "project_id": proj,
            "category": "fact",
            "key": "a",
            "value": "1",
        })
        r = client.request("DELETE", "/persona/memory", json={
            "project_id": proj,
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_missing_fields_400(self, client):
        r = client.post("/persona/memory", json={
            "project_id": self.PROJECT_ID,
            # missing key and value
        })
        assert r.status_code == 400

    def test_delete_missing_project_400(self, client):
        r = client.request("DELETE", "/persona/memory", json={})
        assert r.status_code == 400
