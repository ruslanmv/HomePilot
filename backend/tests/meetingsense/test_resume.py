"""Resume on reconnect (batch MS3-a, decision D10).

MS3 ended a meeting when its socket dropped. That is right for the store — no row saying "in
progress" forever — and wrong for the person whose Wi-Fi blinked forty minutes into a board
meeting. Otter, Zoom and Teams all survive a blip without a split recording; somebody who
loses ten minutes to one does not come back.

So a drop now *suspends*: the session is held, with its assemblers and its numbering intact,
for a grace window. A client that reconnects inside the window carries on. After it, the MS3
end path runs exactly as it did.

Two things here are load-bearing and neither is obvious.

**The assemblers must survive.** They hold the 200 ms overlap window. Rebuilding them on
resume would restart the dedupe with an empty window, and the first chunk after every
reconnection would duplicate the words it overlaps.

**What died in the socket has to come back.** D10 says the server replays nothing because the
client already has it — true of everything that arrived, and false of exactly the frames that
were in flight when the socket died. Those exist only in the store, so replaying them is what
makes "no gap in seq" true rather than aspirational.
"""

from __future__ import annotations

import array
import asyncio
import base64
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MS_ENV_VARS = [
    "MEETINGSENSE_ENABLED",
    "MEETINGSENSE_RESUME_GRACE_S",
    "MEETINGSENSE_RESUME_MAX_REPLAY",
    "STT_BASE_URL",
    "WHISPER_MODEL",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in MS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.config as config
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

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


class StubSTT:
    name = "stub"
    available = True
    supports_segments = True

    def __init__(self):
        self.script = []
        self.calls = []

    async def transcribe_segments(self, data, *, fmt="wav", duration_s=None):
        self.calls.append({"fmt": fmt, "duration_s": duration_s})
        if self.script:
            return self.script.pop(0)
        return [{"t0": 0.0, "t1": duration_s, "text": f"line {len(self.calls)}", "conf": 0.9}]


@pytest.fixture()
def stt(modules, monkeypatch):
    provider = StubSTT()
    import app.voice.providers as providers

    monkeypatch.setattr(providers, "get_stt_provider", lambda: provider)
    return provider


@pytest.fixture()
def client(modules):
    app = FastAPI()
    app.include_router(modules.routes.router)
    return TestClient(app)


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")


# ── helpers ─────────────────────────────────────────────────────────────────


def pcm(samples=(1, 2)):
    return array.array("h", samples).tobytes()


def audio(**extra):
    return {"type": "audio", "format": "pcm16", "data_b64": base64.b64encode(pcm()).decode(), **extra}


def start(ws, **extra):
    ws.send_json({"type": "start", "conversation_id": "conv-1", **extra})
    return ws.receive_json()


def collect(ws):
    """Everything queued, bounded by a ping/pong so a missing frame fails instead of hanging."""
    ws.send_json({"type": "ping"})
    frames = []
    while True:
        frame = ws.receive_json()
        if frame.get("type") == "pong":
            return frames
        frames.append(frame)


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── the store ───────────────────────────────────────────────────────────────


class TestStore:
    def test_suspend_records_a_time_without_ending_the_meeting(self, modules):
        mid = modules.store.create_meeting(conversation_id="c", retention="text")
        modules.store.suspend_meeting(mid, suspended_at=1_000.0)
        row = modules.store.get_meeting(mid)
        assert row["status"] == "suspended"
        assert row["suspended_at"] == 1_000.0
        # Not `ended_at`: a suspended meeting has no end yet, and writing one now would have
        # to be un-written on resume. A timestamp that moves backwards is worse than none.
        assert row["ended_at"] is None

    def test_resume_clears_it(self, modules):
        mid = modules.store.create_meeting(conversation_id="c", retention="text")
        modules.store.suspend_meeting(mid)
        assert modules.store.resume_meeting(mid) is True
        row = modules.store.get_meeting(mid)
        assert row["status"] == "live"
        assert row["suspended_at"] is None

    def test_an_ended_meeting_cannot_be_resumed(self, modules):
        # The guard that stops a client recording into a closed meeting because its reconnect
        # raced the grace timer.
        mid = modules.store.create_meeting(conversation_id="c", retention="text")
        modules.store.suspend_meeting(mid)
        modules.store.end_meeting(mid)
        assert modules.store.resume_meeting(mid) is False

    def test_suspending_an_ended_meeting_does_nothing(self, modules):
        mid = modules.store.create_meeting(conversation_id="c", retention="text")
        modules.store.end_meeting(mid, ended_at=5.0)
        modules.store.suspend_meeting(mid)
        assert modules.store.get_meeting(mid)["ended_at"] == 5.0

    def test_segments_after_seq_reads_in_sequence_order(self, modules):
        mid = modules.store.create_meeting(conversation_id="c", retention="text")
        modules.store.add_segments(
            mid,
            [
                {"t0_ms": 0, "t1_ms": 1, "text": "one", "seq": 1},
                # Same t0 as the next: two channels of one chunk. This is exactly why the
                # replay is ordered by `seq` and not by time — time is not a numbering.
                {"t0_ms": 10, "t1_ms": 11, "text": "two", "seq": 2},
                {"t0_ms": 10, "t1_ms": 11, "text": "three", "seq": 3},
            ],
        )
        rows = modules.store.segments_after_seq(mid, 1)
        assert [r["text"] for r in rows] == ["two", "three"]

    def test_the_replay_is_bounded(self, modules):
        mid = modules.store.create_meeting(conversation_id="c", retention="text")
        modules.store.add_segments(
            mid, [{"t0_ms": i, "text": f"s{i}", "seq": i} for i in range(1, 51)]
        )
        assert len(modules.store.segments_after_seq(mid, 0, limit=10)) == 10

    def test_segments_recorded_before_this_batch_are_never_replayed(self, modules):
        # A meeting recorded by MS3 has `seq = NULL`. It cannot be resumed, which is correct:
        # it was recorded by a server that had no resume. Replaying it from an assumed
        # ordering would be inventing a numbering that never existed.
        mid = modules.store.create_meeting(conversation_id="c", retention="text")
        modules.store.add_segments(mid, [{"t0_ms": 0, "text": "old"}])
        assert modules.store.segments_after_seq(mid, 0) == []


class TestMigration:
    def test_a_schema_1_database_gains_the_new_columns(self, tmp_path, monkeypatch, modules):
        # `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so without
        # the ALTER a database created by MS2 keeps the old shape — and the failure would be
        # an OperationalError on the first resume, mid-meeting.
        db = tmp_path / "old.sqlite3"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE ms_meetings(id TEXT PRIMARY KEY, conversation_id TEXT, project_id TEXT,"
            " title TEXT, source TEXT, started_at REAL NOT NULL, ended_at REAL, audio_mode TEXT,"
            " retention TEXT NOT NULL DEFAULT 'text', status TEXT NOT NULL DEFAULT 'live',"
            " summary_json TEXT)"
        )
        con.execute(
            "CREATE TABLE ms_segments(id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL,"
            " t0_ms INTEGER NOT NULL, t1_ms INTEGER, speaker TEXT, text TEXT NOT NULL, conf REAL)"
        )
        con.execute("INSERT INTO ms_meetings(id, started_at) VALUES ('m1', 1.0)")
        con.commit()
        con.close()

        def _connect():
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            return conn

        monkeypatch.setattr(modules.store, "_connect", _connect)
        modules.store.migrate()

        con = _connect()
        try:
            meetings = {r[1] for r in con.execute("PRAGMA table_info(ms_meetings)").fetchall()}
            segments = {r[1] for r in con.execute("PRAGMA table_info(ms_segments)").fetchall()}
            # The existing row survives; adding a nullable column does not rewrite the table.
            assert con.execute("SELECT COUNT(*) FROM ms_meetings").fetchone()[0] == 1
        finally:
            con.close()
        assert "suspended_at" in meetings
        assert "seq" in segments

    def test_migrating_twice_is_free(self, modules):
        modules.store.migrate()
        modules.store.migrate()
        assert modules.store.tables_exist()


# ── the socket ──────────────────────────────────────────────────────────────


class TestSuspendOnDisconnect:
    def test_a_drop_suspends_rather_than_ends(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
            ws.send_json(audio())
            ws.receive_json()
        row = modules.store.get_meeting(ready["meeting_id"])
        assert row["status"] == "suspended"
        assert row["ended_at"] is None
        assert row["suspended_at"] is not None

    def test_the_session_is_kept_but_is_no_longer_live(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
        mid = ready["meeting_id"]
        # Held, so a reconnect finds it — but not live, so nothing treats it as recording.
        assert mid in modules.session.suspended_sessions()
        assert modules.session.live_sessions() == {}
        assert modules.session.for_conversation("conv-1") is None

    def test_a_stopped_meeting_is_not_suspended_by_the_disconnect(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
            ws.send_json({"type": "stop"})
            ws.receive_json()
        row = modules.store.get_meeting(ready["meeting_id"])
        assert row["status"] == "ended"
        assert modules.session.suspended_sessions() == {}


class TestResume:
    def _drop(self, client, stt, **kw):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws, **kw)
            ws.send_json(audio(t0=0, t1=1400))
            first = ws.receive_json()
        return ready["meeting_id"], first

    def test_a_reconnect_inside_the_window_carries_on(self, client, enabled, stt, modules):
        mid, first = self._drop(client, stt)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": mid, "last_seq": first["seq"]})
            frame = ws.receive_json()
            assert frame["type"] == "resumed"
            assert frame["meeting_id"] == mid
            # Checked inside the socket: closing it suspends the meeting again, which is the
            # correct behaviour and would make this read "suspended" a line later.
            assert modules.store.get_meeting(mid)["status"] == "live"

    def test_numbering_continues_with_no_duplicate_and_no_gap(self, client, enabled, stt, modules):
        mid, first = self._drop(client, stt)
        assert first["seq"] == 1
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": mid, "last_seq": 1})
            assert ws.receive_json()["type"] == "resumed"
            ws.send_json(audio(t0=5_000, t1=6_400))
            nxt = ws.receive_json()
        assert nxt["seq"] == 2

    def test_what_died_in_the_socket_comes_back(self, client, enabled, stt, modules):
        # The case D10's "the client already has it" does not cover: the server sent a segment
        # into a socket that was already gone. It is in the store and nowhere else, so without
        # the replay the live transcript keeps a hole that only heals on reload.
        mid, first = self._drop(client, stt)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": mid, "last_seq": 0})
            frames = collect(ws)
        assert frames[0]["type"] == "resumed"
        replayed = [f for f in frames if f.get("type") == "segment"]
        assert [f["seq"] for f in replayed] == [1]
        assert replayed[0]["text"] == first["text"]
        # Marked, so a client can tell a re-delivery from something newly said.
        assert replayed[0]["replayed"] is True

    def test_a_client_that_missed_nothing_is_sent_nothing(self, client, enabled, stt):
        mid, first = self._drop(client, stt)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": mid, "last_seq": first["seq"]})
            frames = collect(ws)
        assert [f["type"] for f in frames] == ["resumed"]

    def test_the_overlap_window_survives_the_drop(self, client, enabled, stt, modules):
        # The assemblers hold the 200 ms overlap window. Rebuilding them on resume would
        # restart the dedupe empty, and the first chunk after every reconnection would
        # duplicate the words it overlaps.
        stt.script = [
            [{"t0": 0.0, "t1": 2.0, "text": "the launch moves to October", "conf": 0.9}],
            [{"t0": 0.0, "t1": 2.0, "text": "moves to October and legal", "conf": 0.9}],
        ]
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
            ws.send_json(audio(t0=0, t1=2000))
            ws.receive_json()
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": ready["meeting_id"], "last_seq": 1})
            ws.receive_json()
            ws.send_json(audio(t0=1_800, t1=3_800))
            frame = ws.receive_json()
        assert frame["text"] == "and legal"

    def test_the_counters_survive_the_drop(self, client, enabled, stt):
        mid, _ = self._drop(client, stt)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": mid, "last_seq": 1})
            resumed = ws.receive_json()
        assert resumed["segments"] == 1

    def test_a_resumed_meeting_is_findable_again(self, client, enabled, stt, modules):
        mid, _ = self._drop(client, stt)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": mid, "last_seq": 1})
            ws.receive_json()
            # MS18's context provider looks a live meeting up by conversation; a resumed one
            # has to be visible there again or a persona stops seeing the meeting mid-way.
            assert modules.session.for_conversation("conv-1") is not None

    def test_stop_after_a_resume_ends_it_properly(self, client, enabled, stt, modules):
        mid, _ = self._drop(client, stt)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": mid, "last_seq": 1})
            ws.receive_json()
            ws.send_json({"type": "stop"})
            final = ws.receive_json()
        assert final["type"] == "final"
        assert modules.store.get_meeting(mid)["ended_at"] is not None


class TestResumeRefusals:
    def test_an_unknown_meeting_is_refused_with_the_socket_left_open(self, client, enabled, stt):
        # A client that reconnected only to be hung up on cannot tell "too late" from "wrong
        # server", and will keep trying.
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": "nope", "last_seq": 3})
            frame = ws.receive_json()
            assert frame["type"] == "error"
            assert frame["code"] == "not_resumable"
            # Still usable: the client can start a fresh meeting on this same socket.
            assert start(ws)["type"] == "ready"

    def test_a_resume_without_a_meeting_id_is_named(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume"})
            assert ws.receive_json()["code"] == "meeting_required"

    def test_a_live_meeting_cannot_be_resumed_out_from_under_its_socket(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as first:
            ready = start(first)
            with client.websocket_connect("/v1/meetingsense/session") as second:
                second.send_json({"type": "resume", "meeting_id": ready["meeting_id"], "last_seq": 0})
                assert second.receive_json()["code"] == "not_resumable"

    def test_an_ended_meeting_is_refused(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
            ws.send_json({"type": "stop"})
            ws.receive_json()
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": ready["meeting_id"], "last_seq": 0})
            assert ws.receive_json()["code"] == "not_resumable"


# ── the grace window ────────────────────────────────────────────────────────


class TestExpiry:
    def _suspended(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
        return modules.session.get(ready["meeting_id"])

    def test_it_stays_resumable_inside_the_window(self, client, enabled, stt, modules):
        session = self._suspended(client, enabled, stt, modules)
        expired = run(
            modules.session.expire_if_due(session, grace_s=120.0, now=session.suspended_at + 1)
        )
        assert expired is False
        assert modules.store.get_meeting(session.meeting_id)["ended_at"] is None

    def test_it_ends_once_the_window_closes(self, client, enabled, stt, modules):
        session = self._suspended(client, enabled, stt, modules)
        expired = run(
            modules.session.expire_if_due(session, grace_s=120.0, now=session.suspended_at + 121)
        )
        assert expired is True
        assert modules.store.get_meeting(session.meeting_id)["status"] == "ended"
        assert modules.session.get(session.meeting_id) is None

    def test_the_end_time_is_when_the_socket_dropped(self, modules):
        # Not two minutes later when a timer noticed: the elapsed time a card shows should be
        # how long people were actually talking.
        #
        # This needs an injected clock, and the first version of it did not have one — it
        # compared two real timestamps a millisecond apart with `pytest.approx`, whose default
        # tolerance is *relative*. On a Unix timestamp that is roughly ±1700 seconds, so the
        # assertion could not fail and the mutation that ends the meeting at "now" survived it.
        clock = {"t": 1_000.0}
        session = modules.session.MeetingSession(
            transport=modules.session.ListTransport(),
            config=modules.config.MeetingSenseConfig(enabled=True),
            now=lambda: clock["t"],
        )
        run(session.start({"conversation_id": "c"}))
        clock["t"] = 1_060.0
        session.suspend()
        clock["t"] = 1_400.0  # the timer fires five minutes later
        run(modules.session.expire_if_due(session, grace_s=120.0, now=clock["t"]))

        assert modules.store.get_meeting(session.meeting_id)["ended_at"] == 1_060.0
        # And the elapsed time is the minute of conversation, not the six minutes of wall clock.
        assert session.elapsed_ms == 60_000

    def test_expiring_a_live_session_does_nothing(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
            session = modules.session.get(ready["meeting_id"])
            assert run(modules.session.expire_if_due(session, grace_s=0.0, now=1e9)) is False

    def test_the_timer_is_actually_armed(self, client, enabled, stt, modules):
        # The ignition, not the engine: `expire_if_due` can be perfect and never called, and
        # a unit test of it would not notice. This drives the route's own disconnect handler
        # and then awaits the task it armed, so the thing under test is the wiring.
        #
        # It cannot go through TestClient: the portal that runs the websocket is torn down
        # when the connection context exits, taking the pending task with it. In a server the
        # loop outlives the handler, which is why the task is the right mechanism there and
        # the wrong one to assert through a test client.
        config = modules.config.MeetingSenseConfig(
            enabled=True, resume=modules.config.ResumeConfig(grace_s=0.05)
        )

        async def scenario():
            session = modules.session.MeetingSession(
                transport=modules.session.ListTransport(), config=config
            )
            await session.start({"conversation_id": "c"})
            modules.session.register(session)
            await modules.routes._on_disconnect(session, config)
            assert session.state == modules.session.MeetingState.SUSPENDED
            assert session.expiry_task is not None
            await session.expiry_task
            return session.meeting_id

        meeting_id = run(scenario())
        assert modules.store.get_meeting(meeting_id)["status"] == "ended"
        assert modules.session.get(meeting_id) is None

    def test_a_resume_cancels_the_timer(self, client, enabled, stt, modules, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_RESUME_GRACE_S", "30")  # long enough not to fire
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "resume", "meeting_id": ready["meeting_id"], "last_seq": 0})
            ws.receive_json()
            session = modules.session.get(ready["meeting_id"])
            assert session.expiry_task is None
            assert session.state == modules.session.MeetingState.LIVE

    def test_zero_grace_is_exactly_the_old_behaviour(self, client, enabled, stt, modules, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_RESUME_GRACE_S", "0")
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
        row = modules.store.get_meeting(ready["meeting_id"])
        assert row["status"] == "ended"
        assert row["suspended_at"] is None
        assert modules.session.suspended_sessions() == {}


class TestStatusFrame:
    def test_a_live_meeting_has_no_deadline(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "status"})
            frame = ws.receive_json()
        assert frame["resumable_until"] is None
        assert frame["seq"] == 0

    def test_status_reports_the_sequence(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json(audio(t0=0, t1=1400))
            ws.receive_json()
            ws.send_json({"type": "status"})
            frame = ws.receive_json()
        assert frame["seq"] == 1

    def test_a_suspended_session_knows_its_deadline(self, client, enabled, stt, modules, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_RESUME_GRACE_S", "30")
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
        session = modules.session.get(ready["meeting_id"])
        assert session.resumable_until(30.0) == pytest.approx(session.suspended_at + 30)


# ── the session object ──────────────────────────────────────────────────────


class TestSessionState:
    def _live(self, modules):
        session = modules.session.MeetingSession(
            transport=modules.session.ListTransport(),
            config=modules.config.MeetingSenseConfig(enabled=True),
            now=lambda: 1_000.0,
        )
        run(session.start({"conversation_id": "c"}))
        return session

    def test_suspend_detaches_the_transport(self, modules):
        # A write to the socket that just died raises, and the raise would land in whatever
        # was mid-way through handling a timer.
        session = self._live(modules)
        socket = session.transport
        session.suspend()
        assert session.transport is not socket
        run(session.send_status())
        assert socket.frames == [f for f in socket.frames if f["type"] == "ready"]

    def test_a_suspended_session_refuses_audio(self, modules):
        session = self._live(modules)
        session.suspend()
        with pytest.raises(modules.session.MeetingSessionError) as exc:
            run(session.on_audio({"audio_bytes": b"x"}))
        assert exc.value.code == "not_live"

    def test_suspending_twice_is_refused(self, modules):
        session = self._live(modules)
        session.suspend()
        with pytest.raises(modules.session.MeetingSessionError):
            session.suspend()

    def test_resuming_a_live_session_is_refused(self, modules):
        session = self._live(modules)
        with pytest.raises(modules.session.MeetingSessionError) as exc:
            run(session.resume(modules.session.ListTransport()))
        assert exc.value.code == "not_suspended"

    def test_resume_is_refused_when_the_store_disagrees(self, modules):
        # The reconnect raced the grace timer: the meeting ended underneath. Believe the
        # store, not the in-memory object.
        session = self._live(modules)
        session.suspend()
        modules.store.end_meeting(session.meeting_id)
        with pytest.raises(modules.session.MeetingSessionError) as exc:
            run(session.resume(modules.session.ListTransport()))
        assert exc.value.code == "not_resumable"

    def test_stop_works_from_suspended(self, modules):
        session = self._live(modules)
        session.suspend()
        final = run(session.stop())
        assert final["type"] == "final"
        assert session.state == modules.session.MeetingState.ENDED
