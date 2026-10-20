"""A recorded call stays one meeting, ends when it ends, and transcribes what was said.

The reported meeting (20 Oct 2026) went wrong in five separate ways, and each has a test here:

1. **One call became eight "Untitled meeting" cards.** The rolling notes waited on a slow local
   model inside the frame loop; the socket stopped being read, its keepalive failed, the
   browser reconnected, and its resume was refused because the server still held the meeting
   as live on the old socket. → model work runs beside the audio path, and a resume takes a
   still-live meeting over instead of refusing it.
2. **Ended parts said "Recording" in the library.** `stop` wrote the end to the store only
   after the final notes call came back. → the store first; and the library closes rows no
   session holds.
3. **A traceback on every dropped socket.** Sending to a closed socket raised inside the error
   handler, which sent again. → one guarded transport.
4. **Every remote line twice, once as "You".** The call reached the microphone through the
   speakers. → the echo guard.
5. **"e piacco".** English decoded as Italian, clip by clip. → the language lock.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest
from fastapi import WebSocketDisconnect


class Modules:
    def __init__(self):
        import app.meetingsense.ask as ask
        import app.meetingsense.config as config
        import app.meetingsense.echo as echo
        import app.meetingsense.language as language
        import app.meetingsense.minutes as minutes
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.ask = ask
        self.config = config
        self.echo = echo
        self.language = language
        self.minutes = minutes
        self.routes = routes
        self.session = session
        self.store = store


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_LANGUAGE", "MEETINGSENSE_RESUME_GRACE_S"):
        monkeypatch.delenv(name, raising=False)
    # Never a real model: these tests are about the meeting, not about what a model says.
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MEETINGSENSE_SUMMARY_AUTO", "false")
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


def run(coro):
    return asyncio.run(coro)


def config(modules):
    return modules.config.load_config()


def scripted(*answers):
    """A transcriber that returns one scripted list of spans per call."""
    queue = list(answers)
    calls = []

    async def transcribe(data, *, fmt="wav", duration_s=None, **kwargs):
        calls.append(kwargs)
        return queue.pop(0) if queue else []

    transcribe.calls = calls
    return transcribe


def frame(speaker="them", t0=0, t1=2_000):
    return {"type": "audio", "audio_bytes": b"x", "format": "wav", "speaker": speaker, "t0": t0, "t1": t1}


def status(modules, meeting_id):
    return modules.store.get_meeting(meeting_id)["status"]


# ── 1. model work never holds the audio path ────────────────────────────────


class SlowNotes:
    """A notes engine whose model takes far longer than the inline wait."""

    def __init__(self, delay):
        self.delay = delay
        self.runs = 0
        self.started = asyncio.Event()

    def add(self, fresh):
        pass

    def due(self):
        return True

    async def run(self, *, force=False):
        self.runs += 1
        self.started.set()
        await asyncio.sleep(self.delay)
        return None


class TestModelWorkIsOffTheAudioPath:
    def test_a_slow_notes_window_does_not_hold_the_next_utterance(self, modules, monkeypatch):
        monkeypatch.setattr(modules.session, "FOLLOW_UP_INLINE_S", 0.05)
        monkeypatch.setattr(modules.session, "FOLLOW_UP_DRAIN_S", 0.05)
        monkeypatch.setattr(modules.session, "FINAL_NOTES_S", 0.05)

        async def scenario():
            transport = modules.session.ListTransport()
            session = modules.session.MeetingSession(
                transport=transport, config=config(modules),
                transcribe=scripted([{"t0": 0.0, "t1": 1.0, "text": "first line", "conf": 0.9}],
                                    [{"t0": 0.0, "t1": 1.0, "text": "second line", "conf": 0.9}]),
            )
            await session.start({"conversation_id": "c1"})
            session.notes = SlowNotes(delay=30)
            began = time.monotonic()
            await session.on_audio(frame(t0=0))
            await session.on_audio(frame(t0=3_000))
            took = time.monotonic() - began
            texts = [f["text"] for f in transport.frames if f.get("type") == "segment"]
            runs = session.notes.runs
            await session.stop()
            return took, texts, runs

        took, texts, runs = run(scenario())
        assert texts == ["first line", "second line"]
        # Two utterances in well under the thirty seconds one notes window takes.
        assert took < 2.0
        # Single-flight: the second utterance did not start a second window beside the first.
        assert runs == 1

    def test_stop_ends_the_meeting_in_the_store_before_waiting_on_the_model(self, modules, monkeypatch):
        monkeypatch.setattr(modules.session, "FOLLOW_UP_DRAIN_S", 0.05)
        monkeypatch.setattr(modules.session, "FINAL_NOTES_S", 5.0)
        seen = {}

        class WatchingNotes(SlowNotes):
            async def run(self, *, force=False):
                if force:
                    seen["status_during_final_notes"] = status(modules, session.meeting_id)
                return None

        session = modules.session.MeetingSession(
            transport=modules.session.ListTransport(), config=config(modules), transcribe=scripted(),
        )

        async def scenario():
            await session.start({"conversation_id": "c1"})
            session.notes = WatchingNotes(delay=0)
            await session.stop()

        run(scenario())
        assert seen["status_during_final_notes"] == "ended"

    def test_a_final_notes_window_that_never_returns_does_not_keep_the_meeting_open(self, modules, monkeypatch):
        monkeypatch.setattr(modules.session, "FOLLOW_UP_DRAIN_S", 0.05)
        monkeypatch.setattr(modules.session, "FINAL_NOTES_S", 0.1)
        session = modules.session.MeetingSession(
            transport=modules.session.ListTransport(), config=config(modules), transcribe=scripted(),
        )

        async def scenario():
            await session.start({"conversation_id": "c1"})
            session.notes = SlowNotes(delay=60)
            began = time.monotonic()
            final = await session.stop()
            return final, time.monotonic() - began

        final, took = run(scenario())
        assert final["type"] == "final"
        assert took < 5
        assert status(modules, session.meeting_id) == "ended"


# ── 2. the store and the library tell the truth ─────────────────────────────


class TestTheLibraryClosesWhatNobodyHolds:
    def test_rows_no_session_holds_are_closed_and_held_ones_kept(self, modules):
        store = modules.store
        old = time.time() - 600
        store.create_meeting(conversation_id="c", meeting_id="held", started_at=old)
        store.create_meeting(conversation_id="c", meeting_id="orphan", started_at=old)
        store.suspend_meeting("orphan", suspended_at=old + 40)
        store.create_meeting(conversation_id="c", meeting_id="brand-new", started_at=time.time())

        closed = store.close_orphaned_meetings(["held"], started_before=time.time() - 60)

        assert closed == 1
        assert status(modules, "orphan") == "ended"
        # Ends when the socket dropped, not when the library happened to be opened.
        assert store.get_meeting("orphan")["ended_at"] == pytest.approx(old + 40)
        assert status(modules, "held") == "live"
        assert status(modules, "brand-new") == "live"

    def test_a_suspended_meeting_reads_as_reconnecting_not_recording(self, modules):
        from app.meetingsense.library import projection

        row = {"id": "m1", "status": "suspended", "started_at": time.time() - 30, "ended_at": None,
               "title": "", "source": ""}
        item = projection._item(row, {}, [], {}, {}, 3, False)
        assert item["recording_state"] == "paused"
        assert item["transcript_state"] != "live"


# ── 3. a dead socket is one clean disconnect ────────────────────────────────


class DeadSocket:
    def __init__(self, exc):
        self.exc = exc
        self.sends = 0

    async def send_json(self, frame):
        self.sends += 1
        raise self.exc

    async def close(self, code=1000):
        raise RuntimeError("already closed")


class TestTheTransportGuard:
    @pytest.mark.parametrize("exc", [
        RuntimeError('Cannot call "send" once a close message has been sent.'),
        OSError("ClientDisconnected"),
        WebSocketDisconnect(code=1006),
    ])
    def test_every_way_a_socket_dies_is_one_disconnect(self, modules, exc):
        socket = DeadSocket(exc)
        transport = modules.routes.WebSocketTransport(socket)

        async def scenario():
            with pytest.raises(WebSocketDisconnect):
                await transport.send({"type": "segment"})
            # Known dead: refused without touching the socket again.
            with pytest.raises(WebSocketDisconnect):
                await transport.send({"type": "error"})
            await transport.close()

        run(scenario())
        assert socket.sends == 1
        assert transport.closed is True

    def test_a_serialisation_bug_is_not_mistaken_for_a_disconnect(self, modules):
        transport = modules.routes.WebSocketTransport(DeadSocket(TypeError("not JSON serialisable")))
        with pytest.raises(TypeError):
            run(transport.send({"type": "segment"}))
        assert transport.closed is False


# ── 1b. a reconnect continues the meeting rather than starting another ──────


class TestResumeTakesOver:
    def test_a_resume_while_the_old_socket_is_half_open_continues_the_same_meeting(self, modules):
        cfg = config(modules)
        old = modules.session.ListTransport()
        session = modules.session.MeetingSession(transport=old, config=cfg, transcribe=scripted())
        new = modules.session.ListTransport()

        async def scenario():
            await session.start({"conversation_id": "c1"})
            modules.session.register(session)
            resumed = await modules.routes._handle_resume(
                new, None, {"meeting_id": session.meeting_id, "last_seq": 0}, cfg
            )
            # The old frame loop notices its socket is gone only now.
            await modules.routes._on_disconnect(session, cfg, old)
            return resumed

        resumed = run(scenario())
        assert resumed is session
        assert session.state == modules.session.MeetingState.LIVE
        assert session.transport is new
        assert [f["type"] for f in new.frames][:1] == ["resumed"]
        assert status(modules, session.meeting_id) == "live"

    def test_a_socket_that_is_still_talking_keeps_its_meeting(self, modules):
        cfg = config(modules)
        old = modules.session.ListTransport()
        session = modules.session.MeetingSession(transport=old, config=cfg, transcribe=scripted())
        intruder = modules.session.ListTransport()

        async def scenario():
            await session.start({"conversation_id": "c1"})
            modules.session.register(session)
            session.last_heard = time.monotonic()
            return await modules.routes._handle_resume(
                intruder, None, {"meeting_id": session.meeting_id, "last_seq": 0}, cfg
            )

        assert run(scenario()) is None
        assert intruder.frames[-1]["code"] == "not_resumable"
        assert session.transport is old

    def test_an_unknown_meeting_is_still_refused(self, modules):
        cfg = config(modules)
        transport = modules.session.ListTransport()
        result = run(modules.routes._handle_resume(transport, None, {"meeting_id": "nope"}, cfg))
        assert result is None
        assert transport.frames[-1]["code"] == "not_resumable"


# ── 4. the call, heard twice ────────────────────────────────────────────────


class TestEcho:
    def test_the_microphone_repeating_the_call_is_dropped(self, modules):
        transport = modules.session.ListTransport()
        session = modules.session.MeetingSession(
            transport=transport, config=config(modules),
            transcribe=scripted(
                [{"t0": 0.2, "t1": 2.0, "text": "We moved the launch to the twenty eighth.", "conf": 0.9}],
                [{"t0": 0.4, "t1": 2.1, "text": "we moved the launch to the twenty-eighth", "conf": 0.6}],
                [{"t0": 0.1, "t1": 1.5, "text": "Sounds good, I will tell the team.", "conf": 0.9}],
            ),
        )

        async def scenario():
            await session.start({"conversation_id": "c1", "audio": {"mode": "system+mic", "channels": 2}})
            await session.on_audio(frame("them", t0=10_000, t1=12_500))
            await session.on_audio(frame("me", t0=10_000, t1=12_500))
            await session.on_audio(frame("me", t0=14_000, t1=16_000))

        run(scenario())
        lines = [(f["speaker"], f["text"]) for f in transport.frames if f.get("type") == "segment"]
        assert lines == [
            ("them", "We moved the launch to the twenty eighth."),
            ("me", "Sounds good, I will tell the team."),
        ]

    def test_real_crosstalk_survives(self, modules):
        guard = modules.echo.EchoGuard()
        guard.heard({"t0_ms": 0, "t1_ms": 2_000, "text": "the budget is approved for next quarter"})
        assert not guard.is_echo({"t0_ms": 500, "t1_ms": 2_000, "text": "wait, which budget do you mean"})
        # The same words much later are a person agreeing, not an echo.
        assert not guard.is_echo({"t0_ms": 20_000, "t1_ms": 22_000, "text": "the budget is approved"})

    def test_a_short_reply_is_only_an_echo_when_every_word_matches(self, modules):
        guard = modules.echo.EchoGuard()
        guard.heard({"t0_ms": 0, "t1_ms": 1_000, "text": "Okay, great."})
        assert guard.is_echo({"t0_ms": 200, "t1_ms": 900, "text": "Okay great"})
        assert not guard.is_echo({"t0_ms": 200, "t1_ms": 900, "text": "Okay, thanks"})

    def test_the_user_is_told_once(self, modules):
        transport = modules.session.ListTransport()
        lines = [[{"t0": 0.0, "t1": 1.5, "text": f"line number {n} about the plan", "conf": 0.9}]
                 for n in range(3)]
        answers = []
        for line in lines:
            answers += [line, line]  # the call, then the microphone repeating it
        session = modules.session.MeetingSession(transport=transport, config=config(modules),
                                                 transcribe=scripted(*answers))

        async def scenario():
            await session.start({"conversation_id": "c1"})
            for n in range(3):
                await session.on_audio(frame("them", t0=n * 5_000))
                await session.on_audio(frame("me", t0=n * 5_000))

        run(scenario())
        notices = [f for f in transport.frames if f.get("type") == "notice"]
        assert len(notices) == 1
        assert notices[0]["code"] == "echo"
        assert "headphones" in notices[0]["msg"]


# ── 5. one language per meeting ─────────────────────────────────────────────


class TestLanguage:
    def test_two_confident_detections_lock_the_meeting(self, modules):
        lock = modules.language.LanguageLock()
        spans = [{"text": "let us review the numbers", "lang": "en", "lang_p": 0.97}]
        assert lock.observe(spans) is None
        assert lock.observe([{"text": "e piacco", "lang": "it", "lang_p": 0.55}]) is None  # unsure
        assert lock.observe([{"text": "ok", "lang": "it", "lang_p": 0.99}]) is None  # too short
        assert lock.observe(spans) == "en"
        assert lock.decode_language == "en"

    @pytest.mark.parametrize("value,expected", [
        ("", ("auto", None)), ("auto", ("auto", None)), ("en-US", ("fixed", "en")),
        ("IT", ("fixed", "it")), ("multi", ("multi", None)), ("klingon!", ("auto", None)),
    ])
    def test_requests_are_normalised(self, modules, value, expected):
        assert modules.language.normalise(value) == expected

    def test_the_start_frame_language_reaches_the_transcriber(self, modules):
        transcribe = scripted([{"t0": 0.0, "t1": 1.0, "text": "buongiorno a tutti", "conf": 0.9}])
        session = modules.session.MeetingSession(transport=modules.session.ListTransport(),
                                                 config=config(modules), transcribe=transcribe)

        async def scenario():
            await session.start({"conversation_id": "c1", "language": "it"})
            await session.on_audio(frame("them"))

        run(scenario())
        assert transcribe.calls == [{"language": "it"}]

    def test_a_transcriber_without_the_keyword_still_works(self, modules):
        async def old_style(data, *, fmt="wav", duration_s=None):
            return [{"t0": 0.0, "t1": 1.0, "text": "hello there", "conf": 0.9}]

        transport = modules.session.ListTransport()
        session = modules.session.MeetingSession(transport=transport, config=config(modules),
                                                 transcribe=old_style)

        async def scenario():
            await session.start({"conversation_id": "c1", "language": "en"})
            await session.on_audio(frame("them"))

        run(scenario())
        assert [f["text"] for f in transport.frames if f.get("type") == "segment"] == ["hello there"]


# ── the recap and Ask after the meeting ─────────────────────────────────────


class TestAfterTheMeeting:
    def test_the_recap_is_told_a_summary_is_being_written(self, modules):
        modules.minutes.expect_summary("m1")
        assert modules.minutes.is_writing("m1")
        modules.minutes.summary_done("m1")
        assert not modules.minutes.is_writing("m1")

    def test_ask_sees_the_whole_meeting_when_there_is_no_recap(self, modules):
        segments = [
            {"t0_ms": i * 20_000, "t1_ms": i * 20_000 + 5_000, "speaker": "them",
             "text": f"topic {i}: the migration plan for the billing service"}
            for i in range(30)
        ]
        text = modules.ask.overview(segments, before_ms=segments[-5]["t0_ms"])
        assert text.startswith("Lines from across the meeting")
        assert "[00:00:00]" in text  # the start of the meeting, not only its last minute
        assert len(text.split()) < modules.ask.OVERVIEW_WORDS * 2
