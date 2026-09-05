"""The store and the session core (batch MS2).

The claim this batch exists to make true: **one core, two transports.** MS3 will run it over
a FastAPI WebSocket, MS7 over the avatar session that OllaBridge proxies, and neither may
change a line of `session.py`. So the tests drive it through `ListTransport` — a list with
two methods — and if the core ever needs more than `send` and `close`, that is where it shows
up first.

The store tests run against a real SQLite file in a tmp directory, not a mock. A mocked
database proves the calls were made in the right order and nothing about whether the schema
accepts them.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    """The MeetingSense modules, with the database pointed at a temporary file.

    Imported inside the fixture, never at module scope: `tests/conftest.py:34` purges every
    `app.*` module from `sys.modules` in a session fixture, so anything captured at collection
    time is a different object from the one the code under test uses.
    """
    import app.meetingsense.session as session_mod
    import app.meetingsense.store as store_mod
    from app.meetingsense.config import MeetingSenseConfig

    db = tmp_path / "meetings.sqlite"
    monkeypatch.setattr(store_mod, "_connect", _connector(str(db)))
    store_mod.migrate()

    # A registry left populated by one test would leak a live meeting into the next.
    session_mod._SESSIONS.clear()
    yield type("Mods", (), {"store": store_mod, "session": session_mod, "Config": MeetingSenseConfig})
    session_mod._SESSIONS.clear()


def _connector(path):
    import sqlite3

    def _connect():
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        return con

    return _connect


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── store ───────────────────────────────────────────────────────────────────


class TestStore:
    def test_migrate_is_idempotent(self, modules):
        modules.store.migrate()
        modules.store.migrate()
        assert modules.store.tables_exist() is True

    def test_migrate_if_enabled_does_nothing_while_the_flag_is_off(self, modules, monkeypatch):
        # An install that never turns MeetingSense on should not grow four tables.
        called = []
        monkeypatch.setattr(modules.store, "migrate", lambda: called.append(1))
        assert modules.store.migrate_if_enabled(modules.Config(enabled=False)) is False
        assert called == []
        assert modules.store.migrate_if_enabled(modules.Config(enabled=True)) is True
        assert called == [1]

    def test_a_meeting_round_trips(self, modules):
        mid = modules.store.create_meeting(
            conversation_id="conv-1", title="Q3 planning", source="teams", audio_mode="system+mic"
        )
        meeting = modules.store.get_meeting(mid)
        assert meeting["conversation_id"] == "conv-1"
        assert meeting["title"] == "Q3 planning"
        assert meeting["status"] == "live"
        assert meeting["ended_at"] is None

    def test_ending_a_meeting_twice_is_safe(self, modules):
        # Both ends of a socket notice a disconnect, and both will try to stop.
        mid = modules.store.create_meeting(conversation_id="c")
        modules.store.end_meeting(mid, summary={"decisions": []})
        modules.store.end_meeting(mid)
        assert modules.store.get_meeting(mid)["status"] == "ended"

    def test_an_unmeasured_end_is_stored_as_null_not_zero(self, modules):
        # MS1's contract carried into the schema: `t1_ms` None means the provider did not
        # measure the end. A zero would be a number a reader cannot tell from a real one.
        mid = modules.store.create_meeting(conversation_id="c")
        modules.store.add_segments(mid, [{"t0_ms": 100, "t1_ms": None, "text": "hello"}])
        assert modules.store.get_segments(mid)[0]["t1_ms"] is None

    def test_segments_come_back_in_time_order(self, modules):
        mid = modules.store.create_meeting(conversation_id="c")
        modules.store.add_segments(
            mid,
            [
                {"t0_ms": 3000, "text": "third"},
                {"t0_ms": 1000, "text": "first"},
                {"t0_ms": 2000, "text": "second"},
            ],
        )
        assert [s["text"] for s in modules.store.get_segments(mid)] == ["first", "second", "third"]

    def test_a_time_window_selects_the_slide_join(self, modules):
        # What MS10's lightbox needs: the transcript spoken while one slide was up.
        mid = modules.store.create_meeting(conversation_id="c")
        modules.store.add_segments(
            mid, [{"t0_ms": t, "text": f"s{t}"} for t in (500, 1500, 2500, 3500)]
        )
        window = modules.store.get_segments(mid, t0_ms=1000, t1_ms=3000)
        assert [s["text"] for s in window] == ["s1500", "s2500"]

    def test_blank_segments_are_never_stored(self, modules):
        mid = modules.store.create_meeting(conversation_id="c")
        assert modules.store.add_segments(mid, [{"t0_ms": 0, "text": "   "}]) == []
        assert modules.store.get_segments(mid) == []

    def test_a_caption_can_arrive_after_the_frame(self, modules):
        # The vision model answers seconds later; the keyframe is stored immediately.
        mid = modules.store.create_meeting(conversation_id="c")
        kid = modules.store.add_keyframe(mid, t_ms=1000, url="/files/a.jpg")
        assert modules.store.get_keyframes(mid)[0]["caption"] is None
        modules.store.set_keyframe_caption(kid, "Timeline v3")
        assert modules.store.get_keyframes(mid)[0]["caption"] == "Timeline v3"

    def test_notes_are_versioned_not_overwritten(self, modules):
        # The card corrects by appending and striking through, which needs the previous
        # version to still exist.
        mid = modules.store.create_meeting(conversation_id="c")
        assert modules.store.save_notes(mid, {"decisions": ["a"]}) == 1
        assert modules.store.save_notes(mid, {"decisions": ["a", "b"]}) == 2
        assert modules.store.get_notes(mid)["version"] == 2
        assert modules.store.get_notes(mid, version=1)["notes"] == {"decisions": ["a"]}

    def test_deleting_a_meeting_reports_what_it_removed(self, modules):
        mid = modules.store.create_meeting(conversation_id="c")
        modules.store.add_segments(mid, [{"t0_ms": 0, "text": "x"}, {"t0_ms": 1, "text": "y"}])
        modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg")
        modules.store.save_notes(mid, {})
        counts = modules.store.delete_meeting(mid)
        assert counts == {"segments": 2, "keyframes": 1, "notes": 1, "meetings": 1}
        assert modules.store.get_meeting(mid) is None

    def test_deleting_one_meeting_leaves_another_alone(self, modules):
        keep = modules.store.create_meeting(conversation_id="c")
        drop = modules.store.create_meeting(conversation_id="c")
        modules.store.add_segments(keep, [{"t0_ms": 0, "text": "keep"}])
        modules.store.add_segments(drop, [{"t0_ms": 0, "text": "drop"}])
        modules.store.delete_meeting(drop)
        assert [s["text"] for s in modules.store.get_segments(keep)] == ["keep"]


# ── the transport seam ──────────────────────────────────────────────────────


class TestTransportSeam:
    def test_the_core_imports_no_web_framework(self, modules):
        # The load-bearing claim of MS2. If this fails, MS7 becomes a rewrite rather than an
        # implementation, and the yourfriend.online deployment gets its own copy of the core.
        import inspect

        source = inspect.getsource(modules.session)
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith(("#", '"', "*"))
        )
        for forbidden in ("import fastapi", "from fastapi", "WebSocket("):
            assert forbidden not in code, f"session.py must not reach for {forbidden}"

    def test_a_transport_is_two_methods(self, modules):
        # Anything more — the peer address, the negotiated capabilities, whether the socket
        # is open — is knowledge the core would branch on, and branching on it is how one
        # core becomes two.
        methods = {m for m in dir(modules.session.Transport) if not m.startswith("_")}
        assert methods == {"send", "close"}

    def test_the_list_transport_satisfies_it(self, modules):
        transport = modules.session.ListTransport()
        run(transport.send({"type": "ping"}))
        run(transport.close())
        assert transport.types() == ["ping"]
        assert transport.closed is True


# ── session lifecycle ───────────────────────────────────────────────────────


def _session(modules, *, transcribe=None, now=None):
    clock = now or (lambda: 1_000.0)
    return modules.session.MeetingSession(
        transport=modules.session.ListTransport(),
        config=modules.Config(enabled=True),
        transcribe=transcribe,
        now=clock,
    )


class TestLifecycle:
    def test_start_answers_ready_and_writes_the_meeting(self, modules):
        s = _session(modules)
        run(s.start({"conversation_id": "conv-1", "title": "Q3"}))
        assert s.state == "live"
        assert s.transport.types() == ["ready"]
        assert modules.store.get_meeting(s.meeting_id)["conversation_id"] == "conv-1"

    def test_a_meeting_needs_somewhere_to_land(self, modules):
        # A meeting with no conversation is a meeting nobody can find again.
        s = _session(modules)
        with pytest.raises(modules.session.MeetingSessionError) as exc:
            run(s.start({}))
        assert exc.value.code == "conversation_required"

    def test_starting_twice_is_refused(self, modules):
        s = _session(modules)
        run(s.start({"conversation_id": "c"}))
        with pytest.raises(modules.session.MeetingSessionError):
            run(s.start({"conversation_id": "c"}))

    def test_stop_answers_final_and_ends_the_row(self, modules):
        s = _session(modules)
        run(s.start({"conversation_id": "c"}))
        run(s.stop())
        assert s.state == "ended"
        assert s.transport.types() == ["ready", "final"]
        assert modules.store.get_meeting(s.meeting_id)["status"] == "ended"

    def test_stopping_twice_is_a_no_op_not_an_error(self, modules):
        # Both ends notice a disconnect and both will try. The second is the same outcome
        # arriving twice, not a fault to report.
        s = _session(modules)
        run(s.start({"conversation_id": "c"}))
        run(s.stop())
        run(s.stop())
        assert s.transport.types().count("final") == 1

    def test_stopping_something_never_started_is_an_error(self, modules):
        s = _session(modules)
        with pytest.raises(modules.session.MeetingSessionError):
            run(s.stop())

    def test_elapsed_freezes_when_the_meeting_ends(self, modules):
        clock = {"t": 1_000.0}
        s = _session(modules, now=lambda: clock["t"])
        run(s.start({"conversation_id": "c"}))
        clock["t"] = 1_042.0
        run(s.stop())
        clock["t"] = 9_999.0
        assert s.elapsed_ms == 42_000

    def test_elapsed_is_zero_before_the_start(self, modules):
        assert _session(modules).elapsed_ms == 0

    def test_audio_before_start_is_refused(self, modules):
        s = _session(modules, transcribe=_fixed([{"t0": 0.0, "t1": 1.0, "text": "x"}]))
        with pytest.raises(modules.session.MeetingSessionError) as exc:
            run(s.on_audio({"audio_bytes": b"x"}))
        assert exc.value.code == "not_live"


# ── audio in, segments out ──────────────────────────────────────────────────


def _fixed(spans):
    async def transcribe(audio, *, fmt="wav", duration_s=None):
        return spans

    return transcribe


class TestAudio:
    def test_a_chunk_becomes_a_segment_frame_and_a_row(self, modules):
        s = _session(modules, transcribe=_fixed([{"t0": 0.0, "t1": 1.4, "text": "so the launch moves"}]))
        run(s.start({"conversation_id": "c"}))
        sent = run(s.on_audio({"audio_bytes": b"pcm", "t0": 0, "t1": 1400}))
        assert [f["text"] for f in sent] == ["so the launch moves"]
        assert s.transport.of_type("segment")[0]["t0"] == 0
        assert [r["text"] for r in modules.store.get_segments(s.meeting_id)] == ["so the launch moves"]

    def test_overlap_between_chunks_is_removed_before_it_is_stored(self, modules):
        s = _session(modules, transcribe=_fixed([{"t0": 0.0, "t1": 2.0, "text": "the launch moves to October"}]))
        run(s.start({"conversation_id": "c"}))
        run(s.on_audio({"audio_bytes": b"a", "t0": 0, "t1": 2000}))

        s._transcribe = _fixed([{"t0": 0.0, "t1": 2.0, "text": "moves to October and legal"}])
        run(s.on_audio({"audio_bytes": b"b", "t0": 1800, "t1": 3800}))

        stored = [r["text"] for r in modules.store.get_segments(s.meeting_id)]
        assert stored == ["the launch moves to October", "and legal"]

    def test_a_chunk_that_is_all_overlap_sends_nothing(self, modules):
        s = _session(modules, transcribe=_fixed([{"t0": 0.0, "t1": 2.0, "text": "we need legal sign-off"}]))
        run(s.start({"conversation_id": "c"}))
        run(s.on_audio({"audio_bytes": b"a", "t0": 0, "t1": 2000}))
        before = len(s.transport.of_type("segment"))

        s._transcribe = _fixed([{"t0": 0.0, "t1": 1.0, "text": "need legal sign-off"}])
        assert run(s.on_audio({"audio_bytes": b"b", "t0": 1800, "t1": 2800})) == []
        assert len(s.transport.of_type("segment")) == before

    def test_the_frame_duration_is_offered_to_the_provider(self, modules):
        # MS1's fallback needs it: a provider that only returns text cannot know the span,
        # but the client that framed the audio can.
        seen = {}

        async def transcribe(audio, *, fmt="wav", duration_s=None):
            seen["duration_s"] = duration_s
            return [{"t0": 0.0, "t1": None, "text": "hello"}]

        s = _session(modules, transcribe=transcribe)
        run(s.start({"conversation_id": "c"}))
        run(s.on_audio({"audio_bytes": b"x", "t0": 1000, "t1": 3500}))
        assert seen["duration_s"] == pytest.approx(2.5)

    def test_no_speech_provider_is_a_named_refusal(self, modules):
        s = _session(modules, transcribe=None)
        run(s.start({"conversation_id": "c"}))
        with pytest.raises(modules.session.MeetingSessionError) as exc:
            run(s.on_audio({"audio_bytes": b"x"}))
        assert exc.value.code == "stt_unavailable"

    def test_an_audio_frame_with_no_audio_is_refused(self, modules):
        s = _session(modules, transcribe=_fixed([]))
        run(s.start({"conversation_id": "c"}))
        with pytest.raises(modules.session.MeetingSessionError) as exc:
            run(s.on_audio({"t0": 0}))
        assert exc.value.code == "audio_missing"


# ── status, mute, keyframes ─────────────────────────────────────────────────


class TestStatusAndExtras:
    def test_mute_is_recorded_and_echoed(self, modules):
        # The pill and the card may be on different surfaces — a hosted avatar and the web
        # UI can both watch one meeting — and only the server knows what both should show.
        s = _session(modules)
        run(s.start({"conversation_id": "c"}))
        run(s.on_mute({"mic": True}))
        assert s.mic_muted is True
        assert s.transport.of_type("status")[-1]["mic_muted"] is True

    def test_a_keyframe_is_counted_and_stored(self, modules):
        s = _session(modules)
        run(s.start({"conversation_id": "c"}))
        run(s.on_keyframe({"t": 1500, "url": "/files/slide.jpg", "hash": "abc"}))
        assert s.keyframe_count == 1
        assert modules.store.get_keyframes(s.meeting_id)[0]["url"] == "/files/slide.jpg"

    def test_a_keyframe_without_a_url_is_refused(self, modules):
        s = _session(modules)
        run(s.start({"conversation_id": "c"}))
        with pytest.raises(modules.session.MeetingSessionError):
            run(s.on_keyframe({"t": 0}))

    def test_errors_use_the_avatar_protocol_shape(self, modules):
        # So one client handles both transports without a special case for ours.
        s = _session(modules)
        frame = run(s.send_error("stt_unavailable", "no provider"))
        assert frame == {"type": "error", "code": "stt_unavailable", "msg": "no provider"}


# ── registry ────────────────────────────────────────────────────────────────


class TestRegistry:
    def test_a_live_session_is_findable_by_conversation(self, modules):
        # MS18's context provider reads this to know whether a chat turn is happening during
        # a meeting.
        s = _session(modules)
        run(s.start({"conversation_id": "conv-7"}))
        modules.session.register(s)
        assert modules.session.for_conversation("conv-7") is s

    def test_an_ended_session_is_not_live(self, modules):
        s = _session(modules)
        run(s.start({"conversation_id": "conv-7"}))
        modules.session.register(s)
        run(s.stop())
        assert modules.session.for_conversation("conv-7") is None
        assert modules.session.get(s.meeting_id) is s, "still retrievable by id"

    def test_unregister_forgets_it(self, modules):
        s = _session(modules)
        run(s.start({"conversation_id": "c"}))
        modules.session.register(s)
        modules.session.unregister(s.meeting_id)
        assert modules.session.get(s.meeting_id) is None
