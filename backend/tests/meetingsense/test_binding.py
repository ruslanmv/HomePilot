"""Getting back into a meeting (batch MS16, wave W5).

A meeting ends and the useful part starts. The design's three ways back in all reuse
conversation machinery that already exists, and each of them has one claim worth a test.

**Reopening the chat brings the card back.** Nothing on a chat message says which meeting
produced it, so the pairing is recorded when the meeting *starts* — not when it stops, because
a meeting that never ends should still bring its card back.

**A branched thread is usable without asking first.** The brief leads with what is still open
rather than with what was said, because its reader may be a week late with no context, and it
ends by saying the transcript is searchable — otherwise the reader's first message is "can you
see the meeting?" rather than a question about the meeting.

**Attaching is a deliberate act, through the existing upload path.** Being recorded does not
put a meeting into a project (D4). Attaching does, through the same `process_and_add_file` the
upload button calls, so it needs no new job type — asserted, because "we reuse X" is the kind
of claim that quietly stops being true.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_RETENTION"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.binding as binding
        import app.meetingsense.config as config
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.binding = binding
        self.config = config
        self.routes = routes
        self.session = session
        self.store = store


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    mods = Modules()
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(mods.store, "_connect", _connect)
    mods.store.migrate()
    mods.session._SESSIONS.clear()
    return mods


@pytest.fixture()
def messages(modules, monkeypatch):
    """Capture what would land in a conversation, without the chat database."""
    written = []
    import app.storage as storage

    monkeypatch.setattr(
        storage, "add_message",
        lambda cid, role, content, **kw: written.append({"cid": cid, "role": role, "content": content, **kw}),
    )
    return written


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")


@pytest.fixture()
def client(modules, enabled):
    app = FastAPI()
    app.include_router(modules.routes.router)
    return TestClient(app)


def meeting(mods, mid="m1", *, conversation="conv-1", title="Q3 planning",
            started=1_700_000_000.0, ended=1_700_003_600.0):
    mods.store.create_meeting(conversation_id=conversation, meeting_id=mid, title=title,
                              source="teams", started_at=started)
    if ended:
        mods.store.end_meeting(mid, ended_at=ended)
    mods.store.add_thread(mid, conversation, kind="origin", created_at=started)
    return mid


def add(mods, mid, t0, text, speaker="them"):
    return mods.store.add_segments(mid, [{"t0_ms": t0, "t1_ms": t0 + 3_000, "text": text, "speaker": speaker}])


NOTES = {
    "recap": "The team agreed to hold enterprise pricing and pushed the legal review to October.",
    "decisions": [{"text": "Hold pricing at forty a seat", "t0": 600_000}],
    "actions": [
        {"text": "Send the vendor the revised terms", "owner": "Ana", "t0": 900_000},
        {"text": "Book the legal slot", "owner": "Sam", "done": True},
    ],
    "questions": [
        {"text": "Who signs off on the discount tier?", "resolved": False},
        {"text": "Is October realistic?", "resolved": True},
    ],
}


# ── the link a card hydrates from ───────────────────────────────────────────


class TestThreads:
    def test_a_meeting_records_its_conversation_when_it_starts(self, modules):
        # When it starts, not when it stops: a meeting interrupted by a server restart should
        # still bring its card back when the chat is reopened.
        async def scenario():
            session = modules.session.MeetingSession(
                transport=modules.session.ListTransport(),
                config=modules.config.load_config(),
                now=lambda: 100.0,
            )
            await session.start({"conversation_id": "conv-9", "title": "Standup"})
            return session.meeting_id

        mid = run(scenario())
        assert [m["meeting_id"] for m in modules.binding.hydrate("conv-9")] == [mid]

    def test_the_same_pairing_is_recorded_once(self, modules):
        # Both ends write it — a start, and a resume onto the same conversation — and two rows
        # would hydrate the card twice.
        meeting(modules)
        modules.store.add_thread("m1", "conv-1")
        modules.store.add_thread("m1", "conv-1", kind="branch")
        assert len(modules.store.threads_for_meeting("m1")) == 1

    def test_a_conversation_with_several_meetings_gets_them_oldest_first(self, modules):
        meeting(modules, "later", conversation="conv-1", started=2_000.0, ended=3_000.0)
        meeting(modules, "earlier", conversation="conv-1", started=1_000.0, ended=1_500.0)
        assert [m["meeting_id"] for m in modules.binding.hydrate("conv-1")] == ["earlier", "later"]

    def test_a_conversation_with_none_is_empty_rather_than_an_error(self, modules):
        assert modules.binding.hydrate("conv-nothing") == []

    def test_the_card_can_be_drawn_collapsed_without_a_second_call(self, modules):
        # The chat load path asks this on every open. A row that forced a follow-up request
        # per meeting to render a one-line collapsed card would be a request per meeting on
        # every chat open.
        meeting(modules)
        add(modules, "m1", 0, "we should hold pricing")
        modules.store.add_keyframe("m1", t_ms=1_000, url="/files/a.jpg")
        row = modules.binding.hydrate("conv-1")[0]
        assert row["title"] == "Q3 planning"
        assert row["counts"] == {"segments": 1, "slides": 1}
        assert row["thread_kind"] == "origin"


# ── the brief ───────────────────────────────────────────────────────────────


class TestBrief:
    def brief_for(self, mods, notes=NOTES):
        mid = meeting(mods)
        add(mods, mid, 0, "right, pricing")
        mods.store.set_notes(mid, notes) if hasattr(mods.store, "set_notes") else None
        return mods.binding.brief(mods.store.get_meeting(mid), mods.store.get_segments(mid),
                                  mods.store.get_keyframes(mid), {"notes": notes})

    def test_it_leads_with_the_meeting_and_is_findable_in_history(self, modules):
        # History labels a conversation with the content of its last message, so the first
        # line of a brief is the name of a thread nobody has spoken in yet.
        text = self.brief_for(modules)
        first = text.splitlines()[0]
        assert first.startswith(modules.binding.BRIEF_PREFIX)
        assert "Q3 planning" in first

    def test_open_questions_and_unfinished_actions_lead(self, modules):
        # They are the reason somebody opens a thread from a meeting rather than reading the
        # summary again.
        text = self.brief_for(modules)
        assert "Who signs off on the discount tier?" in text
        assert "Send the vendor the revised terms — Ana" in text

    def test_what_is_already_done_is_left_out(self, modules):
        # A "still open" list that includes closed items is a list the reader has to re-check,
        # which is the opposite of what it is for.
        text = self.brief_for(modules)
        assert "Is October realistic?" not in text
        assert "Book the legal slot" not in text

    def test_it_says_the_transcript_is_searchable(self, modules):
        # Without this the reader's first message is "can you see the meeting?" rather than a
        # question about the meeting.
        assert "search the full transcript" in self.brief_for(modules)

    def test_a_meeting_with_no_notes_says_so_rather_than_showing_a_gap(self, modules):
        text = self.brief_for(modules, notes=None)
        assert "No notes were taken" in text
        assert "search the full transcript" in text

    def test_an_empty_section_is_omitted_rather_than_left_as_a_heading(self, modules):
        # "Decisions:" with nothing under it reads as a meeting where nothing was decided,
        # which is a different statement from "no notes were taken".
        text = self.brief_for(modules, notes={"recap": "Short one.", "decisions": []})
        assert "Decisions:" not in text

    def test_a_section_whose_items_all_render_blank_is_omitted_too(self, modules):
        # An empty *list* never reaches the heading; a list of items that all render to
        # nothing does, and produces the same misleading heading with nothing under it. The
        # same hole MS14's note sections had.
        text = self.brief_for(
            modules,
            notes={"recap": "Short one.", "decisions": [{"text": "   "}, {"text": ""}]},
        )
        assert "Decisions:" not in text

    def test_the_slide_list_is_capped(self, modules):
        mid = meeting(modules)
        for i in range(20):
            modules.store.add_keyframe(mid, t_ms=i * 60_000, url=f"/files/{i}.jpg",
                                       caption=f"Slide number {i}")
        text = modules.binding.brief(modules.store.get_meeting(mid), [],
                                     modules.store.get_keyframes(mid), {"notes": NOTES})
        assert text.count("Slide number") == modules.binding.MAX_BRIEF_SLIDES
        assert "and 14 more" in text

    def test_an_uncaptioned_slide_is_not_listed(self, modules):
        mid = meeting(modules)
        modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg")
        text = modules.binding.brief(modules.store.get_meeting(mid), [],
                                     modules.store.get_keyframes(mid), {"notes": NOTES})
        assert "Slides:" not in text


class TestBranch:
    def test_it_opens_a_conversation_and_records_the_link(self, modules, messages):
        meeting(modules)
        result = modules.binding.branch("m1")
        assert result["conversation_id"] != "conv-1"
        assert result["message_written"] is True
        assert [m["role"] for m in messages] == ["assistant"]
        assert messages[0]["content"].startswith(modules.binding.BRIEF_PREFIX)
        # Reachable from both conversations now: the original and the branch.
        kinds = {t["conversation_id"]: t["kind"] for t in modules.store.threads_for_meeting("m1")}
        assert kinds == {"conv-1": "origin", result["conversation_id"]: "branch"}

    def test_the_brief_is_an_assistant_message(self, modules, messages):
        # It is the meeting speaking, not the user — and History labels a conversation with
        # its last message, so a thread nobody has spoken in still reads as the meeting.
        meeting(modules)
        modules.binding.branch("m1")
        assert messages[0]["role"] == "assistant"

    def test_a_thread_inherits_the_meeting_project(self, modules, messages):
        modules.store.create_meeting(conversation_id="conv-1", meeting_id="m2",
                                     project_id="proj-7", started_at=1.0)
        modules.binding.branch("m2")
        assert messages[0]["project_id"] == "proj-7"

    def test_a_failed_message_still_records_the_link_and_says_so(self, modules, monkeypatch):
        # A thread whose brief did not land is one the client should render from `brief`
        # itself rather than wait for a message that is not coming.
        import app.storage as storage

        def angry(*args, **kwargs):
            raise RuntimeError("the chat database is locked")

        monkeypatch.setattr(storage, "add_message", angry)
        meeting(modules)
        result = modules.binding.branch("m1")
        assert result["message_written"] is False
        assert result["brief"].startswith(modules.binding.BRIEF_PREFIX)
        assert len(modules.store.threads_for_meeting("m1")) == 2

    def test_branching_a_meeting_that_is_not_there(self, modules):
        assert modules.binding.branch("nope") is None


# ── attaching to a project ──────────────────────────────────────────────────


class TestAttach:
    @pytest.fixture()
    def uploads(self, tmp_path, modules, monkeypatch):
        root = tmp_path / "uploads"
        root.mkdir()
        monkeypatch.setattr(modules.binding, "_upload_root", lambda: root)
        return root

    @pytest.fixture()
    def indexer(self, modules, monkeypatch):
        """The project upload path, watched rather than replaced."""
        calls = []
        import app.vectordb as vectordb

        def process(project_id, path):
            calls.append({"project_id": project_id, "path": path, "text": path.read_text()})
            return 7

        monkeypatch.setattr(vectordb, "process_and_add_file", process)
        return calls

    def test_it_goes_through_the_existing_project_upload_path(self, modules, uploads, indexer):
        # The claim the batch row makes: this needs no new job type, because the project
        # already knows how to extract, chunk and embed a Markdown file. "We reuse X" is the
        # kind of claim that quietly stops being true.
        mid = meeting(modules)
        add(modules, mid, 600_000, "we should hold pricing at forty a seat")
        result = modules.binding.attach_to_project(mid, "proj-7")
        assert result["chunks"] == 7
        assert [c["project_id"] for c in indexer] == ["proj-7"]

    def test_what_is_attached_is_the_meeting_a_reader_would_recognise(self, modules, uploads, indexer):
        mid = meeting(modules)
        add(modules, mid, 600_000, "we should hold pricing at forty a seat")
        modules.store.add_keyframe(mid, t_ms=1_000, url="/files/a.jpg", caption="The pricing slide.")
        modules.binding.attach_to_project(mid, "proj-7")
        text = indexer[0]["text"]
        assert "hold pricing at forty a seat" in text
        assert "The pricing slide." in text

    def test_the_file_is_named_so_a_person_can_recognise_it(self, modules, uploads, indexer):
        # It lands in the project's file list beside their own uploads. A uuid there is a row
        # nobody can decide whether to delete.
        mid = meeting(modules, title="Q3 planning / pricing!")
        add(modules, mid, 0, "anything at all here")
        result = modules.binding.attach_to_project(mid, "proj-7")
        assert result["filename"].startswith("meeting-q3-planning-pricing-")
        assert result["filename"].endswith(".md")

    def test_the_attachment_is_recorded(self, modules, uploads, indexer):
        mid = meeting(modules)
        add(modules, mid, 0, "anything at all here")
        modules.binding.attach_to_project(mid, "proj-7")
        rows = modules.store.artifacts_for_meeting(mid, kind="project")
        assert [r["target"] for r in rows] == ["proj-7"]
        assert rows[0]["detail"] == "7"

    def test_no_vector_store_writes_the_file_and_reports_why(self, modules, uploads, monkeypatch):
        import app.vectordb as vectordb

        def angry(project_id, path):
            raise ImportError("chromadb is not installed")

        monkeypatch.setattr(vectordb, "process_and_add_file", angry)
        mid = meeting(modules)
        add(modules, mid, 0, "anything at all here")
        result = modules.binding.attach_to_project(mid, "proj-7")
        assert result["chunks"] == 0
        assert "chromadb" in result["error"]
        # The transcript is on disk either way, so the attach can be retried without
        # re-exporting — and the user is told rather than shown a silent success.
        assert (uploads / result["filename"]).exists()

    def test_attaching_a_meeting_that_is_not_there(self, modules, uploads):
        assert modules.binding.attach_to_project("nope", "proj-7") is None


# ── the endpoints ───────────────────────────────────────────────────────────


class TestRoutes:
    def test_the_conversation_route_is_not_swallowed_by_the_meeting_route(self, modules, client):
        # FastAPI matches in declaration order. With `/{meeting_id}` first, "conversations"
        # is read as a meeting id and every hydration 404s — a bug that looks like a missing
        # feature rather than a routing mistake.
        meeting(modules)
        response = client.get("/v1/meetingsense/conversations/conv-1")
        assert response.status_code == 200
        assert [m["meeting_id"] for m in response.json()["meetings"]] == ["m1"]

    def test_hydrating_an_unknown_conversation_is_empty_rather_than_404(self, modules, client):
        # The chat load path asks this on every open, and an error there would be a red toast
        # on a conversation that is perfectly fine.
        response = client.get("/v1/meetingsense/conversations/nothing-here")
        assert response.status_code == 200
        assert response.json()["meetings"] == []

    def test_with_the_flag_off_the_card_stops_rather_than_the_chat_erroring(self, modules, monkeypatch):
        # Turning MeetingSense off leaves the tables where they are. A chat that used to host
        # a meeting should stop showing its card, not start failing to load.
        # Set off, not merely unset: since MS30 an unset variable means *on*, so deleting it
        # would leave the flag exactly the way this test needs it not to be.
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "false")
        meeting(modules)
        app = FastAPI()
        app.include_router(modules.routes.router)
        response = TestClient(app).get("/v1/meetingsense/conversations/conv-1")
        assert response.status_code == 200
        assert response.json()["meetings"] == []

    def test_branching_over_http(self, modules, client, messages):
        meeting(modules)
        response = client.post("/v1/meetingsense/m1/thread")
        assert response.status_code == 200
        assert response.json()["conversation_id"]
        assert len(messages) == 1

    def test_attaching_needs_a_project(self, modules, client):
        meeting(modules)
        assert client.post("/v1/meetingsense/m1/attach", json={}).status_code == 400

    def test_attaching_over_http(self, modules, client, monkeypatch, tmp_path):
        import app.vectordb as vectordb

        root = tmp_path / "uploads"
        root.mkdir()
        monkeypatch.setattr(modules.binding, "_upload_root", lambda: root)
        monkeypatch.setattr(vectordb, "process_and_add_file", lambda p, path: 3)
        meeting(modules)
        add(modules, "m1", 0, "anything at all here")
        response = client.post("/v1/meetingsense/m1/attach", json={"project_id": "proj-7"})
        assert response.status_code == 200
        assert response.json()["chunks"] == 3

    def test_both_refuse_a_meeting_that_is_not_there(self, modules, client):
        assert client.post("/v1/meetingsense/nope/thread").status_code == 404
        assert client.post("/v1/meetingsense/nope/attach", json={"project_id": "p"}).status_code == 404


# ── delete still means delete ───────────────────────────────────────────────


def test_deleting_a_meeting_removes_its_threads_and_artifacts(modules):
    # Two new tables, and the same rule as the other three: whatever was kept is removed. A
    # thread row left behind hydrates a card for a meeting that no longer exists.
    meeting(modules)
    modules.store.add_artifact("m1", kind="project", target="proj-7")
    modules.store.delete_meeting("m1")
    assert modules.store.threads_for_meeting("m1") == []
    assert modules.store.artifacts_for_meeting("m1") == []
    assert modules.binding.hydrate("conv-1") == []
