"""The summary a meeting leaves, and deleting one (batch MS14).

Two claims carry this batch.

**The summary message is self-sufficient (D9).** HomePilot's chat path passes the last six
messages and drops the rest, so in any conversation with a little activity after the meeting,
this message *is* the meeting as far as the model is concerned. A summary that says "see the
meeting card" is useless to the reader who cannot see it — so the recap, the decisions, the
actions with owners and the open questions are all in the body.

**Nothing is remembered (D4).** No job is enqueued, no long-term-memory extraction happens. The
meeting is a normal chat message — readable, deletable — and a persona's route to anything more
is retrieval. This is how Otter, Fireflies and Copilot work: index and cite, never "remember".
A test asserts the jobs queue is untouched, because that is a claim about an absence and an
absence is exactly what nobody notices breaking.

Deletion is the third thing, and its rule is that **retention does not modify it.** Whatever
was kept is removed. A mode that let something survive an explicit delete would be a setting
quietly overriding an instruction.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_RETENTION", "STT_BASE_URL", "WHISPER_MODEL"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.finalize as finalize
        import app.meetingsense.retention as retention
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.finalize = finalize
        self.retention = retention
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
def files(tmp_path, modules, monkeypatch):
    """An upload root the retention module will actually use."""
    root = tmp_path / "uploads"
    (root / "meetings").mkdir(parents=True)
    monkeypatch.setattr(modules.retention, "upload_root", lambda: root)
    return root


@pytest.fixture()
def client(modules):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(modules.routes.router)
    return TestClient(app)


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")


MEETING = {
    "id": "m1",
    "title": "Q3 planning",
    "source": "teams",
    "started_at": 1_756_900_000.0,
    "ended_at": 1_756_901_800.0,
}

SEGMENTS = [
    {"t0_ms": 1_000, "t1_ms": 3_400, "speaker": "them", "text": "the launch moves to October"},
    {"t0_ms": 3_500, "t1_ms": 6_000, "speaker": "me", "text": "legal needs to sign off"},
]

NOTES = {
    "notes": {
        "recap": "The launch slipped to October and legal sign-off is the remaining blocker.",
        "summary": "Launch moved.",
        "decisions": [{"text": "Launch moves to October", "t0": 1000}],
        "actions": [{"text": "Get legal sign-off", "owner": "Marina", "t0": 3500}],
        "questions": [
            {"text": "Who chases legal?", "t0": 5000},
            {"text": "Already answered", "t0": 100, "resolved": True},
        ],
    }
}


# ── the summary is self-sufficient (D9) ─────────────────────────────────────


class TestSummaryMessage:
    def test_it_carries_the_recap_rather_than_pointing_at_the_card(self, modules):
        # The chat path passes six messages. This one *is* the meeting, and a summary saying
        # "see the meeting card" is useless to the reader who cannot see it.
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, (), NOTES)
        assert "legal sign-off is the remaining blocker" in body

    def test_it_carries_decisions_actions_and_open_questions(self, modules):
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, (), NOTES)
        assert "Launch moves to October" in body
        assert "Get legal sign-off — Marina" in body
        assert "Who chases legal?" in body

    def test_an_action_carries_its_owner_and_its_citation(self, modules):
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, (), NOTES)
        assert "— Marina [00:00:03]" in body

    def test_a_resolved_question_is_left_out(self, modules):
        # An "open questions" list containing answered ones is a list the reader has to
        # re-check, which is the opposite of what it is for.
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, (), NOTES)
        assert "Already answered" not in body

    def test_an_empty_section_is_omitted_rather_than_left_bare(self, modules):
        # "Decisions:" with nothing under it reads as a meeting where nothing was decided.
        notes = {"notes": {"recap": "Just a chat.", "decisions": [], "actions": [], "questions": []}}
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, (), notes)
        assert "Decisions:" not in body
        assert "Just a chat." in body

    def test_a_section_whose_items_are_all_blank_is_omitted_too(self, modules):
        # The harder half, and the one an empty list does not reach: the section has items, and
        # every one of them renders to nothing. Without the second check the heading is written
        # and the bullets are not, which is the bare heading this test exists to prevent.
        notes = {"notes": {"recap": "Just a chat.", "decisions": [{"text": "   "}, {}]}}
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, (), notes)
        assert "Decisions:" not in body

    def test_the_title_still_leads_the_message(self, modules):
        # History labels a conversation with its last message. MS6's rule survives MS14.
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, (), NOTES)
        assert body.splitlines()[0].startswith("[Meeting] 🎙 Q3 planning")

    def test_it_falls_back_to_the_transcript_when_there_are_no_notes(self, modules):
        # An install with no model reachable records a perfectly good transcript, and the
        # message still has to say what the meeting was about.
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, (), None)
        assert "the launch moves to October" in body

    def test_it_reads_the_shape_the_store_returns(self, modules):
        # The MS6 bug, pinned here too: `get_notes()` wraps the object under "notes".
        meeting_id = modules.store.create_meeting(conversation_id="c", title="T", retention="text")
        modules.store.save_notes(meeting_id, {"recap": "From the store.", "decisions": []})
        body = modules.finalize.meeting_message(
            modules.store.get_meeting(meeting_id), [], (), modules.store.get_notes(meeting_id)
        )
        assert "From the store." in body

    def test_slides_are_listed_with_their_captions(self, modules):
        frames = [{"t_ms": 65_000, "url": "/files/meetings/s1.png", "caption": "Roadmap"}]
        body = modules.finalize.meeting_message(MEETING, SEGMENTS, frames, NOTES)
        assert "00:01:05 Roadmap" in body

    def test_thumbnails_are_capped(self, modules):
        # A meeting can produce sixty keyframes in an hour, and a chat message carrying sixty
        # images is a scroll trap. The card shows the whole strip.
        frames = [{"t_ms": i, "url": f"/files/meetings/s{i}.png"} for i in range(40)]
        assert len(modules.finalize.thumbnails(frames)) == modules.finalize.MAX_THUMBNAILS

    def test_a_keyframe_with_no_url_is_not_a_thumbnail(self, modules):
        assert modules.finalize.thumbnails([{"t_ms": 1}, {"t_ms": 2, "url": " "}]) == []


class TestFinalizeWritesTheMessage:
    def _seed(self, modules, *, with_notes=True):
        meeting_id = modules.store.create_meeting(
            conversation_id="conv-1", title="Q3 planning", source="teams", retention="text"
        )
        modules.store.add_segments(meeting_id, [{**s, "seq": i + 1} for i, s in enumerate(SEGMENTS)])
        modules.store.add_keyframe(meeting_id, t_ms=1000, url="/files/meetings/s1.png")
        if with_notes:
            modules.store.save_notes(meeting_id, NOTES["notes"])
        modules.store.end_meeting(meeting_id)
        return meeting_id

    def test_the_notes_reach_the_message(self, modules, monkeypatch):
        import app.storage as storage

        written = []
        monkeypatch.setattr(storage, "add_message", lambda *a, **k: written.append((a, k)))
        modules.finalize.finalize_meeting(self._seed(modules))
        assert "legal sign-off is the remaining blocker" in written[0][0][2]

    def test_slide_thumbnails_are_attached_as_media(self, modules, monkeypatch):
        import app.storage as storage

        written = []
        monkeypatch.setattr(storage, "add_message", lambda *a, **k: written.append((a, k)))
        modules.finalize.finalize_meeting(self._seed(modules))
        assert written[0][1]["media"] == {"images": ["/files/meetings/s1.png"]}

    def test_a_meeting_with_no_slides_attaches_no_media(self, modules, monkeypatch):
        # `media={"images": []}` would put an empty gallery in the chat.
        import app.storage as storage

        written = []
        monkeypatch.setattr(storage, "add_message", lambda *a, **k: written.append((a, k)))
        meeting_id = modules.store.create_meeting(conversation_id="c", retention="text")
        modules.store.end_meeting(meeting_id)
        modules.finalize.finalize_meeting(meeting_id)
        assert written[0][1]["media"] is None


# ── D4: nothing is remembered ───────────────────────────────────────────────


class TestNothingIsEnqueued:
    """The claim is about an *absence*, which is exactly what nobody notices breaking."""

    def test_finalizing_enqueues_no_job(self, modules, monkeypatch):
        import app.jobs as jobs
        import app.storage as storage

        monkeypatch.setattr(storage, "add_message", lambda *a, **k: None)
        enqueued = []
        for name in ("schedule_session_jobs", "enqueue", "enqueue_job"):
            if hasattr(jobs, name):
                monkeypatch.setattr(jobs, name, lambda *a, **k: enqueued.append(a))

        meeting_id = modules.store.create_meeting(conversation_id="c", project_id="p", retention="text")
        modules.store.end_meeting(meeting_id)
        modules.finalize.finalize_meeting(meeting_id)
        assert enqueued == []

    def test_the_module_never_mentions_the_jobs_queue(self, modules):
        # D4 deletes the LTM finding rather than fixing it, and this is where that stays true.
        # A future batch reaching for `jobs` here would be reopening a closed decision.
        import inspect

        source = inspect.getsource(modules.finalize)
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith(("#", '"', "*"))
        )
        assert "jobs" not in code
        assert "schedule_session_jobs" not in code


# ── deleting ────────────────────────────────────────────────────────────────


class TestResolveOwned:
    def test_a_files_url_resolves_under_the_root(self, modules, files):
        assert modules.retention.resolve_owned("/files/meetings/a.png", files) == (
            files / "meetings" / "a.png"
        ).resolve()

    def test_a_query_string_is_ignored(self, modules, files):
        assert modules.retention.resolve_owned("/files/meetings/a.png?v=2", files) is not None

    @pytest.mark.parametrize(
        "url",
        [
            "/files/../../etc/passwd",          # traversal
            "/etc/passwd",                       # not ours
            "https://elsewhere/a.png",           # absolute
            "/files//etc/passwd",                # leading slash after the prefix
            "",
            None,
            "/files/",
        ],
    )
    def test_anything_not_ours_resolves_to_nothing(self, modules, files, url):
        # A keyframe URL came from a client, and a delete endpoint that unlinks whatever it is
        # handed is a delete endpoint that can be pointed at anything.
        assert modules.retention.resolve_owned(url, files) is None

    def test_a_symlink_pointing_out_of_the_root_is_refused(self, modules, files, tmp_path):
        outside = tmp_path / "secret.txt"
        outside.write_text("private")
        (files / "meetings" / "link.txt").symlink_to(outside)
        assert modules.retention.resolve_owned("/files/meetings/link.txt", files) is None

    def test_a_sibling_directory_sharing_the_roots_name_is_refused(self, modules, files, tmp_path):
        # The case that separates `is_relative_to` from a string prefix check, and the reason
        # this is not `str(candidate).startswith(str(base))`. "/uploads-evil/x" starts with
        # "/uploads" and is not inside it. A symlink test does not catch this — both checks
        # refuse that one — so without this the weaker implementation passes the whole suite.
        evil = tmp_path / f"{files.name}-evil"
        evil.mkdir()
        (evil / "x.png").write_bytes(b"png")
        assert modules.retention.resolve_owned(f"/files/../{evil.name}/x.png", files) is None


class TestRemoveFiles:
    def test_it_removes_what_the_meeting_owned(self, modules, files):
        target = files / "meetings" / "s1.png"
        target.write_bytes(b"png")
        counts = modules.retention.remove_files(["/files/meetings/s1.png"])
        assert counts["removed"] == 1
        assert not target.exists()

    def test_a_file_already_gone_is_counted_not_an_error(self, modules, files):
        assert modules.retention.remove_files(["/files/meetings/missing.png"])["missing"] == 1

    def test_a_url_outside_the_root_is_refused_and_counted(self, modules, files):
        assert modules.retention.remove_files(["/files/../../etc/passwd"])["refused"] == 1

    def test_no_upload_root_refuses_everything_rather_than_guessing(self, modules, monkeypatch):
        monkeypatch.setattr(modules.retention, "upload_root", lambda: None)
        assert modules.retention.remove_files(["/files/a.png"])["refused"] == 1


class TestRetentionModes:
    def test_the_modes_say_what_was_ever_written(self, modules):
        assert modules.retention.keeps_frames("text") is False
        assert modules.retention.keeps_frames("text+frames") is True
        assert modules.retention.keeps_frames("all") is True
        assert modules.retention.keeps_audio("all") is True
        assert modules.retention.keeps_audio("text+frames") is False


class TestDeleteMeeting:
    def _seed(self, modules, files, retention="text+frames"):
        meeting_id = modules.store.create_meeting(conversation_id="c", retention=retention)
        modules.store.add_segments(meeting_id, [{"t0_ms": 0, "text": "hello", "seq": 1}])
        (files / "meetings" / "s1.png").write_bytes(b"png")
        modules.store.add_keyframe(meeting_id, t_ms=0, url="/files/meetings/s1.png")
        modules.store.save_notes(meeting_id, {"summary": "s"})
        return meeting_id

    def test_it_removes_rows_and_files(self, modules, files):
        meeting_id = self._seed(modules, files)
        result = modules.retention.delete_meeting(meeting_id)
        assert result["rows"] == {"segments": 1, "keyframes": 1, "notes": 1, "meetings": 1}
        assert result["files"]["removed"] == 1
        assert modules.store.get_meeting(meeting_id) is None
        assert not (files / "meetings" / "s1.png").exists()

    def test_retention_does_not_spare_anything_from_an_explicit_delete(self, modules, files):
        # A mode that let something survive delete would be a setting quietly overriding an
        # instruction. `text` never wrote the frame; if one exists anyway, it still goes.
        meeting_id = self._seed(modules, files, retention="text")
        result = modules.retention.delete_meeting(meeting_id)
        assert result["files"]["removed"] == 1
        assert not (files / "meetings" / "s1.png").exists()

    def test_deleting_something_that_is_not_there_says_so(self, modules, files):
        assert modules.retention.delete_meeting("nope") is None

    def test_one_meetings_files_are_not_another_meetings(self, modules, files):
        keep = self._seed(modules, files)
        (files / "meetings" / "other.png").write_bytes(b"png")
        other = modules.store.create_meeting(conversation_id="c", retention="text+frames")
        modules.store.add_keyframe(other, t_ms=0, url="/files/meetings/other.png")

        modules.retention.delete_meeting(other)
        assert (files / "meetings" / "s1.png").exists()
        assert modules.store.get_meeting(keep) is not None


class TestDeleteRoute:
    def test_one_call_removes_everything_and_reports_counts(self, client, enabled, modules, files):
        meeting_id = modules.store.create_meeting(conversation_id="c", retention="text+frames")
        modules.store.add_segments(meeting_id, [{"t0_ms": 0, "text": "hello", "seq": 1}])
        (files / "meetings" / "s1.png").write_bytes(b"png")
        modules.store.add_keyframe(meeting_id, t_ms=0, url="/files/meetings/s1.png")

        body = client.delete(f"/v1/meetingsense/{meeting_id}").json()
        # Counts rather than "ok": deleting a meeting with twelve slides and being told "done"
        # leaves no way to know whether the twelve images went.
        assert body["rows"]["segments"] == 1
        assert body["files"]["removed"] == 1
        assert client.get(f"/v1/meetingsense/{meeting_id}").status_code == 404

    def test_deleting_a_live_meeting_stops_it_first(self, client, enabled, modules, files):
        # Deleting rows under a running session would leave it transcribing into a meeting
        # that no longer exists, and the next segment would resurrect a row the user removed.
        session = modules.session.MeetingSession(
            transport=modules.session.ListTransport(),
            config=modules.routes.load_config(),
            now=lambda: 1000.0,
        )
        run(session.start({"conversation_id": "c"}))
        modules.session.register(session)

        client.delete(f"/v1/meetingsense/{session.meeting_id}")
        assert modules.session.get(session.meeting_id) is None
        assert modules.store.get_meeting(session.meeting_id) is None

    def test_a_missing_meeting_is_a_404(self, client, enabled):
        assert client.delete("/v1/meetingsense/nope").status_code == 404

    def test_delete_is_a_404_while_the_flag_is_off(self, client, modules, monkeypatch):
        # Stated rather than inherited: since MS30 an unset MEETINGSENSE_ENABLED means
        # *on*, so a test about the flag being off has to say so.
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "false")
        meeting_id = modules.store.create_meeting(conversation_id="c", retention="text")
        assert client.delete(f"/v1/meetingsense/{meeting_id}").status_code == 404
        # And nothing was removed on the way to saying so.
        assert modules.store.get_meeting(meeting_id) is not None


# ── the session drives the engine ───────────────────────────────────────────


class FakeEngine:
    def __init__(self, frame=None, *, due=True, explode=False):
        self.added = []
        self.runs = 0
        self._frame = frame or {"type": "notes", "version": 1, "recap": "r"}
        self._due = due
        self._explode = explode

    def add(self, segments):
        self.added.extend(segments)

    def due(self):
        return self._due

    async def run(self, *, force=False):
        self.runs += 1
        if self._explode:
            raise RuntimeError("model gone")
        return self._frame


class TestSessionNotes:
    def _session(self, modules, engine, script=None):
        async def transcribe(data, *, fmt="wav", duration_s=None):
            return script or [{"t0": 0.0, "t1": 1.0, "text": "hello there", "conf": 0.9}]

        return modules.session.MeetingSession(
            transport=modules.session.ListTransport(),
            config=modules.routes.load_config(),
            transcribe=transcribe,
            notes=engine,
            now=lambda: 1000.0,
        )

    def test_segments_are_fed_to_the_engine(self, modules):
        engine = FakeEngine()
        session = self._session(modules, engine)
        run(session.start({"conversation_id": "c"}))
        run(session.on_audio({"audio_bytes": b"x", "t0": 0, "t1": 1000}))
        assert engine.added and engine.added[0]["text"] == "hello there"

    def test_a_notes_frame_is_pushed_when_one_is_produced(self, modules):
        session = self._session(modules, FakeEngine())
        run(session.start({"conversation_id": "c"}))
        run(session.on_audio({"audio_bytes": b"x", "t0": 0, "t1": 1000}))
        assert session.transport.of_type("notes")

    def test_nothing_is_pushed_when_the_window_is_not_due(self, modules):
        engine = FakeEngine(due=False)
        session = self._session(modules, engine)
        run(session.start({"conversation_id": "c"}))
        run(session.on_audio({"audio_bytes": b"x", "t0": 0, "t1": 1000}))
        assert engine.runs == 0
        assert session.transport.of_type("notes") == []

    def test_an_engine_that_raises_never_costs_the_meeting(self, modules):
        # An install with no model reachable records a perfectly good transcript.
        session = self._session(modules, FakeEngine(explode=True))
        run(session.start({"conversation_id": "c"}))
        sent = run(session.on_audio({"audio_bytes": b"x", "t0": 0, "t1": 1000}))
        assert sent and sent[0]["type"] == "segment"

    def test_stopping_forces_the_last_window(self, modules, monkeypatch):
        # Without it the final minute of every meeting is missing from its notes, and the
        # summary is built from an incomplete picture.
        import app.storage as storage

        monkeypatch.setattr(storage, "add_message", lambda *a, **k: None)
        engine = FakeEngine(due=False)
        session = self._session(modules, engine)
        run(session.start({"conversation_id": "c"}))
        run(session.on_audio({"audio_bytes": b"x", "t0": 0, "t1": 1000}))
        run(session.stop())
        assert engine.runs == 1
        assert session.transport.of_type("notes")

    def test_a_session_with_no_engine_behaves_exactly_as_before(self, modules):
        session = self._session(modules, None)
        run(session.start({"conversation_id": "c"}))
        sent = run(session.on_audio({"audio_bytes": b"x", "t0": 0, "t1": 1000}))
        assert [f["type"] for f in session.transport.frames] == ["ready", "segment"]
        assert sent[0]["type"] == "segment"
