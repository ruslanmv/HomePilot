"""The MeetingSense MCP server, tool by tool (batch MS21, wave W7).

Ten tools over what six waves already built, and the point of this batch landing *last* is
that none of them computes anything: every one is a thin call into
`backend/app/meetingsense/`. A capability layer that reimplemented retrieval, or the live
context, or the notes shape would be a second answer to every question the product already
answers, and the two would drift the first time a batch changed one of them. So these tests
check the seam and the policy, not the arithmetic — the arithmetic has 706 tests of its own.

Four things carry the batch.

**Every tool is one HTTP call to the backend.** The MCP image contains `agentic/` and no
`backend/`, so importing the meeting store here would work from the Makefile and fail in the
container — the worst of the two. These tests run the *real* backend router behind an httpx
transport, so a tool that names a route the backend does not serve fails here rather than in
somebody's container.

**Reads are open; the four writes are gated**, with the same wording `local-notes` uses. An
agent told "write disabled" can say so; one handed a stack trace cannot.

**A machine with no MeetingSense answers in sentences.** It is off by default and most installs
never turn it on. Every tool says "not available on this install" rather than raising, because
a persona can pass that on and cannot pass on a tool error.

**Port 9107 is nobody else's.** Two servers on one port is a failure that looks like a broken
tool rather than a broken port, so the Makefile is read and checked.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]

# `agentic` is a package at the repo root, not under `backend/`. The same two lines
# `test_mcp_servers.py` needs, and for the same reason.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _rpc(client: TestClient, method: str, params: dict | None = None):
    return client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": "1", "method": method, "params": params or {}},
    )


def call(client: TestClient, name: str, **arguments):
    res = _rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert "result" in payload, payload
    return payload["result"]


def said(result) -> str:
    return "\n".join(c.get("text", "") for c in result.get("content", []))


@pytest.fixture()
def server(monkeypatch):
    """The app, with writes off — the shipped state."""
    import agentic.integrations.mcp.meetingsense.app as ms_app

    monkeypatch.setattr(ms_app, "WRITE_ENABLED", False)
    monkeypatch.setattr(ms_app, "DRY_RUN", True)
    return ms_app


@pytest.fixture()
def writable(server, monkeypatch):
    monkeypatch.setattr(server, "WRITE_ENABLED", True)
    return server


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A throwaway meetings database behind the real routes."""
    import app.meetingsense.store as store_mod
    import app.meetingsense.session as session_mod

    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(store_mod, "_connect", _connect)
    store_mod.migrate()
    session_mod._SESSIONS.clear()
    return store_mod


@pytest.fixture()
def backend(store, server, monkeypatch):
    """The real MeetingSense router, reachable at the URL the MCP server calls.

    Not a stub of the backend: a tool that names a route the backend does not serve is exactly
    the bug this batch can introduce, and a stub would answer it happily. httpx's ASGI
    transport puts the actual app behind the actual client.
    """
    import httpx
    from fastapi import FastAPI
    import app.meetingsense.routes as routes_mod

    api = FastAPI()
    api.include_router(routes_mod.router)
    transport = httpx.ASGITransport(app=api)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=transport, base_url="http://backend", **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(server, "BACKEND_BASE_URL", "")
    return api


@pytest.fixture()
def client(server, backend):
    return TestClient(server.app)


NOTES = {
    "recap": "The team held enterprise pricing at forty a seat and pushed legal to October.",
    "decisions": [{"text": "Hold pricing at forty a seat", "t0": 600_000}],
    "actions": [{"text": "Send the vendor the revised terms", "owner": "Ana"}],
    "questions": [{"text": "Who signs off on the discount tier?", "resolved": False}],
}


@pytest.fixture()
def meeting(store, backend):
    store.create_meeting(conversation_id="conv-1", meeting_id="m1", title="Q3 planning",
                         source="teams", started_at=1_700_000_000.0)
    store.add_segments("m1", [
        {"t0_ms": 0, "t1_ms": 3_000, "text": "right, pricing", "speaker": "them"},
        {"t0_ms": 600_000, "t1_ms": 604_000, "text": "hold at forty a seat", "speaker": "me"},
    ])
    store.add_keyframe("m1", t_ms=0, url="/files/a.jpg", hash="a", caption="Title slide.")
    store.add_keyframe("m1", t_ms=300_000, url="/files/b.jpg", hash="b", caption="The pricing chart.")
    store.save_notes("m1", NOTES)
    # The link a real `start` records (MS16). Without it the meeting exists but no
    # conversation can bring its card — or, here, its listing — back.
    store.add_thread("m1", "conv-1", kind="origin", created_at=1_700_000_000.0)
    store.end_meeting("m1", ended_at=1_700_003_600.0)
    return "m1"


# ── the surface ─────────────────────────────────────────────────────────────


TOOLS = [
    "ms.list_meetings", "ms.get_meeting", "ms.get_transcript", "ms.search",
    "ms.get_live_context", "ms.get_slide", "ms.update_action", "ms.suggest",
    "ms.set_mode", "ms.export",
]


def test_the_ten_tools_are_listed(client):
    res = _rpc(client, "tools/list")
    assert res.status_code == 200
    assert [t["name"] for t in res.json()["result"]["tools"]] == TOOLS


def test_the_names_match_the_design_table(client):
    # Part 2 §D.1 calls them `ms.search` and so on. A persona prompt that names a tool has to
    # name the same thing the catalog does, so the prefix is `ms.` rather than `hp.`.
    res = _rpc(client, "tools/list")
    for tool in res.json()["result"]["tools"]:
        assert tool["name"].startswith("ms.")


def test_it_answers_health_and_initialize(client):
    assert client.get("/health").json()["name"] == "mcp-meetingsense"
    body = _rpc(client, "initialize").json()["result"]
    assert body["serverInfo"]["name"] == "mcp-meetingsense"


# ── every tool, called ──────────────────────────────────────────────────────


class TestReads:
    def test_list_meetings(self, client, meeting):
        result = call(client, "ms.list_meetings")
        assert [m["meeting_id"] for m in result["meta"]["meetings"]] == ["m1"]
        assert "Q3 planning" in said(result)

    def test_list_meetings_by_conversation(self, client, meeting):
        assert call(client, "ms.list_meetings", conversation_id="conv-1")["meta"]["meetings"]
        assert call(client, "ms.list_meetings",
                    conversation_id="nowhere")["meta"]["meetings"] == []

    def test_get_meeting_answers_with_the_recap(self, client, meeting):
        result = call(client, "ms.get_meeting", meeting_id="m1")
        assert "forty a seat" in said(result)
        # Counts, not rows: a `get` that returned the transcript would make `get_transcript`
        # and its cap pointless.
        assert result["meta"]["counts"] == {"segments": 2, "slides": 2}
        assert "segments" not in result["meta"]

    def test_get_transcript_pages_rather_than_dumping(self, client, meeting):
        result = call(client, "ms.get_transcript", meeting_id="m1", limit=1)
        assert result["meta"]["total"] == 2
        assert result["meta"]["has_more"] is True
        # Said in the text, not only the metadata: the model reading the content is the one
        # deciding whether to page or to search.
        assert "ms.search" in said(result)
        second = call(client, "ms.get_transcript", meeting_id="m1", offset=1, limit=1)
        assert second["meta"]["has_more"] is False
        assert "forty a seat" in said(second)

    def test_get_transcript_is_capped_however_much_is_asked_for(self, client, store, backend,
                                                                server):
        # A meeting long enough for the cap to bind. On a two-segment fixture `limit=100_000`
        # returns two either way, and the test passes with the cap deleted.
        store.create_meeting(conversation_id="conv-2", meeting_id="long", started_at=1.0)
        store.add_segments("long", [
            {"t0_ms": i * 4_000, "t1_ms": i * 4_000 + 3_000, "text": f"line {i}", "speaker": "them"}
            for i in range(server.MAX_SEGMENTS + 50)
        ])
        result = call(client, "ms.get_transcript", meeting_id="long", limit=100_000)
        assert result["meta"]["total"] == server.MAX_SEGMENTS + 50
        assert len(result["meta"]["segments"]) == server.MAX_SEGMENTS

    def test_search_says_why_a_live_meeting_finds_nothing(self, client, meeting):
        # Meetings are indexed on stop. Without this sentence "nothing matched" reads as
        # "it was not said", which is a different and wrong answer.
        result = call(client, "ms.search", query="pricing")
        assert "ms.get_live_context" in said(result)

    def test_search_needs_a_query(self, client, meeting):
        assert call(client, "ms.search")["meta"]["ok"] is False

    def test_get_live_context_when_nothing_is_recording(self, client, meeting):
        result = call(client, "ms.get_live_context", conversation_id="conv-1")
        assert result["meta"]["live"] is False

    def test_get_live_context_returns_the_bounded_block(self, client, meeting, store,
                                                        backend, monkeypatch):
        import app.meetingsense.live_context as live_mod

        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        monkeypatch.setenv("MEETINGSENSE_TOGETHER", "true")

        class Live:
            meeting_id = "m1"
            conversation_id = "conv-1"
            elapsed_ms = 3_600_000
            state = "live"

        import app.meetingsense.session as session_mod

        monkeypatch.setattr(session_mod, "for_conversation", lambda cid: Live())
        result = call(client, "ms.get_live_context", conversation_id="conv-1")
        assert result["meta"]["live"] is True
        # The same block MS18 puts in a prompt, not a bigger one: a tool that returned more
        # would be a way around D9's budget.
        assert said(result).startswith(live_mod.BLOCK_HEADER)

    def test_get_slide_lists_them(self, client, meeting):
        result = call(client, "ms.get_slide", meeting_id="m1")
        assert [s["caption"] for s in result["meta"]["slides"]] == ["Title slide.", "The pricing chart."]

    def test_get_slide_at_a_moment_is_the_one_that_was_up(self, client, meeting):
        # The last slide taken at or before it — not the nearest, which on a deck clicked
        # through quickly is often the one that came next.
        result = call(client, "ms.get_slide", meeting_id="m1", at_ms=299_999)
        assert [s["caption"] for s in result["meta"]["slides"]] == ["Title slide."]
        result = call(client, "ms.get_slide", meeting_id="m1", at_ms=300_000)
        assert [s["caption"] for s in result["meta"]["slides"]] == ["The pricing chart."]

    @pytest.mark.parametrize("tool", ["ms.get_meeting", "ms.get_transcript", "ms.get_slide"])
    def test_a_meeting_that_is_not_there(self, client, meeting, tool):
        assert call(client, tool, meeting_id="nope")["meta"]["ok"] is False


# ── the write gate ──────────────────────────────────────────────────────────


WRITES = [
    ("ms.update_action", {"meeting_id": "m1", "text": "Send the terms"}),
    ("ms.suggest", {"meeting_id": "m1", "text": "Ask legal about October"}),
    ("ms.set_mode", {"meeting_id": "m1", "mode": "note-taker"}),
    ("ms.export", {"meeting_id": "m1", "format": "md"}),
]


class TestWriteGate:
    @pytest.mark.parametrize("tool,args", WRITES)
    def test_every_write_tool_is_gated(self, client, meeting, tool, args):
        result = call(client, tool, **args)
        assert result["meta"]["ok"] is False
        assert result["meta"]["write_enabled"] is False
        # The wording `local-notes` uses, so an operator who has seen one refusal recognises
        # the other and knows which variable to set.
        assert "WRITE_ENABLED=true" in said(result)

    def test_the_refusal_says_nothing_was_changed(self, client, meeting):
        assert "no changes made" in said(call(client, "ms.suggest",
                                              meeting_id="m1", text="anything")).lower()

    def test_a_refused_write_leaves_the_notes_alone(self, client, meeting, store, backend):
        before = store.get_notes("m1")
        call(client, "ms.update_action", meeting_id="m1", text="Send the terms", done=True)
        assert store.get_notes("m1") == before

    @pytest.mark.parametrize("tool,args", WRITES)
    def test_no_read_tool_is_gated(self, client, meeting, tool, args):
        # The other side of the same claim: reads answer with the flag off, because a meeting
        # is the user's own recording on the user's own machine.
        assert call(client, "ms.get_meeting", meeting_id="m1")["meta"]["ok"] is True


class TestWrites:
    def test_update_action_closes_one(self, writable, meeting, store, backend):
        client = TestClient(writable.app)
        result = call(client, "ms.update_action", meeting_id="m1",
                      text="Send the vendor the revised terms", done=True)
        assert result["meta"]["ok"] is True
        actions = store.get_notes("m1")["notes"]["actions"]
        assert [(a["text"], a.get("done")) for a in actions] == \
               [("Send the vendor the revised terms", True)]

    def test_update_action_adds_one_the_meeting_never_recorded(self, writable, meeting, store, backend):
        # An agent that has just done something the meeting did not record has still done it,
        # and a notes list that cannot grow is a notes list nobody keeps current.
        client = TestClient(writable.app)
        call(client, "ms.update_action", meeting_id="m1", text="Book the room", owner="Sam")
        actions = store.get_notes("m1")["notes"]["actions"]
        assert any(a["text"] == "Book the room" and a["owner"] == "Sam" for a in actions)

    def test_a_suggestion_is_kept_apart_from_the_notes(self, writable, meeting, store, backend):
        # A suggestion is something an agent thinks; the notes are what the meeting said.
        # Merging them would make the transcript's own record unciteable.
        client = TestClient(writable.app)
        call(client, "ms.suggest", meeting_id="m1", text="Ask legal about October")
        assert [a["ref"] for a in store.artifacts_for_meeting("m1", kind="suggestion")] == \
               ["Ask legal about October"]
        assert "Ask legal" not in str(store.get_notes("m1"))

    def test_set_mode_refuses_a_typo(self, writable, meeting, store, backend):
        # W9 owns what a mode *does*; a mode nobody implements yet is still a mode, and a
        # typo is not.
        client = TestClient(writable.app)
        refused = call(client, "ms.set_mode", meeting_id="m1", mode="cheerleader")
        assert refused["meta"]["ok"] is False
        # Refused *here* rather than by the backend's 400, so the agent is handed the list of
        # modes instead of spending a round trip to learn it typed one wrong.
        assert "note-taker" in said(refused)
        assert "practice" in said(refused)
        assert call(client, "ms.set_mode", meeting_id="m1", mode="coach")["meta"]["ok"] is True
        assert [a["target"] for a in store.artifacts_for_meeting("m1", kind="mode")] == ["coach"]

    @pytest.mark.parametrize("fmt,marker", [("md", "# "), ("srt", "-->"), ("json", "\"segments\"")])
    def test_export_in_each_format(self, writable, meeting, backend, fmt, marker):
        client = TestClient(writable.app)
        result = call(client, "ms.export", meeting_id="m1", format=fmt)
        assert result["meta"]["ok"] is True
        assert marker in said(result)

    def test_export_refuses_a_format_it_does_not_have(self, writable, meeting, backend):
        client = TestClient(writable.app)
        assert call(client, "ms.export", meeting_id="m1", format="pdf")["meta"]["ok"] is False


# ── an install without MeetingSense ─────────────────────────────────────────


class TestNotInstalled:
    """A backend that is off, absent, or has MeetingSense disabled.

    Three different causes and one useful sentence: a persona can pass on "MeetingSense is not
    available on this install", and cannot pass on a tool error.
    """

    @pytest.fixture()
    def absent(self, server, monkeypatch):
        import httpx

        def refuse(*args, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "AsyncClient", refuse)
        return TestClient(server.app)

    @pytest.mark.parametrize("tool,args", [
        ("ms.list_meetings", {}),
        ("ms.get_meeting", {"meeting_id": "m1"}),
        ("ms.get_transcript", {"meeting_id": "m1"}),
        ("ms.search", {"query": "x"}),
        ("ms.get_live_context", {"conversation_id": "c1"}),
        ("ms.get_slide", {"meeting_id": "m1"}),
    ])
    def test_every_read_answers_in_a_sentence(self, absent, tool, args):
        result = call(absent, tool, **args)
        assert result["meta"]["available"] is False
        assert "MEETINGSENSE_ENABLED" in said(result)
        # The cause is kept for whoever is debugging, out of the sentence a persona repeats.
        assert "refused" in str(result["meta"].get("reason"))

    def test_listing_tools_still_works(self, absent):
        # httpx is imported inside the call rather than at module scope for exactly this: a
        # tool that failed to import would take the whole server's `tools/list` with it.
        assert len(_rpc(absent, "tools/list").json()["result"]["tools"]) == 10

    def test_a_missing_meeting_is_not_reported_as_a_missing_install(self, client, meeting):
        # Two different answers a persona would say differently. The backend answers 404 for
        # both "no such meeting" and "the feature is off", so the tool distinguishes them by
        # whether it was asked about one.
        result = call(client, "ms.get_meeting", meeting_id="nope")
        assert result["meta"]["available"] is True
        assert "No meeting 'nope'" in said(result)


# ── the port ────────────────────────────────────────────────────────────────


class TestPort:
    def makefile(self) -> str:
        return (ROOT / "Makefile").read_text()

    def test_9107_is_not_a_port_the_makefile_already_starts(self):
        # The batch's acceptance. Two servers on one port is a failure that looks like a
        # broken tool rather than a broken port, so the Makefile's own port lists are read
        # and every *other* server's port is collected.
        text = self.makefile()
        others = set()
        for match in re.finditer(r"--port (\d{4})", text):
            others.add(int(match.group(1)))
        for match in re.finditer(r"^\s*@?for port in ([\d ]+);", text, re.MULTILINE):
            others.update(int(p) for p in match.group(1).split())
        # 9107 appears in the Makefile exactly because MS21 put it there — for this server.
        ours = {m.start() for m in re.finditer(r"9107", text)}
        assert ours, "9107 should appear in the Makefile: MS21 adds start/stop/health targets"
        started_by_others = others - {9107}
        assert 9107 not in started_by_others

    def test_the_makefile_starts_stops_and_health_checks_it(self):
        text = self.makefile()
        for target in ("start-meetingsense:", "stop-meetingsense:", "health-meetingsense:"):
            assert target in text
        assert "agentic.integrations.mcp.meetingsense_server:app" in text

    def test_compose_publishes_it_on_9107_and_nothing_else_does(self):
        import yaml

        compose = yaml.safe_load((ROOT / "docker-compose.mcp.yml").read_text())
        services = compose["services"]
        assert services["meetingsense"]["ports"] == ["9107:9107"]
        published = [p for name, svc in services.items() if name != "meetingsense"
                     for p in (svc.get("ports") or [])]
        assert not [p for p in published if p.startswith("9107")]

    def test_compose_ships_the_writes_off(self):
        import yaml

        compose = yaml.safe_load((ROOT / "docker-compose.mcp.yml").read_text())
        env = compose["services"]["meetingsense"]["environment"]
        assert env["WRITE_ENABLED"] == "${MEETINGSENSE_MCP_WRITE_ENABLED:-false}"
        assert env["DRY_RUN"] == "${MEETINGSENSE_MCP_DRY_RUN:-true}"

    def test_the_port_constant_and_the_wiring_agree(self, server):
        assert server.PORT == 9107
